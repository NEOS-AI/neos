"""승인 서비스 (spec 2026-10-13 §4.5) -- 그래프 객체가 아니라 `workflow_runs` 행을 읽는다.

그래서 어느 프로세스에서든 동작한다(웹·채널·워커의 타임아웃이 같은 경로). 결정은 작업 행을 CAS
로 바꾸고(같은 결정 두 번은 하나만 이긴다), 재개 티켓이 결정을 나른다. 재개는 저장된 세션 위에서
게이트 노드부터 러너를 돌리고 `execute_workflow` 와 같은 결과 dict 를 낸다.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from neos.workflow.runtime.work import WorkConflict, WorkLifecycle


@dataclass(frozen=True)
class PendingApproval:
    work_id: str
    user_id: str
    session_id: str
    request_ids: tuple[str, ...]
    pending: list


@dataclass(frozen=True)
class ResumeTicket:
    work_id: str
    session_id: str
    user_id: str
    next_node: str
    decision: str
    request_id: str
    # 승인 대기를 저장한 세션 버전 -- 재개는 세션이 그때 그대로일 때만 돈다(옛 행은 None → 거절).
    session_version: int | None = None


@dataclass(frozen=True)
class Refusal:
    reason: Literal["expired", "unknown_request", "not_owner", "conflict"]


class WorkflowApprovals:
    def __init__(self, workflow: Any, lifecycle: WorkLifecycle) -> None:
        self._workflow = workflow
        self._lifecycle = lifecycle

    async def pending_for_session(self, session_id: str) -> PendingApproval | None:
        record = await self._lifecycle.store.waiting_for_session(session_id)
        if record is None or not record.pending:
            return None
        return PendingApproval(
            work_id=record.work_id,
            user_id=record.user_id,
            session_id=str(record.session_id),
            request_ids=tuple(str(item) for item in record.pending.get("request_ids") or ()),
            pending=list(record.pending.get("pending") or []),
        )

    async def decide(
        self, work_id: str, request_id: str, decision: str, actor: str | None
    ) -> ResumeTicket | Refusal:
        """`actor=None` 은 시스템(타임아웃)이다 -- 소유자 검사를 건너뛴다."""
        record = await self._lifecycle.store.get(work_id)
        if record is None or record.status != "waiting_approval" or not record.pending:
            return Refusal("expired")
        if request_id not in (record.pending.get("request_ids") or []):
            return Refusal("unknown_request")
        if actor is not None and actor != record.user_id:
            return Refusal("not_owner")
        try:
            await self._lifecycle.claim(work_id, expected_version=record.version)
        except WorkConflict:
            return Refusal("conflict")
        return ResumeTicket(
            work_id=work_id,
            session_id=str(record.session_id),
            user_id=record.user_id,
            next_node=str(record.pending["next_node"]),
            decision=decision,
            request_id=request_id,
            session_version=record.pending.get("session_version"),
        )

    async def resume(self, ticket: ResumeTicket, event_handler: Any = None) -> Mapping[str, Any]:
        return await self._workflow.execute_workflow(
            {"user_id": ticket.user_id, "session_id": ticket.session_id, "query": ""},
            event_handler,
            use_checkpointer=True,
            resume=ticket,
        )

    async def expire(self, session_id: str, request_id: str) -> bool:
        """타임아웃 -- 최신 대기 행이 아니라 그 request_id 를 가진 대기 행을 닫는다."""
        record = await self._lifecycle.store.waiting_by_request(session_id, request_id)
        if record is None:
            return False
        try:
            await self._lifecycle.expire(record.work_id, expected_version=record.version)
        except WorkConflict:
            return False
        return True
