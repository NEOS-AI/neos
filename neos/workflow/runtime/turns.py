"""턴의 앞뒤 -- 세션 읽기·병합·저장, 작업 시작·중단·완료 (spec 2026-10-13 §4.3·§4.4).

러너는 대화 개념을 모른다. 이 모듈이 `execute_workflow` 의 시작과 끝에 붙어 "이번 턴" 의 의미를
준다. LangGraph 런타임은 `NULL_TURN` 을 쓴다 -- 저장은 그쪽 체크포인터가 한다.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from neos.workflow.runtime.sessions import SessionConflict, SessionStore, carry, trim
from neos.workflow.runtime.work import WorkLifecycle, entry_and_delivery

logger = logging.getLogger(__name__)


class TurnHandle(Protocol):
    work_id: str | None

    async def interrupted(self, state: Mapping[str, Any], next_node: str) -> None: ...

    async def completed(self, state: Mapping[str, Any], result: Mapping[str, Any]) -> None: ...

    async def failed(self, error: str) -> None: ...


@dataclass(frozen=True)
class TurnStart:
    state: dict[str, Any]
    start_at: str | None
    handle: Any


class ResumeUnavailable(RuntimeError):
    pass


class _NullTurn:
    work_id = None

    async def interrupted(self, state, next_node) -> None:
        return None

    async def completed(self, state, result) -> None:
        return None

    async def failed(self, error) -> None:
        return None


NULL_TURN = _NullTurn()


def _count(name: str, **labels: str) -> None:
    try:
        from neos.observability.metrics import metrics

        counter = getattr(metrics, name)
        (counter.labels(**labels) if labels else counter).inc()
    except Exception:  # noqa: BLE001 -- 계측 실패가 턴을 막지 않는다
        logger.debug("%s unavailable", name, exc_info=True)


class _NativeHandle:
    def __init__(self, turns: "NativeTurns", *, session_id: str, user_id: str, version: int | None, work_id: str, stateful: bool) -> None:
        self._turns = turns
        self._session_id = session_id
        self._user_id = user_id
        self._version = version
        self.work_id = work_id
        self._stateful = stateful

    async def _save(self, state: Mapping[str, Any]) -> None:
        trimmed, cut = trim(state, self._turns.max_carried_items)
        for field, dropped in cut.items():
            for _ in range(dropped):
                _count("workflow_session_trimmed_total", field=field)
        self._version = await self._turns.sessions.save(
            self._session_id, user_id=self._user_id, state=trimmed, expected_version=self._version
        )

    async def interrupted(self, state: Mapping[str, Any], next_node: str) -> None:
        # 승인 대기 저장이 실패하면 재개할 지점이 없다 -- 예외를 올려 그 턴을 오류로 끝낸다(spec §4.3).
        await self._save(state)
        pending = list(state.get("pending_approvals") or [])
        await self._turns.lifecycle.interrupt(
            self.work_id,
            {
                "next_node": next_node,
                "request_ids": [str(item.get("request_id")) for item in pending if isinstance(item, Mapping)],
                "pending": pending,
            },
        )

    async def completed(self, state: Mapping[str, Any], result: Mapping[str, Any]) -> None:
        if self._stateful:
            try:
                await self._save(state)
            except SessionConflict:
                logger.warning("workflow session lost a save race: %s", self._session_id)
                _count("workflow_session_conflicts_total")
            except Exception:  # noqa: BLE001 -- 응답은 이미 만들어졌다
                logger.warning("workflow session save failed: %s", self._session_id, exc_info=True)
                _count("workflow_session_failures_total", op="save")
        try:
            await self._turns.lifecycle.complete(
                self.work_id,
                {"final_response": result.get("response"), "author": None, "verified_by": None},
            )
        except Exception:  # noqa: BLE001 -- 응답은 이미 만들어졌다; 작업 기록 실패가 답을 버리지 않는다
            logger.warning("work completion could not be recorded: %s", self.work_id, exc_info=True)
            _count("workflow_work_failures_total", op="complete")

    async def failed(self, error: str) -> None:
        await self._turns.lifecycle.fail(self.work_id, error)


class NativeTurns:
    def __init__(self, sessions: SessionStore, lifecycle: WorkLifecycle, *, max_carried_items: int) -> None:
        self.sessions = sessions
        self.lifecycle = lifecycle
        self.max_carried_items = max_carried_items

    async def begin(self, user_input: Mapping[str, Any], initial_state: Mapping[str, Any], *, stateful: bool) -> TurnStart:
        session_id = str(user_input["session_id"])
        user_id = str(user_input.get("user_id") or "")
        saved = None
        if stateful:
            try:
                saved = await self.sessions.load(session_id)
            except Exception:  # noqa: BLE001 -- 디코드·DB 실패는 빈 이어받기로 진행한다(spec §4.3)
                logger.warning("workflow session load failed: %s", session_id, exc_info=True)
                _count("workflow_session_failures_total", op="load")
                # 읽지 못한 행을 지운다 -- 남겨 두면 이 핸들의 version=None 저장이 매번
                # SessionConflict 로 져서 이어받기가 영영 저장되지 않고 승인 게이트가 실패한다.
                try:
                    await self.sessions.reset(session_id)
                except Exception:  # noqa: BLE001 -- 지우지 못해도 이번 턴은 새로 시작한다
                    logger.warning("workflow session reset failed: %s", session_id, exc_info=True)
                    _count("workflow_session_failures_total", op="reset")
        state = carry(saved.state if saved else None, initial_state)
        entry, delivery = entry_and_delivery(user_input)
        work_id = await self.lifecycle.start(
            entry, "workflow", user_id=user_id, session_id=session_id, delivery=delivery
        )
        handle = _NativeHandle(
            self, session_id=session_id, user_id=user_id,
            version=saved.version if saved else None, work_id=work_id, stateful=stateful,
        )
        return TurnStart(state=state, start_at=None, handle=handle)

    async def begin_resume(self, ticket: Any, runtime_keys: Mapping[str, Any]) -> TurnStart:
        """초기 상태를 다시 만들지 않는다(불변식 3) -- 저장된 상태 위에 결정과 런타임 키만 얹는다."""
        saved = await self.sessions.load(ticket.session_id)
        if saved is None:
            raise ResumeUnavailable(f"{ticket.session_id}: 저장된 세션이 없다")
        pending = [
            item for item in (saved.state.get("pending_approvals") or [])
            if not (isinstance(item, Mapping) and str(item.get("request_id")) == ticket.request_id)
        ]
        state = {
            **saved.state,
            "approval_decision": ticket.decision,
            "pending_approvals": pending,
            **dict(runtime_keys),
        }
        handle = _NativeHandle(
            self, session_id=ticket.session_id, user_id=saved.user_id,
            version=saved.version, work_id=ticket.work_id, stateful=True,
        )
        return TurnStart(state=state, start_at=ticket.next_node, handle=handle)
