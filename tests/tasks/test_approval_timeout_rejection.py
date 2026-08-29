"""승인 타임아웃 자동 거부가 **재개와 같은 그래프**에 쓴다.

`_inject_timeout_rejection` 은 이 저장소에 남아 있던 마지막 resume-adjacent
write 다. 핸들러 경로(`approval_handlers.respond_to_approval`)는
`resume_graph_for` 를 거치도록 바뀌었지만 이 Celery beat 경로는 정적 그래프에
그대로 썼다 -- 로드맵 §15.3 H3 ②의 붉은 상자가 "플래그를 켜기 전에 반드시
닫을 것" 으로 적어 둔 항목이다.

**왜 정적 그래프에 쓰면 안 되는가.** LangGraph 의 `update_state` 는 업데이트를
수행하는 **그래프**로 `as_node` 를 풀고 후속 트리거 채널을 올린다. 설계된 run
에서 정적 그래프로 쓰면 정적 후속 노드를 트리거하거나 `InvalidUpdateError` 가
나는데, 그 예외는 이 함수가 들고 있던 `except Exception ... non-critical` 에
삼켜졌다. §3.2가 이 저장소의 관통 주제로 적은 "모든 실패가 성공처럼 보였다"
의 타임아웃 판이다.

**테스트 이중성의 경계.** 정적 그래프만 대역이고(`_recording_graph`),
`resume_graph_for`·`build_ephemeral_workflow`·`validate_topology` 는 전부
실물이다. 대역을 쓰는 이유는 하나뿐이다 -- 정적 그래프가 **쓰기를 받았는지**
를 봐야 하는데, 실물에 쓰면 그것을 관측할 자리가 없다. 같은 코드 경로에 대해
`tests/api/handlers/test_approval_authorization.py` 가 이미 쓰는 패턴이다.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langgraph.checkpoint.memory import MemorySaver

from neos.tasks.scheduled_task_runner import _inject_timeout_rejection
from neos.workflow.graph import MultiAgentWorkflow
from neos.workflow.topology import (
    GRAPH_ENTRY_WRITES,
    GraphTopology,
    topology_to_payload,
)

_REQUEST_ID = "req-timeout-1"
_SESSION_ID = "s-timeout"


def _chain_topology(nodes: tuple[str, ...]) -> GraphTopology:
    return GraphTopology(
        nodes=nodes,
        edges=(
            ("__start__", nodes[0]),
            *((nodes[i], nodes[i + 1]) for i in range(len(nodes) - 1)),
            (nodes[-1], "__end__"),
        ),
        initial_writes=GRAPH_ENTRY_WRITES,
    )


# 노드 하나짜리 설계다. 시나리오에 맞는 노드이면서(`execution_approval` 은
# 승인 게이트다) `requires` 가 비어 있어 단독으로 검증을 통과하고, 노드가
# 하나뿐이라 이어지는 `aupdate_state` 가 `as_node` 없이도 모호하지 않다 --
# LangGraph 는 `as_node` 를 체크포인트의 `versions_seen` 에서 푸는데, 실제로
# 실행된 적 없는 합성 체크포인트에는 그 값이 비어 있기 때문이다.
_DESIGNED = _chain_topology(("execution_approval",))
# 멈춘 뒤 배포가 노드를 없앤 경우. `validate_topology` 가 거부한다.
_STALE = _chain_topology(("node_that_no_longer_exists",))


def _recording_graph(saver, *, values):
    """정적 그래프 대역. 쓰기를 받았는지 보려고 존재한다."""
    return SimpleNamespace(
        aget_state=AsyncMock(return_value=SimpleNamespace(values=values)),
        aupdate_state=AsyncMock(),
        checkpointer=saver,
    )


async def _workflow_stopped_at_approval(monkeypatch, *, topology_payload):
    """승인 게이트에서 멈춘 run 을 재현하고 전역 이름에 꽂는다.

    `_inject_timeout_rejection` 은 호출 시점에 `neos.workflow.graph` 에서
    `multi_agent_workflow` 를 임포트하므로 **모듈이 들고 있는 이름**을 바꾼다
    (§7.4 가 산 교훈: 가로챌 곳은 공유 모듈 자체가 아니라 모듈이 들고 있는
    이름이다). `monkeypatch` 가 테스트 경계에서 되돌린다.
    """
    saver = MemorySaver()

    async def _fake_get_checkpointer():
        return saver

    monkeypatch.setattr("neos.workflow.graph.get_checkpointer", _fake_get_checkpointer)

    workflow = MultiAgentWorkflow()
    await workflow._ensure_graph_initialized(use_checkpointer=True)

    values = {
        "pending_approvals": [{"request_id": _REQUEST_ID, "skill_name": "some_skill"}],
        "execution_topology": topology_payload,
    }
    graph = _recording_graph(saver, values=values)
    monkeypatch.setattr(workflow, "graph", graph)
    monkeypatch.setattr("neos.workflow.graph.multi_agent_workflow", workflow)
    return workflow, graph, saver


def _spy_on_ephemeral_builds(monkeypatch) -> list:
    """설계된 그래프를 실제로 지었는지, 그리고 무엇을 지었는지 본다."""
    from neos.workflow import graph as graph_module

    built = []
    real = graph_module.build_ephemeral_workflow

    def _recording(*args, **kwargs):
        compiled = real(*args, **kwargs)
        built.append(compiled)
        return compiled

    monkeypatch.setattr(graph_module, "build_ephemeral_workflow", _recording)
    return built


@pytest.mark.asyncio
async def test_a_designed_run_is_rejected_on_the_rebuilt_graph(monkeypatch):
    """설계된 run 의 타임아웃 거부는 **다시 지은** 그래프에 쓴다.

    정적 그래프가 쓰기를 받지 않았다는 단언이 이 테스트의 요점이다 -- 거부가
    기록됐다는 것만 보면 어느 그래프에 기록됐는지 구별하지 못한다.
    """
    _, static_graph, _ = await _workflow_stopped_at_approval(
        monkeypatch, topology_payload=topology_to_payload(_DESIGNED)
    )
    built = _spy_on_ephemeral_builds(monkeypatch)

    injected = await _inject_timeout_rejection(
        session_id=_SESSION_ID, request_id=_REQUEST_ID
    )

    assert injected is True
    static_graph.aupdate_state.assert_not_awaited()
    assert len(built) == 1
    assert set(built[0].nodes) == {"execution_approval", "__start__"}
    state = await built[0].aget_state(
        {"configurable": {"thread_id": _SESSION_ID}}
    )
    assert state.values["approval_decision"] == "rejected"


@pytest.mark.asyncio
async def test_a_static_run_is_rejected_on_the_static_graph(monkeypatch):
    """정적 run 은 지금 동작 그대로다 -- 이 변경이 정적 경로까지 새로 짓기
    시작하면 안 된다."""
    _, static_graph, _ = await _workflow_stopped_at_approval(
        monkeypatch, topology_payload=None
    )
    built = _spy_on_ephemeral_builds(monkeypatch)

    injected = await _inject_timeout_rejection(
        session_id=_SESSION_ID, request_id=_REQUEST_ID
    )

    assert injected is True
    assert built == []
    static_graph.aupdate_state.assert_awaited_once_with(
        config={"configurable": {"thread_id": _SESSION_ID}},
        values={"approval_decision": "rejected"},
    )


@pytest.mark.asyncio
async def test_an_unrestorable_topology_writes_nothing(monkeypatch):
    """복원할 수 없으면 **정적 그래프로 내려가지 않는다.**

    내려가면 사용자에게는 타임아웃이 처리된 것으로 보이면서 설계가 의도한
    것과 다른 파이프라인이 트리거된다 -- `resume_graph.py` 독스트링이 재개에
    대해 적은 것과 같은 실패다. 쓰지 않는 쪽이 옳다: 결정이 없으면 상태의
    `pending_approvals` 가 그대로 남아 사실과 어긋나지 않는다.
    """
    _, static_graph, _ = await _workflow_stopped_at_approval(
        monkeypatch, topology_payload=topology_to_payload(_STALE)
    )

    injected = await _inject_timeout_rejection(
        session_id=_SESSION_ID, request_id=_REQUEST_ID
    )

    assert injected is False
    static_graph.aupdate_state.assert_not_awaited()


@pytest.mark.asyncio
async def test_an_already_decided_run_is_not_counted_as_a_rejection(monkeypatch):
    """건너뛴 것은 거부한 것이 아니다.

    반환값이 `rejected_count` 를 정한다. 건너뜀을 성공으로 세면
    "Auto-rejected N개" 의 N 이 실제 주입 수보다 커진다 -- 이 함수가 모든
    예외를 삼키던 시절 그 로그가 정확히 그랬다(바깥 루프의 try/except 가
    죽은 코드였다).
    """
    _, static_graph, _ = await _workflow_stopped_at_approval(
        monkeypatch, topology_payload=None
    )
    static_graph.aget_state.return_value.values["approval_decision"] = "approved"

    injected = await _inject_timeout_rejection(
        session_id=_SESSION_ID, request_id=_REQUEST_ID
    )

    assert injected is False
    static_graph.aupdate_state.assert_not_awaited()
