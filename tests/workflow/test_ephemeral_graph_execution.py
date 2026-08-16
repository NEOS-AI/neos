"""`build_ephemeral_workflow` -- 검증을 통과한 토폴로지를 실행 가능한 그래프로.

Task 8 까지는 토폴로지를 설계·검증·기록할 뿐, 그 토폴로지로 실제 `StateGraph` 를
조립해 실행하는 코드가 없었다. 이 태스크는 그 마지막 이음매를 놓는다:
`NODE_CONTRACTS[name].handler` 로 각 노드의 핸들러를 찾아 `MultiAgentWorkflow`
인스턴스에 바인딩하고, 토폴로지의 정적 엣지대로 이어 붙여 컴파일한다.

가장 중요한 성질은 `test_the_compiled_static_graph_matches_its_pre_task_9_snapshot`
가 고정한다: `graph_design_enabled` 가 꺼져 있으면(기본값) 이 새 경로는 아예
타지 않고, 기존 정적 그래프의 배선은 바이트 단위로 그대로다. 실제로 컴파일한
정적 그래프의 노드·엣지 집합을 해시해, 이번 태스크의 코드 변경 **이전**에
캡처한 값과 비교한다 -- `_create_workflow_graph` 를 이번 태스크가 단 한 줄도
건드리지 않았다는 주장을, 손으로 짠 그래프 구조 스냅샷으로 검증 가능하게
만든다.

승인 게이트(`execution_approval`/`mission_approval`)는 정적 그래프에서
checkpointer + `interrupt_before` 로만 사람 승인을 기다린다.
`build_ephemeral_workflow` 는 이제 그 둘을 인자로 받아 정적 경로와 같은 방식
으로 `compile()` 에 넘긴다(I3). checkpointer 가 없거나, checkpointer 는
있어도 게이트 노드를 `interrupt_before` 에 넣지 않으면 여전히
`EphemeralApprovalGateUnsupported` 로 명시적으로 거부한다 --
`test_build_ephemeral_workflow_refuses_a_topology_with_an_approval_gate_and_
no_checkpointer` 가 그 남은 계약을 고정하고,
`test_build_ephemeral_workflow_honours_interrupt_before_with_a_checkpointer`
가 checkpointer + interrupt_before 를 제대로 주면 더는 거부되지 않고 그
설정이 실제로 컴파일된 그래프에 반영됨을 확인한다.
"""

import hashlib
import json
import sys
import types

import pytest

import neos.config.settings as settings_module

settings_module.settings.GOOGLE_API_KEY = "test-key"
settings_module.settings.OPENAI_API_KEY = "test-key"

# 다른 워크플로우 테스트(test_harness_graph_repair.py 등)와 같은 이유로,
# MultiAgentWorkflow 를 실제로 인스턴스화하려면 선택적 의존성 세 개를 가짜
# 모듈로 미리 꽂아 둬야 임포트가 죽지 않는다.
_youtube_module = types.ModuleType("youtube_transcript_api")
_youtube_module.YouTubeTranscriptApi = object
_youtube_errors_module = types.ModuleType("youtube_transcript_api._errors")
_youtube_errors_module.TranscriptsDisabled = Exception
_youtube_errors_module.NoTranscriptFound = Exception
_youtube_errors_module.VideoUnavailable = Exception
sys.modules.setdefault("youtube_transcript_api", _youtube_module)
sys.modules.setdefault("youtube_transcript_api._errors", _youtube_errors_module)

_googleapi_module = types.ModuleType("googleapiclient")
_googleapi_discovery_module = types.ModuleType("googleapiclient.discovery")
_googleapi_discovery_module.build = lambda *args, **kwargs: object()
_googleapi_errors_module = types.ModuleType("googleapiclient.errors")
_googleapi_errors_module.HttpError = Exception
sys.modules.setdefault("googleapiclient", _googleapi_module)
sys.modules.setdefault("googleapiclient.discovery", _googleapi_discovery_module)
sys.modules.setdefault("googleapiclient.errors", _googleapi_errors_module)

_isodate_module = types.ModuleType("isodate")
_isodate_module.parse_duration = lambda value: value
sys.modules.setdefault("isodate", _isodate_module)

from neos.workflow.enums import WorkflowNode  # noqa: E402
from neos.workflow.graph import (  # noqa: E402
    EphemeralApprovalGateUnsupported,
    MultiAgentWorkflow,
    build_ephemeral_workflow,
)
from neos.workflow.topology import END, START, GraphTopology  # noqa: E402

# `_create_workflow_graph(use_checkpointer=False)` 가 이번 태스크의 코드 변경
# 이전에 실제로 컴파일해 낸 정적 그래프의 (정렬된 노드 목록, 정렬된 엣지 목록)
# 을 표준 JSON 으로 인코딩해 sha256 한 값. 이 해시가 바뀌면
# `_create_workflow_graph` 의 배선(add_node/add_edge 호출 순서나 대상)이
# 달라졌다는 뜻이다.
#
# 재현/재캡처 방법 (그래프 배선을 실제로 바꾼 뒤 이 상수를 의도적으로
# 갱신해야 할 때 -- 이 파일이 유일한 재현 경로다, 리포트에만 있으면 안 된다):
#
#     GOOGLE_API_KEY=test-key OPENAI_API_KEY=test-key \
#       .venv/bin/python -c "
#     import asyncio
#     from neos.workflow.graph import MultiAgentWorkflow
#
#     async def main():
#         wf = MultiAgentWorkflow()
#         compiled = await wf._create_workflow_graph(use_checkpointer=False)
#         g = compiled.get_graph()
#         nodes = sorted(g.nodes)
#         edges = sorted((e.source, e.target) for e in g.edges)
#         import hashlib, json
#         payload = json.dumps(
#             {'nodes': nodes, 'edges': edges}, sort_keys=True
#         ).encode()
#         print(hashlib.sha256(payload).hexdigest())
#     asyncio.run(main())
#     "
#
# (실행 전 이 파일 상단의 youtube_transcript_api/googleapiclient/isodate
# 가짜 모듈 등록을 그대로 앞에 붙여야 임포트가 죽지 않는다.) 출력된 해시로
# 아래 상수를 교체하고, 왜 배선이 바뀌었는지를 커밋 메시지에 남긴다 -- 이
# 테스트가 실패했다고 해시만 바꿔치기하면 "정적 그래프가 안 바뀌었다" 는
# 보증 자체가 조용히 사라진다.
# 2026-08-16 (G1-a): 위 스크립트로 재캡처했다. 정적 배선이 **의도적으로**
# 바뀌었다 -- `skip_orchestrators` 가 `response_generator` 대신
# `direct_response` 로 가고, `direct_response -> response_generator` 엣지가
# 생겼다. 검색이 필요 없다고 판정된 질의(인사·잡담)가 요약할 결과가 없다는
# 이유로 사과문을 받던 것이 G1-a 이며, 그 경로에 답을 만드는 노드가 하나도
# 없었던 것이 원인이다. 이전 값: 79fada0e...
_STATIC_GRAPH_SNAPSHOT_SHA256 = (
    "a78abc14a1c0cdea097f4f05e9fc03345258d5a518e628f473b53300205afa37"
)


@pytest.fixture(autouse=True)
def no_ambient_embedding_backend(monkeypatch):
    """쿼리 분류가 임베딩을 만들지 못하게 한다 -- 이 파일이 재는 것은 배선이다.

    `test_an_ephemeral_graph_can_actually_run` 은 진짜 `QUERY_CLS` 핸들러를
    돌리고, 그 경로는 이렇게 흐른다:

        _classify_query_node -> classify_query -> _generate_embedding
          -> embedding_manager.get_embedding -> cache_manager.get -> Redis

    개발 기계에는 Redis 가 떠 있어서 통과했지만 CI 에는 없다. 2026-08-16 dev
    에서 `workflow-tests` 가 이것으로 붉었다. 죽은 포트를 물려 실측하니
    `tests/workflow` + `tests/api` 1,457건 중 **Redis 에 실제로 기대는 것은 이
    한 건뿐**이라, 잡에 Redis 를 붙이는 대신 의존을 끊는다.

    같은 자리가 실제 임베딩 프로바이더도 부른다(`provider.get_embedding`).
    캐시가 비면 API 키가 있는 기계에서 **진짜 호출이 나간다** -- 게이트에
    돈과 네트워크를 섞지 않는다는 같은 이유로 여기서 함께 끊는다.
    """
    from neos.utils.embeddings import embedding_manager

    async def fake_get_embedding(text, use_cache=True):
        return [0.0] * 8

    monkeypatch.setattr(embedding_manager, "get_embedding", fake_get_embedding)


def _harness(*, graph_design_enabled: bool = False) -> MultiAgentWorkflow:
    """실제 `MultiAgentWorkflow` 인스턴스를 만들되, 설계 플래그를 명시적으로
    맞춰 준다. 오늘은 이 플래그를 읽어 인스턴스 상태를 채우는 코드가 없어
    결과에 영향을 주지 않지만(Task 9 의 의도적 범위 제한 -- 실제 배선은
    다음 태스크), 앞으로 그 배선이 생겼을 때도 이 헬퍼 하나만 고치면
    되도록 지금부터 신호를 흘려 둔다."""

    settings_module.settings.config.workflow.graph_design_enabled = graph_design_enabled
    return MultiAgentWorkflow()


def _static_graph_snapshot_hash(workflow: MultiAgentWorkflow) -> str:
    """정적 그래프를 실제로 컴파일해 노드·엣지 집합의 안정적 해시를 낸다."""

    import asyncio

    compiled = asyncio.run(workflow._create_workflow_graph(use_checkpointer=False))
    graph = compiled.get_graph()
    nodes = sorted(graph.nodes)
    edges = sorted((edge.source, edge.target) for edge in graph.edges)
    payload = json.dumps({"nodes": nodes, "edges": edges}, sort_keys=True).encode(
        "utf-8"
    )
    return hashlib.sha256(payload).hexdigest()


def test_an_ephemeral_graph_wires_only_the_designed_nodes() -> None:
    topology = GraphTopology(
        nodes=(WorkflowNode.QUERY_CLS.value, WorkflowNode.RESP_GENERATOR.value),
        edges=(
            (START, WorkflowNode.QUERY_CLS.value),
            (WorkflowNode.QUERY_CLS.value, WorkflowNode.RESP_GENERATOR.value),
            (WorkflowNode.RESP_GENERATOR.value, END),
        ),
    )
    compiled = build_ephemeral_workflow(_harness(), topology)
    assert set(compiled.get_graph().nodes) >= set(topology.nodes)


def test_an_ephemeral_graph_can_actually_run() -> None:
    """조립만 되고 실행은 안 되는 그래프라면 "ephemeral 실행 배선" 이라는
    이 태스크의 존재 이유가 없다 -- 실제로 `ainvoke` 까지 돌려 확인한다."""

    import asyncio

    topology = GraphTopology(
        nodes=(WorkflowNode.QUERY_CLS.value, WorkflowNode.RESP_GENERATOR.value),
        edges=(
            (START, WorkflowNode.QUERY_CLS.value),
            (WorkflowNode.QUERY_CLS.value, WorkflowNode.RESP_GENERATOR.value),
            (WorkflowNode.RESP_GENERATOR.value, END),
        ),
    )
    workflow = _harness()
    compiled = build_ephemeral_workflow(workflow, topology)

    state = workflow._create_initial_state(
        {"query": "안녕하세요", "user_id": "u1", "session_id": "s1"}
    )

    result = asyncio.run(compiled.ainvoke(state, {"recursion_limit": 10}))
    assert result is not None


def _gated_topology(gated_node: str) -> GraphTopology:
    return GraphTopology(
        nodes=(WorkflowNode.QUERY_CLS.value, gated_node),
        edges=(
            (START, WorkflowNode.QUERY_CLS.value),
            (WorkflowNode.QUERY_CLS.value, gated_node),
            (gated_node, END),
        ),
    )


@pytest.mark.parametrize(
    "gated_node",
    [WorkflowNode.EXECUTION_APPROVAL.value, WorkflowNode.MISSION_APPROVAL.value],
)
def test_build_ephemeral_workflow_refuses_a_topology_with_an_approval_gate_and_no_checkpointer(
    gated_node: str,
) -> None:
    """정적 그래프에서 이 두 노드는 checkpointer + interrupt_before 로만
    사람 승인을 기다린다. checkpointer 없이 컴파일하면 interrupt_before 를
    넘겨도 상태가 저장되지 않아 재개할 지점이 없다 -- build_ephemeral_workflow
    는 그 토폴로지를 조용히 컴파일해 승인 게이트를 잃어버리는 대신 명시적으로
    거부해야 한다(I3, checkpointer 가 없는 경우로 범위가 좁아진 refusal)."""

    with pytest.raises(EphemeralApprovalGateUnsupported):
        build_ephemeral_workflow(_harness(), _gated_topology(gated_node))


@pytest.mark.parametrize(
    "gated_node",
    [WorkflowNode.EXECUTION_APPROVAL.value, WorkflowNode.MISSION_APPROVAL.value],
)
def test_build_ephemeral_workflow_refuses_a_checkpointer_that_omits_the_gated_node(
    gated_node: str,
) -> None:
    """checkpointer 를 줘도 게이트 노드를 interrupt_before 에 넣지 않으면
    그 노드는 인터럽트 없이 그냥 지나가며 실행돼 사람 승인이 조용히
    생략된다 -- 이 경우도 여전히 거부해야 한다."""

    from langgraph.checkpoint.memory import MemorySaver

    with pytest.raises(EphemeralApprovalGateUnsupported):
        build_ephemeral_workflow(
            _harness(),
            _gated_topology(gated_node),
            checkpointer=MemorySaver(),
            interrupt_before=(),
        )


@pytest.mark.parametrize(
    "gated_node",
    [WorkflowNode.EXECUTION_APPROVAL.value, WorkflowNode.MISSION_APPROVAL.value],
)
def test_build_ephemeral_workflow_honours_interrupt_before_with_a_checkpointer(
    gated_node: str,
) -> None:
    """I3: checkpointer 와 그 안에 게이트 노드를 담은 interrupt_before 를
    함께 주면, 더 이상 거부되지 않고 정적 경로(`workflow.compile(checkpointer=
    ..., interrupt_before=...)`)와 똑같은 방식으로 컴파일된다 -- 컴파일된
    그래프의 `interrupt_before_nodes` 로 실제로 그 설정이 반영됐는지까지
    확인한다(조립만 되고 설정이 무시되는 것과 구별하기 위해)."""

    from langgraph.checkpoint.memory import MemorySaver

    compiled = build_ephemeral_workflow(
        _harness(),
        _gated_topology(gated_node),
        checkpointer=MemorySaver(),
        interrupt_before=[gated_node],
    )
    assert list(compiled.interrupt_before_nodes) == [gated_node]


def test_the_static_path_does_not_carry_a_shared_designed_topology_slot() -> None:
    """`_designed_topology` 를 인스턴스 속성으로 두면, 오래 살아남고 요청들이
    공유하는 `MultiAgentWorkflow` 위에 질의별 값을 얹는 꼴이라 동시 요청
    두 개가 서로의 설계를 덮어쓰는 경합을 만든다(fix round 1/5, 리뷰 지적).
    그래서 그런 슬롯을 아예 두지 않는다 -- 이 테스트는 그 부재를 고정해,
    나중에 누군가 실제 배선을 만들며 인스턴스 속성을 다시 들이는 것을
    막는다. 설계된 토폴로지는 호출 스코프로만 전달돼야 한다."""

    harness = _harness(graph_design_enabled=False)
    assert not hasattr(harness, "_designed_topology")


def test_the_compiled_static_graph_matches_its_pre_task_9_snapshot() -> None:
    """`_create_workflow_graph` 가 실제로 컴파일해 내는 노드·엣지 집합이
    이번 태스크의 코드 변경 이전에 캡처한 스냅샷과 정확히 같은지를 해시로
    고정한다. `_create_workflow_graph`/`_ensure_graph_initialized` 는 이
    태스크에서 단 한 줄도 바뀌지 않았으므로 항상 같아야 한다."""

    harness = _harness(graph_design_enabled=False)
    actual_hash = _static_graph_snapshot_hash(harness)
    assert actual_hash == _STATIC_GRAPH_SNAPSHOT_SHA256, (
        "정적 그래프(_create_workflow_graph)가 컴파일해 내는 노드/엣지 집합이 "
        "바뀌었다. graph_design 관련 코드는 이 그래프를 절대 건드리지 않아야 "
        "하므로, 이 실패는 (a) 이 태스크의 변경이 실수로 정적 배선에 영향을 "
        "줬거나 (b) 다른 누군가 정적 그래프 배선을 의도적으로 바꿨다는 뜻이다. "
        "(b) 라면 이 파일 상단의 '재현/재캡처 방법' 주석에 있는 스크립트로 "
        "새 해시를 다시 캡처해 _STATIC_GRAPH_SNAPSHOT_SHA256 을 갱신하고, "
        "무엇이 왜 바뀌었는지 커밋 메시지에 남긴다."
    )
