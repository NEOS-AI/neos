from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional


class MissionEventName(str, Enum):
    PLANNED = "mission.planned"
    APPROVAL_REQUESTED = "mission.approval_requested"
    STARTED = "mission.started"
    TASK_STARTED = "mission.task.started"
    TASK_COMPLETED = "mission.task.completed"
    TASK_FAILED = "mission.task.failed"
    VALIDATION_STARTED = "mission.validation.started"
    VALIDATION_COMPLETED = "mission.validation.completed"
    VALIDATION_FAILED = "mission.validation.failed"
    COMPLETED = "mission.completed"
    PARTIAL = "mission.partial"
    FAILED = "mission.failed"


def build_mission_event(
    *,
    name: MissionEventName,
    mission_id: str,
    task_id: Optional[str] = None,
    correlation_id: Optional[str] = None,
    role: str,
    data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "event": name.value,
        "mission_id": mission_id,
        "task_id": task_id,
        "correlation_id": correlation_id,
        "role": role,
        "data": data or {},
        "created_at": datetime.utcnow().isoformat(),
    }
