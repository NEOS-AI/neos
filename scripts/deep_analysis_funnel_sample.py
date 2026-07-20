"""Run the bounded production-like deep-analysis funnel sample."""

import argparse
import asyncio
from pathlib import Path

from neos.config.settings import settings
from neos.database.connection import get_session_ctx
from neos.workflow.deep_analysis.funnel_sample import QUESTION_CASES
from neos.workflow.deep_analysis.funnel_sample_runner import (
    preflight,
    run_sample,
    write_artifacts,
)
from neos.workflow.deep_analysis.jobs import execute_run


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


async def _main(output_root: Path) -> tuple[Path, list[str]]:
    await preflight(settings, get_session_ctx)
    result = await run_sample(
        cases=QUESTION_CASES,
        session_factory=get_session_ctx,
        execute_fn=execute_run,
        timeout_seconds=settings.config.deep_analysis.job_time_limit,
        secrets=[settings.ANTHROPIC_API_KEY, settings.TAVILY_API_KEY],
    )
    if not any(
        item.get("status") == "completed" for item in result["dev_runs"]
    ):
        raise NoCompletedDevRunsError("no dev runs completed")
    artifact_dir = write_artifacts(result, output_root)
    run_ids = [
        item["run_id"]
        for item in result["dev_runs"]
        if item.get("run_id")
    ]
    default_run = result.get("default_run")
    if default_run and default_run.get("run_id"):
        run_ids.append(default_run["run_id"])
    return artifact_dir, run_ids


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
