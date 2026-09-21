"""트랙 I GS4 -- 병렬 가지의 템플릿 자식 둘: 동시성 상한 · 조인 한 번 · 한쪽 실패 · 스코프 취소.

두 템플릿이 **다른 길이**로 끝나게 만든다(하나는 도구를 한 번 부르고, 하나는 바로
답한다). 같은 길이면 LangGraph 가 조인을 한 번만 돌려 `defer` 없이도 초록이 된다 --
그 테스트는 조인 중복을 지키지 못한다.
"""

import asyncio
from dataclasses import replace

import pytest
from langgraph.checkpoint.memory import MemorySaver

from neos.coding.model.base import ModelCompleted, ModelUsage, TextDelta, ToolCallCompleted
from neos.coding.model.errors import CodingModelError
from neos.config import settings as settings_module
from neos.subagent.catalog import SpecRegistry
from neos.subagent.memory import InMemorySubagentStore
from neos.subagent.ports import SystemClock
from neos.subagent.runtime import SubagentRuntime
from neos.subagent.stepper import ChildStepper
from neos.subagent.types import SubagentStatus
from neos.workflow.graph import MultiAgentWorkflow, build_ephemeral_workflow
from neos.workflow.subagent_nodes import EXPLORE_WEB, SubagentNodeHost, expand_subagent_nodes
from neos.workflow.topology import END, GRAPH_ENTRY_WRITES, START, GraphTopology

LONG = EXPLORE_WEB
SHORT = replace(
    EXPLORE_WEB,
    name="explore_web_short",
    briefing_from={"goal": "original_query", "scope": "refined_query"},
)
TEMPLATES = {LONG.name: LONG, SHORT.name: SHORT}
_SHORT_MARKER = "answer-without-tools"
_FAIL_MARKER = "fail-this-child"


class _BriefAwareModel:
    """브리핑(첫 사용자 메시지)을 보고 자식마다 다른 대본을 낸다 -- 순서에 기대지 않는다."""

    def __init__(self) -> None:
        self.requests = []

    async def stream(self, request):
        self.requests.append(request)
        brief = request.messages[0].content[0].text
        turns = sum(1 for message in request.messages if message.role == "assistant")
        await asyncio.sleep(0.01)  # 다른 가지가 끼어들 틈
        if _FAIL_MARKER in brief:
            raise CodingModelError("model_refused", retryable=False)
        if _SHORT_MARKER in brief or turns >= 1:
            yield TextDelta("report from " + ("short" if _SHORT_MARKER in brief else "long"))
            yield ModelCompleted("end_turn", ModelUsage(3, 2))
            return
        yield TextDelta("searching")
        yield ToolCallCompleted("call_1", "search", {"query": "q"})
        yield ModelCompleted("tool_use", ModelUsage(4, 1))


class _Tools:
    def definitions(self):
        return ("search", "fetch")

    async def execute(self, name, input):
        await asyncio.sleep(0.01)
        return {"results": []}


class _InFlightRuntime:
    def __init__(self, inner) -> None:
        self.inner = inner
        self.in_flight = 0
        self.peak = 0
        self.advances = 0

    async def advance(self, ticket):
        self.advances += 1
        self.in_flight += 1
        self.peak = max(self.peak, self.in_flight)
        try:
            return await self.inner.advance(ticket)
        finally:
            self.in_flight -= 1

    def __getattr__(self, name):
        return getattr(self.inner, name)


class _Crash(BaseException):
    pass


def _host(max_active: int):
    store = InMemorySubagentStore()
    runtime = _InFlightRuntime(
        SubagentRuntime(
            store=store,
            catalog=SpecRegistry(),
            stepper=ChildStepper(model=_BriefAwareModel(), tools=_Tools()),
            events=_NullSink(),
            clock=SystemClock(),
        )
    )
    host = SubagentNodeHost(
        runtime=runtime,
        provider="anthropic",
        max_active=max_active,
        templates=TEMPLATES,
        model_for_role=lambda provider, role: "claude-sonnet-5",
    )
    return host, runtime, store


class _NullSink:
    async def emit(self, event_type, payload) -> None:
        return None


_FANOUT = expand_subagent_nodes(
    GraphTopology(
        nodes=(LONG.name, SHORT.name, "fact_check"),
        edges=(
            (START, LONG.name),
            (START, SHORT.name),
            (LONG.name, "fact_check"),
            (SHORT.name, "fact_check"),
            ("fact_check", END),
        ),
        initial_writes=GRAPH_ENTRY_WRITES,
    ),
    TEMPLATES,
)


def _initial(*, short_scope=_SHORT_MARKER, query="누가 부르나") -> dict:
    return {
        "original_query": query,
        "refined_query": short_scope,
        "subagent_scope": "wf_fanout",
        "search_results": [],
        "execution_steps": [],
    }


async def _run(host, initial, *, thread="t-fanout"):
    app = build_ephemeral_workflow(
        MultiAgentWorkflow(), _FANOUT, checkpointer=MemorySaver(), subagent_host=host
    )
    config = {"configurable": {"thread_id": thread}, "recursion_limit": 50}
    chunks = [chunk async for chunk in app.astream(initial, config)]
    return chunks, (await app.aget_state(config)).values


@pytest.fixture(autouse=True)
def _no_fact_check_llm(monkeypatch):
    monkeypatch.setattr(settings_module.settings, "FACT_CHECK_ENABLED", False)


@pytest.mark.asyncio
@pytest.mark.parametrize("max_active", [1, 2])
async def test_two_parallel_children_respect_the_cap_and_join_once(max_active) -> None:
    host, runtime, _store = _host(max_active)
    chunks, final = await _run(host, _initial())

    assert runtime.peak == max_active, "상한이 안 걸렸거나(>) 병렬이 실제로 안 일어났다(<)"
    assert sum(1 for chunk in chunks if "fact_check" in chunk) == 1
    assert {report["status"] for report in final["subagent_reports"].values()} == {"completed"}
    assert sorted(result.content for result in final["search_results"]) == [
        "report from long",
        "report from short",
    ]
    # 긴 자식 3 걸음 + 짧은 자식 1 걸음 = advance 4 = 템플릿 노드 실행 4
    node_runs = sum(1 for chunk in chunks for name in chunk if name in TEMPLATES)
    assert runtime.advances == node_runs == 4


@pytest.mark.asyncio
async def test_without_defer_the_join_runs_twice(monkeypatch) -> None:
    """변이: `defer` 를 끄면 조인이 가지마다 돈다. 이 테스트가 없으면 위의 '한 번' 이 공허할 수 있다."""
    host, _runtime, _store = _host(2)
    monkeypatch.setattr(host, "defer_nodes", lambda topology: frozenset())
    chunks, _final = await _run(host, _initial(), thread="t-no-defer")
    assert sum(1 for chunk in chunks if "fact_check" in chunk) == 2


@pytest.mark.asyncio
async def test_one_failing_child_does_not_stop_the_other_or_the_join() -> None:
    host, _runtime, _store = _host(2)
    chunks, final = await _run(host, _initial(short_scope=_FAIL_MARKER), thread="t-one-fails")

    reports = final["subagent_reports"]
    assert reports[SHORT.name]["status"] == "failed"
    assert reports[LONG.name]["status"] == "completed"
    assert [result.content for result in final["search_results"]] == ["report from long"]
    assert sum(1 for chunk in chunks if "fact_check" in chunk) == 1
    assert final["fact_check_skipped"] is True


@pytest.mark.asyncio
async def test_finishing_the_scope_kills_every_live_child_after_a_crash(monkeypatch) -> None:
    host, runtime, store = _host(2)
    original = runtime.inner.advance
    calls = {"n": 0}

    async def _crash_on_third(ticket):
        calls["n"] += 1
        if calls["n"] == 3:
            raise _Crash("worker died mid fan-out")
        return await original(ticket)

    monkeypatch.setattr(runtime.inner, "advance", _crash_on_third)
    initial = _initial(short_scope="also-long")
    with pytest.raises(_Crash):
        await _run(host, initial, thread="t-crash")
    live_ids = {
        run.run_id
        for run in store._runs.values()
        if run.status in (SubagentStatus.PENDING, SubagentStatus.RUNNING)
    }
    assert live_ids, "크래시 시점에 살아 있는 자식이 없으면 이 테스트는 아무것도 증명하지 않는다"

    class _ExecutionGraph:
        subagent_host = host

    await MultiAgentWorkflow()._finish_subagent_scope(_ExecutionGraph(), initial, "workflow_failed")
    assert all(store._runs[run_id].status is SubagentStatus.KILLED for run_id in live_ids)
    assert not any(
        run.status in (SubagentStatus.PENDING, SubagentStatus.RUNNING)
        for run in store._runs.values()
    )


@pytest.mark.asyncio
async def test_finishing_the_scope_never_raises() -> None:
    class _Broken:
        async def cancel_scope(self, scope, reason):
            raise RuntimeError("db down")

    class _ExecutionGraph:
        subagent_host = _Broken()

    await MultiAgentWorkflow()._finish_subagent_scope(
        _ExecutionGraph(), {"subagent_scope": "wf_x"}, "workflow_failed"
    )

    class _Static:
        subagent_host = None

    await MultiAgentWorkflow()._finish_subagent_scope(_Static(), {}, "workflow_failed")
