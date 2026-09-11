"""Resume a workflow interrupt from a channel /approve or /deny."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

_NOT_READY = "Workflow is not ready to resume approval."
_INVALID_REQUEST = "Invalid or expired approval request."
_STATE_FAILED = "Failed to load workflow state."
_RESUME_FAILED = "Cannot resume this workflow."
_UPDATE_FAILED = "Failed to apply approval decision."


async def _mark_resolved_best_effort(request_id: str, owner_id: str) -> None:
    try:
        from neos.api.handlers.approval_handlers import _mark_approval_resolved

        await _mark_approval_resolved(request_id, owner_id)
    except Exception as error:
        logger.warning(
            "[RuntimeWorkflowApprovals] mark resolved failed (non-critical): %s",
            error,
        )


class RuntimeWorkflowApprovals:
    def __init__(self, workflow: Any) -> None:
        self._workflow = workflow

    async def decide(
        self,
        *,
        session_id: str,
        request_id: str,
        owner_id: str,
        approve: bool,
    ) -> str:
        decision = "approved" if approve else "rejected"
        workflow = self._workflow
        graph = getattr(workflow, "graph", None)
        if (
            graph is None
            or not getattr(workflow, "_graph_initialized", False)
            or not getattr(workflow, "_graph_uses_checkpointer", False)
        ):
            return _NOT_READY

        config = {"configurable": {"thread_id": session_id}}
        try:
            current_graph_state = await graph.aget_state(config)
            values = getattr(current_graph_state, "values", None) or {}
            pending = values.get("pending_approvals") or []
        except Exception as error:
            logger.error(
                "[RuntimeWorkflowApprovals] aget_state failed: session=%s: %s",
                session_id,
                error,
            )
            return _STATE_FAILED

        valid_ids = {
            str(item.get("request_id"))
            for item in pending
            if isinstance(item, dict) and item.get("request_id")
        }
        if not request_id or request_id not in valid_ids:
            return _INVALID_REQUEST

        try:
            from neos.workflow.resume_graph import (
                ResumeGraphUnavailable,
                resume_graph_for,
            )

            resume_graph = await resume_graph_for(
                values,
                workflow=workflow,
                checkpointer=graph.checkpointer,
            )
        except ResumeGraphUnavailable as error:
            logger.error(
                "[RuntimeWorkflowApprovals] resume graph unavailable: "
                "session=%s reason=%s",
                session_id,
                error.reason,
            )
            return _RESUME_FAILED
        except Exception as error:
            logger.error(
                "[RuntimeWorkflowApprovals] resume_graph_for failed: "
                "session=%s: %s",
                session_id,
                error,
            )
            return _RESUME_FAILED

        try:
            await resume_graph.aupdate_state(
                config=config,
                values={"approval_decision": decision},
            )
        except Exception as error:
            logger.error(
                "[RuntimeWorkflowApprovals] aupdate_state failed: "
                "session=%s: %s",
                session_id,
                error,
            )
            return _UPDATE_FAILED

        await _mark_resolved_best_effort(request_id, owner_id)

        async def _resume() -> None:
            try:
                async for _chunk in resume_graph.astream(None, config=config):
                    pass
            except Exception as error:
                logger.error(
                    "[RuntimeWorkflowApprovals] astream failed: "
                    "session=%s: %s",
                    session_id,
                    error,
                )

        asyncio.create_task(_resume(), name=f"channel_approval_resume_{session_id}")
        return f"{request_id} {'approved' if approve else 'denied'}"
