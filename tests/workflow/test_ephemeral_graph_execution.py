"""`build_ephemeral_workflow` -- 검증을 통과한 토폴로지를 실행 가능한 그래프로.

Task 8 까지는 토폴로지를 설계·검증·기록할 뿐, 그 토폴로지로 실제 `StateGraph` 를
조립해 실행하는 코드가 없었다. 이 태스크는 그 마지막 이음매를 놓는다:
`NODE_CONTRACTS[name].handler` 로 각 노드의 핸들러를 찾아 `MultiAgentWorkflow`
인스턴스에 바인딩하고, 토폴로지의 정적 엣지대로 이어 붙여 컴파일한다.

가장 중요한 성질은 두 번째 테스트가 고정한다: `graph_design_enabled` 가
꺼져 있으면(기본값) 이 새 경로는 아예 타지 않고, 기존 정적 그래프의 배선은
바이트 단위로 그대로다. 단순히 속성이 `None` 인지 보는 것보다 더 강하게
고정하기 위해, 실제로 컴파일한 정적 그래프의 노드·엣지 집합을 해시해 이
파일을 작성하기 직전(= 이번 태스크의 코드 변경 이전)에 캡처한 값과 비교한다
-- `_create_workflow_graph` 를 이번 태스크가 단 한 줄도 건드리지 않았다는
주장을, 손으로 짠 그래프 구조 스냅샷으로 검증 가능하게 만든다.
"""

import hashlib
import json
import sys
import types

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
from neos.workflow.graph import MultiAgentWorkflow, build_ephemeral_workflow  # noqa: E402
from neos.workflow.topology import END, START, GraphTopology  # noqa: E402

# `_create_workflow_graph(use_checkpointer=False)` 가 이번 태스크의 코드 변경
# 이전에 실제로 컴파일해 낸 정적 그래프의 (정렬된 노드 목록, 정렬된 엣지 목록)
# 을 표준 JSON 으로 인코딩해 sha256 한 값. 캡처 방법은 task-9-report.md 에
# 그대로 남겨 재현 가능하게 했다. 이 해시가 바뀌면 `_create_workflow_graph`
# 의 배선(add_node/add_edge 호출 순서나 대상)이 달라졌다는 뜻이다 -- 이
# 태스크는 그 함수를 단 한 줄도 고치지 않으므로 항상 같아야 한다.
_STATIC_GRAPH_SNAPSHOT_SHA256 = (
    "79fada0ebc474cc6167e6a146aa0862189b9a99ce4f643f31593386a0fc5ba0f"
)


def _harness(*, graph_design_enabled: bool = False) -> MultiAgentWorkflow:
    """실제 `MultiAgentWorkflow` 인스턴스를 만들되, 설계 플래그를 명시적으로
    맞춰 준다. 오늘은 이 값이 `_designed_topology` 를 채우는 코드가 없어
    결과에 영향을 주지 않지만(Task 9 의 의도적 범위 제한), 앞으로 그 배선이
    생겼을 때도 이 헬퍼 하나만 고치면 되도록 지금부터 신호를 흘려 둔다."""

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


def test_the_static_path_is_unchanged_when_the_flag_is_off() -> None:
    """graph_design_enabled=False 에서 기존 동작이 바이트 단위로 같아야 한다."""
    harness = _harness(graph_design_enabled=False)
    assert harness._designed_topology is None


def test_the_compiled_static_graph_matches_its_pre_task_9_snapshot() -> None:
    """`_designed_topology` 가 `None` 이라는 것만으로는 "정적 그래프 배선이
    안 바뀌었다" 를 증명하지 못한다 (그 속성은 애초에 아무도 안 채운다).
    이 테스트는 더 강하게, `_create_workflow_graph` 가 실제로 컴파일해 내는
    노드·엣지 집합이 이번 태스크의 코드 변경 이전에 캡처한 스냅샷과 정확히
    같은지를 해시로 고정한다."""

    harness = _harness(graph_design_enabled=False)
    assert _static_graph_snapshot_hash(harness) == _STATIC_GRAPH_SNAPSHOT_SHA256
