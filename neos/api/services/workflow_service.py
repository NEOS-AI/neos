"""Workflow execution service layer."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from neos.config.settings import settings
from neos.workflow.events import WorkflowEventHandler

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
            return settings.DEFAULT_AUTONOMY_LEVEL

        if level in (0, 1, 2):
            return level
        return settings.DEFAULT_AUTONOMY_LEVEL

    @staticmethod
    async def execute(
        user_id: str,
        session_id: str,
        query: str,
        preferences: Optional[Dict[str, Any]] = None,
        event_handler: Optional[WorkflowEventHandler] = None,
        use_checkpointer: bool = True,
    ) -> Dict[str, Any]:
        from neos.workflow.graph import multi_agent_workflow

        autonomy_level = WorkflowService.resolve_autonomy_level(preferences)
        workflow_input = {
            "user_id": user_id,
            "session_id": session_id,
            "query": query,
            "autonomy_level": autonomy_level,
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
