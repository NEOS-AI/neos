import json
from datetime import datetime

import pytest

from neos.workflow.harness.models import (
    HarnessMode,
    HarnessRun,
    HarnessVerdict,
)
from scripts.harness_calibration import run_calibration


class FakeRunner:
    async def arun(self, *, report, sources, contract, context, repair_attempts=0):
        passed = context["case_id"] == "case-pass"
        return HarnessRun(
            run_id=f"run-{context['case_id']}",
            mode=HarnessMode.GATE,
            verdict=HarnessVerdict.PASS if passed else HarnessVerdict.FAIL,
            score=0.95 if passed else 0.2,
            checks=[],
            failed_checks=[] if passed else ["source_count"],
            repair_attempts=repair_attempts,
            started_at=datetime.now(),
        )


@pytest.mark.asyncio
async def test_calibration_script_writes_runtime_and_agreement_rows(tmp_path):
    input_path = tmp_path / "candidates.jsonl"
    output_path = tmp_path / "report.jsonl"
    rows = [
        {
            "case_id": "case-pass",
            "query": "passing research question",
            "report": "A supported report [1].",
            "sources": [{"id": 1, "title": "Source", "url": "https://example.com"}],
            "metadata": {"harness_profile": "mission_strict"},
            "offline_graders": [
                {"grader_id": "factual_accuracy", "score": 0.9, "passed": True}
            ],
        },
        {
            "case_id": "case-fail",
            "query": "failing research question",
            "report": "Unsupported report.",
            "sources": [],
            "metadata": {"harness_profile": "mission_strict"},
            "offline_graders": [
                {"grader_id": "source_count", "score": 0.2, "passed": False}
            ],
        },
    ]
    input_path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )

    await run_calibration(
        input_path=input_path,
        output_path=output_path,
        profile="mission_strict",
        runner=FakeRunner(),
    )

    output_rows = [
        json.loads(line)
        for line in output_path.read_text(encoding="utf-8").splitlines()
    ]

    assert [row["case_id"] for row in output_rows] == ["case-pass", "case-fail"]
    assert output_rows[0]["runtime_verdict"] == "pass"
    assert output_rows[0]["runtime_failed_checks"] == []
    assert output_rows[0]["agreement"] == "agree_pass"
    assert output_rows[1]["runtime_failed_checks"] == ["source_count"]
    assert output_rows[1]["agreement"] == "agree_fail"
