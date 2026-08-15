"""서브에이전트가 제안한 그래프 토폴로지가 구조적/의미론적으로 성립하는지 검증한다.

Task 1-2 는 각 노드가 `AgentState` 의 무엇을 읽고·쓰고·요구하는지를 데이터
(`NodeContract`) 로 명시했다. Task 3 는 노드들이 어떻게 이어져 있는지 -- START 에서
모든 노드에 닿는가, 모든 노드가 END 로 빠져나가는가, 엣지가 실존하는 노드만
가리키는가, 사이클에 반복 상한이 선언되어 있는가 -- 만 봤다.

이 태스크는 계약의 의미론적 절반을 마저 본다: 노드 N 이 키 K 를 `requires` 한다면,
START 에서 N 에 이르는 **모든** 경로에 K 를 `writes` 하는 노드가 있어야 한다. 어느
한 경로에만 있으면, 그 나머지 경로로 들어온 실행은 예외 없이 조용히 빈 값을 읽는다
-- 이 검증기가 유일한 방어선이다. 그 밖에 필수 노드 존재 여부(`missing_mandatory`)와
노드 비용 합계가 예산을 넘지 않는지(`budget_exceeded`)도 함께 본다.

계약의 `writes`/`requires` 두 필드만 있으면 위 규칙을 계산할 수 있다. 그래서
`neos.workflow.contracts` (AST 로 소스를 파싱해 위임 체인을 추적하는 계약
레지스트리 전체)를 임포트하지 않고, 아래 `_ContractLike` 프로토콜로 그 두 필드만
구조적으로 요구한다 -- Task 3 가 지켰던 "순수 그래프 모듈" 속성을 유지해, 계약
레지스트리 없이도 토폴로지 규칙만 독립적으로 시험·추론할 수 있게 한다.
`NodeContract` 는 이 프로토콜을 별도 선언 없이 구조적으로 만족한다.
"""

from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

# START/END 는 실제 노드가 아니라 그래프의 진입점·종료점을 나타내는 센티널이다.
# `NODE_CONTRACTS` 에 존재하지 않으며, 어떤 계약도 요구하지 않는다.
START = "__start__"
END = "__end__"


class _ContractLike(Protocol):
    """`validate_topology` 가 실제로 쓰는 계약 속성 두 개만 요구하는 구조적 타입.

    `neos.workflow.contracts.NodeContract` 전체(핸들러, hand_curated 플래그,
    AST 추출 로직 등)가 아니라 `writes`/`requires` 만 있으면 이 모듈의 규칙을
    계산할 수 있다. `Protocol` 을 쓰면 `NodeContract` 가 이 타입을 상속하지
    않고도 구조적으로 만족하므로, 이 모듈은 계약 레지스트리를 임포트하지 않고도
    타입 안정성을 잃지 않는다.
    """

    writes: frozenset[str]
    requires: frozenset[str]


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
    # 그래프 호출자가 START 이전에 이미 채워 넣는 키 -- 어떤 노드도 쓰지 않지만
    # 항상 존재하는 "그래프 진입 계약" 이다 (예: 사용자의 원본 질의). 어떤
    # 노드의 `requires` 가 이 집합의 부분집합이면, 그 노드가 START 에서 바로
    # 이어지는 경로로 들어와도(즉 아무 노드도 거치지 않아도) 위반으로 잡히지
    # 않는다. Task 3-4 의 `_guaranteed_keys` 는 이 필드가 없던 시절 "START 를
    # 거치는 경로는 아무것도 보장하지 않는다" 로 짰다(정확히 노드가 쓴 것만
    # 인정) -- 그 규칙은 그래프 *내부* 에서 흐르는 키에는 여전히 맞지만, 호출자가
    # 애초에 채워 주는 키에는 안 맞다: 그런 키를 요구하는 진입 노드가 하나만
    # 있어도 매번 거짓 위반이 뜬다. 기본값이 빈 집합이므로 이 필드를 쓰지 않는
    # 기존 호출자(Task 3-4 의 손으로 만든 토폴로지들)는 동작이 그대로다.
    initial_writes: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class TopologyViolation:
    """토폴로지 규칙 위반 하나. `rule` 은 안정적인 snake_case 식별자다."""

    rule: str
    node: str | None
    detail: str


def validate_topology(
    topology: GraphTopology,
    *,
    contracts: Mapping[str, _ContractLike],
    mandatory: Sequence[str] = (),
    budget: int | None = None,
    node_costs: Mapping[str, int] | None = None,
) -> tuple[TopologyViolation, ...]:
    """일곱 가지 규칙을 검사한다. 빈 튜플이면 유효.

    구조 규칙 넷(`unknown_node`, `unreachable_node`, `dead_end`,
    `unbounded_cycle`) 은 Task 3 그대로다. 이 태스크가 더하는 셋:

    - `unsatisfied_requires`: 노드가 `requires` 하는 키가 START 에서 그 노드에
      이르는 모든 경로에서 보장되지 않는다.
    - `missing_mandatory`: `mandatory` 로 지정한 노드 이름이 토폴로지에 없다.
    - `budget_exceeded`: `node_costs` 합계가 `budget` 을 넘는다. 비용이
      선언되지 않은 노드는 0 (무료)으로 보지 않고 그 자체로 위반이다 -- 값을
      모르면 통과시키지 않는다(fail closed).

    `mandatory`, `budget`, `node_costs` 는 기본값이 no-op 이라 기존 호출부
    (`contracts` 만 넘기는 Task 3 호출자)는 그대로 동작한다.
    """

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

    # -- 계약 충족: requires 하는 키가 모든 경로에서 보장되는가 -----------------
    writes_by_node = {node: contract.writes for node, contract in contracts.items()}
    guaranteed = _guaranteed_keys(topology, writes_by_node)
    for node in topology.nodes:
        contract = contracts.get(node)
        if contract is None:
            continue
        missing_keys = contract.requires - guaranteed.get(node, frozenset())
        for key in sorted(missing_keys):
            violations.append(
                TopologyViolation(
                    rule="unsatisfied_requires",
                    node=node,
                    detail=(
                        f"'{node}' 가 요구하는 키 '{key}' 가 START 에서 "
                        f"'{node}' 에 이르는 모든 경로에서 보장되지 않는다"
                    ),
                )
            )

    # -- 필수 노드 -----------------------------------------------------------
    declared_nodes = frozenset(topology.nodes)
    for name in mandatory:
        if name not in declared_nodes:
            violations.append(
                TopologyViolation(
                    rule="missing_mandatory",
                    node=name,
                    detail=f"필수 노드 '{name}' 가 토폴로지에 없다",
                )
            )

    # -- 예산 -----------------------------------------------------------------
    # 방어선이 실패 시 열리면 안 된다: 비용이 선언되지 않은 노드를 0 으로 취급해
    # 조용히 넘어가면, 값비싼 노드 하나가 node_costs 에서 누락되는 것만으로
    # 예산 검사가 아무 경고 없이 무력화된다. 그래서 비용 미선언 노드는 "무료"가
    # 아니라 그 자체로 위반으로 본다 (fail closed) -- 합계를 계산하기 전에
    # 먼저 전부 가격이 매겨져 있는지부터 확인한다.
    if budget is not None:
        costs = node_costs or {}
        unpriced_nodes = tuple(node for node in topology.nodes if node not in costs)
        if unpriced_nodes:
            for node in unpriced_nodes:
                violations.append(
                    TopologyViolation(
                        rule="budget_exceeded",
                        node=node,
                        detail=f"'{node}' 의 비용이 node_costs 에 선언되지 않아 예산을 계산할 수 없다",
                    )
                )
        else:
            total_cost = sum(costs.get(node, 0) for node in topology.nodes)
            if total_cost > budget:
                violations.append(
                    TopologyViolation(
                        rule="budget_exceeded",
                        node=None,
                        detail=f"노드 비용 합계 {total_cost} 가 예산 {budget} 을 초과했다",
                    )
                )

    return tuple(violations)


def _guaranteed_keys(
    topology: GraphTopology,
    writes: Mapping[str, frozenset[str]],
) -> dict[str, frozenset[str]]:
    """노드 진입 시점에 **모든 경로에서** 이미 쓰였음이 보장되는 키.

    선행 노드들의 보장 집합을 **교집합** 한다 -- 어느 한 경로에만 있는 키는
    보장이 아니다. 사이클이 있어도 수렴하도록 비-START 노드를 전체 집합으로
    낙관적으로 초기화하고 줄여 나간다(must-analysis 의 표준 형태). 선행 노드
    중 하나가 START 면 그 경로에서는 `topology.initial_writes` (그래프
    호출자가 이미 채워 준 키) 만큼만 보장된다 -- 노드가 쓴 게 아니라도 이
    키들은 항상 있다는 뜻이다. `initial_writes` 가 비어 있으면(기본값)
    START 경로의 기여가 빈 집합이 되어 교집합 전체가 무너지는 예전 동작과
    100% 동일하다.
    """

    universe = frozenset().union(*writes.values(), topology.initial_writes)
    incoming: dict[str, list[str]] = {n: [] for n in topology.nodes}
    for source, target in topology.edges:
        if target in incoming:
            incoming[target].append(source)

    guaranteed = {n: universe for n in topology.nodes}
    changed = True
    while changed:
        changed = False
        for node in topology.nodes:
            preds = incoming[node]
            if not preds:
                merged = frozenset()
            else:
                merged = frozenset(universe)
                for pred in preds:
                    if pred == START:
                        merged &= topology.initial_writes
                        continue
                    merged &= guaranteed.get(pred, frozenset()) | writes.get(
                        pred, frozenset()
                    )
            if merged != guaranteed[node]:
                guaranteed[node] = merged
                changed = True
    return guaranteed


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
