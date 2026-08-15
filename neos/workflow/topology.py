"""서브에이전트가 제안한 그래프 토폴로지가 구조적으로 성립하는지 검증한다.

Task 1-2 는 각 노드가 `AgentState` 의 무엇을 읽고·쓰고·요구하는지를 데이터
(`NodeContract`) 로 명시했다. 이 모듈은 그 다음 절반 -- 노드들이 어떻게 이어져
있는지 -- 를 다룬다: START 에서 모든 노드에 닿는가, 모든 노드가 END 로 빠져나가는가,
엣지가 실존하는 노드만 가리키는가, 사이클에 반복 상한이 선언되어 있는가.

노드가 실제로 필요한 상태를 상류에서 만들어내는지(계약의 의미론적 절반)는 다음
태스크의 몫이다. 이 모듈은 그래서 `contracts` 인자를 받기만 하고 아직 쓰지 않는다
-- `neos/workflow/contracts.py` 를 임포트하지 않는 순수 그래프 모듈로 남겨, 계약
레지스트리 없이도 토폴로지 규칙을 독립적으로 시험할 수 있게 한다.
"""

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field

# START/END 는 실제 노드가 아니라 그래프의 진입점·종료점을 나타내는 센티널이다.
# `NODE_CONTRACTS` 에 존재하지 않으며, 어떤 계약도 요구하지 않는다.
START = "__start__"
END = "__end__"


@dataclass(frozen=True, slots=True)
class GraphTopology:
    """서브에이전트가 제안하는 그래프의 구조 -- 노드 집합과 방향 엣지."""

    nodes: tuple[str, ...]
    edges: tuple[tuple[str, str], ...]
    # 사이클마다 선언된 반복 상한. 키는 사이클에 속한 노드 이름, 값은 최대 반복
    # 횟수다. Task 4 가 예산 검증에 실제로 사용하며, 여기서는 "사이클인데
    # 상한이 없다" 를 표현하기 위해서만 존재한다 -- 기본값이 빈 매핑이므로
    # 이 태스크의 사이클은 전부 거부된다.
    loop_bounds: Mapping[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TopologyViolation:
    """토폴로지 규칙 위반 하나. `rule` 은 안정적인 snake_case 식별자다."""

    rule: str
    node: str | None
    detail: str


def validate_topology(
    topology: GraphTopology, *, contracts: Mapping[str, object]
) -> tuple[TopologyViolation, ...]:
    """네 가지 구조 규칙을 검사한다. 빈 튜플이면 유효.

    `contracts` 는 이 태스크에서 실제로 쓰이지 않는다 -- 다음 태스크가 노드의
    `requires` 가 상류에서 채워지는지 검증할 때 이 시그니처를 확장해 사용한다.
    """

    del contracts  # 이 태스크의 규칙 넷은 구조만 보고, 계약 내용은 보지 않는다.

    violations: list[TopologyViolation] = []
    declared = frozenset(topology.nodes) | {START, END}

    unknown_nodes = _find_unknown_nodes(topology.edges, declared)
    for node in unknown_nodes:
        violations.append(
            TopologyViolation(
                rule="unknown_node",
                node=node,
                detail=f"엣지가 선언되지 않은 노드 '{node}' 를 가리킨다",
            )
        )

    # 이후의 도달성·사이클 판단은 두 끝점이 모두 선언된 엣지만으로 그래프를
    # 구성한다 -- 미지 노드를 그래프의 일부인 것처럼 취급하지 않는다.
    valid_edges = tuple(
        (source, target)
        for source, target in topology.edges
        if source in declared and target in declared
    )
    forward = _adjacency(declared, valid_edges)
    backward = _adjacency(
        declared, tuple((target, source) for source, target in valid_edges)
    )

    reachable_from_start = _bfs(START, forward)
    for node in topology.nodes:
        if node not in reachable_from_start:
            violations.append(
                TopologyViolation(
                    rule="unreachable_node",
                    node=node,
                    detail=f"'{node}' 는 START 에서 어떤 경로로도 도달할 수 없다",
                )
            )

    reaches_end = _bfs(END, backward)
    for node in topology.nodes:
        if node not in reaches_end:
            violations.append(
                TopologyViolation(
                    rule="dead_end",
                    node=node,
                    detail=f"'{node}' 에서 END 로 도달하는 경로가 없다",
                )
            )

    self_loop_nodes = {source for source, target in valid_edges if source == target}
    for component in _strongly_connected_components(declared, forward):
        is_cycle = len(component) >= 2 or (
            len(component) == 1 and next(iter(component)) in self_loop_nodes
        )
        if not is_cycle:
            continue
        for node in component:
            if node in (START, END):
                # 센티널은 사이클 판단 대상이 아니다 -- 계약을 요구하지 않는 것과
                # 같은 이유로, 반복 상한 선언 역시 대상이 아니다.
                continue
            if node not in topology.loop_bounds:
                violations.append(
                    TopologyViolation(
                        rule="unbounded_cycle",
                        node=node,
                        detail=f"'{node}' 는 사이클에 속하지만 반복 상한이 선언되지 않았다",
                    )
                )

    return tuple(violations)


def _find_unknown_nodes(
    edges: Iterable[tuple[str, str]], declared: frozenset[str]
) -> tuple[str, ...]:
    """`declared` (노드 ∪ 센티널) 에 없는 엣지 끝점을 발견 순서대로 반환한다."""

    unknown: list[str] = []
    seen: set[str] = set()
    for source, target in edges:
        for endpoint in (source, target):
            if endpoint not in declared and endpoint not in seen:
                seen.add(endpoint)
                unknown.append(endpoint)
    return tuple(unknown)


def _adjacency(
    nodes: Iterable[str], edges: Iterable[tuple[str, str]]
) -> dict[str, set[str]]:
    """엣지 목록을 인접 리스트로 바꾼다. 고립 노드도 빈 집합으로 채워 둔다."""

    adjacency: dict[str, set[str]] = {node: set() for node in nodes}
    for source, target in edges:
        adjacency.setdefault(source, set()).add(target)
    return adjacency


def _bfs(source: str, adjacency: Mapping[str, set[str]]) -> frozenset[str]:
    """`source` 에서 `adjacency` 를 따라 전방 도달 가능한 노드 집합(자기 자신 포함)."""

    visited = {source}
    stack = [source]
    while stack:
        current = stack.pop()
        for neighbor in adjacency.get(current, ()):
            if neighbor not in visited:
                visited.add(neighbor)
                stack.append(neighbor)
    return frozenset(visited)


def _strongly_connected_components(
    nodes: Iterable[str], forward: Mapping[str, set[str]]
) -> list[frozenset[str]]:
    """Kosaraju 알고리즘으로 강결합 성분을 구한다. 재귀 대신 명시적 스택을 쓴다.

    1단계: 원본 그래프를 DFS 하며 완료(finish) 순서를 기록한다.
    2단계: 역방향 그래프를 완료 순서의 역순으로 DFS 해, 한 번의 방문으로 닿는
    노드들을 하나의 성분으로 묶는다.
    """

    node_list = list(nodes)
    visited: set[str] = set()
    finish_order: list[str] = []

    for start in node_list:
        if start in visited:
            continue
        visited.add(start)
        stack: list[tuple[str, Iterator[str]]] = [(start, iter(forward.get(start, ())))]
        while stack:
            current, neighbors = stack[-1]
            descended = False
            for neighbor in neighbors:
                if neighbor not in visited:
                    visited.add(neighbor)
                    stack.append((neighbor, iter(forward.get(neighbor, ()))))
                    descended = True
                    break
            if not descended:
                finish_order.append(current)
                stack.pop()

    reverse: dict[str, set[str]] = {node: set() for node in node_list}
    for node in node_list:
        for neighbor in forward.get(node, ()):
            reverse.setdefault(neighbor, set()).add(node)

    assigned: set[str] = set()
    components: list[frozenset[str]] = []
    for node in reversed(finish_order):
        if node in assigned:
            continue
        component: set[str] = set()
        stack = [node]
        assigned.add(node)
        while stack:
            current = stack.pop()
            component.add(current)
            for neighbor in reverse.get(current, ()):
                if neighbor not in assigned:
                    assigned.add(neighbor)
                    stack.append(neighbor)
        components.append(frozenset(component))

    return components
