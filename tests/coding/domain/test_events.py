from datetime import UTC, datetime

import pytest

from neos.coding.domain.events import CodingEvent, make_event


NOW = datetime(2026, 7, 18, 10, 0, tzinfo=UTC)


def test_make_event_builds_versioned_envelope() -> None:
    event = make_event(
        task_id="ct_01",
        seq=1,
        event_type="task.created",
        payload={"status": "queued"},
        now=NOW,
        event_id="ce_01",
    )

    assert event == CodingEvent(
        version=1,
        task_id="ct_01",
        seq=1,
        event_id="ce_01",
        type="task.created",
        payload={"status": "queued"},
        created_at=NOW,
        run_id=None,
        turn_id=None,
        tool_call_id=None,
    )


@pytest.mark.parametrize("seq", [0, -1])
def test_event_sequence_must_be_positive(seq: int) -> None:
    with pytest.raises(ValueError, match="seq"):
        make_event(
            task_id="ct_01",
            seq=seq,
            event_type="task.created",
            payload={},
            now=NOW,
        )


@pytest.mark.parametrize(
    ("task_id", "event_type"),
    [("", "task.created"), ("ct_01", "")],
)
def test_event_identifiers_cannot_be_empty(task_id: str, event_type: str) -> None:
    with pytest.raises(ValueError):
        make_event(
            task_id=task_id,
            seq=1,
            event_type=event_type,
            payload={},
            now=NOW,
        )
