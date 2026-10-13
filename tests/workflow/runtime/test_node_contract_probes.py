"""실제 노드, 가짜 LLM -- 계약의 `writes` 가 실제 쓰기를 덮는지 노드 경계에서 확인한다.

계약 테스트(`test_static_graph_contract.py` 등)는 스텁 핸들러로 돌아서 실제 노드가
무엇을 쓰는지 보지 못했다. 최종 리뷰가 프로브로 찾은 구멍(search_orchestrator 의
execution_steps·비용 키, result_integrator 의 execution_steps 등)이 그것이다.
여기서는 `MultiAgentWorkflow` 의 **실제 핸들러**를 꺼내 LLM·네트워크에 닿는
협력자만 작은 가짜로 바꾸고, `wrap_node(..., policy="raise")` 로 돌린다 --
계약 밖 키를 쓰면 `NodeUpdateRejected` 가 난다.

다루지 않는 노드와 이유
- query_classifier · conversation_context_processor · research_harness ·
  mission_planner · analysis/generation_orchestrator 의 실행 경로 ·
  recursive/hyper_deep · direct_response · ui_frame_generator · 소규모 LLM 노드
  (refinement·hypothesis·self_reflection·replanner·research_continuation):
  본문이 LLM 호출이거나 LLM 에이전트에 위임한다. 가짜로 바꿀 협력자가 노드
  본문 자체라 프로브가 계약이 아니라 가짜를 검사하게 된다. 이 노드들의 쓰기는
  코드 읽기로 대조했다(fixwave-report 의 표).
"""

import sys
import types
from datetime import datetime

import pytest

import neos.config.settings as settings_module

settings_module.settings.GOOGLE_API_KEY = "test-key"
settings_module.settings.OPENAI_API_KEY = "test-key"

# `MultiAgentWorkflow` 를 인스턴스화하려면 선택적 의존성이 임포트돼야 한다
# (test_execution_topology_state.py 와 같은 이유). 설치돼 있으면 아무것도 하지 않는다.
for _name, _attrs in {
    "youtube_transcript_api": {"YouTubeTranscriptApi": object},
    "youtube_transcript_api._errors": {
        "TranscriptsDisabled": Exception,
        "NoTranscriptFound": Exception,
        "VideoUnavailable": Exception,
    },
    "googleapiclient": {},
    "googleapiclient.discovery": {"build": lambda *args, **kwargs: object()},
    "googleapiclient.errors": {"HttpError": Exception},
    "isodate": {"parse_duration": lambda value: value},
}.items():
    try:
        __import__(_name)
    except ImportError:
        _module = types.ModuleType(_name)
        for _attr, _value in _attrs.items():
            setattr(_module, _attr, _value)
        sys.modules[_name] = _module

from neos.workflow.graph import MultiAgentWorkflow  # noqa: E402
from neos.workflow.orchestrators.search_strategies import (  # noqa: E402
    IterativeSearchStrategy,
    MultiHopSearchStrategy,
    StandardSearchStrategy,
)
from neos.workflow.processors import search_result_synthesizer  # noqa: E402
from neos.workflow.runtime.node_updates import NodeUpdateRejected, wrap_node  # noqa: E402
from neos.workflow.state import SearchResult  # noqa: E402

pytestmark = [pytest.mark.no_db, pytest.mark.asyncio]

A = SearchResult(source="web", title="A", content="a", url="https://a", score=0.8)
B = SearchResult(source="web", title="B", content="b", url="https://b", score=0.6)


@pytest.fixture(scope="module")
def workflow() -> MultiAgentWorkflow:
    return MultiAgentWorkflow()


def _state(workflow: MultiAgentWorkflow, **overrides):
    state = workflow._create_initial_state(
        {"user_id": "probe-user", "session_id": "probe-session", "query": "프로브 질의"}
    )
    state.update(
        {
            "detected_language": "ko",
            "query_intent": "information_seeking",
            "query_classification": {"complexity_score": 0.9},
            "required_agents": ["realtime_info_search"],
        }
    )
    state.update(overrides)
    return state


async def _run(workflow: MultiAgentWorkflow, node: str, handler_name: str, state):
    handler = getattr(workflow, handler_name)
    return await wrap_node(node, handler, policy="raise")(state)


class _ReadyToolSelector:
    initialized = True


@pytest.fixture
def search(workflow, monkeypatch):
    """검색 오케스트레이터의 네트워크·LLM 가장자리만 가짜로 바꾼다."""
    orchestrator = workflow.search_orchestrator
    monkeypatch.setattr(orchestrator, "tool_selector", _ReadyToolSelector())
    standard = next(s for s in orchestrator.strategies if isinstance(s, StandardSearchStrategy))

    async def no_cache(cache_key, state):
        return False

    async def no_tasks(state, search_agents, agents, tool_selector):
        return []

    async def no_store(cache_key, results):
        return None

    async def synthesize(self, **kwargs):
        return {
            "results": [A],
            "synthesis": "종합",
            "sources_checked": 1,
            "sources_succeeded": 1,
        }

    monkeypatch.setattr(standard, "_check_cache", no_cache)
    monkeypatch.setattr(standard, "_create_search_tasks", no_tasks)
    monkeypatch.setattr(standard, "_cache_results", no_store)
    monkeypatch.setattr(
        search_result_synthesizer.SearchResultSynthesizer,
        "synthesize_search_results",
        synthesize,
    )
    for strategy in orchestrator.strategies:
        if not isinstance(strategy, StandardSearchStrategy):
            monkeypatch.setattr(strategy, "is_applicable", lambda state: False)
    return orchestrator


@pytest.fixture
def no_llm_response(monkeypatch):
    monkeypatch.setattr(settings_module.settings, "EXECUTIVE_SUMMARY_ENABLED", False, raising=False)
    monkeypatch.setattr(settings_module.settings, "ENABLE_RESPONSE_REFINEMENT", False, raising=False)


async def test_result_integrator(workflow) -> None:
    update = await _run(
        workflow,
        "result_integrator",
        "_integrate_results_node",
        _state(workflow, search_results=[A]),
    )
    assert update["integrated_results"]["total_sources"] == 1
    assert update["execution_steps"][-1]["step"] == "result_integration"


async def test_fact_check_skips_without_an_llm(workflow, monkeypatch) -> None:
    monkeypatch.setattr(settings_module.settings, "FACT_CHECK_ENABLED", False, raising=False)
    update = await _run(workflow, "fact_check", "_fact_check_node", _state(workflow, search_results=[A]))
    assert update.get("fact_check_skipped", True) is True
    assert "execution_steps" not in update


async def test_fact_check_error_path_keeps_its_in_place_step(workflow, monkeypatch) -> None:
    monkeypatch.setattr(settings_module.settings, "FACT_CHECK_ENABLED", True, raising=False)
    monkeypatch.setattr(settings_module.settings, "FACT_CHECK_COMPLEXITY_THRESHOLD", 0.1, raising=False)

    def broken_llm():
        raise RuntimeError("no llm in probes")

    monkeypatch.setattr(workflow.fact_check_processor, "_get_llm", broken_llm)
    update = await _run(workflow, "fact_check", "_fact_check_node", _state(workflow, search_results=[A]))
    assert update["fact_check_skipped"] is True
    assert update["execution_steps"][-1]["step"] == "fact_check"


async def test_search_orchestrator_standard_path(workflow, search) -> None:
    update = await _run(workflow, "search_orchestrator", "_orchestrate_search_node", _state(workflow))
    assert update["search_results"] == [A]
    assert update["search_metadata"]["sources_succeeded"] == 1
    assert "cumulative_cost" in update and "cost_tracking" in update
    assert update["execution_steps"][-1]["step"] == "search_orchestration"


async def test_search_orchestrator_with_context_enhances_the_classification(
    workflow, search, monkeypatch
) -> None:
    async def enhance(original_query, context):
        return "개선된 질의"

    monkeypatch.setattr(search, "_enhance_query_with_context", enhance)
    update = await _run(
        workflow,
        "search_orchestrator",
        "_orchestrate_search_node",
        _state(workflow, conversation_context="이전 대화"),
    )
    assert update["query_classification"]["enhanced_query"] == "개선된 질의"


async def test_search_orchestrator_without_search_agents(workflow, search) -> None:
    update = await _run(
        workflow,
        "search_orchestrator",
        "_orchestrate_search_node",
        _state(workflow, required_agents=[]),
    )
    assert update["execution_steps"][-1]["result"].startswith("skipped")


async def test_search_orchestrator_strategy_failure(workflow, search, monkeypatch) -> None:
    standard = next(s for s in search.strategies if isinstance(s, StandardSearchStrategy))

    async def fail(state, search_agents, agents, tool_selector):
        raise RuntimeError("boom")

    monkeypatch.setattr(standard, "execute", fail)
    update = await _run(workflow, "search_orchestrator", "_orchestrate_search_node", _state(workflow))
    assert update["errors"] == ["Standard strategy failed: boom"]


async def test_search_orchestrator_iterative_path(workflow, search, monkeypatch) -> None:
    iterative = next(s for s in search.strategies if isinstance(s, IterativeSearchStrategy))

    class _Explorer:
        async def execute(self, query, context):
            return {"success": True, "result": [B], "metadata": {"depth_reached": 2, "pages_visited": 5}}

    monkeypatch.setattr(iterative, "iterative_explorer", _Explorer())
    monkeypatch.setattr(iterative, "is_applicable", lambda state: True)
    update = await _run(workflow, "search_orchestrator", "_orchestrate_search_node", _state(workflow))
    assert update["search_results"] == [B]
    assert update["exploration_depth_reached"] == 2
    assert update["exploration_pages_visited"] == 5


async def test_search_orchestrator_multi_hop_writes_a_key_outside_agent_state(
    workflow, search, monkeypatch
) -> None:
    """알려진 구멍을 고정한다: `multi_hop_metadata` 는 `AgentState` 에 없는 키다.

    LangGraph 는 스키마 밖 키를 조용히 버리므로 지금까지 아무 데도 닿지 않았다
    (읽는 곳도 없다). 계약에 넣을 수 없고(`test_declared_keys_exist_on_agent_state`),
    `raise` 로 뒤집기 전에 쓰기를 지우거나 필드를 추가해야 한다 -- 고치면 이
    테스트가 빨개져 알려 준다.
    """
    multi_hop = next(s for s in search.strategies if isinstance(s, MultiHopSearchStrategy))

    class _Agent:
        async def execute(self, query, context):
            return {"success": True, "result": [B], "metadata": {"hop_count": 2}}

    monkeypatch.setattr(multi_hop, "multi_hop_agent", _Agent())
    monkeypatch.setattr(multi_hop, "is_applicable", lambda state: True)
    with pytest.raises(NodeUpdateRejected) as error:
        await _run(workflow, "search_orchestrator", "_orchestrate_search_node", _state(workflow))
    assert error.value.keys == ("multi_hop_metadata",)


async def test_quality_validator(workflow) -> None:
    update = await _run(
        workflow,
        "quality_validator",
        "_validate_quality_node",
        _state(workflow, search_results=[A]),
    )
    assert "quality_score" in update
    assert update["execution_steps"][-1]["step"] == "quality_validation"


async def test_response_generator(workflow, no_llm_response) -> None:
    update = await _run(
        workflow,
        "response_generator",
        "_generate_response_node",
        _state(workflow, search_results=[A], execution_start=datetime.now()),
    )
    assert update["final_response"]
    assert update["execution_steps"][-1]["step"] == "response_generation"


async def test_research_harness_repair_reruns_search_and_response(
    workflow, search, no_llm_response, monkeypatch
) -> None:
    """복구 계획 산출은 가짜다(하네스 점검 결과를 꾸미는 비용이 크다) -- 검사하는 것은
    그 뒤 노드 래퍼가 연쇄 호출하는 검색·통합·응답 생성의 실제 쓰기다."""

    async def plan(state):
        return {
            "harness_repair_plan": {"attempt": 1, "actions": [{"action_type": "request_more_sources"}]},
            "harness_repair_attempts": 1,
            "required_agents": ["realtime_info_search"],
            "execution_steps": [*state.get("execution_steps", []), {"step": "research_harness_repair"}],
        }

    monkeypatch.setattr(workflow.research_harness_repair_processor, "process", plan)
    update = await _run(
        workflow,
        "research_harness_repair",
        "_research_harness_repair_node",
        _state(workflow, execution_start=datetime.now(), final_response="이전 답"),
    )
    assert update["final_response"] != "이전 답"
    assert update["integrated_results"]["total_sources"] == 1
    assert "cost_tracking" in update and "execution_time_ms" in update


async def test_mission_validator_runs_the_quality_validator(workflow, monkeypatch) -> None:
    # 점수가 문턱 아래여야 QualityValidator 가 retry_count 를 올린다
    monkeypatch.setattr(workflow.quality_validator.config, "MIN_QUALITY_SCORE", 0.99)
    monkeypatch.setattr(workflow.quality_validator.config, "MAX_RETRIES", 3)
    update = await _run(
        workflow,
        "mission_validator",
        "_mission_validator_node",
        _state(
            workflow, search_results=[A], quality_score=None, mission_id="m1", validation_contract={}
        ),
    )
    assert "validation_summary" in update
    assert "retry_count" in update


async def test_mission_executor_runs_a_search_task(workflow, search) -> None:
    mission_plan = {
        "tasks": [
            {
                "task_id": "t1",
                "required_capability": "web_search",
                "suggested_agent": "realtime_info_search",
            }
        ]
    }
    update = await _run(
        workflow,
        "mission_executor",
        "_mission_executor_node",
        _state(workflow, mission_plan=mission_plan, required_agents=["knowledge_search"]),
    )
    assert update["mission_status"] == "completed"
    assert update["search_results"] == [A]
