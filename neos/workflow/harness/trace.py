from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from itertools import count
from typing import Any


_sequence = count()


@dataclass(frozen=True)
class TraceEvent:
    sequence: int
    event_type: str
    run_id: str | None
    node_id: str
    data: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def trace_event(
    *,
    event_type: str,
    node_id: str,
    run_id: str | None = None,
    data: dict[str, Any] | None = None,
) -> TraceEvent:
    return TraceEvent(
        sequence=next(_sequence),
        event_type=event_type,
        run_id=run_id,
        node_id=node_id,
        data=data or {},
    )


def compact_trace_event(
    event: TraceEvent,
    *,
    max_text_length: int = 240,
) -> dict[str, Any]:
    payload = event.to_dict()
    payload["data"] = {
        key: _compact_value(value, max_text_length=max_text_length)
        for key, value in payload["data"].items()
    }
    return payload


def _compact_value(value: Any, *, max_text_length: int) -> Any:
    if isinstance(value, str):
        return value[:max_text_length]
    if isinstance(value, list):
        return [
            _compact_value(item, max_text_length=max_text_length)
            for item in value[:20]
        ]
    if isinstance(value, dict):
        return {
            key: _compact_value(item, max_text_length=max_text_length)
            for key, item in value.items()
        }
    return value
