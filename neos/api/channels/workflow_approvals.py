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


def _native() -> bool:
    from neos.workflow.runtime.select import runtime_name

    return runtime_name() == "native"


class RuntimeWorkflowApprovals:
    def __init__(self, workflow: Any) -> None:
        self._workflow = workflow
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock_for(self, session_id: str) -> asyncio.Lock:
        lock = self._locks.get(session_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[session_id] = lock
        return lock

    def _native_approvals(self) -> Any:
        """이 포트가 쥔 워크플로를 재개한다 -- 전역 싱글턴이 아니다(컨트롤러 결정, Task 7)."""
        from neos.workflow.runtime.approvals import WorkflowApprovals
        from neos.workflow.runtime.select import native_turns

        return WorkflowApprovals(self._workflow, native_turns().lifecycle)

    async def interrupt_owner(self, session_id: str) -> str | None:
        if _native():
            pending = await self._native_approvals().pending_for_session(session_id)
            return pending.user_id if pending is not None else None
        workflow = self._workflow
        graph = getattr(workflow, "graph", None)
        if graph is None:
            return None
        try:
            current = await graph.aget_state(
                {"configurable": {"thread_id": session_id}}
            )
        except Exception:
            return None
        values = getattr(current, "values", None) or {}
        owner = values.get("user_id")
        return str(owner) if owner else None

    async def decide(
        self,
        *,
        session_id: str,
        request_id: str,
        owner_id: str,
        approve: bool,
    ) -> str:
        decision = "approved" if approve else "rejected"
        if _native():
            return await self._decide_native(
                session_id=session_id, request_id=request_id, owner_id=owner_id, approve=approve
            )
        workflow = self._workflow
        graph = getattr(workflow, "graph", None)
        if (
            graph is None
            or not getattr(workflow, "_graph_initialized", False)
            or not getattr(workflow, "_graph_uses_checkpointer", False)
        ):
            return _NOT_READY

        config = {"configurable": {"thread_id": session_id}}
        async with self._lock_for(session_id):
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

            remaining = [
                item
                for item in pending
                if isinstance(item, dict)
                and str(item.get("request_id") or "") != request_id
            ]
            claimed = any(
                isinstance(item, dict) and str(item.get("request_id") or "") == request_id
                for item in pending
            )
            if not request_id or not claimed:
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
                    values={
                        "approval_decision": decision,
                        "pending_approvals": remaining,
                    },
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

            asyncio.create_task(
                _resume(), name=f"channel_approval_resume_{session_id}"
            )
            return f"{request_id} {'approved' if approve else 'denied'}"

    async def _decide_native(self, *, session_id: str, request_id: str, owner_id: str, approve: bool) -> str:
        """반환 문자열은 LangGraph 경로와 같다(게이트웨이·Q 계약, spec §5 경계 2)."""
        from neos.workflow.runtime.approvals import Refusal

        approvals = self._native_approvals()
        pending = await approvals.pending_for_session(session_id)
        if pending is None or not request_id:
            return _INVALID_REQUEST
        ticket = await approvals.decide(
            pending.work_id,
            request_id,
            "approved" if approve else "rejected",
            actor=owner_id or pending.user_id,
        )
        if isinstance(ticket, Refusal):
            return _INVALID_REQUEST
        await _mark_resolved_best_effort(request_id, owner_id)

        async def _resume() -> None:
            try:
                await approvals.resume(ticket)
            except Exception as error:  # noqa: BLE001
                logger.error("[RuntimeWorkflowApprovals] native resume failed: session=%s: %s", session_id, error)

        asyncio.create_task(_resume(), name=f"channel_approval_resume_{session_id}")
        return f"{request_id} {'approved' if approve else 'denied'}"
