"""Run the bounded production-like deep-analysis funnel sample."""

import argparse
import asyncio
from datetime import datetime, timezone
import functools
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

sys.path.append(str(Path(__file__).parent.parent))

from neos.config.settings import settings
from neos.database.connection import get_session_ctx
from neos.workflow.deep_analysis.cassette import Cassette
from neos.workflow.deep_analysis.funnel_sample import QUESTION_CASES
from neos.workflow.deep_analysis.funnel_sample_runner import (
    preflight,
    run_sample,
    write_artifacts,
)
from neos.workflow.deep_analysis.jobs import execute_run
from neos.workflow.deep_analysis.manifest import MANIFEST_VERSION
from neos.workflow.deep_analysis.manifest_reader import (
    manifests_for,
    runs_without_manifest,
)
from neos.workflow.deep_analysis.service import build_orchestrator


class NoCompletedDevRunsError(RuntimeError):
    """Raised when a sample has no successful dev observation."""


class MissingManifestError(RuntimeError):
    """매니페스트 없는 런이 표본에 있다 (로드맵 §15.4 금지 3번).

    지침이 아니라 기계가 거부한다. 이 예외가 나면 아티팩트를 쓰지 않는다 --
    무엇으로 조립됐는지 모르는 런은 나중에 판독할 수 없고, 판독할 수 없는
    표본은 §10.2 의 "정확히 1회" 규칙 때문에 다시 낼 기회가 없다.
    """

    def __init__(self, run_ids: list[str]) -> None:
        super().__init__(
            "매니페스트 없는 런: " + ", ".join(run_ids) + " -- 표본이 아니다"
        )
        self.run_ids = run_ids


async def _gate_and_read_manifests(session, run_ids: list[str]) -> dict:
    """모든 런이 매니페스트를 가졌는지 확인하고 그것들을 돌려준다.

    로드맵 §15.4 금지 3번의 집행 지점. 거부는 여기 한 곳뿐이며
    `Orchestrator.run()` 은 건드리지 않는다 -- 금지가 겨누는 것은 '런' 이
    아니라 '표본' 이고, 오케스트레이터에 걸면 그것을 직접 짓는 골든·통합
    테스트 수십 건이 깨진다.
    """
    missing = await runs_without_manifest(session, run_ids)
    if missing:
        raise MissingManifestError(missing)
    return await manifests_for(session, run_ids)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the production-like deep-analysis claim funnel sample"
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("artifacts/deep-analysis-funnel"),
    )
    parser.add_argument(
        "--test-report",
        type=Path,
        default=None,
        help=(
            "JSON file holding the pre-run test-suite result "
            "(keys: command, exit_status, summary). Recorded verbatim in "
            "the execution receipt; absence is recorded as unavailable."
        ),
    )
    return parser.parse_args()


_REPO_ROOT = Path(__file__).parent.parent


def _git(*args: str) -> str:
    """One git query, or the string `unavailable`.

    Never raises: a missing git binary or a detached checkout must not take
    down a sample that costs real money to produce.
    """
    try:
        completed = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=_REPO_ROOT,
            check=True,
        )
    except (subprocess.SubprocessError, OSError):
        return "unavailable"
    return completed.stdout.strip()


def _git_identity() -> dict:
    """Which code produced this sample.

    No manifest has ever carried this. W1 asks whether the post-D25/G10 code
    finally reaches `report_assembly`, and the artifact could not say which
    commit it ran on -- the same gap `20260725T081707Z` had for its exit
    code, one field over. Samples are not reproducible (§10.2), so the code
    identity has to be captured at write time or not at all.
    """
    status = _git("status", "--porcelain")
    if status == "unavailable":
        return {
            "commit": _git("rev-parse", "HEAD"),
            "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
            "dirty": "unavailable",
            "dirty_paths": [],
        }
    return {
        "commit": _git("rev-parse", "HEAD"),
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "dirty": bool(status),
        "dirty_paths": status.splitlines(),
    }


def _verification(test_report: Path | None) -> dict:
    """The pre-run gates §10.2 lists in the execution receipt.

    No sample has ever carried them. Ruff runs here: it is read-only and
    takes seconds. The test suite does not, and deliberately -- it writes to
    the same PostgreSQL this sample is about to fill, so running it from
    inside would contaminate the ledger the sample exists to produce. It is
    handed in via `--test-report` instead.

    A missing report is recorded as `unavailable` rather than omitted. That
    is the lesson of `20260725T081707Z`: a field that is silently absent
    reads as "nobody thought about it", while an explicit `unavailable`
    reads as "checked, and it was not recoverable".
    """
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "ruff", "check", "."],
            capture_output=True,
            text=True,
            timeout=300,
            cwd=_REPO_ROOT,
        )
        ruff = {
            "command": "python -m ruff check .",
            "exit_status": completed.returncode,
            "summary": (completed.stdout or completed.stderr).strip().splitlines()[-1:]
            or [""],
        }
    except (subprocess.SubprocessError, OSError):
        ruff = {"command": "python -m ruff check .", "exit_status": "unavailable"}

    if test_report is None:
        tests = "unavailable"
    else:
        try:
            tests = json.loads(test_report.read_text())
        except (OSError, ValueError):
            tests = "unavailable"
    return {"ruff": ruff, "tests": tests}


def _fingerprint(manifests: dict[str, dict]) -> dict:
    """이 표본의 런별 구성. 계산하지 않는다 -- 원장이 답한다.

    이전에는 이 함수가 설정을 다시 읽어 지문을 만들었고, 그래서 dev 런
    5건에 기본 프로파일 캡을 적었다(표본 #20). 이제 값의 출처는
    `build_orchestrator` 가 발행한 이벤트 하나뿐이다.

    `git` 이 `runs` 밖에 있는 이유: 저장소 상태는 런의 구성이 아니라
    표본의 구성이고, `deep_analysis_diagnostician.py` 의 `_scrub_config()`
    가 이 자리에서 `git.commit` 을 떼어낸다.
    """
    return {
        "manifest_version": MANIFEST_VERSION,
        "git": _git_identity(),
        "runs": manifests,
    }


def _receipt(
    started_at: datetime,
    finished_at: datetime,
    exit_status: int,
    verification: dict | None = None,
) -> dict:
    """Process metadata proving this run's wall-clock window and exit status."""
    return {
        "pid": os.getpid(),
        "started_at": started_at.isoformat().replace("+00:00", "Z"),
        "finished_at": finished_at.isoformat().replace("+00:00", "Z"),
        "exit_status": exit_status,
        "verification": verification if verification is not None else "unavailable",
    }


def _new_recording_cassette() -> tuple[Cassette, Path]:
    """A record-mode cassette backed by a private temp directory.

    `Cassette.save()` is the only thing that ever flushes `_data` to disk,
    and nothing calls it implicitly (`cassette.py:46-60`) -- the caller must
    do so explicitly (`_finalize_cassette`) before the temp directory is
    discarded, or every call recorded during the run is lost.
    """
    tmp_dir = Path(tempfile.mkdtemp(prefix="deep-analysis-cassette-"))
    cassette = Cassette(tmp_dir / "cassette.json", mode="record")
    return cassette, tmp_dir


def _finalize_cassette(cassette: Cassette, artifact_dir: Path) -> None:
    """Flush the cassette to disk and move it next to the sample's artifacts.

    A cassette that is never flushed is worse than none: it looks like the
    run was captured when nothing was. `save()` must run, and must run
    before the caller's temp-dir cleanup.
    """
    cassette.save()
    if cassette.path.exists():
        shutil.move(str(cassette.path), str(artifact_dir / "cassette.json"))


async def _main(
    output_root: Path, test_report: Path | None = None
) -> tuple[Path, list[str]]:
    await preflight(settings, get_session_ctx)
    # Captured before the first LLM call: these gates describe the tree the
    # sample ran from, and running them afterwards would describe a tree the
    # sample never used.
    verification = _verification(test_report)
    started_at = datetime.now(timezone.utc)
    cassette, cassette_tmp_dir = _new_recording_cassette()
    # `execute_run` accepts `build_orchestrator_fn` (jobs.py:132) and
    # `build_orchestrator` accepts `cassette` (service.py:51) -- threading a
    # cassette through the sample needs no change to `jobs.py` or its test
    # fakes, only this partial application at the call site.
    sample_execute_fn = functools.partial(
        execute_run,
        build_orchestrator_fn=functools.partial(
            build_orchestrator, cassette=cassette
        ),
    )
    try:
        try:
            result = await run_sample(
                cases=QUESTION_CASES,
                session_factory=get_session_ctx,
                execute_fn=sample_execute_fn,
                timeout_seconds=settings.config.deep_analysis.job_time_limit,
                secrets=[settings.ANTHROPIC_API_KEY, settings.TAVILY_API_KEY],
            )
        except Exception:
            # The receipt must survive failure: persist the exit status and
            # wall-clock window even though the sample never produced a
            # result, then let the original exception propagate.
            finished_at = datetime.now(timezone.utc)
            artifact_dir = write_artifacts(
                {},
                output_root,
                receipt=_receipt(
                    started_at, finished_at, 1, verification=verification
                ),
                fingerprint=_fingerprint({}),
            )
            _finalize_cassette(cassette, artifact_dir)
            raise
        finished_at = datetime.now(timezone.utc)

        if not any(
            item.get("status") == "completed" for item in result["dev_runs"]
        ):
            raise NoCompletedDevRunsError("no dev runs completed")

        run_ids = [
            item["run_id"]
            for item in result["dev_runs"]
            if item.get("run_id")
        ]
        default_run = result.get("default_run")
        if default_run and default_run.get("run_id"):
            run_ids.append(default_run["run_id"])

        # 관문은 완료된 런만 본다. 체크포인트 이전에 죽은 런은 매니페스트가
        # 롤백되어 사라지므로(`Ledger.log`는 flush 만 하고, `Orchestrator.run`
        # 의 예외 처리기가 `fail_run()` 전에 `db.rollback()` 을 부른다) 실패한
        # 런 하나가 나머지 완료된 런들의 증거까지 통째로 버리게 된다. 표본은
        # 정확히 1회이므로 그 다섯 런은 다시 돌릴 기회가 없다. 실패한 런은
        # 여전히 `result["dev_runs"]`(아티팩트의 런 목록)에 남는다 -- 여기서
        # 바꾸는 것은 관문이 무엇을 검사하는지 뿐이다.
        completed_run_ids = [
            item["run_id"]
            for item in result["dev_runs"]
            if item.get("run_id") and item.get("status") == "completed"
        ]
        if (
            default_run
            and default_run.get("run_id")
            and default_run.get("status") == "completed"
        ):
            completed_run_ids.append(default_run["run_id"])

        async with get_session_ctx() as session:
            manifests = await _gate_and_read_manifests(
                session, completed_run_ids
            )

        artifact_dir = write_artifacts(
            result,
            output_root,
            receipt=_receipt(
                started_at, finished_at, 0, verification=verification
            ),
            fingerprint=_fingerprint(manifests),
        )
        _finalize_cassette(cassette, artifact_dir)
        return artifact_dir, run_ids
    finally:
        shutil.rmtree(cassette_tmp_dir, ignore_errors=True)


def main() -> None:
    args = _parse_args()
    try:
        artifact_dir, run_ids = asyncio.run(
            _main(args.output_root, args.test_report)
        )
    except NoCompletedDevRunsError as exc:
        raise SystemExit(f"sample failed: {exc}") from exc
    print(artifact_dir)
    for run_id in run_ids:
        print(run_id)


if __name__ == "__main__":
    main()
