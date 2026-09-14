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
from typing import Any, Protocol

# START/END 는 실제 노드가 아니라 그래프의 진입점·종료점을 나타내는 센티널이다.
# `NODE_CONTRACTS` 에 존재하지 않으며, 어떤 계약도 요구하지 않는다.
START = "__start__"
END = "__end__"

# `MultiAgentWorkflow._create_initial_state` (neos/workflow/graph.py) 가 그래프
# 실행 전에 `user_input[...]` 필수 접근(=`.get()` 이 아니라 서브스크립트)으로
# 채우는 키들 -- 노드가 하나도 안 써도 START 이전부터 항상 진짜 값이 들어
# 있다. `user_id`/`session_id`/`original_query` 는 각각 `user_input["user_id"]`
# / `["session_id"]` / `["query"]` 로 대입되고(누락되면 그래프가 시작하기도
# 전에 KeyError), `execution_start` 는 `datetime.now()` 로 무조건 대입된다.
# 이 넷 말고 `_create_initial_state` 가 채우는 나머지 필드(`search_results=[]`,
# `mission_id=None` 등)는 전부 `.get()` 이거나 빈 컨테이너/None 기본값이라
# "항상 의미 있는 값" 이 아니므로 여기 넣지 않는다 -- 그런 필드를 requires 하는
# 노드가 실제로 빈 값을 받는 경로는 이 함수가 아니라 진짜 그래프 배선(또는
# 계약)의 문제이지, 초기 상태의 문제가 아니다.
#
# 원래 `topology_export.py` (정적 그래프를 AST 로 추출하는 모듈) 안에만
# `_INITIAL_WRITES` 로 사설(private)로 존재했다. 이 상수는 그 모듈 하나의
# 관심사가 아니라 "그래프 진입 계약" 그 자체를 나타내는 그래프 어휘라서,
# `GraphTopology.initial_writes` 를 채우는 모든 호출자(정적 배선을 뽑는
# `topology_export.static_topology`, 서브에이전트 설계를 파싱하는
# `graph_designer.parse_topology` 양쪽 다) 가 같은 정의 하나를 공유해야
# 한다 -- 두 곳에 값을 따로 적으면 언젠가 한쪽만 고쳐져 드리프트한다. 그래서
# `GraphTopology` 가 사는 이 모듈로 옮겼다.
GRAPH_ENTRY_WRITES: frozenset[str] = frozenset(
    {"user_id", "session_id", "original_query", "execution_start"}
)


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
    requires_unless: Mapping[str, frozenset[str]]


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
class SubagentRuleInputs:
    """서브에이전트 템플릿 노드(트랙 I)에만 걸리는 규칙 셋의 재료.

    이 모듈이 `neos.subagent` 도 템플릿 레지스트리도 import 하지 않도록 필요한
    사실만 값으로 받는다 -- `_ContractLike` 가 계약 레지스트리를 import 하지
    않는 것과 같은 이유다. 채우는 곳은 `neos.workflow.subagent_nodes`.

    `validate_topology(subagent=None)` (기본)이면 규칙 셋은 **아예 돌지 않는다.**
    넘겨도 토폴로지에 템플릿 노드가 하나도 없으면 돌지 않는다(GS-K9′) --
    템플릿을 고르지 않은 설계의 판정이 플래그를 켜기 전과 같아야 M-1 이 M-0 과
    같은 규칙으로 그 설계들을 셀 수 있다.
    """

    template_nodes: frozenset[str]
    # 보고를 검사하는 노드. 설계 GS-K5 는 `fact_check` 하나만 인정한다.
    check_nodes: frozenset[str]
    # 리듀서가 붙은 `AgentState` 키. 병렬 가지가 같이 써도 안전하다.
    reducer_keys: frozenset[str]
    # 템플릿 노드 -> 계산 비용 상한(micros). `None` 은 미가격(fail closed).
    cost_ceilings_micros: Mapping[str, int | None] = field(default_factory=dict)
    # 템플릿 비용 상한 합의 예산. `None` 이면 예산이 없다는 위반이다(fail closed).
    budget_micros: int | None = None


@dataclass(frozen=True, slots=True)
class TopologyViolation:
    """토폴로지 규칙 위반 하나. `rule` 은 안정적인 snake_case 식별자다.

    `key` 는 위반이 특정 `AgentState` 키에 관한 것일 때만 채워진다(현재는
    `unsatisfied_requires` 뿐). 예전에는 이 정보가 한국어 `detail` 문장 안에만
    있어서, 이 위반 집합을 핀으로 고정하는 회귀 테스트가 정규식으로 `detail`
    에서 키를 파싱해야 했다 -- 문구를 다듬기만 해도 그 테스트가 깨질 수
    있었다. `key` 를 구조화된 필드로 분리해 그 결합을 끊는다. `detail` 은
    사람이 읽는 설명으로 그대로 남는다.
    """

    rule: str
    node: str | None
    detail: str
    key: str | None = None
    # 위반이 **특정 진입 경로**에서만 성립할 때 그 선행 노드 이름. 조건부 요구
    # (`requires_unless`) 검사만 채운다 -- 그 검사는 경로별로 돌기 때문에 범인을
    # 지목할 수 있고, 경로가 아홉인 노드에서 키 이름만 주면 어디를 고쳐야
    # 하는지 알 수 없다. 모든 경로의 교집합으로 계산하는 무조건 `requires`
    # 위반은 특정 경로의 잘못이 아니므로 `None` 으로 남는다.
    via: str | None = None


def validate_topology(
    topology: GraphTopology,
    *,
    contracts: Mapping[str, _ContractLike],
    mandatory: Sequence[str] = (),
    must_write: frozenset[str] = frozenset(),
    budget: int | None = None,
    node_costs: Mapping[str, int] | None = None,
    subagent: SubagentRuleInputs | None = None,
) -> tuple[TopologyViolation, ...]:
    """규칙 열 가지(+ 템플릿 노드가 있으면 셋)를 검사한다. 빈 튜플이면 유효.

    (아래 서술은 태스크 순서대로 쌓인 것이다. `missing_contract` 와
    `no_writer_for_required_key` 가 그 뒤에 더해져 기본 규칙은 열이다.)

    구조 규칙 넷(`unknown_node`, `unreachable_node`, `dead_end`,
    `unbounded_cycle`) 은 Task 3 그대로다. Task 4 가 더한 셋:

    - `unsatisfied_requires`: 노드가 `requires` 하는 키가 START 에서 그 노드에
      이르는 모든 경로에서 보장되지 않는다.
    - `missing_mandatory`: `mandatory` 로 지정한 노드 이름이 토폴로지에 없다.
    - `budget_exceeded`: `node_costs` 합계가 `budget` 을 넘는다. 비용이
      선언되지 않은 노드는 0 (무료)으로 보지 않고 그 자체로 위반이다 -- 값을
      모르면 통과시키지 않는다(fail closed).

    Task 6 이 더한 하나:

    - `empty_topology`: `nodes` 가 비어 있다. `mandatory` 를 넘기지 않은
      호출부(기본값 `()`)에서도 **무조건** 검사한다 -- 노드가 하나도 없는
      설계는 필수 노드 목록과 무관하게 항상 무효다. 이게 없으면
      `{"nodes": [], "edges": []}` 처럼 `parse_topology` 를 통과한 빈
      토폴로지가 이 함수에서도 위반 0개로 승인되고, 훨씬 나중에야(예: 실제
      그래프를 빌드하는 단계에서) 정체불명의 오류로 죽는다 -- 폴백이
      조용히 일어나면 안 된다는 이 시스템의 불변식을 어긴다.

    `mandatory`, `budget`, `node_costs` 는 기본값이 no-op 이라 기존 호출부
    (`contracts` 만 넘기는 Task 3 호출자)는 그대로 동작한다.
    """

    violations: list[TopologyViolation] = []

    if not topology.nodes:
        # 노드가 없으면 이후의 도달성·사이클·requires 계산은 전부 공허하게
        # 참(vacuously true)이 되어 아무 신호도 못 낸다 -- 그 "위반 없음"을
        # "유효함"으로 오인하지 않도록 여기서 명시적으로 위반을 하나 낸다.
        # `mandatory`/`budget` 검사는 그대로 아래에서 계속 돈다 -- 이 규칙은
        # 그것들을 대체하는 게 아니라, 그것들이 비어 있는 nodes 앞에서
        # 침묵하는 상황에 무조건 추가되는 방어선이다.
        violations.append(
            TopologyViolation(
                rule="empty_topology",
                node=None,
                detail="노드가 하나도 없다 -- 빈 설계는 mandatory 목록과 무관하게 항상 무효다",
            )
        )
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
            # 방어선이 실패 시 열리면 안 된다: 계약이 없는 노드를 "요구하는 게
            # 없다"로 취급해 조용히 넘어가면, 계약을 깜빡 붙이지 않은 노드
            # 하나만으로 requires 검증 전체가 그 노드에서 무력화된다 --
            # `budget_exceeded`가 비용 미선언 노드를 "무료"로 보지 않고 그
            # 자체로 위반으로 보는 것과 정확히 같은 이유(fail closed)다.
            # `NODE_CONTRACTS` 는 `neos.workflow.graph` 를 임포트해야 채워지는
            # 전역 레지스트리라, 호출자가 그 임포트를 빼먹으면 `contracts={}`
            # 가 넘어와 이 분기가 모든 노드에서 조용히 통과를 내줄 수 있었다.
            violations.append(
                TopologyViolation(
                    rule="missing_contract",
                    node=node,
                    detail=f"'{node}' 에 계약(NodeContract)이 선언되지 않아 requires 를 검증할 수 없다",
                    key=None,
                )
            )
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
                    key=key,
                )
            )
        violations.extend(
            _conditional_violations(
                node, contract, topology, writes_by_node, guaranteed
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

    # -- 반드시 쓰여야 하는 키 -------------------------------------------------
    #
    # `mandatory` 와 같은 요구(I1: "응답 없는 설계를 승인하지 않는다")를 **노드
    # 이름이 아니라 키**로 적는다. 둘의 차이가 실측으로 드러났다 -- 표본
    # `20260824T101448Z` 에서 대화형 질의 5건이 전부 `missing_mandatory` 로
    # 거부됐는데, 거부된 설계(`[direct_response]` 등)는 **옳은 그래프**였다.
    # "고마워요" 에 검색·분석·생성 오케스트레이터를 지나갈 이유가 없다.
    #
    # 원인은 표현이다: `direct_response` 도 `final_response` 를 쓴다(§14.2의
    # G1-a 가 그 노드를 응답 생산자로 인정한 그대로다). 요구를 노드 이름으로
    # 적는 순간 **진짜 요구(응답이 만들어지는가)와 구현 세부(어느 노드가
    # 만드는가)가 섞인다.**
    #
    # `mandatory` 를 지우지 않는 이유: 그쪽은 "이 노드가 반드시 있어야 한다"는
    # 다른 요구를 여전히 표현할 수 있다(예: 감사 로깅 노드). 둘은 대체가 아니라
    # 다른 질문이고, 기본값이 no-op 이라 안 쓰면 돌지 않는다.
    if must_write:
        written_anywhere: set[str] = set()
        for name in topology.nodes:
            contract = contracts.get(name)
            if contract is not None:
                written_anywhere |= set(contract.writes)
        for key in sorted(must_write):
            if key not in written_anywhere:
                violations.append(
                    TopologyViolation(
                        rule="no_writer_for_required_key",
                        node=None,
                        detail=(
                            f"'{key}' 를 쓰는 노드가 토폴로지에 하나도 없다 -- "
                            "구조적으로 성립해도 이 설계는 그 값을 만들지 않는다"
                        ),
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

    if subagent is not None:
        violations.extend(
            _subagent_violations(topology, contracts, subagent, forward)
        )

    return tuple(violations)


def _subagent_violations(
    topology: GraphTopology,
    contracts: Mapping[str, _ContractLike],
    inputs: SubagentRuleInputs,
    forward: Mapping[str, set[str]],
) -> list[TopologyViolation]:
    """템플릿 노드 규칙 셋. 토폴로지에 템플릿이 없으면 빈 목록(GS-K9′)."""

    present = [node for node in topology.nodes if node in inputs.template_nodes]
    if not present:
        return []
    violations: list[TopologyViolation] = []

    # -- unchecked_subagent_report ------------------------------------------
    # 기존 `_guaranteed_keys` 는 START -> N 방향이라 여기 쓸 수 없다. 묻는 것은
    # "검사 노드를 지운 그래프에서 S 의 후속으로부터 END 에 닿는가" 다 -- 닿는
    # 경로가 하나라도 있으면 그 경로의 보고는 검사 없이 응답까지 간다.
    for node in present:
        stack = [
            succ
            for succ in forward.get(node, ())
            if succ != node and succ not in inputs.check_nodes
        ]
        seen = set(stack)
        leaks = False
        while stack:
            current = stack.pop()
            if current == END:
                leaks = True
                break
            for succ in forward.get(current, ()):
                if succ in inputs.check_nodes or succ in seen:
                    continue
                seen.add(succ)
                stack.append(succ)
        if leaks:
            violations.append(
                TopologyViolation(
                    rule="unchecked_subagent_report",
                    node=node,
                    detail=(
                        f"'{node}' 의 보고가 {sorted(inputs.check_nodes)} 를 거치지 않고 "
                        "END 에 닿는 경로가 있다 -- 검증되지 않은 보고가 응답에 섞인다"
                    ),
                )
            )

    # -- subagent_budget_exceeded -------------------------------------------
    unpriced = [
        node for node in present if inputs.cost_ceilings_micros.get(node) is None
    ]
    for node in unpriced:
        violations.append(
            TopologyViolation(
                rule="subagent_budget_exceeded",
                node=node,
                detail=f"'{node}' 의 비용 상한을 계산할 수 없다(가격 또는 모델 창 미상)",
            )
        )
    if inputs.budget_micros is None:
        violations.append(
            TopologyViolation(
                rule="subagent_budget_exceeded",
                node=None,
                detail="템플릿 노드가 있는데 subagent_budget_micros 가 없다",
            )
        )
    elif not unpriced:
        total = sum(int(inputs.cost_ceilings_micros[node] or 0) for node in present)
        if total > inputs.budget_micros:
            violations.append(
                TopologyViolation(
                    rule="subagent_budget_exceeded",
                    node=None,
                    detail=(
                        f"템플릿 노드 비용 상한 합계 {total} micros 가 예산 "
                        f"{inputs.budget_micros} 을 초과했다"
                    ),
                )
            )

    # -- concurrent_write_conflict ------------------------------------------
    # 설계된 그래프의 엣지는 전부 정적이라 한 노드의 후속은 **모두** 같은
    # 슈퍼스텝에 뜬다. 서로에게 닿지 않는 두 노드는 같은 슈퍼스텝에 설 수 있고,
    # 둘이 리듀서 없는 키를 같이 쓰면 LangGraph 1.2 가 `InvalidUpdateError` 로
    # run 을 죽인다. 깊이가 달라 실제로는 겹치지 않는 쌍도 거부한다(보수적).
    reach = {node: _bfs(node, forward) for node in topology.nodes}
    ordered = sorted(set(topology.nodes))
    for index, left in enumerate(ordered):
        for right in ordered[index + 1 :]:
            if right in reach[left] or left in reach[right]:
                continue
            left_contract = contracts.get(left)
            right_contract = contracts.get(right)
            if left_contract is None or right_contract is None:
                continue
            shared = (
                left_contract.writes & right_contract.writes
            ) - inputs.reducer_keys
            for key in sorted(shared):
                violations.append(
                    TopologyViolation(
                        rule="concurrent_write_conflict",
                        node=left,
                        detail=(
                            f"'{left}' 와 '{right}' 는 병렬로 설 수 있는데 리듀서 없는 "
                            f"키 '{key}' 를 같이 쓴다"
                        ),
                        key=key,
                        via=right,
                    )
                )
    return violations


def _conditional_violations(
    node: str,
    contract: _ContractLike,
    topology: GraphTopology,
    writes: Mapping[str, frozenset[str]],
    guaranteed: Mapping[str, frozenset[str]],
) -> list[TopologyViolation]:
    """`requires_unless` 를 **진입 경로마다** 검사한다.

    무조건 `requires` 는 `_guaranteed_keys` 의 교집합 하나로 판정하면 되지만
    조건부 요구는 그럴 수 없다. 교집합은 "모든 경로에서 참인 것" 이므로, 아홉
    경로 중 여덟이 면제 키를 줘도 한 경로가 안 주면 노드 수준에서는 면제 키가
    없는 것으로 나온다 -- 노드 단위로 면제를 판정하면 **면제가 발동조차 하지
    않는다.** 조건이 성립하는 단위가 경로이므로 경로별로 본다.

    한 경로가 합법인 조건은 둘 중 하나다: 면제 키를 얻었거나(그 경로로 들어온
    실행은 조건부 키를 읽지 않는다), 조건부 키를 전부 얻었거나. 둘 다 아니면
    그 경로로 들어온 실행은 **빈 값을 읽고 조용히 저하된다** -- §14.0 이
    이 저장소의 관통 주제로 적은 실패다.
    """
    if not contract.requires_unless:
        return []

    predecessors = sorted({source for source, target in topology.edges if target == node})
    violations: list[TopologyViolation] = []
    for waiver, keys in sorted(contract.requires_unless.items()):
        for pred in predecessors:
            if pred == START:
                # START 경로에서 쓸 수 있는 것은 호출자가 채워 준 것뿐이다.
                available = topology.initial_writes
            else:
                available = guaranteed.get(pred, frozenset()) | writes.get(
                    pred, frozenset()
                )
            if waiver in available:
                continue
            for key in sorted(keys - available):
                violations.append(
                    TopologyViolation(
                        rule="unsatisfied_requires",
                        node=node,
                        detail=(
                            f"'{node}' 가 '{pred}' 경로로 들어올 때 키 '{key}' 가 "
                            f"보장되지 않는다 -- 그 경로는 면제 키 '{waiver}' 도 "
                            "주지 않는다"
                        ),
                        key=key,
                        via=pred,
                    )
                )
    return violations


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


class TopologyPayloadError(ValueError):
    """저장된 토폴로지 페이로드를 `GraphTopology` 로 되돌릴 수 없다.

    재개 경로가 이것을 잡아 **정적으로 흐르지 않고** 거부한다 -- 복원할 수 없는
    토폴로지로 재개하는 것은 다른 그래프로 재개하는 것과 같다.
    """


def topology_to_payload(topology: GraphTopology) -> dict[str, Any]:
    """`GraphTopology` 를 JSON 에 실을 수 있는 dict 로 만든다.

    상태에 실려 체크포인트에 저장되므로 JSON 안전해야 한다. tuple 은 list 가
    되고 `topology_from_payload` 가 되돌린다.
    """
    return {
        "nodes": list(topology.nodes),
        "edges": [list(edge) for edge in topology.edges],
        "loop_bounds": dict(topology.loop_bounds),
        "initial_writes": sorted(topology.initial_writes),
    }


def topology_from_payload(payload: Mapping[str, Any]) -> GraphTopology:
    """`topology_to_payload` 의 역. 모양이 틀리면 `TopologyPayloadError`.

    관대하게 받지 않는다 -- 여기서 통과시킨 이상한 페이로드는
    `build_ephemeral_workflow` 안에서 알아보기 어려운 예외가 된다.
    """
    if not isinstance(payload, Mapping):
        raise TopologyPayloadError(f"페이로드가 매핑이 아니다: {type(payload).__name__}")

    try:
        raw_nodes = payload["nodes"]
        raw_edges = payload["edges"]
    except KeyError as error:
        raise TopologyPayloadError(f"페이로드에 {error} 가 없다") from error

    if not isinstance(raw_nodes, (list, tuple)):
        raise TopologyPayloadError("nodes 가 시퀀스가 아니다")
    if not isinstance(raw_edges, (list, tuple)):
        raise TopologyPayloadError("edges 가 시퀀스가 아니다")

    edges: list[tuple[str, str]] = []
    for edge in raw_edges:
        if not isinstance(edge, (list, tuple)) or len(edge) != 2:
            raise TopologyPayloadError(f"간선이 2-튜플이 아니다: {edge!r}")
        edges.append((str(edge[0]), str(edge[1])))

    try:
        loop_bounds_dict = dict(payload.get("loop_bounds") or {})
    except (ValueError, TypeError) as error:
        raise TopologyPayloadError(f"loop_bounds 를 변환할 수 없다: {error}") from error

    try:
        initial_writes_set = frozenset(payload.get("initial_writes") or ())
    except (ValueError, TypeError) as error:
        raise TopologyPayloadError(f"initial_writes 를 변환할 수 없다: {error}") from error

    return GraphTopology(
        nodes=tuple(str(node) for node in raw_nodes),
        edges=tuple(edges),
        loop_bounds=loop_bounds_dict,
        initial_writes=initial_writes_set,
    )
