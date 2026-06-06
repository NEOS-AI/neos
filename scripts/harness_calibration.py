from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from neos.workflow.harness.contract_builder import build_harness_contract
from neos.workflow.harness.models import HarnessVerdict
from neos.workflow.harness.runner import HarnessRunner


PASSING_VERDICTS = {
    HarnessVerdict.PASS.value,
    HarnessVerdict.ADVISORY_PASS.value,
}


async def run_calibration(
    *,
    input_path: Path,
    output_path: Path,
    profile: str,
    runner: HarnessRunner | None = None,
) -> None:
    runner = runner or HarnessRunner()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with input_path.open("r", encoding="utf-8") as input_file, output_path.open(
        "w",
        encoding="utf-8",
    ) as output_file:
        for line in input_file:
            if not line.strip():
                continue
            row = json.loads(line)
            metadata = dict(row.get("metadata") or {})
            selected_profile = profile or metadata.get("harness_profile") or "research_default"
            metadata["harness_profile"] = selected_profile
            contract = build_harness_contract(
                {
                    "original_query": row.get("query"),
                    "metadata": metadata,
                    "harness_profile": selected_profile,
                }
            )
            run = await runner.arun(
                report=str(row.get("report") or ""),
                sources=[
                    source
                    for source in row.get("sources") or []
                    if isinstance(source, dict)
                ],
                contract=contract,
                context={
                    "case_id": row.get("case_id"),
                    "query": row.get("query"),
                    **metadata,
                },
                repair_attempts=0,
            )
            offline_graders = [
                grader
                for grader in row.get("offline_graders") or []
                if isinstance(grader, dict)
            ]
            output_file.write(
                json.dumps(
                    {
                        "case_id": row.get("case_id"),
                        "profile": selected_profile,
                        "runtime_score": float(run.score),
                        "runtime_verdict": run.verdict.value,
                        "runtime_failed_checks": run.failed_checks,
                        "offline_grader_scores": {
                            str(grader.get("grader_id")): grader.get("score")
                            for grader in offline_graders
                        },
                        "offline_failed_graders": [
                            str(grader.get("grader_id"))
                            for grader in offline_graders
                            if grader.get("passed") is False
                        ],
                        "agreement": _agreement_label(
                            runtime_pass=run.verdict.value in PASSING_VERDICTS,
                            offline_pass=_offline_passed(offline_graders),
                        ),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )


def _offline_passed(offline_graders: list[dict[str, Any]]) -> bool | None:
    if not offline_graders:
        return None
    return all(grader.get("passed") is True for grader in offline_graders)


def _agreement_label(
    *,
    runtime_pass: bool,
    offline_pass: bool | None,
) -> str:
    if offline_pass is None:
        return "mixed"
    if runtime_pass and offline_pass:
        return "agree_pass"
    if not runtime_pass and not offline_pass:
        return "agree_fail"
    if not runtime_pass and offline_pass:
        return "runtime_stricter"
    if runtime_pass and not offline_pass:
        return "offline_stricter"
    return "mixed"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare runtime research harness verdicts with offline eval results."
    )
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--profile", default="mission_strict")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    asyncio.run(
        run_calibration(
            input_path=args.input,
            output_path=args.output,
            profile=args.profile,
        )
    )


if __name__ == "__main__":
    main()
