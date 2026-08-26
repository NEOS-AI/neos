"""설계된 run 은 자기 토폴로지를 상태에 남기고, 정적 run 은 남기지 않는다.

재개 경로가 읽을 유일한 근거다. 남기지 않으면 재개는 어느 그래프로 멈췄는지
알 수 없고, 정적 run 에 남기면 재개가 없는 토폴로지를 지으려 든다.
"""

import sys
import types

import pytest

import neos.config.settings as settings_module

settings_module.settings.GOOGLE_API_KEY = "test-key"
settings_module.settings.OPENAI_API_KEY = "test-key"

# `MultiAgentWorkflow` 를 실제로 인스턴스화하려면 선택적 의존성 세 개를 가짜
# 모듈로 미리 꽂아 둬야 임포트가 죽지 않는다 (test_ephemeral_graph_execution.py 와
# test_designed_run_state_readback.py 와 같은 이유 --
# youtube_transcript_api/googleapiclient/isodate 가 개발 환경에 항상 설치돼
# 있는 것은 아니다).
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

from neos.workflow.graph import MultiAgentWorkflow  # noqa: E402
from neos.workflow.graph_design_ledger import topology_hash  # noqa: E402
from neos.workflow.topology import (  # noqa: E402
    GRAPH_ENTRY_WRITES,
    GraphTopology,
    topology_from_payload,
)

_CHAIN = (
    "query_classifier",
    "search_orchestrator",
    "analysis_orchestrator",
    "generation_orchestrator",
    "response_generator",
)
_DESIGNED = GraphTopology(
    nodes=_CHAIN,
    edges=(
        ("__start__", _CHAIN[0]),
        *((_CHAIN[i], _CHAIN[i + 1]) for i in range(len(_CHAIN) - 1)),
        (_CHAIN[-1], "__end__"),
    ),
    initial_writes=GRAPH_ENTRY_WRITES,
)


class _FakeDesigner:
    async def design(self, request):
        return _DESIGNED


def _enable_design(monkeypatch):
    config = settings_module.settings.config
    monkeypatch.setattr(config.workflow, "graph_design_enabled", True)


@pytest.mark.asyncio
async def test_a_designed_graph_carries_its_topology(monkeypatch):
    """설계 분기가 `ExecutionGraph.topology` 를 채우는가.

    이 필드가 `None` 인 채로 남으면(예: `_resolve_execution_graph` 의 마지막
    `return ExecutionGraph(...)` 에서 `topology=` 인자를 빠뜨리면)
    `execution_topology_payload` 가 모든 설계된 run 에서도 `None` 을 돌려주고,
    재개는 설계된 run 과 정적 run 을 구별할 수 없게 된다."""
    workflow = MultiAgentWorkflow()
    _enable_design(monkeypatch)
    monkeypatch.setattr(workflow, "_build_graph_designer", lambda: _FakeDesigner())
    await workflow._ensure_graph_initialized(use_checkpointer=False)

    resolved = await workflow._resolve_execution_graph(
        user_input={"query": "테스트 질의", "session_id": "s1"},
        use_checkpointer=False,
        span=None,
    )

    assert resolved.source == "designed"
    assert resolved.topology is not None
    assert topology_hash(resolved.topology) == resolved.topology_hash


@pytest.mark.asyncio
async def test_a_static_graph_carries_no_topology(monkeypatch):
    """정적 run 의 `topology` 는 None 이다. 여기에 정적 토폴로지를 실으면
    재개가 정적 run 마다 그래프를 새로 짓게 되고, 그것은 지금 동작을 바꾼다."""
    workflow = MultiAgentWorkflow()
    await workflow._ensure_graph_initialized(use_checkpointer=False)

    resolved = await workflow._resolve_execution_graph(
        user_input={"query": "테스트 질의", "session_id": "s1"},
        use_checkpointer=False,
        span=None,
    )

    assert resolved.source == "static"
    assert resolved.topology is None


@pytest.mark.asyncio
async def test_the_state_payload_round_trips_back_to_the_same_graph(monkeypatch):
    """상태에 실리는 것은 페이로드이고, 그것이 같은 그래프로 되돌아와야 한다."""
    workflow = MultiAgentWorkflow()
    _enable_design(monkeypatch)
    monkeypatch.setattr(workflow, "_build_graph_designer", lambda: _FakeDesigner())
    await workflow._ensure_graph_initialized(use_checkpointer=False)

    resolved = await workflow._resolve_execution_graph(
        user_input={"query": "테스트 질의", "session_id": "s1"},
        use_checkpointer=False,
        span=None,
    )
    payload = workflow.execution_topology_payload(resolved)

    assert topology_hash(topology_from_payload(payload)) == resolved.topology_hash


def test_a_static_graph_yields_no_payload():
    """정적 `ExecutionGraph` 에서 `execution_topology_payload` 가 `None` 을 내는가.

    여기서 `None` 대신 정적 토폴로지를 실으면(`topology=static_topology(...)`
    처럼), 재개 경로가 그 페이로드를 보고 "이 run 은 설계됐다" 고 오인해 정적
    run 마다 그래프를 새로 짓는다 -- 지금은 존재하지 않는 동작이다."""
    workflow = MultiAgentWorkflow()

    from neos.workflow.execution_graph import ExecutionGraph

    static = ExecutionGraph(
        compiled=object(), nodes=("a",), topology_hash="x", source="static", topology=None
    )

    assert workflow.execution_topology_payload(static) is None


def _capture_initial_state(captured):
    """`graph_astream_source` 를 갈음해 `initial_state` 를 가로챈다.

    `graph_astream_source` 는 이 목적(실제 LLM 없이 chunk 흐름을 주입)으로
    이미 존재하는 이음매다(`graph.py` 의 그 메서드 docstring 참고). 실제
    `astream` 을 돌리지 않는 이유는 이 테스트가 재는 것이 배선이지 실행이
    아니기 때문이다 -- 빈 async generator 를 돌려주면 `execute_workflow` 의
    루프가 즉시 끝나고, 그 뒤의 실패(예: `final_state` 가 `None`)는 이미
    감싸인 `except Exception` 경로로 삼켜진다."""

    def _capture(execution_graph, initial_state, config):
        captured["state"] = initial_state

        async def _empty():
            return
            yield

        return _empty()

    return _capture


@pytest.mark.asyncio
async def test_the_initial_state_actually_carries_the_payload_for_a_designed_run(
    monkeypatch,
):
    """배선 자체(`initial_state["execution_topology"] = ...`)를 잡는 테스트다.

    위 테스트들은 `_resolve_execution_graph` 의 반환값이나
    `execution_topology_payload` 의 반환값에서 멈춘다 -- 즉
    `execute_workflow` 안의 `initial_state["execution_topology"] = ...` 한
    줄이 통째로 사라져도 전부 통과한다. 그 배선이 깨지면 설계된 run 이 상태에
    토폴로지를 남기지 않고, 재개가 정적 그래프로 떨어진다. 이 플랜이 고치려는
    버그가 정확히 그것이라, 여기서 `execute_workflow` 를 실제로 돌려 그것이
    핸들러에 넘기는 `initial_state` 를 직접 검사한다."""
    workflow = MultiAgentWorkflow()
    _enable_design(monkeypatch)
    monkeypatch.setattr(workflow, "_build_graph_designer", lambda: _FakeDesigner())
    await workflow._ensure_graph_initialized(use_checkpointer=False)

    captured: dict = {}
    monkeypatch.setattr(
        workflow, "graph_astream_source", _capture_initial_state(captured)
    )

    await workflow.execute_workflow(
        {
            "query": "테스트 질의",
            "session_id": "s-designed",
            "user_id": "u1",
            "bypass_cache": True,
        },
        use_checkpointer=False,
    )

    assert "state" in captured, "graph_astream_source 가 아예 호출되지 않았다"
    payload = captured["state"]["execution_topology"]
    assert payload is not None
    assert payload["nodes"] == list(_CHAIN)


@pytest.mark.asyncio
async def test_the_initial_state_carries_no_payload_for_a_static_run(monkeypatch):
    """정적 run 이 같은 배선을 타도 `execution_topology` 가 `None` 으로
    남는가. 설계가 꺼져 있으면 `_resolve_execution_graph` 가 정적
    `ExecutionGraph` 를 돌려주고, `execution_topology_payload` 가 그것을
    `None` 으로 매핑한다 -- 그 `None` 이 실제로 `initial_state` 까지
    전달되는지가 `test_a_static_graph_yields_no_payload` 가 재지 못하는
    부분이다."""
    workflow = MultiAgentWorkflow()
    await workflow._ensure_graph_initialized(use_checkpointer=False)

    captured: dict = {}
    monkeypatch.setattr(
        workflow, "graph_astream_source", _capture_initial_state(captured)
    )

    await workflow.execute_workflow(
        {
            "query": "테스트 질의",
            "session_id": "s-static",
            "user_id": "u1",
            "bypass_cache": True,
        },
        use_checkpointer=False,
    )

    assert "state" in captured, "graph_astream_source 가 아예 호출되지 않았다"
    assert "execution_topology" in captured["state"]
    assert captured["state"]["execution_topology"] is None
