import pytest

from neos.workflow.harness.events import (
    HarnessEventType,
    build_harness_event,
)
from neos.workflow.harness.models import (
    HarnessCheckResult,
    HarnessContract,
    HarnessMode,
    HarnessRiskLevel,
)
from neos.workflow.harness.runner import HarnessRunner


def test_builds_harness_started_event_payload():
    event = build_harness_event(
        HarnessEventType.STARTED,
        run_id="run-1",
        data={"mode": "gate"},
    )

    assert event["event"] == "harness_started"
    assert event["run_id"] == "run-1"
    assert event["data"]["mode"] == "gate"


def test_builds_check_completed_event_payload():
    event = build_harness_event(
        HarnessEventType.CHECK_COMPLETED,
        run_id="run-1",
        data={"check": "freshness", "passed": False},
    )

    assert event["event"] == "harness_check_completed"
    assert event["data"]["check"] == "freshness"


class EventedChecker:
    name = "evented_check"

    def run(self, *, report, sources, contract, context=None):
        return HarnessCheckResult(
            name=self.name,
            passed=True,
            score=0.8,
            severity="info",
            summary="Evented checker completed.",
        )


@pytest.mark.asyncio
async def test_runner_arun_emits_check_started_and_completed_callbacks():
    events = []

    async def collect_event(event_type, payload):
        events.append((event_type, payload))

    await HarnessRunner(checkers=[EventedChecker()]).arun(
        report="Report",
        sources=[],
        contract=HarnessContract(
            mode=HarnessMode.ADVISORY,
            risk_level=HarnessRiskLevel.LOW,
            min_score=0.0,
            optional_checks=["evented_check"],
        ),
        context={},
        event_callback=collect_event,
    )

    assert events == [
        (
            HarnessEventType.CHECK_STARTED,
            {"check": "evented_check", "mode": "advisory"},
        ),
        (
            HarnessEventType.CHECK_COMPLETED,
            {
                "check": "evented_check",
                "passed": True,
                "score": 0.8,
                "severity": "info",
            },
        ),
    ]
