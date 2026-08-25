"""설계된 그래프로 쓴 체크포인트를 **정적** 그래프로 읽을 수 있는가.

이 저장소는 지금까지 정적 run 의 체크포인트만 읽어 왔다. 재개 경로
(`approval_handlers`)가 `multi_agent_workflow.graph` 로 `aget_state` 를 부르므로,
설계된 run 을 재개하려면 이 왕복이 성립해야 한다. LangGraph 는 상태 채널 외에
노드별 트리거 채널을 갖고, 노드 집합이 다를 때 `aget_state` 가 무엇을 하는지
확인된 바 없다 -- 그래서 잰다.

**판정 (2026-08-25):** 성립한다 -- `aupdate_state`/`aget_state` 왕복이 예외 없이
끝났고 `state.values["original_query"] == "설계된 run 의 질의"` 로 읽혔다. 설계된
그래프의 노드 집합(`_CHAIN` 의 5개 -- `query_classifier`, `search_orchestrator`,
`analysis_orchestrator`, `generation_orchestrator`, `response_generator`)은 정적
그래프가 실제로 컴파일하는 ~25개 노드의 **부분집합**이다(`_create_workflow_graph`
가 `add_node` 로 등록하는 노드 목록 확인). 즉 이 프로브가 실측한 것은 "설계된
그래프의 노드가 정적 그래프에도 모두 존재하는" 경우다 -- 설계된 그래프가 정적
그래프에 없는 새 노드 이름을 쓰는 경우(완전히 이질적인 노드 집합)까지 일반화하는
근거는 아니다. 다만 스펙이 요구하는 "설계 후보가 후보 검증(`validate_topology`)을
통과한 기존 `NODE_CONTRACTS` 노드만 쓴다"는 전제 아래서는, 설계된 run 의 노드가
정적 그래프의 부분집합이 되는 것이 일반 케이스다. 따라서 Task 4 는 스펙대로 상태
경로(`multi_agent_workflow.graph.aget_state`)를 그대로 쓴다 -- 체크포인터를 직접
여는 우회 경로는 필요 없다.
"""

import sys
import types

import pytest

import neos.config.settings as settings_module

settings_module.settings.GOOGLE_API_KEY = "test-key"
settings_module.settings.OPENAI_API_KEY = "test-key"

# `MultiAgentWorkflow` 를 실제로 인스턴스화하려면 선택적 의존성 세 개를 가짜
# 모듈로 미리 꽂아 둬야 임포트가 죽지 않는다 (test_ephemeral_graph_execution.py 와
# 같은 이유 -- youtube_transcript_api/googleapiclient/isodate 가 개발 환경에
# 항상 설치돼 있는 것은 아니다).
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

from langgraph.checkpoint.memory import MemorySaver  # noqa: E402

from neos.workflow.graph import MultiAgentWorkflow, build_ephemeral_workflow  # noqa: E402
from neos.workflow.topology import GRAPH_ENTRY_WRITES, GraphTopology  # noqa: E402

_CHAIN = (
    "query_classifier",
    "search_orchestrator",
    "analysis_orchestrator",
    "generation_orchestrator",
    "response_generator",
)


def _chain_topology(chain):
    return GraphTopology(
        nodes=chain,
        edges=(
            ("__start__", chain[0]),
            *((chain[i], chain[i + 1]) for i in range(len(chain) - 1)),
            (chain[-1], "__end__"),
        ),
        initial_writes=GRAPH_ENTRY_WRITES,
    )


@pytest.mark.asyncio
async def test_a_designed_runs_checkpoint_is_readable_through_the_static_graph():
    saver = MemorySaver()
    workflow = MultiAgentWorkflow()
    await workflow._ensure_graph_initialized(use_checkpointer=True)

    designed = build_ephemeral_workflow(
        workflow, _chain_topology(_CHAIN), checkpointer=saver
    )
    config = {"configurable": {"thread_id": "readback-probe"}}

    # 설계된 그래프로 상태를 하나 쓴다. 노드를 돌리지 않고 aupdate_state 만
    # 쓰는 이유는 이 테스트가 재는 것이 실행이 아니라 **채널 호환성**이기 때문이다.
    await designed.aupdate_state(config, {"original_query": "설계된 run 의 질의"})

    # 정적 그래프로 같은 thread 를 읽는다. 정적 그래프도 같은 saver 를 써야
    # 한다 -- 체크포인터가 다르면 이 테스트는 아무것도 재지 않는다.
    static = workflow.graph
    static.checkpointer = saver
    state = await static.aget_state(config)

    assert state.values.get("original_query") == "설계된 run 의 질의"
