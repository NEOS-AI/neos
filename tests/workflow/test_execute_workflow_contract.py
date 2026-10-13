"""`execute_workflow` 결과 계약 (spec 2026-10-13 §5 경계 1, §7.1).

웹 파이프라인·채널 게이트웨이(Q8 포함)·예약 러너가 이 dict 의 키를 읽는다. 런타임을
갈아도 이 키들이 같아야 dots(트랙 Q)가 영향을 받지 않는다.
"""

import pytest

from neos.workflow.enums import WorkflowNode as N
from tests.workflow.support.stub_workflow import (
    SKIP_PATH_ROUTES,
    RecordingHandler,
    StubPlan,
    stub_workflow,
    user_input,
)

pytestmark = [pytest.mark.no_db, pytest.mark.asyncio]

_SUCCESS_KEYS = {
    "success",
    "response",
    "metadata",
    "execution_time_ms",
    "quality_score",
    "errors",
    "cache_hit",
    "execution_steps",
    "retry_count",
    "channel_source",
}


def _answer(state):
    return {
        "final_response": "답",
        "response_metadata": {"k": "v"},
        "execution_time_ms": 7,
        "execution_steps": [{"step": "response_generation"}],
    }


def _harness_like_today(state):
    # 진짜 `_research_harness_node` 는 `{**state, **updates}` 를 돌려준다.
    return {**state, "harness_verdict": "pass", "harness_mode": "advisory"}


def _skip_plan(**nodes):
    base = {
        N.RESP_GENERATOR.value: _answer,
        N.RESEARCH_HARNESS.value: _harness_like_today,
    }
    base.update(nodes)
    return StubPlan(nodes=base, routes=SKIP_PATH_ROUTES)


async def test_a_successful_turn_returns_the_contract_keys(monkeypatch) -> None:
    workflow = stub_workflow(monkeypatch, _skip_plan())
    result = await workflow.execute_workflow(
        user_input(), event_handler=RecordingHandler(), use_checkpointer=False
    )
    assert _SUCCESS_KEYS <= set(result)
    assert result["success"] is True
    assert result["response"] == "답"
    assert result["metadata"] == {"k": "v"}
    assert result["cache_hit"] is False
    assert result["channel_source"] == "api"


async def test_a_gate_blocked_turn_reports_failure_with_the_blocked_text(monkeypatch) -> None:
    def blocked(state):
        return {
            **state,
            "harness_mode": "gate",
            "harness_verdict": "fail",
            "harness_failed_checks": ["citations"],
        }

    workflow = stub_workflow(monkeypatch, _skip_plan(**{N.RESEARCH_HARNESS.value: blocked}))
    result = await workflow.execute_workflow(
        user_input(), event_handler=RecordingHandler(), use_checkpointer=False
    )
    assert result["success"] is False
    assert "citations" in result["response"]
    assert result["blocked_response"] == "답"
    assert "research_harness_gate_failed" in result["errors"]


async def test_a_failing_node_returns_the_error_shape(monkeypatch) -> None:
    def boom(state):
        raise RuntimeError("노드 실패")

    workflow = stub_workflow(monkeypatch, _skip_plan(**{N.DIRECT_RESPONSE.value: boom}))
    handler = RecordingHandler()
    result = await workflow.execute_workflow(user_input(), event_handler=handler, use_checkpointer=False)
    assert result["success"] is False
    assert "노드 실패" in result["error"]
    assert {"partial_state", "cache_hit", "execution_time_ms"} <= set(result)
    assert handler.errors


async def test_progress_events_follow_the_nodes_actually_run(monkeypatch) -> None:
    workflow = stub_workflow(monkeypatch, _skip_plan())
    handler = RecordingHandler()
    await workflow.execute_workflow(user_input(), event_handler=handler, use_checkpointer=False)
    assert [name for name, _step, _max in handler.starts] == [
        N.REFINEMENT_CHECKER.value,
        N.CONVERSATION_CTX_PROC.value,
        N.QUERY_CLS.value,
        N.SKILL_TOOL_SELECTOR.value,
        N.DIRECT_RESPONSE.value,
        N.RESP_GENERATOR.value,
        N.RESEARCH_HARNESS.value,
    ]
    assert [step for _name, step, _max in handler.starts] == list(range(1, 8))
