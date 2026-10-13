"""네이티브 러너 (spec 2026-10-13 §4.2). 배선 표를 해석해 LangGraph updates 모드와 같은 chunk 를 낸다."""

import pytest

from neos.workflow.runtime.runner import Completed, Interrupted, StepLimitExceeded, WorkflowRunner
from neos.workflow.state import SearchResult
from neos.workflow.topology import END, START
from neos.workflow.wiring import Branch, Edge, NodeSpec, Route, Wiring, WiringError

pytestmark = [pytest.mark.no_db, pytest.mark.asyncio]

A = SearchResult(source="web", title="A", content="a", url="https://a")


class Owner:
    def __init__(self, label="end"):
        self.label = label
        self.calls: list[str] = []

    async def first(self, state):
        self.calls.append("first")
        return {"search_results": [A], "final_response": "draft"}

    async def second(self, state):
        self.calls.append("second")
        return {"final_response": state["final_response"] + "!"}

    def route(self, state):
        return self.label


def _wiring(**kw) -> Wiring:
    return Wiring(
        nodes=(NodeSpec("first", "first"), NodeSpec("second", "second")),
        edges=(Edge(START, "first"),),
        branches=(
            Branch("first", "route", (Route("again", "second"), Route("end", END))),
        )
        if kw.get("branch", True)
        else (),
        interrupt_before=kw.get("interrupt_before", ()),
    )


async def _drain(runner, state, **kw):
    return [chunk async for chunk in runner.stream(state, **kw)]


async def test_chunks_have_the_langgraph_updates_shape_and_state_folds() -> None:
    owner = Owner(label="again")
    wiring = Wiring(
        nodes=(NodeSpec("first", "first"), NodeSpec("second", "second")),
        edges=(Edge(START, "first"), Edge("second", END)),
        branches=(Branch("first", "route", (Route("again", "second"), Route("end", END))),),
    )
    runner = WorkflowRunner(wiring, owner, step_limit=10)
    chunks = await _drain(runner, {"search_results": [], "final_response": None})
    assert chunks == [
        {"first": {"search_results": [A], "final_response": "draft"}},
        {"second": {"final_response": "draft!"}},
    ]
    assert isinstance(runner.outcome, Completed)
    assert runner.outcome.state["search_results"] == [A]
    assert runner.outcome.state["final_response"] == "draft!"


async def test_accumulating_fields_append_across_nodes() -> None:
    class Twice(Owner):
        async def second(self, state):
            return {"search_results": [A]}

    wiring = Wiring(
        nodes=(NodeSpec("first", "first"), NodeSpec("second", "second")),
        edges=(Edge(START, "first"), Edge("first", "second"), Edge("second", END)),
        branches=(),
    )
    runner = WorkflowRunner(wiring, Twice(), step_limit=10)
    await _drain(runner, {"search_results": []})
    assert runner.outcome.state["search_results"] == [A, A]


async def test_an_interrupt_stops_before_the_gated_node() -> None:
    owner = Owner(label="again")
    runner = WorkflowRunner(_wiring(), owner, step_limit=10, interrupt_before=("second",))
    chunks = await _drain(runner, {"search_results": [], "final_response": None})
    assert chunks[-1] == {"__interrupt__": ("second",)}
    assert owner.calls == ["first"]
    assert isinstance(runner.outcome, Interrupted)
    assert runner.outcome.next_node == "second"
    assert runner.outcome.state["final_response"] == "draft"


async def test_resuming_at_the_gated_node_runs_it() -> None:
    owner = Owner()
    wiring = Wiring(
        nodes=(NodeSpec("first", "first"), NodeSpec("second", "second")),
        edges=(Edge(START, "first"), Edge("second", END)),
        branches=(Branch("first", "route", (Route("again", "second"), Route("end", END))),),
        interrupt_before=("second",),
    )
    runner = WorkflowRunner(wiring, owner, step_limit=10, interrupt_before=("second",))
    await _drain(runner, {"final_response": "kept"}, start_at="second")
    assert owner.calls == ["second"]
    assert runner.outcome.state["final_response"] == "kept!"


async def test_the_step_limit_stops_a_loop() -> None:
    class Loop(Owner):
        def route(self, state):
            return "again"

        async def second(self, state):
            return {}

    wiring = Wiring(
        nodes=(NodeSpec("first", "first"), NodeSpec("second", "second")),
        edges=(Edge(START, "first"), Edge("second", "first")),
        branches=(Branch("first", "route", (Route("again", "second"), Route("end", END))),),
    )
    runner = WorkflowRunner(wiring, Loop(), step_limit=5)
    with pytest.raises(StepLimitExceeded):
        await _drain(runner, {"search_results": []})


async def test_an_unknown_label_is_a_wiring_error() -> None:
    runner = WorkflowRunner(_wiring(), Owner(label="nowhere"), step_limit=10)
    with pytest.raises(WiringError, match="nowhere"):
        await _drain(runner, {"search_results": [], "final_response": None})


async def test_callable_refs_and_the_wrap_hook() -> None:
    seen: list[str] = []

    async def handler(state):
        return {"final_response": "x"}

    def wrap(node, fn):
        async def run(state):
            seen.append(node)
            return await fn(state)

        return run

    wiring = Wiring(
        nodes=(NodeSpec("solo", handler), NodeSpec("raw", handler, wrapped=False)),
        edges=(Edge(START, "solo"), Edge("solo", "raw"), Edge("raw", END)),
        branches=(),
    )
    runner = WorkflowRunner(wiring, object(), step_limit=10, wrap=wrap)
    await _drain(runner, {})
    assert seen == ["solo"]


async def test_two_unconditional_exits_are_rejected_as_parallel() -> None:
    wiring = Wiring(
        nodes=(NodeSpec("first", "first"), NodeSpec("second", "second")),
        edges=(Edge(START, "first"), Edge("first", "second"), Edge("first", END)),
        branches=(),
    )
    with pytest.raises(WiringError, match="parallel"):
        WorkflowRunner(wiring, Owner(), step_limit=10)


async def test_the_static_table_builds_a_runner() -> None:
    from neos.workflow.graph import MultiAgentWorkflow
    from neos.workflow.wiring import resolve_wiring

    for flags in ({}, {"skill_execution": False, "execution_approval": False}):
        WorkflowRunner(resolve_wiring(flags), MultiAgentWorkflow, step_limit=50)
