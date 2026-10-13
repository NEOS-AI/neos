"""승인된 설계 토폴로지 → 순차 배선 (spec 2026-10-13 §4.10).

LangGraph 경로의 `build_ephemeral_workflow` 와 같은 규칙을 배선 표로 옮긴다.
- 계약 노드는 `NODE_CONTRACTS[name].handler` 를 `owner` 에 바인딩해 넣는다
- 서브에이전트 템플릿 노드는 호스트의 핸들러를 감싸지 않고 넣고, 나가는 간선을 분기로 바꾼다:
  자식이 살아 있으면 자기 자신, 끝났으면 후속 하나. 후속이 둘 이상이면 병렬이라 거절한다
- 게이트 노드가 토폴로지에 있으면 `interrupt_before` 가 된다
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from neos.workflow.contracts import NODE_CONTRACTS
from neos.workflow.topology import GraphTopology
from neos.workflow.wiring import Branch, Edge, NodeSpec, Route, Wiring, WiringError


def _label_router(node: str, route: Callable[[Any], list[str]]) -> Callable[[Any], str]:
    def router(state: Any) -> str:
        targets = list(route(state))
        if len(targets) != 1:
            raise WiringError(f"{node}: 템플릿 후속이 {len(targets)}개다(parallel) -- 네이티브 러너는 순차만 돈다")
        return targets[0]

    router.__name__ = f"route_{node}"
    return router


def designed_wiring(
    topology: GraphTopology,
    owner: Any,
    *,
    subagent_host: Any = None,
    gated_nodes: frozenset[str],
) -> Wiring:
    templates = frozenset(subagent_host.template_names) if subagent_host is not None else frozenset()
    nodes: list[NodeSpec] = []
    for name in topology.nodes:
        if name in templates:
            nodes.append(NodeSpec(name, subagent_host.handler_for(name), wrapped=False))
        else:
            handler = NODE_CONTRACTS[name].handler.__get__(owner, type(owner))
            nodes.append(NodeSpec(name, handler))
    edges = tuple(Edge(source, target) for source, target in topology.edges if source not in templates)
    branches: list[Branch] = []
    for name in topology.nodes:
        if name not in templates:
            continue
        done = [target for source, target in topology.edges if source == name and target != name]
        router = _label_router(name, subagent_host.route_for(name, done))
        branches.append(Branch(name, router, (Route(name, name), *(Route(target, target) for target in done))))
    interrupts = tuple(sorted(set(topology.nodes) & gated_nodes))
    return Wiring(tuple(nodes), edges, tuple(branches), interrupts)
