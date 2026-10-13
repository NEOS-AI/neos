"""채팅 워크플로의 배선 -- 노드·엣지·조건 분기를 데이터 하나로 (spec 2026-10-13 §4.1).

정적 토폴로지(`topology_export.static_topology`)와 LangGraph 조립
(`runtime/langgraph_adapter.compile_wiring`)이 이 표 하나를 읽는다. 표가 생기기
전에는 `_create_workflow_graph` 의 `workflow.add_*` 호출이 원천이었고, 정적
토폴로지는 그 소스를 AST 로 읽었다(트랙 S 불변식 5).

**플래그.** 항목의 `requires` 는 `(플래그 키, 기대값)` 쌍들이고 전부 맞아야 켜진다.
키는 `FLAG_ATTR_TO_KEY` 의 값이다. 플래그별로 대상이 바뀌는 분기 경로는 `Route` 마다
`requires` 를 두고, 한 라벨에 켜진 경로는 하나여야 한다(`resolve_wiring` 이 강제).

**중복 엣지.** `topology_of` 는 같은 (출발, 도착) 쌍을 경로 수만큼 낸다 -- 옛 AST
추출기가 그랬고, `topology_hash` 는 정렬만 하고 중복을 지우지 않는다. 해시를 지키려면
배수까지 같아야 한다.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from neos.workflow.enums import WorkflowNode as N
from neos.workflow.enums import WorkflowPathway as P
from neos.workflow.topology import END, GRAPH_ENTRY_WRITES, START, GraphTopology

Requires = tuple[tuple[str, bool], ...]

# `settings` 의 별칭 속성 → 배선 플래그 키. `execution_graph.current_static_flags` 가
# 이 지도로 실행 시점 플래그를 읽는다 -- 키가 빠지면 그 자리가 기본값('켬')으로 채워져
# 꺼진 기능이 켜진 것으로 계산된다.
FLAG_ATTR_TO_KEY: dict[str, str] = {
    "RECURSIVE_AGENT_ENABLED": "recursive",
    "HYPER_DEEP_AGENT_ENABLED": "hyper_deep",
    "DEEP_ANALYSIS_ENABLED": "deep_analysis",
    "EXECUTION_APPROVAL_ENABLED": "execution_approval",
    "A2UI_ENABLED": "a2ui",
    "SKILL_EXECUTION_ENABLED": "skill_execution",
}

# 기본값은 전부 켠 상태 -- 가장 넓은 그래프가 가장 많은 위반을 드러낸다.
DEFAULT_FLAGS: dict[str, bool] = dict.fromkeys(FLAG_ATTR_TO_KEY.values(), True)

# 사이클마다 선언하는 반복 상한 (옛 `topology_export` 에서 옮김). 값의 출처:
#   replan            neos/workflow/routing/quality_router.py `replan_count < 2`
#   quality regenerate config/neos.default.yaml workflow.max_retries 기본값
#   harness repair    neos/workflow/harness/models.py max_repair_attempts 기본값
_REPLAN_MAX_ATTEMPTS = 2
_QUALITY_REGENERATE_MAX_ATTEMPTS = 2
_HARNESS_REPAIR_MAX_ATTEMPTS = 1

LOOP_BOUNDS: dict[str, int] = {
    **dict.fromkeys(
        (
            N.HYPOTHESIS_GENERATION.value,
            N.SEARCH_ORCHESTRATOR.value,
            N.HYPOTHESIS_EVALUATION.value,
            N.REPLANNER.value,
        ),
        _REPLAN_MAX_ATTEMPTS,
    ),
    **dict.fromkeys(
        (
            N.ANALYSIS_ORCHESTRATOR.value,
            N.GENERATION_ORCHESTRATOR.value,
            N.RESULT_INTEGRATOR.value,
            N.FACT_CHECK.value,
            N.QUALITY_VALIDATOR.value,
        ),
        _QUALITY_REGENERATE_MAX_ATTEMPTS,
    ),
    **dict.fromkeys(
        (N.RESEARCH_HARNESS.value, N.RESEARCH_HARNESS_REPAIR.value),
        _HARNESS_REPAIR_MAX_ATTEMPTS,
    ),
}


class WiringError(ValueError):
    """표가 닫혀 있지 않거나(없는 노드를 가리킨다) 한 라벨에 경로가 둘 켜졌다."""


@dataclass(frozen=True)
class NodeSpec:
    name: str
    handler: str  # MultiAgentWorkflow 의 메서드 이름
    requires: Requires = ()


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    requires: Requires = ()


@dataclass(frozen=True)
class Route:
    label: str
    target: str
    requires: Requires = ()


@dataclass(frozen=True)
class Branch:
    source: str
    router: str  # MultiAgentWorkflow 의 메서드 이름 -- 상태를 받아 라벨을 돌려준다
    routes: tuple[Route, ...]
    requires: Requires = ()


@dataclass(frozen=True)
class Interrupt:
    node: str
    requires: Requires = ()


@dataclass(frozen=True)
class Wiring:
    nodes: tuple[NodeSpec, ...]
    edges: tuple[Edge, ...]
    branches: tuple[Branch, ...]
    interrupt_before: tuple[str, ...] = ()

    def path_map(self, branch: Branch) -> dict[str, str]:
        return {route.label: route.target for route in branch.routes}


def _on(*keys: str) -> Requires:
    return tuple((key, True) for key in keys)


def _off(*keys: str) -> Requires:
    return tuple((key, False) for key in keys)


NODES: tuple[NodeSpec, ...] = (
    NodeSpec(N.REFINEMENT_CHECKER.value, "_check_refinement_node"),
    NodeSpec(N.QUERY_REFINEMENT.value, "_refine_query_node"),
    NodeSpec(N.RESEARCH_CONTINUATION.value, "_research_continuation_node"),
    NodeSpec(N.CONVERSATION_CTX_PROC.value, "_process_conversation_context_node"),
    NodeSpec(N.QUERY_CLS.value, "_classify_query_node"),
    NodeSpec(N.SKILL_TOOL_SELECTOR.value, "_select_skills_tools_node"),
    NodeSpec(N.HYPOTHESIS_GENERATION.value, "_hypothesis_generation_node"),
    NodeSpec(N.SEARCH_ORCHESTRATOR.value, "_orchestrate_search_node"),
    NodeSpec(N.HYPOTHESIS_EVALUATION.value, "_hypothesis_evaluation_node"),
    NodeSpec(N.REPLANNER.value, "_replanner_node"),
    NodeSpec(N.ANALYSIS_ORCHESTRATOR.value, "_orchestrate_analysis_node"),
    NodeSpec(N.GENERATION_ORCHESTRATOR.value, "_orchestrate_generation_node"),
    NodeSpec(N.RESULT_INTEGRATOR.value, "_integrate_results_node"),
    NodeSpec(N.FACT_CHECK.value, "_fact_check_node"),
    NodeSpec(N.QUALITY_VALIDATOR.value, "_validate_quality_node"),
    NodeSpec(N.RESEARCH_HARNESS.value, "_research_harness_node"),
    NodeSpec(N.RESEARCH_HARNESS_REPAIR.value, "_research_harness_repair_node"),
    NodeSpec(N.SELF_REFLECTION.value, "_self_reflection_node"),
    NodeSpec(N.MISSION_PLANNER.value, "_mission_planner_node"),
    NodeSpec(N.MISSION_APPROVAL.value, "_mission_approval_node"),
    NodeSpec(N.MISSION_EXECUTOR.value, "_mission_executor_node"),
    NodeSpec(N.MISSION_VALIDATOR.value, "_mission_validator_node"),
    NodeSpec(N.MISSION_INTEGRATOR.value, "_mission_integrator_node"),
    NodeSpec(N.RESP_GENERATOR.value, "_generate_response_node"),
    # G1-a: `skip_orchestrators` 는 요약할 결과를 만드는 노드를 하나도 지나지 않는다.
    # 이 노드가 그 자리에서 직접 답을 만든다.
    NodeSpec(N.DIRECT_RESPONSE.value, "_direct_response_node"),
    NodeSpec(N.SKILL_EXECUTOR.value, "_skill_executor_node", _on("skill_execution")),
    NodeSpec(N.RECURSIVE_ORCHESTRATOR.value, "_recursive_orchestrator_node", _on("recursive")),
    NodeSpec(N.HYPER_DEEP_ORCHESTRATOR.value, "_hyper_deep_orchestrator_node", _on("hyper_deep")),
    NodeSpec(N.DEEP_ANALYSIS_DISPATCH.value, "_deep_analysis_dispatch_node", _on("deep_analysis")),
    # Phase 2 (OpenClaw Execution Approval): 민감 스킬 사용자 승인 노드. `INTERRUPTS` 가
    # 이 노드 앞에서 멈추고, 재개되면 이 노드가 실행된다.
    NodeSpec(N.EXECUTION_APPROVAL.value, "_execution_approval_node", _on("execution_approval")),
    # Phase 4 (OpenClaw Cron): 자연어 스케줄 등록 노드
    NodeSpec(N.TASK_SCHEDULING_NODE.value, "_handle_task_scheduling_node"),
    # Phase 8: A2UI -- UI 폼 생성 단락 경로. 노드 등록과 라우팅 맵 키를 같은 플래그로
    # 함께 켠다(노드 미등록 상태에서 라우팅 맵에 키만 있으면 LangGraph 경고가 난다).
    NodeSpec(N.UI_FRAME_GENERATOR.value, "_ui_frame_generator_node", _on("a2ui")),
)

EDGES: tuple[Edge, ...] = (
    Edge(START, N.REFINEMENT_CHECKER.value),
    # G1-a: 직접 응답 노드는 답을 만든 뒤 응답 생성기로 넘어가고, 거기서
    # `_preserve_existing_response` 가 그 답을 그대로 반환한다.
    Edge(N.DIRECT_RESPONSE.value, N.RESP_GENERATOR.value),
    Edge(N.QUERY_REFINEMENT.value, N.CONVERSATION_CTX_PROC.value),
    Edge(N.RESEARCH_CONTINUATION.value, N.CONVERSATION_CTX_PROC.value),
    Edge(N.QUERY_CLS.value, N.SKILL_TOOL_SELECTOR.value),
    # G1-b: 두 재귀 경로는 **스스로 `final_response` 를 만든다.** 예전에는 거기서
    # RESULT_INTEGRATOR 로 합류시켰는데, 그 뒤의 레거시 체인(result_integrator →
    # fact_check → quality_validator)은 search/analysis/generation 결과를 입력으로
    # 요구한다. 재귀 경로는 그 셋을 하나도 채우지 않으므로 체인 전체가 **빈 입력
    # 위에서** 돌았다 -- integrated_results 는 비고, quality_validator 는 빈 상태로
    # 점수를 매겨 REGENERATE 를 낼 수 있었다. 그러면 ROMA 가 이미 낸 답을 두고
    # 레거시 파이프라인이 통째로 헛돈다.
    #
    # 답을 만든 노드는 응답 생성기로 바로 간다 -- task_scheduling_node ·
    # mission_integrator · direct_response 와 같은 모양이고, 거기서
    # `_preserve_existing_response` 가 그 답을 그대로 돌려준다.
    Edge(N.RECURSIVE_ORCHESTRATOR.value, N.RESP_GENERATOR.value, _on("recursive")),
    Edge(N.HYPER_DEEP_ORCHESTRATOR.value, N.RESP_GENERATOR.value, _on("hyper_deep")),
    # 디스패치 노드는 END 로 단락한다 -- 챗 턴은 job 핸들을 낸 뒤 즉시 끝난다(AC2).
    Edge(N.DEEP_ANALYSIS_DISPATCH.value, END, _on("deep_analysis")),
    Edge(N.UI_FRAME_GENERATOR.value, END, _on("a2ui")),
    # Phase 4 (OpenClaw Cron): TASK_SCHEDULING_NODE → 바로 응답 생성
    Edge(N.TASK_SCHEDULING_NODE.value, N.RESP_GENERATOR.value),
    # Mission Runtime: plan -> optional approval -> serial executor -> validators -> response
    Edge(N.MISSION_EXECUTOR.value, N.MISSION_VALIDATOR.value),
    Edge(N.MISSION_VALIDATOR.value, N.MISSION_INTEGRATOR.value),
    Edge(N.MISSION_INTEGRATOR.value, N.RESP_GENERATOR.value),
    Edge(N.HYPOTHESIS_GENERATION.value, N.SEARCH_ORCHESTRATOR.value),
    Edge(N.SEARCH_ORCHESTRATOR.value, N.HYPOTHESIS_EVALUATION.value),
    Edge(N.ANALYSIS_ORCHESTRATOR.value, N.GENERATION_ORCHESTRATOR.value),
    Edge(N.GENERATION_ORCHESTRATOR.value, N.RESULT_INTEGRATOR.value),
    Edge(N.RESULT_INTEGRATOR.value, N.FACT_CHECK.value),
    Edge(N.FACT_CHECK.value, N.QUALITY_VALIDATOR.value),
    Edge(N.SELF_REFLECTION.value, N.RESP_GENERATOR.value),
    Edge(N.RESP_GENERATOR.value, N.RESEARCH_HARNESS.value),
    Edge(N.RESEARCH_HARNESS_REPAIR.value, N.RESEARCH_HARNESS.value),
)

BRANCHES: tuple[Branch, ...] = (
    Branch(
        N.REFINEMENT_CHECKER.value,
        "_should_refine_or_continue",
        (
            Route("refine_query", N.QUERY_REFINEMENT.value),
            Route("continue_research", N.RESEARCH_CONTINUATION.value),
            Route("skip_refinement", N.CONVERSATION_CTX_PROC.value),
        ),
    ),
    Branch(
        N.CONVERSATION_CTX_PROC.value,
        "_should_process_context",
        (
            Route("process_context", N.QUERY_CLS.value),
            Route("skip_context", N.QUERY_CLS.value),
        ),
    ),
    Branch(
        N.SKILL_TOOL_SELECTOR.value,
        "_route_after_skill_tool_selector",
        (
            # spec 2026-10-11 §2: skip·use 는 스킬 실행이 켜졌으면 공통 스킬 실행 노드를 지난다.
            Route(P.SKIP_ORCHESTRATORS.value, N.DIRECT_RESPONSE.value, _off("skill_execution")),
            Route(P.SKIP_ORCHESTRATORS.value, N.SKILL_EXECUTOR.value, _on("skill_execution")),
            Route(P.USE_ORCHESTRATORS.value, N.HYPOTHESIS_GENERATION.value, _off("skill_execution")),
            Route(P.USE_ORCHESTRATORS.value, N.SKILL_EXECUTOR.value, _on("skill_execution")),
            Route("mission", N.MISSION_PLANNER.value),
            Route("recursive", N.RECURSIVE_ORCHESTRATOR.value, _on("recursive")),
            Route("hyper_deep", N.HYPER_DEEP_ORCHESTRATOR.value, _on("hyper_deep")),
            Route("deep_analysis", N.DEEP_ANALYSIS_DISPATCH.value, _on("deep_analysis")),
            # Phase 2: 승인 대기 경로(최우선 -- `_should_use_recursive_agent` 가 먼저 본다)
            Route("needs_approval", N.EXECUTION_APPROVAL.value, _on("execution_approval")),
            # Phase 4: 스케줄 등록 경로
            Route("task_scheduling", N.TASK_SCHEDULING_NODE.value),
            # Phase 8: A2UI -- UI 폼 생성 단락 경로
            Route("ui_frame", N.UI_FRAME_GENERATOR.value, _on("a2ui")),
        ),
    ),
    # 실행 노드 출구: skip 은 직접 응답, 그 밖(use · approved)은 가설 생성.
    Branch(
        N.SKILL_EXECUTOR.value,
        "_route_after_skill_executor",
        (
            Route(P.SKIP_ORCHESTRATORS.value, N.DIRECT_RESPONSE.value),
            Route(P.USE_ORCHESTRATORS.value, N.HYPOTHESIS_GENERATION.value),
        ),
        _on("skill_execution"),
    ),
    Branch(
        N.MISSION_PLANNER.value,
        "_should_continue_after_mission_planner",
        (
            Route("approval_unavailable", N.RESP_GENERATOR.value),
            Route("needs_approval", N.MISSION_APPROVAL.value),
            Route("execute", N.MISSION_EXECUTOR.value),
        ),
    ),
    Branch(
        N.MISSION_APPROVAL.value,
        "_should_continue_after_approval",
        (
            Route("approved", N.MISSION_EXECUTOR.value),
            Route("rejected", N.RESP_GENERATOR.value),
        ),
    ),
    # Phase 2: approved → 오케스트레이터 경로(스킬 실행이 켜졌으면 실행 노드 먼저),
    # rejected → 응답 생성
    Branch(
        N.EXECUTION_APPROVAL.value,
        "_should_continue_after_approval",
        (
            Route("approved", N.HYPOTHESIS_GENERATION.value, _off("skill_execution")),
            Route("approved", N.SKILL_EXECUTOR.value, _on("skill_execution")),
            Route("rejected", N.RESP_GENERATOR.value),
        ),
        _on("execution_approval"),
    ),
    Branch(
        N.HYPOTHESIS_EVALUATION.value,
        "_should_replan",
        (
            Route("replan", N.REPLANNER.value),
            Route("skip_replan", N.ANALYSIS_ORCHESTRATOR.value),
        ),
    ),
    Branch(
        N.REPLANNER.value,
        "_should_continue_research",
        (
            Route("continue_search", N.HYPOTHESIS_GENERATION.value),
            Route("proceed", N.ANALYSIS_ORCHESTRATOR.value),
        ),
    ),
    Branch(
        N.QUALITY_VALIDATOR.value,
        "_should_regenerate",
        (
            Route(P.REGENERATE.value, N.HYPOTHESIS_GENERATION.value),
            Route(P.PROCEED.value, N.SELF_REFLECTION.value),
        ),
    ),
    Branch(
        N.RESEARCH_HARNESS.value,
        "_route_after_research_harness",
        (
            Route("repair", N.RESEARCH_HARNESS_REPAIR.value),
            Route("end", END),
        ),
    ),
)

# 사람 승인 게이트. 체크포인터가 있는 경로에서만 쓰인다(호출자가 정한다) --
# stateless 경로에서는 중단해도 재개할 지점이 없다.
INTERRUPTS: tuple[Interrupt, ...] = (
    Interrupt(N.EXECUTION_APPROVAL.value, _on("execution_approval")),
    Interrupt(N.MISSION_APPROVAL.value, _on("execution_approval")),
)


def _resolve_flags(flags: Mapping[str, bool] | None) -> dict[str, bool]:
    resolved = dict(DEFAULT_FLAGS)
    if flags:
        unknown = set(flags) - set(DEFAULT_FLAGS)
        if unknown:
            raise ValueError(f"알 수 없는 플래그: {sorted(unknown)}")
        resolved.update({key: bool(value) for key, value in flags.items()})
    return resolved


def resolve_wiring(flags: Mapping[str, bool] | None = None) -> Wiring:
    """플래그로 켜진 항목만 골라 닫힌 배선을 만든다. `flags` 에 없는 키는 켜짐."""
    resolved = _resolve_flags(flags)

    def active(requires: Requires) -> bool:
        return all(resolved[key] is expected for key, expected in requires)

    nodes = tuple(spec for spec in NODES if active(spec.requires))
    edges = tuple(edge for edge in EDGES if active(edge.requires))
    branches: list[Branch] = []
    for branch in BRANCHES:
        if not active(branch.requires):
            continue
        routes = tuple(route for route in branch.routes if active(route.requires))
        labels = [route.label for route in routes]
        clashes = sorted({label for label in labels if labels.count(label) > 1})
        if clashes:
            raise WiringError(f"{branch.source}: 라벨 {clashes} 에 켜진 경로가 둘 이상이다")
        branches.append(Branch(branch.source, branch.router, routes))
    interrupts = tuple(item.node for item in INTERRUPTS if active(item.requires))
    wiring = Wiring(nodes, edges, tuple(branches), interrupts)
    _check_closed(wiring)
    return wiring


def _check_closed(wiring: Wiring) -> None:
    names = {spec.name for spec in wiring.nodes}
    known = names | {START, END}
    dangling: list[str] = []
    for edge in wiring.edges:
        dangling += [end for end in (edge.source, edge.target) if end not in known]
    for branch in wiring.branches:
        if branch.source not in names:
            dangling.append(branch.source)
        dangling += [route.target for route in branch.routes if route.target not in known]
    dangling += [node for node in wiring.interrupt_before if node not in names]
    if dangling:
        raise WiringError(f"켜지지 않은 노드를 가리킨다: {sorted(set(dangling))}")


def topology_of(wiring: Wiring) -> GraphTopology:
    """검증기·해시·노드 수 테스트가 읽는 정적 토폴로지. 분기는 모든 경로를 엣지로 펼친다."""
    names = {spec.name for spec in wiring.nodes}
    edges = [(edge.source, edge.target) for edge in wiring.edges]
    for branch in wiring.branches:
        edges.extend((branch.source, route.target) for route in branch.routes)
    return GraphTopology(
        nodes=tuple(sorted(names)),
        edges=tuple(edges),
        loop_bounds={node: bound for node, bound in LOOP_BOUNDS.items() if node in names},
        initial_writes=GRAPH_ENTRY_WRITES,
    )
