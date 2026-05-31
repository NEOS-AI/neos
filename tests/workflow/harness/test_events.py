from neos.workflow.harness.events import (
    HarnessEventType,
    build_harness_event,
)


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
