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
    workflow = MultiAgentWorkflow()

    from neos.workflow.execution_graph import ExecutionGraph

    static = ExecutionGraph(
        compiled=object(), nodes=("a",), topology_hash="x", source="static", topology=None
    )

    assert workflow.execution_topology_payload(static) is None
