"""재개 핸들러가 복원된 그래프를 쓰는가, 그리고 못 쓰면 무엇을 하는가.

핸들러 전체를 HTTP 로 돌리지 않고 그래프 선택 지점만 본다 -- 이 태스크가
바꾸는 것이 그것이고, 소유권·세션·스트림은 기존 테스트가 덮는다.
"""

import pytest
from fastapi import HTTPException

from neos.workflow.resume_graph import ResumeGraphUnavailable


@pytest.mark.asyncio
async def test_an_unavailable_resume_graph_becomes_a_503(monkeypatch):
    """정적으로 흐르지 않는다. 흐르면 사용자는 승인이 처리됐다고 보고
    실제로는 다른 파이프라인이 돈다(스펙 §2.1)."""
    from neos.api.handlers import approval_handlers

    async def _refuse(*args, **kwargs):
        raise ResumeGraphUnavailable("stored topology is no longer valid")

    monkeypatch.setattr(approval_handlers, "resume_graph_for", _refuse)

    with pytest.raises(HTTPException) as caught:
        await approval_handlers._resolve_resume_graph(
            state_values={"execution_topology": {"nodes": ["a"], "edges": []}},
            workflow=object(),
            checkpointer=None,
        )

    assert caught.value.status_code == 503
    assert "topology" in caught.value.detail


@pytest.mark.asyncio
async def test_a_resolvable_graph_is_returned_as_is(monkeypatch):
    from neos.api.handlers import approval_handlers

    sentinel = object()

    async def _resolve(*args, **kwargs):
        return sentinel

    monkeypatch.setattr(approval_handlers, "resume_graph_for", _resolve)

    graph = await approval_handlers._resolve_resume_graph(
        state_values={"execution_topology": None},
        workflow=object(),
        checkpointer=None,
    )

    assert graph is sentinel


@pytest.mark.asyncio
async def test_a_designed_resume_records_which_topology_it_used(monkeypatch, caplog):
    """해시를 남기지 않으면 스펙 §1의 관문을 프로덕션에서 확인할 수 없다.
    `graph_design_accepted` 의 topology_hash 와 조인할 수 있어야 한다.

    라벨(`"topology_hash"`)만 있고 값 계산이 깨진 변이는 "라벨이 있는가"만
    보는 단언을 통과한다 -- 그래서 이 테스트가 만든 토폴로지로 `topology_hash`
    를 직접 계산해 그 값이 로그 레코드에 실제로 실리는지까지 확인한다."""
    import logging

    from neos.api.handlers import approval_handlers
    from neos.workflow.graph_design_ledger import topology_hash
    from neos.workflow.topology import GRAPH_ENTRY_WRITES, GraphTopology, topology_to_payload

    topology = GraphTopology(
        nodes=("query_classifier", "response_generator"),
        edges=(
            ("__start__", "query_classifier"),
            ("query_classifier", "response_generator"),
            ("response_generator", "__end__"),
        ),
        initial_writes=GRAPH_ENTRY_WRITES,
    )
    sentinel = object()

    async def _resolve(*args, **kwargs):
        return sentinel

    monkeypatch.setattr(approval_handlers, "resume_graph_for", _resolve)

    with caplog.at_level(logging.INFO):
        await approval_handlers._resolve_resume_graph(
            state_values={"execution_topology": topology_to_payload(topology)},
            workflow=object(),
            checkpointer=None,
        )

    expected_hash = topology_hash(topology)
    assert any(expected_hash in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_resume_completed_event_carries_the_final_response(monkeypatch):
    """노드 경계 정규화 뒤 마지막 chunk 는 부분 갱신이다 -- 재개 결과는 접힌 상태에서 읽는다.

    마지막 노드가 전체 상태를 돌려줘도 변하지 않은 `final_response` 는 갱신에서
    빠진다. 마지막 chunk 만 보면 `completed` 가 빈 응답을 싣는다."""
    import asyncio
    from types import SimpleNamespace

    from neos.api.handlers import approval_handlers

    values = {
        "final_response": "승인 전에 만든 답",
        "pending_approvals": [{"request_id": "r1", "skill_name": "s"}],
    }

    class _Graph:
        checkpointer = None

        async def aget_state(self, config):
            return SimpleNamespace(values=values)

        async def aupdate_state(self, config, values):
            return None

        async def astream(self, _input, config=None):
            yield {"__interrupt__": ()}
            yield {"skill_executor": {"execution_steps": [{"step": 1}]}}
            yield {"research_harness": {"harness_verdict": "pass"}}  # final_response 는 변하지 않았다

    graph = _Graph()
    events: list[tuple[str, dict]] = []

    class _Streams:
        def get_session(self, session_id):
            return object()

        async def add_event(self, session_id, kind, payload):
            events.append((kind, payload))

    async def _owner(**kwargs):
        return {"skill_name": "s"}

    async def _noop(*args, **kwargs):
        return None

    async def _resolve(**kwargs):
        return graph

    monkeypatch.setattr(approval_handlers, "multi_agent_workflow", SimpleNamespace(
        _graph_initialized=True, _graph_uses_checkpointer=True, graph=graph))
    monkeypatch.setattr(approval_handlers, "stream_manager", _Streams())
    monkeypatch.setattr(approval_handlers, "_require_pending_approval_owner", _owner)
    monkeypatch.setattr(approval_handlers, "require_stream_session_owner", lambda *a, **k: None)
    monkeypatch.setattr(approval_handlers, "_resolve_resume_graph", _resolve)
    monkeypatch.setattr(approval_handlers, "_mark_approval_resolved", _noop)

    body = approval_handlers.ApprovalResponse(
        session_id="s1", request_id="r1", decision="approved", skill_name="s"
    )
    await approval_handlers.respond_to_approval(body, SimpleNamespace(user_id="u1"))
    for _ in range(50):
        if any(kind == "completed" for kind, _ in events):
            break
        await asyncio.sleep(0.01)

    assert ("completed", {"response": "승인 전에 만든 답"}) in events
