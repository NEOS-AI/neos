"""Workflow execution service layer."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from neos.config.settings import settings
from neos.workflow.events import WorkflowEventHandler
from neos.workflow.enums import AutonomyLevel

logger = logging.getLogger(__name__)


class WorkflowService:
    """Wrap workflow execution and request-level options."""

    @staticmethod
    def resolve_autonomy_level(preferences: Optional[Dict[str, Any]]) -> int:
        if not preferences:
            return settings.DEFAULT_AUTONOMY_LEVEL

        raw_level = preferences.get("autonomy_level")
        if raw_level is None:
            return settings.DEFAULT_AUTONOMY_LEVEL

        try:
            level = int(raw_level)
        except (TypeError, ValueError):
            return AutonomyLevel.ASSISTED.value

        if level in (0, 1, 2):
            return level
        return AutonomyLevel.ASSISTED.value

    @staticmethod
    async def execute(
        user_id: str,
        session_id: str,
        query: str,
        preferences: Optional[Dict[str, Any]] = None,
        event_handler: Optional[WorkflowEventHandler] = None,
        use_checkpointer: bool = True,
        bypass_cache: bool = False,
    ) -> Dict[str, Any]:
        from neos.workflow.graph import multi_agent_workflow

        autonomy_level = WorkflowService.resolve_autonomy_level(preferences)
        effective_bypass_cache = bool(
            bypass_cache or (preferences or {}).get("bypass_cache", False)
        )
        workflow_input = {
            "user_id": user_id,
            "session_id": session_id,
            "query": query,
            "autonomy_level": autonomy_level,
            "bypass_cache": effective_bypass_cache,
        }

        logger.info(
            "[WorkflowService] Executing workflow user=%s session=%s autonomy_level=%s",
            user_id,
            session_id,
            autonomy_level,
        )

        return await multi_agent_workflow.execute_workflow(
            workflow_input,
            event_handler=event_handler,
            use_checkpointer=use_checkpointer,
        )
