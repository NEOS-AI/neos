"""트랙 I GS2 -- 템플릿 노드가 실제 `SubagentRuntime` 위에서 한 걸음씩 도는가.

가짜는 모델 하나뿐이다. 런타임·스테퍼·CAS 저장소(`InMemorySubagentStore`)·LangGraph
체크포인터(`MemorySaver`)는 진짜다 -- "노드 한 번 = advance 한 번" 과 "체크포인트를
가로질러 잇는다" 는 둘이 **맞물려야** 참이 되는 주장이라 한쪽을 가짜로 두면 증명이 안 된다.
"""

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
from neos.subagent.types import ParentKind, StepKind, SubagentStatus
from neos.workflow.graph import (
    EphemeralSubagentUnsupported,
    MultiAgentWorkflow,
    _recursion_limit_for,
    build_ephemeral_workflow,
)
from neos.workflow.state import merge_node_dict
from neos.workflow.subagent_nodes import EXPLORE_WEB, SubagentNodeHost, expand_subagent_nodes
from neos.workflow.topology import END, GRAPH_ENTRY_WRITES, START, GraphTopology

NODE = EXPLORE_WEB.name


class _ScriptedModel:
    def __init__(self, script) -> None:
        self.script = [tuple(turn) for turn in script]
        self.requests = []

    async def stream(self, request):
        self.requests.append(request)
        if not self.script:
            raise CodingModelError("model_script_exhausted", retryable=False)
        for event in self.script.pop(0):
            yield event


class _Tools:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def definitions(self):
        return ("search", "fetch", "spawn_agent.v1", "edit_file.v1")

    async def execute(self, name, input):
        self.calls.append((name, dict(input)))
        return {"results": [{"url": "https://example.test/a"}], "url": "https://example.test/a"}


class _Sink:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    async def emit(self, event_type, payload) -> None:
        self.events.append((event_type, dict(payload)))


class _Crash(BaseException):
    """노드 핸들러의 `except Exception` 을 통과해 run 을 죽이는 프로세스 사망 대역."""


class _CountingRuntime:
    """진짜 런타임에 위임하며 `advance` 를 센다. `crash` 로 사망 시점을 고른다."""

    def __init__(self, inner) -> None:
        self.inner = inner
        self.advances = 0
        self.crash_before: int | None = None
        self.crash_after: int | None = None

    async def advance(self, ticket):
        self.advances += 1
        if self.crash_before == self.advances:
            self.crash_before = None
            raise _Crash("before advance")
        outcome = await self.inner.advance(ticket)
        if self.crash_after == self.advances:
            self.crash_after = None
            raise _Crash("after advance, before the graph checkpoint")
        return outcome

    def __getattr__(self, name):
        return getattr(self.inner, name)


def _text(text="found it"):
    return (TextDelta(text), ModelCompleted("end_turn", ModelUsage(3, 2)))


def _tool_turn(count=1):
    return (
        TextDelta("searching"),
        *(ToolCallCompleted(f"call_{i}", "search", {"query": "q"}) for i in range(count)),
        ModelCompleted("tool_use", ModelUsage(4, 1)),
    )


def _host(script, *, templates=None, max_active=1):
    model = _ScriptedModel(script)
    tools = _Tools()
    sink = _Sink()
    store = InMemorySubagentStore()
    runtime = _CountingRuntime(
        SubagentRuntime(
            store=store,
            catalog=SpecRegistry(),
            stepper=ChildStepper(model=model, tools=tools),
            events=sink,
            clock=SystemClock(),
        )
    )
    emitted: list[tuple[str, dict]] = []
    host = SubagentNodeHost(
        runtime=runtime,
        provider="anthropic",
        max_active=max_active,
        templates=templates,
        model_for_role=lambda provider, role: "claude-sonnet-5",
        emit=lambda kind, payload: emitted.append((kind, dict(payload))),
    )
    return host, runtime, model, tools, sink, store, emitted


def _apply(state: dict, update: dict) -> dict:
    merged = dict(state)
    for key, value in update.items():
        if key in ("subagent_runs", "subagent_reports"):
            merged[key] = merge_node_dict(merged.get(key), value)
        elif key == "search_results":
            merged[key] = list(merged.get(key) or []) + list(value)
        else:
            merged[key] = value
    return merged


def _state(scope="wf_test") -> dict:
    return {"original_query": "누가 이 함수를 부르나", "subagent_scope": scope, "search_results": []}


# -- 핸들러 단위 --------------------------------------------------------------


@pytest.mark.asyncio
async def test_each_invocation_advances_exactly_once_until_the_child_completes() -> None:
    host, runtime, model, tools, _sink, _store, emitted = _host([_tool_turn(), _text()])
    handler = host.handler_for(NODE)
    route = host.route_for(NODE, ["fact_check"])
    state = _state()
    kinds = []
    for expected_advances in (1, 2, 3):
        update = await handler(state)
        assert runtime.advances == expected_advances
        state = _apply(state, update)
        kinds.append(route(state))
    assert kinds == [[NODE], [NODE], ["fact_check"]]
    assert len(model.requests) == 2 and len(tools.calls) == 1

    report = state["subagent_reports"][NODE]
    assert report["status"] == "completed" and report["unverified"] is True
    [result] = state["search_results"]
    assert result.source == f"subagent:{NODE}"
    assert result.metadata["unverified"] is True and result.content == "found it"
    # 요약 본문은 이벤트에 실리지 않는다.
    folded = [payload for kind, payload in emitted if kind == "graph_subagent_folded"]
    assert folded and all("found it" not in str(payload) for payload in folded)
    assert [kind for kind, _ in emitted].count("graph_subagent_step") == 3


@pytest.mark.asyncio
async def test_the_child_is_a_workflow_child_scoped_to_the_execution_and_never_spawns() -> None:
    host, _runtime, model, _tools, _sink, store, _emitted = _host([_text()])
    await host.handler_for(NODE)(_state("wf_scope_a"))
    record = next(iter(store._runs.values()))
    assert record.parent_kind is ParentKind.WORKFLOW
    assert (record.parent_id, record.parent_run_id) == ("wf_scope_a", "wf_scope_a")
    assert record.parent_tool_call_id == f"node:{NODE}"
    offered = {tool.name for tool in model.requests[0].tools}
    assert "spawn_agent.v1" not in offered and "edit_file.v1" not in offered


@pytest.mark.asyncio
async def test_a_rerun_after_a_crash_between_advance_and_checkpoint_does_not_step_twice() -> None:
    host, runtime, model, tools, sink, _store, _emitted = _host([_tool_turn(), _text()])
    handler = host.handler_for(NODE)
    state = _apply(_state(), await handler(_state()))  # 걸음 1 (모델 턴, 도구 요청)
    runtime.crash_after = 2
    with pytest.raises(_Crash):
        await handler(state)  # 걸음 2 는 저장소에 커밋됐지만 그래프 상태에는 안 실렸다
    assert len(tools.calls) == 1
    update = await handler(state)  # 같은 (낡은) 포인터로 재실행
    assert len(tools.calls) == 1, "도구 배치가 두 번 돌았다"
    assert any(kind == "subagent.cas_mismatch" for kind, _ in sink.events)
    state = _apply(state, update)
    while state["subagent_runs"][NODE]["terminal"] is False:
        state = _apply(state, await handler(state))
    assert len(model.requests) == 2
    assert state["subagent_reports"][NODE]["status"] == "completed"


@pytest.mark.asyncio
async def test_the_step_cap_cancels_the_child_and_reports_failure() -> None:
    # max_turns=2 -> max_advances=5. 스테퍼는 걸음마다 턴 소진을 **먼저** 본다 --
    # max_turns=1 이면 둘째 걸음이 대기 도구를 버리고 turns_exhausted 로 끝나 상한에
    # 닿지 않는다. 한 턴에 도구 25개(배치 10)면 걸음 1 모델 · 2-4 배치 · 5 모델(또 도구) =
    # 다섯째 걸음이 여전히 CONTINUING 이다.
    capped = replace(EXPLORE_WEB, max_turns=2)
    host, runtime, _model, _tools, _sink, store, _emitted = _host(
        [_tool_turn(count=25), _tool_turn(count=25)], templates={NODE: capped}
    )
    handler = host.handler_for(NODE)
    state = _state()
    for _ in range(capped.max_advances):
        state = _apply(state, await handler(state))
    assert runtime.advances == capped.max_advances
    report = state["subagent_reports"][NODE]
    assert report["exit_reason"] == "graph_step_cap"
    assert state["search_results"] == []
    assert next(iter(store._runs.values())).status is SubagentStatus.KILLED


@pytest.mark.asyncio
async def test_a_failed_child_still_returns_every_declared_write() -> None:
    host, _runtime, _model, _tools, _sink, _store, _emitted = _host([])
    update = await host.handler_for(NODE)(_state())
    assert set(update) == set(EXPLORE_WEB.contract().writes)
    assert update["search_results"] == []
    assert update["subagent_reports"][NODE]["status"] == "failed"
    assert update["subagent_runs"][NODE]["terminal"] is True


@pytest.mark.asyncio
async def test_a_missing_scope_fails_without_advancing() -> None:
    host, runtime, *_ = _host([_text()])
    update = await host.handler_for(NODE)({"original_query": "q"})
    assert runtime.advances == 0
    assert update["subagent_reports"][NODE]["exit_reason"] == "subagent_scope_missing"
    assert host.route_for(NODE, ["fact_check"])(_apply({}, update)) == ["fact_check"]


@pytest.mark.asyncio
async def test_a_pointer_left_by_a_previous_turn_is_not_resumed() -> None:
    host, _runtime, _model, _tools, _sink, store, _emitted = _host([_text("one"), _text("two")])
    handler = host.handler_for(NODE)
    first = _apply(_state("wf_turn_1"), await handler(_state("wf_turn_1")))
    # 같은 대화 스레드의 다음 턴: 채널 값은 이월되고 스코프만 새로 발급된다.
    second_input = {**first, "subagent_scope": "wf_turn_2", "search_results": []}
    second = _apply(second_input, await handler(second_input))
    assert len(store._runs) == 2
    assert second["subagent_runs"][NODE]["run_id"] != first["subagent_runs"][NODE]["run_id"]
    assert [result.content for result in second["search_results"]] == ["two"]


@pytest.mark.asyncio
async def test_cancel_scope_kills_live_children_of_that_scope_only() -> None:
    host, _runtime, _model, _tools, _sink, store, _emitted = _host([_tool_turn(), _tool_turn()])
    await host.handler_for(NODE)(_state("wf_a"))
    await host.handler_for(NODE)(_state("wf_b"))
    await host.cancel_scope("wf_a", "workflow_failed")
    statuses = {run.parent_id: run.status for run in store._runs.values()}
    assert statuses == {"wf_a": SubagentStatus.KILLED, "wf_b": SubagentStatus.RUNNING}
    assert await host.cancel_scope(None, "noop") == ()


# -- 조립 ------------------------------------------------------------------


_LINEAR = expand_subagent_nodes(
    GraphTopology(
        nodes=(NODE, "fact_check"),
        edges=((START, NODE), (NODE, "fact_check"), ("fact_check", END)),
        initial_writes=GRAPH_ENTRY_WRITES,
    )
)


def test_templates_are_not_assembled_without_a_checkpointer() -> None:
    host, *_ = _host([])
    with pytest.raises(EphemeralSubagentUnsupported):
        build_ephemeral_workflow(MultiAgentWorkflow(), _LINEAR, subagent_host=host)


@pytest.mark.asyncio
async def test_the_assembled_self_loop_resumes_across_checkpoints(monkeypatch) -> None:
    monkeypatch.setattr(settings_module.settings, "FACT_CHECK_ENABLED", False)
    host, runtime, model, tools, _sink, _store, _emitted = _host([_tool_turn(), _text()])
    app = build_ephemeral_workflow(
        MultiAgentWorkflow(), _LINEAR, checkpointer=MemorySaver(), subagent_host=host
    )
    config = {"configurable": {"thread_id": "t-subagent"}, "recursion_limit": 50}
    initial = {**_state(), "execution_steps": []}

    runtime.crash_before = 2  # 걸음 1 은 체크포인트에 실렸고, 걸음 2 에서 프로세스가 죽는다
    with pytest.raises(_Crash):
        await app.ainvoke(initial, config)
    snapshot = await app.aget_state(config)
    assert snapshot.values["subagent_runs"][NODE]["steps"] == 1
    assert snapshot.next == (NODE,)

    updates = [chunk async for chunk in app.astream(None, config)]
    node_runs = sum(1 for chunk in updates if NODE in chunk)
    final = (await app.aget_state(config)).values

    # 재개 뒤 노드 실행 두 번 = advance 두 번 (죽기 전 1 + 죽은 시도 1 + 재개 2)
    assert node_runs == 2
    assert runtime.advances == 4
    assert len(model.requests) == 2 and len(tools.calls) == 1
    assert final["subagent_reports"][NODE]["status"] == "completed"
    assert final["fact_check_skipped"] is True
    assert [result.metadata["unverified"] for result in final["search_results"]] == [True]


def test_the_recursion_limit_grows_with_template_steps_only() -> None:
    host, *_ = _host([])

    class _Graph:
        nodes = _LINEAR.nodes
        topology = _LINEAR
        subagent_host = host

    assert _recursion_limit_for(object()) == 50
    many = expand_subagent_nodes(
        GraphTopology(nodes=(NODE,), edges=((START, NODE), (NODE, END))),
        {NODE: replace(EXPLORE_WEB, max_turns=8)},
    )

    class _Big:
        nodes = many.nodes
        topology = GraphTopology(
            nodes=tuple(f"n{i}" for i in range(4)) + many.nodes,
            edges=many.edges,
            loop_bounds={NODE: 17 * 4},
        )
        subagent_host = host

    assert _recursion_limit_for(_Graph()) == 50
    assert _recursion_limit_for(_Big()) == len(_Big.nodes) + (17 * 4 - 1) + 1


def test_step_kind_enum_is_what_the_router_relies_on() -> None:
    assert StepKind.CONTINUING.value == "continuing"


@pytest.mark.asyncio
async def test_the_production_tool_port_exposes_only_template_tools() -> None:
    from neos.workflow.subagent_nodes import _TemplateToolPort

    inner = _Tools()
    port = _TemplateToolPort(inner, frozenset({"search", "fetch"}))
    assert port.definitions() == ("search", "fetch")
    assert await port.execute("spawn_agent.v1", {}) == {"error": "tool_not_allowed"}
    assert inner.calls == []
    await port.execute("search", {"query": "q"})
    assert inner.calls == [("search", {"query": "q"})]
