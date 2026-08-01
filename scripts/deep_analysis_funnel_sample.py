"""Run the bounded production-like deep-analysis funnel sample."""

import argparse
import asyncio
from datetime import datetime, timezone
import functools
import os
from pathlib import Path
import shutil
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
    return parser.parse_args()


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
        "fetch_user_agent": config.fetch_user_agent,
        "models": {
            "scout": config.models.scout,
            "dig": config.models.dig,
            "synth": config.models.synth,
            "judge": config.models.judge,
        },
        "effort": {
            name: {
                "token_cap": effort.token_cap,
                "wall_clock_cap": effort.wall_clock_cap,
            }
            for name, effort in config.effort.items()
        },
    }


def _receipt(
    started_at: datetime, finished_at: datetime, exit_status: int
) -> dict:
    """Process metadata proving this run's wall-clock window and exit status."""
    return {
        "pid": os.getpid(),
        "started_at": started_at.isoformat().replace("+00:00", "Z"),
        "finished_at": finished_at.isoformat().replace("+00:00", "Z"),
        "exit_status": exit_status,
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


async def _main(output_root: Path) -> tuple[Path, list[str]]:
    await preflight(settings, get_session_ctx)
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
                receipt=_receipt(started_at, finished_at, exit_status=1),
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
            receipt=_receipt(started_at, finished_at, exit_status=0),
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
    try:
        artifact_dir, run_ids = asyncio.run(_main(_parse_args().output_root))
    except NoCompletedDevRunsError as exc:
        raise SystemExit(f"sample failed: {exc}") from exc
    print(artifact_dir)
    for run_id in run_ids:
        print(run_id)


if __name__ == "__main__":
    main()
