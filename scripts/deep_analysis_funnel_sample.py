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

from neos.config.model_routing import resolve_model
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
from neos.workflow.deep_analysis.service import build_orchestrator


class NoCompletedDevRunsError(RuntimeError):
    """Raised when a sample has no successful dev observation."""


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


def _resolved_models(config) -> dict:
    """The model IDs that will actually run, not the config that selects them.

    `deep_analysis.models.*` are all `None` -- the routing contract's "use
    the role default" -- so every past manifest recorded four nulls and
    could not answer the one question this sample is read against: was the
    judge the same model as the SCOUT worker? (E3, roadmap §6 ①.)

    The roles mirror the call sites exactly and must stay in step with them:
    `service.py` (judge), `worker.py` (scout/dig), `synthesizer.py` and
    `orchestrator.py` (synth/dig). A role guessed here would put a lie in
    the one artifact that cannot be regenerated.
    """
    roles = {
        "scout": ("everyday", config.models.scout),
        "judge": ("everyday", config.models.judge),
        "dig": ("powerful", config.models.dig),
        "synth": ("powerful", config.models.synth),
    }
    resolved = {}
    for name, (role, override) in roles.items():
        resolution = resolve_model(
            config=settings.config.model_routing,
            provider="anthropic",
            role=role,
            feature_override=override,
        )
        resolved[name] = {
            "role": role,
            "model": resolution.model,
            "source": str(getattr(resolution, "source", "unknown")),
        }
    return resolved


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


def _fingerprint() -> dict:
    """Non-secret runtime configuration in effect for this sample run.

    Caps, thresholds, and model IDs only — never credentials. Model IDs are
    configuration, not secrets.
    """
    config = settings.config.deep_analysis
    return {
        "global_token_cap": config.global_token_cap,
        "max_depth": config.max_depth,
        "quote_match_threshold": config.quote_match_threshold,
        # Raised 1500 -> 3200 on 2026-07-28 after truncated decompose JSON
        # failed 5 of 7 runs. Recorded so a later reader can tell which
        # samples ran under which cap.
        "decompose_max_tokens": config.decompose_max_tokens,
        "judge_max_output_tokens": config.judge_max_output_tokens,
        "entailment_max_output_tokens": config.entailment_max_output_tokens,
        "fetch_user_agent": config.fetch_user_agent,
        "models": {
            "scout": config.models.scout,
            "dig": config.models.dig,
            "synth": config.models.synth,
            "judge": config.models.judge,
        },
        # `models` above is the *configuration* (all None = role default).
        # This is what those defaults resolve to -- the only way a later
        # reader can tell judge and scout apart. Both are kept: the config
        # says what was chosen, the resolution says what ran.
        "resolved_models": _resolved_models(config),
        "git": _git_identity(),
        "effort": {
            name: {
                "token_cap": effort.token_cap,
                "wall_clock_cap": effort.wall_clock_cap,
            }
            for name, effort in config.effort.items()
        },
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
                fingerprint=_fingerprint(),
            )
            _finalize_cassette(cassette, artifact_dir)
            raise
        finished_at = datetime.now(timezone.utc)

        if not any(
            item.get("status") == "completed" for item in result["dev_runs"]
        ):
            raise NoCompletedDevRunsError("no dev runs completed")
        artifact_dir = write_artifacts(
            result,
            output_root,
            receipt=_receipt(
                started_at, finished_at, 0, verification=verification
            ),
            fingerprint=_fingerprint(),
        )
        _finalize_cassette(cassette, artifact_dir)
        run_ids = [
            item["run_id"]
            for item in result["dev_runs"]
            if item.get("run_id")
        ]
        default_run = result.get("default_run")
        if default_run and default_run.get("run_id"):
            run_ids.append(default_run["run_id"])
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
