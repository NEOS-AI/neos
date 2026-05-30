from __future__ import annotations

from typing import Any, Dict


class MissionIntegrator:
    async def integrate(self, state: Dict[str, Any]) -> Dict[str, Any]:
        metadata = dict(state.get("response_metadata") or {})
        if state.get("mission_id"):
            metadata.update(
                {
                    "mission_id": state.get("mission_id"),
                    "mission_status": state.get("mission_status"),
                    "mission_plan_summary": (state.get("mission_plan") or {}).get(
                        "user_visible_summary"
                    ),
                    "validation_summary": state.get("validation_summary"),
                    "mission_task_results": state.get("mission_task_results", []),
                }
            )
        return {"response_metadata": metadata}
