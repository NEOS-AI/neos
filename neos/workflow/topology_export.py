"""`graph.py` 의 손으로 쓴 배선을 `GraphTopology` 로 뽑아낸다.

`MultiAgentWorkflow._create_workflow_graph` 의 `workflow.add_node` /
`workflow.add_edge` / `workflow.add_conditional_edges` 호출을 `ast` 로 읽어
Task 3-4 의 `validate_topology` 가 소비할 수 있는 순수 데이터 구조로 옮긴다.
`inspect.getsource` 로 얻은 소스를 파싱할 뿐, `MultiAgentWorkflow` 를
인스턴스화하지도 임의 코드를 실행하지도 않는다 -- 검증 대상은 항상
소스 그 자체다.

**조건부 엣지의 확장.** `validate_topology` 는 "START 에서 어떤 경로로도
도달 가능한가" 를 전방 BFS 로만 본다 -- 라우터 함수(`self._route_after_*`)가
실제로 어느 분기를 고르는지는 모른다. 그래서 `add_conditional_edges` 의 세
번째 인자(라우팅 테이블)에 있는 **모든** 값을 엣지로 펼친다: 한 갈래만
옮기면 나머지 갈래로 가는 실제 배선이 검증기 눈에 안 보이는 채로 남아
"모든 경로에서 안전하다" 는 결론이 거짓으로 통과한다.

**기능 플래그.** `_create_workflow_graph` 는 `settings.RECURSIVE_AGENT_ENABLED`
/ `HYPER_DEEP_AGENT_ENABLED` / `DEEP_ANALYSIS_ENABLED` / `EXECUTION_APPROVAL_ENABLED`
/ `A2UI_ENABLED` 다섯 개 플래그로 노드 등록과 라우팅 테이블 내용을 분기한다.
런타임 `settings` 값을 읽는 대신 `flags` 인자로 각 분기를 결정한다 -- 배포
설정과 무관하게 항상 같은 토폴로지를 검증해야 회귀 가드로서 의미가 있고,
기본값을 전부 켠 상태로 두면 가장 넓은(따라서 위반을 가장 많이 드러내는)
그래프를 얻는다.
"""

import ast
import inspect
import textwrap
from collections.abc import Mapping

from neos.workflow.enums import WorkflowNode, WorkflowPathway
from neos.workflow.topology import END, GRAPH_ENTRY_WRITES, START, GraphTopology

# `GRAPH_ENTRY_WRITES` (그래프 실행 전 `_create_initial_state` 가 이미 채워
# 넣는 키 넷)는 `topology.py` 의 그래프 어휘다 -- 이 모듈 하나의 관심사가
# 아니라 `graph_designer.parse_topology` 도 똑같이 채워야 하는 "그래프 진입
# 계약" 이라서, 정의를 여기 사설(private)로 복제하지 않고 그쪽에서 그대로
# 임포트해 쓴다. 두 곳에 따로 적으면 한쪽만 고쳐져 드리프트할 수 있다.

# `_create_workflow_graph` 안 `if settings.X:` 분기가 참조하는 속성 이름을
# `flags` 딕셔너리 키로 매핑한다. 여기 없는 `settings.*` 속성을 조건식에서
# 만나면 `_eval_flag_test` 가 예외를 던진다 -- 새 플래그가 추가됐는데 이
# 매핑을 갱신하지 않으면 "그럴듯한 기본값을 추측" 하는 대신 추출을 실패시켜
# 드러낸다 (브리프의 스톱 조건: 대상 집합을 추측하지 않는다).
_FLAG_ATTR_TO_KEY: dict[str, str] = {
    "RECURSIVE_AGENT_ENABLED": "recursive",
    "HYPER_DEEP_AGENT_ENABLED": "hyper_deep",
    "DEEP_ANALYSIS_ENABLED": "deep_analysis",
    "EXECUTION_APPROVAL_ENABLED": "execution_approval",
    "A2UI_ENABLED": "a2ui",
}

# 기본값은 전부 켠 상태 -- "가장 넓은 그래프가 가장 많은 위반을 드러낸다" (브리프).
_DEFAULT_FLAGS: dict[str, bool] = dict.fromkeys(_FLAG_ATTR_TO_KEY.values(), True)

# 사이클마다 선언하는 반복 상한. `validate_topology` 의 `unbounded_cycle` 규칙은
# "선언 여부" 만 보고 값 자체는 쓰지 않지만(Task 4), 여기 실제 런타임 상수를
# 그대로 옮겨 적어 이 토폴로지가 시늉이 아니라 진짜 배선을 반영하도록 한다.
# 값의 출처:
_REPLAN_MAX_ATTEMPTS = 2  # neos/workflow/routing/quality_router.py: `replan_count < 2`
_QUALITY_REGENERATE_MAX_ATTEMPTS = (
    2  # config/neos.default.yaml: workflow.max_retries 기본값
)
_HARNESS_REPAIR_MAX_ATTEMPTS = (
    1  # neos/workflow/harness/models.py: max_repair_attempts 기본값
)

# "replan ↔ hypothesis" 서브사이클에 속한 노드들 -- REPLANNER 의
# `replan_count < 2` 조건이 이 노드들의 재진입을 직접 제어한다.
_REPLAN_CYCLE_NODES = (
    WorkflowNode.HYPOTHESIS_GENERATION.value,
    WorkflowNode.SEARCH_ORCHESTRATOR.value,
    WorkflowNode.HYPOTHESIS_EVALUATION.value,
    WorkflowNode.REPLANNER.value,
)
# "quality regenerate" 사이클에 속한 노드들 -- QUALITY_VALIDATOR 의
# `retry_count >= MAX_RETRIES` 조건이 재진입을 제어한다. HYPOTHESIS_GENERATION
# 이후 replan 사이클과 하나의 강결합 성분으로 합쳐지지만(둘 다 REGENERATE 가
# HYPOTHESIS_GENERATION 으로 되돌아가므로), 각 노드를 실제로 되돌리는
# 상한값을 그대로 남겨 어떤 카운터가 그 노드를 막는지 알 수 있게 한다.
_QUALITY_REGENERATE_CYCLE_NODES = (
    WorkflowNode.ANALYSIS_ORCHESTRATOR.value,
    WorkflowNode.GENERATION_ORCHESTRATOR.value,
    WorkflowNode.RESULT_INTEGRATOR.value,
    WorkflowNode.FACT_CHECK.value,
    WorkflowNode.QUALITY_VALIDATOR.value,
)
# research_harness ↔ research_harness_repair 2-노드 사이클.
_HARNESS_REPAIR_CYCLE_NODES = (
    WorkflowNode.RESEARCH_HARNESS.value,
    WorkflowNode.RESEARCH_HARNESS_REPAIR.value,
)

_LOOP_BOUND_BY_NODE: dict[str, int] = {
    **dict.fromkeys(_REPLAN_CYCLE_NODES, _REPLAN_MAX_ATTEMPTS),
    **dict.fromkeys(_QUALITY_REGENERATE_CYCLE_NODES, _QUALITY_REGENERATE_MAX_ATTEMPTS),
    **dict.fromkeys(_HARNESS_REPAIR_CYCLE_NODES, _HARNESS_REPAIR_MAX_ATTEMPTS),
}

# `WorkflowNode.<MEMBER>.value` / `WorkflowPathway.<MEMBER>.value` 형태의 AST
# 표현식을 실제 열거형 클래스로 해석하기 위한 이름 조회 테이블.
_ENUM_CLASSES_BY_NAME: dict[str, type] = {
    "WorkflowNode": WorkflowNode,
    "WorkflowPathway": WorkflowPathway,
}


class _StaticExtractionError(RuntimeError):
    """`graph.py` 의 배선 표현식을 정적으로 해석할 수 없을 때."""


_WIRING_METHODS = frozenset({"add_node", "add_edge", "add_conditional_edges"})


def _contains_wiring_call(statements: list[ast.stmt]) -> bool:
    """`statements` 안 어딘가에 `workflow.add_*` 호출이 있으면 True.

    조건을 못 푸는 `if` 블록을 조용히 건너뛰어도 되는지 판단하는 데만 쓴다 --
    재귀적으로 모든 하위 `ast.Call` 을 훑어 `workflow.<add_*>(...)` 형태가
    하나라도 있는지만 본다(값을 해석하려 하지 않는다).
    """
    for node in ast.walk(ast.Module(body=statements, type_ignores=[])):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in _WIRING_METHODS
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "workflow"
        ):
            return True
    return False


def static_topology(*, flags: Mapping[str, bool] | None = None) -> GraphTopology:
    """`MultiAgentWorkflow._create_workflow_graph` 의 배선을 `GraphTopology` 로 뽑는다.

    `flags` 에 없는 키는 기본값(전부 켠 상태)을 쓴다. 알 수 없는 키가 오면
    바로 실패한다 -- 오타가 조용히 무시된 채 엉뚱한 토폴로지를 검증하는 것을
    막는다.
    """

    resolved_flags = dict(_DEFAULT_FLAGS)
    if flags:
        unknown_keys = set(flags) - set(_DEFAULT_FLAGS)
        if unknown_keys:
            raise ValueError(f"알 수 없는 플래그: {sorted(unknown_keys)}")
        resolved_flags.update(flags)

    # 함수 본문에서만 임포트한다 -- 모듈 스코프에서 `graph_module`을 들여오면
    # `graph.py`가 이 모듈을 임포트하는 진입 방향(정상 경로, `sys.modules`
    # 부분 초기화로 안전하다)과 반대로, 이 모듈이 먼저 임포트되는 진입
    # 방향(예: 테스트가 `topology_export`/`execution_graph`를 직접 임포트)
    # 에서 `graph.py -> execution_graph -> topology_export`로 되돌아오며
    # `topology_export`가 아직 이 함수를 정의하기 전이라 순환 임포트가
    # 실패한다. 여기서만 쓰므로 지역 임포트로 양방향을 다 안전하게 만든다.
    from neos.workflow import graph as graph_module

    source = textwrap.dedent(
        inspect.getsource(graph_module.MultiAgentWorkflow._create_workflow_graph)
    )
    func_def = ast.parse(source).body[0]
    if not isinstance(func_def, ast.AsyncFunctionDef):
        raise _StaticExtractionError(
            "_create_workflow_graph 가 async def 가 아니다 -- 소스 구조가 바뀌었다"
        )

    extractor = _Extractor(resolved_flags)
    extractor.walk(func_def.body)

    loop_bounds = {
        node: bound
        for node, bound in _LOOP_BOUND_BY_NODE.items()
        if node in extractor.nodes
    }

    return GraphTopology(
        nodes=tuple(sorted(extractor.nodes)),
        edges=tuple(extractor.edges),
        loop_bounds=loop_bounds,
        initial_writes=GRAPH_ENTRY_WRITES,
    )


class _Extractor:
    """`_create_workflow_graph` 본문을 순서대로 훑는 작은 인터프리터.

    지원하는 문장은 넷뿐이다: `if`(settings 플래그 조건), 딕셔너리 리터럴을
    변수에 대입, 그 변수에 서브스크립트로 항목 추가, `workflow.<method>(...)`
    호출. 이 넷이면 `_create_workflow_graph` 전체를 커버한다 -- 그 밖의
    문장(로그 호출, docstring, 지역 함수 정의 등)은 배선과 무관하므로 무시한다.
    """

    def __init__(self, flags: dict[str, bool]) -> None:
        self._flags = flags
        self.nodes: set[str] = set()
        self.edges: list[tuple[str, str]] = []
        # 라우팅 테이블로 쓰이는 지역 변수(`_routing_map`, `_else_routing`)의
        # 현재 값. 키는 라우터 함수가 반환하는 분기 이름을 그대로 담을 필요가
        # 없다 -- `_resolve_expr` 로 해석 가능한 어떤 표현식이든 딕셔너리 키로
        # 넣어 두면 충분하다(모든 값을 엣지로 펼치는 데만 쓰인다).
        self._dict_vars: dict[str, dict[str, str]] = {}

    def walk(self, statements: list[ast.stmt]) -> None:
        for statement in statements:
            self._visit(statement)

    def _visit(self, statement: ast.stmt) -> None:
        if isinstance(statement, ast.If):
            self._visit_if(statement)
            return
        if isinstance(statement, ast.Assign):
            self._visit_assign(statement)
            return
        if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
            self._visit_call(statement.value)
            return
        # docstring, `return`, 지역 변수 재대입(`workflow = StateGraph(...)`
        # 등)처럼 그래프 배선과 무관한 문장은 조용히 건너뛴다.

    def _visit_if(self, statement: ast.If) -> None:
        """`if` 문을 처리한다. 조건이 `flags` 로 못 푸는 것이면(예:
        `use_checkpointer` 같은 함수 인자) 두 갈래 중 배선 호출이 없는 쪽만
        건너뛴다 -- checkpointer 유무를 가르는 `if use_checkpointer:` 블록이
        정확히 이 경우다(양쪽 다 `workflow.compile(...)` 만 하고 add_node/edge
        가 없다). 어느 한쪽이라도 배선 호출을 담고 있으면 추측 대신 그대로
        실패시킨다 -- 브리프의 스톱 조건: 대상을 추측해 조용히 넘기지 않는다.
        """
        try:
            branch = (
                statement.body if self._eval_test(statement.test) else statement.orelse
            )
        except _StaticExtractionError:
            if _contains_wiring_call(statement.body) or _contains_wiring_call(
                statement.orelse
            ):
                raise
            return
        self.walk(branch)

    # -- 조건 평가 ------------------------------------------------------------

    def _eval_test(self, test: ast.expr) -> bool:
        if isinstance(test, ast.BoolOp):
            values = [self._eval_test(value) for value in test.values]
            if isinstance(test.op, ast.Or):
                return any(values)
            if isinstance(test.op, ast.And):
                return all(values)
            raise _StaticExtractionError(
                f"지원하지 않는 불리언 연산자: {ast.dump(test)}"
            )
        if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
            return not self._eval_test(test.operand)
        if (
            isinstance(test, ast.Attribute)
            and isinstance(test.value, ast.Name)
            and test.value.id == "settings"
        ):
            flag_key = _FLAG_ATTR_TO_KEY.get(test.attr)
            if flag_key is None:
                raise _StaticExtractionError(
                    f"알 수 없는 설정 플래그 settings.{test.attr} -- "
                    "_FLAG_ATTR_TO_KEY 매핑을 갱신해야 한다"
                )
            return self._flags[flag_key]
        raise _StaticExtractionError(
            f"조건식을 정적으로 평가할 수 없다: {ast.dump(test)}"
        )

    # -- 대입 -------------------------------------------------------------

    def _visit_assign(self, assign: ast.Assign) -> None:
        if len(assign.targets) != 1:
            return
        target = assign.targets[0]

        if isinstance(target, ast.Name) and isinstance(assign.value, ast.Dict):
            mapping: dict[str, str] = {}
            for key_node, value_node in zip(
                assign.value.keys, assign.value.values, strict=True
            ):
                if key_node is None:  # `**other` 언패킹 -- 이 파일에는 없다.
                    raise _StaticExtractionError(
                        f"딕셔너리 언패킹은 지원하지 않는다: {ast.dump(assign.value)}"
                    )
                mapping[self._resolve_expr(key_node)] = self._resolve_expr(value_node)
            self._dict_vars[target.id] = mapping
            return

        if isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name):
            var_name = target.value.id
            if var_name not in self._dict_vars:
                # 추적하지 않는 변수 -- 배선과 무관한 걸로 간주하고 건너뛴다.
                return
            key = self._resolve_expr(target.slice)
            self._dict_vars[var_name][key] = self._resolve_expr(assign.value)

    # -- 호출 -------------------------------------------------------------

    def _visit_call(self, call: ast.Call) -> None:
        if not (
            isinstance(call.func, ast.Attribute)
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id == "workflow"
        ):
            return

        method = call.func.attr
        if method == "add_node":
            self.nodes.add(self._resolve_expr(call.args[0]))
        elif method == "add_edge":
            source = self._resolve_expr(call.args[0])
            target = self._resolve_expr(call.args[1])
            self.edges.append((source, target))
        elif method == "add_conditional_edges":
            source = self._resolve_expr(call.args[0])
            for target in self._resolve_targets(call.args[2]):
                self.edges.append((source, target))
        # `compile`/`add_edge` 이외의 메서드(`workflow.compile` 은 이 함수
        # 안에서 안 쓰인다)는 배선에 관여하지 않으므로 무시한다.

    def _resolve_targets(self, node: ast.expr) -> list[str]:
        if isinstance(node, ast.Dict):
            return [self._resolve_expr(value) for value in node.values]
        if isinstance(node, ast.Name):
            tracked = self._dict_vars.get(node.id)
            if tracked is None:
                raise _StaticExtractionError(
                    f"add_conditional_edges 의 대상 변수 '{node.id}' 를 추적하지 못했다 "
                    "-- 런타임에 계산되는 라우팅 테이블일 가능성이 있다"
                )
            return list(tracked.values())
        raise _StaticExtractionError(
            f"add_conditional_edges 의 대상 표현식을 정적으로 해석할 수 없다: {ast.dump(node)}"
        )

    # -- 표현식 → 문자열 ----------------------------------------------------

    def _resolve_expr(self, node: ast.expr) -> str:
        # START/END: langgraph.graph 에서 그대로 임포트한 센티널.
        if isinstance(node, ast.Name):
            if node.id == "START":
                return START
            if node.id == "END":
                return END
            raise _StaticExtractionError(f"알 수 없는 이름 참조: {node.id}")

        # 문자열 리터럴 (예: "mission", "task_scheduling").
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value

        # `WorkflowNode.X.value` / `WorkflowPathway.X.value`.
        if (
            isinstance(node, ast.Attribute)
            and node.attr == "value"
            and isinstance(node.value, ast.Attribute)
            and isinstance(node.value.value, ast.Name)
            and node.value.value.id in _ENUM_CLASSES_BY_NAME
        ):
            enum_cls = _ENUM_CLASSES_BY_NAME[node.value.value.id]
            member = getattr(enum_cls, node.value.attr, None)
            if member is None:
                raise _StaticExtractionError(
                    f"{node.value.value.id}.{node.value.attr} 는 존재하지 않는 멤버다"
                )
            return member.value

        raise _StaticExtractionError(
            f"노드/엣지 대상 표현식을 정적으로 해석할 수 없다: {ast.dump(node)}"
        )
