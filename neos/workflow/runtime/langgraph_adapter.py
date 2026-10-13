"""배선 표 → LangGraph `StateGraph` (spec 2026-10-13 §4.1). Plan 3 에서 지운다.

`graph_factory` 를 인자로 받는 이유: 기존 테스트 다섯이 `neos.workflow.graph.StateGraph`
를 기록용 가짜로 바꿔 조립 호출을 본다. `_create_workflow_graph` 가 자기 모듈의
`StateGraph` 를 넘기면 그 테스트들이 바뀌지 않고 이 어댑터를 시험한다.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from langgraph.graph import END as LG_END
from langgraph.graph import START as LG_START

from neos.workflow.topology import END, START
from neos.workflow.wiring import Wiring

_ENDPOINTS = {START: LG_START, END: LG_END}


def _lg(name: str) -> str:
    return _ENDPOINTS.get(name, name)


def compile_wiring(
    wiring: Wiring,
    owner: Any,
    *,
    graph_factory: Callable[[type], Any],
    state_schema: type,
    checkpointer: Any = None,
    interrupt_before: Sequence[str] = (),
    wrap: Callable[[str, Callable], Callable] | None = None,
) -> Any:
    graph = graph_factory(state_schema)
    for spec in wiring.nodes:
        handler = getattr(owner, spec.handler)
        graph.add_node(spec.name, wrap(spec.name, handler) if wrap else handler)
    for edge in wiring.edges:
        graph.add_edge(_lg(edge.source), _lg(edge.target))
    for branch in wiring.branches:
        graph.add_conditional_edges(
            branch.source,
            getattr(owner, branch.router),
            {route.label: _lg(route.target) for route in branch.routes},
        )
    if checkpointer is not None:
        return graph.compile(checkpointer=checkpointer, interrupt_before=list(interrupt_before))
    return graph.compile()
