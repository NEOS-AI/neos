"""노드가 `AgentState` 의 무엇을 읽고·쓰고·요구하는지 데이터로 선언한다.

이 저장소의 노드 간 계약은 `graph.py` 의 배선 순서에만 존재했다 -- 코드 어디에도
적혀 있지 않았다. 그래서 순서가 틀려도 예외가 나지 않고 `state.get()` 이 기본값을
돌려줘 노드가 빈 산출물을 낸다. 그 암묵적 약속을 여기로 끌어낸다.

`graph.py` 의 `add_node` 대상 30개 중 16개는 한 줄 위임이다
(`return await self.search_orchestrator.orchestrate(state)`). 위임을 따라가지
않으면 `state_keys_read` 는 위임 노드에서 `set()` 을 돌려주고, 드리프트 가드
`undeclared = actual - reads` 는 `reads` 가 무엇이든 항상 통과한다 -- 계약이
선언은 됐지만 검증되지 않는 구멍이다 (Task 1 리뷰가 변조 테스트로 증명함).
그래서 `state_keys_read` 는 `self.<attr>.<method>(state, ...)` 형태의 위임 호출을
정적으로 따라간다. 재귀로도 전부 닿지는 못한다 -- 지역 변수로 감싼 호출
(`strategy.execute(state, ...)`), 이름을 바꿔 넘기는 호출(`self.x.y(repaired_state)`),
`self.<attr>` 이 아닌 일반 함수 호출(`build_harness_contract(state)`)은 정적으로
추적하지 않는다. 그래서 `NodeContract.hand_curated` 플래그로, 추출기가 닿지 못해
검증되지 않는 계약을 명시적으로 표시한다.
"""

import ast
import importlib
import inspect
import textwrap
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from neos.workflow.enums import WorkflowNode

# 위임 체인을 몇 단계까지 따라갈지의 상한. 1단계(노드→오케스트레이터)면 이
# 저장소의 실제 위임 깊이는 대부분 커버된다. 그 이상은 서로 다른 클래스
# 그래프로 계속 번져 나가 정적 추적의 신뢰도가 급격히 떨어지므로, 여유를 두는
# 선에서 3으로 고정한다 (매직넘버로 흩어놓지 않기 위한 이름 있는 상수).
MAX_DELEGATE_DEPTH = 3


@dataclass(frozen=True, slots=True)
class NodeContract:
    node: str
    reads: frozenset[str]
    writes: frozenset[str]
    requires: frozenset[str]
    handler: Callable
    # True 면 추출기가 위임 체인을 따라가도 이 계약의 reads 를 검증할 근거를
    # 소스에서 찾지 못했다는 뜻이다 -- 즉 드리프트 가드가 이 노드에서는
    # 공허하다. 사람이 위임 대상 소스를 직접 읽고 채웠다는 표시이며, 붙일 때
    # 마다 무엇을 보고 채웠는지 데코레이터 옆 주석에 남긴다.
    hand_curated: bool = False

    def __post_init__(self) -> None:
        if not self.requires <= self.reads:
            raise ValueError(f"{self.node}: requires 는 reads 의 부분집합이어야 한다")


NODE_CONTRACTS: dict[str, NodeContract] = {}


def node_contract(
    *,
    node: WorkflowNode,
    reads: Iterable[str] = (),
    writes: Iterable[str] = (),
    requires: Iterable[str] = (),
    hand_curated: bool = False,
):
    """노드 메서드에 계약을 붙이고 전역 레지스트리에 등록한다."""

    def decorate(fn: Callable) -> Callable:
        contract = NodeContract(
            node=node.value,
            reads=frozenset(reads),
            writes=frozenset(writes),
            requires=frozenset(requires),
            handler=fn,
            hand_curated=hand_curated,
        )
        if contract.node in NODE_CONTRACTS:
            raise ValueError(f"{contract.node}: 계약이 두 번 선언됐다")
        NODE_CONTRACTS[contract.node] = contract
        fn.__node_contract__ = contract
        return fn

    return decorate


def _literal_state_keys(tree: ast.AST) -> set[str]:
    """AST 트리에서 `state.get("x")` 와 `state["x"]` 의 리터럴 키만 뽑는다."""
    keys: set[str] = set()
    for item in ast.walk(tree):
        if (
            isinstance(item, ast.Call)
            and isinstance(item.func, ast.Attribute)
            and item.func.attr == "get"
            and isinstance(item.func.value, ast.Name)
            and item.func.value.id == "state"
            and item.args
            and isinstance(item.args[0], ast.Constant)
            and isinstance(item.args[0].value, str)
        ):
            keys.add(item.args[0].value)
        if (
            isinstance(item, ast.Subscript)
            and isinstance(item.value, ast.Name)
            and item.value.id == "state"
            and isinstance(item.slice, ast.Constant)
            and isinstance(item.slice.value, str)
        ):
            keys.add(item.slice.value)
    return keys


def _delegate_calls(tree: ast.AST) -> list[tuple[str, str]]:
    """`self.<attr>.<method>(state, ...)` 형태의 위임 호출을 (attr, method) 로 뽑는다.

    첫 인자가 리터럴 이름 `state` 인 경우만 위임으로 간주한다. `repaired_state`
    처럼 다른 이름으로 감싸 넘기거나, `self.<method>(state)` 처럼 자기 자신의
    다른 메서드를 부르는 형태(같은 인스턴스 안의 헬퍼)는 잡지 않는다 -- 잡으면
    이미 통과 중인 파일럿 계약(search_orchestrator)의 리터럴 read 범위를 벗어나
    기존 테스트가 깨진다.
    """
    calls: list[tuple[str, str]] = []
    for item in ast.walk(tree):
        if (
            isinstance(item, ast.Call)
            and isinstance(item.func, ast.Attribute)
            and isinstance(item.func.value, ast.Attribute)
            and isinstance(item.func.value.value, ast.Name)
            and item.func.value.value.id == "self"
            and item.args
            and isinstance(item.args[0], ast.Name)
            and item.args[0].id == "state"
        ):
            calls.append((item.func.value.attr, item.func.attr))
    return calls


def _owning_class(fn: Callable) -> type | None:
    """`fn` 을 정의한 클래스를 `__qualname__` 과 정의 모듈에서 찾는다.

    한 단계 중첩(`Class.method`)만 지원한다 -- 이 저장소의 노드 메서드와 위임
    대상 클래스는 전부 모듈 최상위 클래스라 충분하다.
    """
    qualname = getattr(fn, "__qualname__", "")
    parts = qualname.split(".")
    if len(parts) < 2:
        return None
    module = inspect.getmodule(fn)
    if module is None:
        return None
    candidate = getattr(module, parts[0], None)
    return candidate if isinstance(candidate, type) else None


def _attr_class_names(cls: type) -> dict[str, str]:
    """`cls.__init__` 소스에서 `self.<attr> = <ClassName>(...)` 대입을 뽑는다.

    정적 추정이라 팩토리 함수 호출, 조건부로 서로 다른 클래스를 대입하는 경우
    (예: Ray on/off 분기) 등은 마지막으로 매칭된 대입이 이긴다 -- 최선의
    근사치이며, 못 찾으면 그 위임 호출은 그냥 추적을 멈춘다.
    """
    try:
        init_source = textwrap.dedent(inspect.getsource(cls.__init__))
    except (OSError, TypeError):
        return {}
    tree = ast.parse(init_source)
    mapping: dict[str, str] = {}
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Attribute)
            and isinstance(node.targets[0].value, ast.Name)
            and node.targets[0].value.id == "self"
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
        ):
            mapping[node.targets[0].attr] = node.value.func.id
    return mapping


def _resolve_class(cls: type, class_name: str) -> type | None:
    """`class_name` 을 `cls` 가 보는 이름공간에서 클래스 객체로 해석한다.

    먼저 `cls` 정의 모듈의 최상위 이름공간을 본다 (`graph.py` 상단의 일반
    import 로 들어온 대부분의 경우). 거기 없으면 `cls.__init__` 안의 지연
    import(`from .mission.executor import MissionExecutor` 같은, 순환 임포트를
    피하려는 이 저장소의 관례) 를 파싱해 상대 경로를 그대로 `importlib` 에
    넘겨 해석한다.
    """
    module = inspect.getmodule(cls)
    if module is not None:
        candidate = getattr(module, class_name, None)
        if isinstance(candidate, type):
            return candidate

    try:
        init_source = textwrap.dedent(inspect.getsource(cls.__init__))
    except (OSError, TypeError):
        return None
    tree = ast.parse(init_source)
    package = getattr(module, "__package__", None)
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        for alias in node.names:
            if (alias.asname or alias.name) != class_name:
                continue
            relative_name = ("." * node.level) + (node.module or "")
            try:
                imported = importlib.import_module(relative_name, package=package)
            except ImportError:
                return None
            candidate = getattr(imported, alias.name, None)
            return candidate if isinstance(candidate, type) else None
    return None


def _state_keys_read(
    fn: Callable, owner: type | None, depth: int, visited: set[int]
) -> set[str]:
    if id(fn) in visited or depth > MAX_DELEGATE_DEPTH:
        return set()
    visited.add(id(fn))

    try:
        source = textwrap.dedent(inspect.getsource(fn))
    except (OSError, TypeError):
        return set()
    tree = ast.parse(source)
    keys = _literal_state_keys(tree)

    if owner is None:
        owner = _owning_class(fn)
    if owner is None:
        return keys

    attr_class_names = _attr_class_names(owner)
    for attr, method_name in _delegate_calls(tree):
        class_name = attr_class_names.get(attr)
        if class_name is None:
            continue
        target_cls = _resolve_class(owner, class_name)
        if target_cls is None:
            continue
        target_fn = inspect.getattr_static(target_cls, method_name, None)
        if not callable(target_fn):
            continue
        keys |= _state_keys_read(target_fn, target_cls, depth + 1, visited)
    return keys


def state_keys_read(fn: Callable) -> set[str]:
    """소스에서 `state.get("x")` 와 `state["x"]` 의 리터럴 키를 뽑는다.

    `self.<attr>.<method>(state)` 형태의 위임 호출을 만나면 위임 대상의
    소스로 내려가 같은 추출을 반복한다 (깊이 상한 `MAX_DELEGATE_DEPTH`,
    방문한 함수는 재방문하지 않는다). 변수를 통한 접근, 위임 대상 자체를
    지역 변수에 담아 호출하는 형태, `self.<attr>` 이 아닌 일반 함수 호출은
    잡지 못한다 -- 그런 노드는 `hand_curated=True` 로 명시해야 한다.
    """
    return _state_keys_read(fn, owner=None, depth=0, visited=set())
