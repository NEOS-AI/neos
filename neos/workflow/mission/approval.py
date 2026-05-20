from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict


def build_mission_approval_request(
    *,
    mission_id: str,
    plan: Dict[str, Any],
    contract: Dict[str, Any],
    timeout_seconds: int,
) -> Dict[str, Any]:
    return {
        "request_id": str(uuid.uuid4()),
        "skill_name": "mission_runtime",
        "params": {
            "mission_id": mission_id,
            "mission_plan": {
                "summary": plan.get("user_visible_summary", ""),
                "tasks": plan.get("tasks", []),
            },
            "validation_contract": {
                "success_criteria": contract.get("success_criteria", []),
                "required_sources": contract.get("required_sources", 0),
                "freshness_requirement": contract.get("freshness_requirement"),
                "citation_requirement": contract.get("citation_requirement"),
                "min_quality_score": contract.get("min_quality_score"),
                "failure_policy": contract.get("failure_policy"),
            },
        },
        "timeout_seconds": timeout_seconds,
        "requested_at": datetime.utcnow().isoformat(),
    }
