from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any


class HarnessEventType(str, Enum):
    STARTED = "harness_started"
    CHECK_STARTED = "harness_check_started"
    CHECK_COMPLETED = "harness_check_completed"
    REPAIR_STARTED = "harness_repair_started"
    REPAIR_COMPLETED = "harness_repair_completed"
    COMPLETED = "harness_completed"


def build_harness_event(
    event_type: HarnessEventType,
    *,
    run_id: str | None = None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "event": event_type.value,
        "run_id": run_id,
        "timestamp": datetime.now().isoformat(),
        "data": data or {},
    }
