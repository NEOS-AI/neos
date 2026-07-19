from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class CodingEvent:
    version: int
    task_id: str
    seq: int
    event_id: str
    type: str
    payload: Mapping[str, Any]
    created_at: datetime
    run_id: str | None = None
    turn_id: str | None = None
    tool_call_id: str | None = None
    checkpoint_id: str | None = None


def make_event(
    *,
    task_id: str,
    seq: int,
    event_type: str,
    payload: Mapping[str, Any],
    now: datetime,
    event_id: str | None = None,
    run_id: str | None = None,
    turn_id: str | None = None,
    tool_call_id: str | None = None,
    checkpoint_id: str | None = None,
) -> CodingEvent:
    if not task_id:
        raise ValueError("task_id cannot be empty")
    if not event_type:
        raise ValueError("event type cannot be empty")
    if seq < 1:
        raise ValueError("event seq must be positive")
    return CodingEvent(
        version=1,
        task_id=task_id,
        seq=seq,
        event_id=event_id or f"ce_{uuid4().hex}",
        type=event_type,
        payload=dict(payload),
        created_at=now,
        run_id=run_id,
        turn_id=turn_id,
        tool_call_id=tool_call_id,
        checkpoint_id=checkpoint_id,
    )
