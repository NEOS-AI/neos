"""LangGraph 런타임의 알려진 결함 (spec 2026-10-13 §1.2 R1·R3·R4·R5).

`xfail(strict=True)` 다 -- 결함이 실행되는 증거로 남고, 누가 고치면 XPASS 가
실패로 바뀌어 이 표시를 지우게 만든다. Plan 3 이 LangGraph 와 함께 이 파일을 지운다.
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from neos.workflow.enums import WorkflowNode as N
from neos.workflow.state import SearchResult
from tests.workflow.support.stub_workflow import (
    SKIP_PATH_ROUTES,
    RecordingHandler,
    StubPlan,
    stub_workflow,
    user_input,
)

pytestmark = [pytest.mark.no_db, pytest.mark.asyncio]


@pytest.mark.xfail(strict=True, reason="R1: aget_tuple 이 CheckpointTuple 이 아니라 튜플을 돌려준다")
async def test_r1_checkpointer_returns_a_checkpoint_tuple() -> None:
    from langgraph.checkpoint.base import CheckpointTuple

    from neos.workflow.checkpointer import PostgreSQLCheckpointer

    with patch("neos.workflow.checkpointer.create_async_engine"):
        checkpointer = PostgreSQLCheckpointer(
            database_url="postgresql+asyncpg://t:t@localhost/t", table_name="t_checkpoints"
        )
    checkpointer._initialized = True
    row = MagicMock()
    row.checkpoint_id = "cp-1"
    row.created_at = datetime.now()
    row.metadata = {}
    row.checkpoint_data = {"v": 1, "channel_values": {}, "channel_versions": {}, "versions_seen": {}}
    session = AsyncMock()
    session.execute.return_value = MagicMock(fetchone=MagicMock(return_value=row))
    with patch.object(checkpointer, "get_session") as get_session:
        get_session.return_value.__aenter__.return_value = session
        saved = await checkpointer.aget_tuple({"configurable": {"thread_id": "s"}})
    assert isinstance(saved, CheckpointTuple)


@pytest.mark.xfail(strict=True, reason="R3: interrupt_before 가 GraphInterrupt 를 던지지 않아 승인 이벤트가 안 나간다")
async def test_r3_an_approval_gate_interrupts_and_asks(monkeypatch) -> None:
    from langgraph.checkpoint.memory import MemorySaver

    pending = [{"request_id": "apr_1"}]
    plan = StubPlan(
        nodes={N.SKILL_TOOL_SELECTOR.value: lambda s: {"pending_approvals": pending, "approval_decision": None}},
        routes={**SKIP_PATH_ROUTES, "_route_after_skill_tool_selector": "needs_approval"},
    )
    workflow = stub_workflow(
        monkeypatch, plan, flags={"execution_approval": True}, checkpointer=MemorySaver()
    )
    handler = RecordingHandler()
    result = await workflow.execute_workflow(user_input(), event_handler=handler, use_checkpointer=True)
    assert result.get("interrupted") is True
    assert result["pending_approvals"] == pending
    assert handler.approvals == [pending]


@pytest.mark.xfail(strict=True, reason="R4: final_state 가 마지막 노드의 부분 갱신이다")
async def test_r4_the_result_reads_the_whole_state(monkeypatch) -> None:
    plan = StubPlan(
        nodes={
            N.RESP_GENERATOR.value: lambda s: {
                "final_response": "답",
                "response_metadata": {},
                "execution_time_ms": 1,
                "execution_steps": [],
            },
            # 갱신분만 돌려주는 하네스 -- 고쳐진 노드의 모양이다.
            N.RESEARCH_HARNESS.value: lambda s: {"harness_verdict": "pass"},
        },
        routes=SKIP_PATH_ROUTES,
    )
    workflow = stub_workflow(monkeypatch, plan)
    result = await workflow.execute_workflow(
        user_input(), event_handler=RecordingHandler(), use_checkpointer=False
    )
    assert result["success"] is True
    assert result["response"] == "답"


@pytest.mark.xfail(strict=True, reason="R5: 전체 상태를 돌려주는 노드가 operator.add 필드를 불린다")
async def test_r5_full_state_returns_do_not_duplicate_accumulated_results(monkeypatch) -> None:
    item = SearchResult(source="web", title="A", content="a", url="https://a")
    seen: list[list] = []

    def harness(state):
        seen.append(list(state["search_results"]))
        return {**state, "harness_verdict": "pass"}

    plan = StubPlan(
        nodes={
            N.DIRECT_RESPONSE.value: lambda s: {"search_results": [item]},
            # 진짜 응답 생성기처럼 전체 상태를 돌려준다.
            N.RESP_GENERATOR.value: lambda s: {
                **s,
                "final_response": "답",
                "response_metadata": {},
                "execution_time_ms": 1,
            },
            N.RESEARCH_HARNESS.value: harness,
        },
        routes=SKIP_PATH_ROUTES,
    )
    workflow = stub_workflow(monkeypatch, plan)
    await workflow.execute_workflow(user_input(), event_handler=RecordingHandler(), use_checkpointer=False)
    assert seen == [[item]]
