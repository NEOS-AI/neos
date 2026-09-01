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

# 위임 체인을 따라 함수 소스를 몇 개까지 훑을지의 상한 (깊이 0 = 노드 핸들러
# 자신, 1 = 첫 위임 대상, ... ). 1단계(노드→오케스트레이터)면 이 저장소의
# 실제 위임 깊이는 대부분 커버된다. 그 이상은 서로 다른 클래스 그래프로 계속
# 번져 나가 정적 추적의 신뢰도가 급격히 떨어지므로, 여유를 두는 선에서 3으로
# 고정한다 (매직넘버로 흩어놓지 않기 위한 이름 있는 상수). `_state_keys_read`
# 는 `depth >= MAX_DELEGATE_DEPTH` 에서 멈추므로 정확히 함수 3개(깊이 0,1,2)
# 까지만 소스를 훑는다 -- 이름이 약속하는 숫자와 실제 스캔 횟수를 맞춘다.
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
    # `writes` 판의 `hand_curated` -- True 면 `state_keys_written` 이 이 계약이
    # 선언한 writes 전부를 노드 자신의 소스에서 확인하지 못했다는 뜻이다.
    # `_guaranteed_keys`(topology.py) 는 정확히 이 `writes` 필드로
    # `unsatisfied_requires` 규칙 전체를 계산한다 -- writes 를 과잉 선언하면
    # (실제로는 안 쓰는 키를 썼다고 주장하면) 검증기가 깨진 토폴로지를 승인해
    # 버리는데, `state_keys_written` 은 위임 체인을 따라가지 않으므로(이번
    # 라운드는 인라인 구현만 커버) `self.<attr>.<method>(state)` 로 위임하는
    # 노드는 예외 없이 이 플래그가 True 다. 붙일 때마다 왜 검증되지 않는지
    # 데코레이터 옆 주석에 남긴다.
    writes_hand_curated: bool = False

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
    writes_hand_curated: bool = False,
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
            writes_hand_curated=writes_hand_curated,
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


def _returned_delegate_calls(tree: ast.AST) -> list[tuple[str, str]]:
    """`return (await)? self.<attr>.<method>(state, ...)` 만 (attr, method) 로 뽑는다.

    `_delegate_calls` 보다 **훨씬 좁다**, 그리고 그것이 요점이다. `reads` 는
    위임 호출이 어디에 있든 그 대상이 읽는 키를 이 노드도 읽으므로 전부
    따라가면 된다. `writes` 는 반대다 -- 위임 대상이 쓰는 키가 이 노드의
    `writes` 가 되려면 **그 반환값이 곧 이 노드의 반환값**이어야 한다.
    중간에서 받아 다른 dict 에 담으면(`result = await self.x.y(state)` 뒤
    `return {"a": result}`) 대상의 키는 상태로 나가지 않는다.

    방향이 다른 이유는 §14.4 가 적은 대로다: `reads` 는 선언이 실제보다
    적으면 위험하고(`actual - declared`), `writes` 는 선언이 실제보다 많으면
    위험하다(`declared - actual`). 추출기가 실제로 쓰지 않는 키를 "확인" 해
    주면 `_guaranteed_keys` 가 그것을 믿고 **깨진 토폴로지를 조용히
    승인한다.** 그래서 이 추출기는 확신할 수 없으면 아무 말도 하지 않는다.
    """
    calls: list[tuple[str, str]] = []
    for item in ast.walk(tree):
        if not isinstance(item, ast.Return) or item.value is None:
            continue
        value = item.value
        if isinstance(value, ast.Await):
            value = value.value
        if (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Attribute)
            and isinstance(value.func.value, ast.Attribute)
            and isinstance(value.func.value.value, ast.Name)
            and value.func.value.value.id == "self"
            and value.args
            and isinstance(value.args[0], ast.Name)
            and value.args[0].id == "state"
        ):
            calls.append((value.func.value.attr, value.func.attr))
    return calls


def _mutated_names(tree: ast.AST) -> set[str]:
    """키가 **사라질 수 있는** 지역 이름. 이 이름들은 추적하지 않는다.

    `del result["x"]` 와 `result.pop("x")` 가 그 둘이다. 추가만 하는 연산
    (`result["x"] = ...`)은 추출을 과소하게 만들 뿐이라 안전하지만, 제거는
    추출을 **과대**하게 만들어 검증기가 없는 write 를 믿게 한다.
    """
    names: set[str] = set()
    for item in ast.walk(tree):
        if isinstance(item, ast.Delete):
            for target in item.targets:
                if isinstance(target, ast.Subscript) and isinstance(
                    target.value, ast.Name
                ):
                    names.add(target.value.id)
        if (
            isinstance(item, ast.Call)
            and isinstance(item.func, ast.Attribute)
            and item.func.attr == "pop"
            and isinstance(item.func.value, ast.Name)
        ):
            names.add(item.func.value.id)
    return names


def _returned_local_dict_keys(tree: ast.AST) -> set[str]:
    """`result = {...}` 뒤 `return result` 형태에서 최상위 키를 뽑는다.

    이 저장소에서 노드가 상태를 쓰는 둘째 흔한 모양이고, `return {...}` 만
    보던 추출기는 이것을 통째로 놓쳤다.

    이름이 **정확히 한 번** 대입된 경우만 본다. 두 번 이상이면 어느 대입이
    반환에 도달하는지가 제어 흐름의 문제가 되고, 정적으로 틀리면 과대 추출
    쪽으로 틀린다 -- `writes` 에서 그 방향은 검증기를 깨뜨린다.
    """
    single_assign: dict[str, int] = {}
    literals: dict[str, set[str]] = {}
    for item in ast.walk(tree):
        if (
            isinstance(item, ast.Assign)
            and len(item.targets) == 1
            and isinstance(item.targets[0], ast.Name)
        ):
            name = item.targets[0].id
            single_assign[name] = single_assign.get(name, 0) + 1
            if isinstance(item.value, ast.Dict):
                literals[name] = {
                    key.value
                    for key in item.value.keys
                    if isinstance(key, ast.Constant)
                    and isinstance(key.value, str)
                }

    subscript_adds: dict[str, set[str]] = {}
    for item in ast.walk(tree):
        if (
            isinstance(item, ast.Subscript)
            and isinstance(item.value, ast.Name)
            and isinstance(item.ctx, ast.Store)
            and isinstance(item.slice, ast.Constant)
            and isinstance(item.slice.value, str)
        ):
            subscript_adds.setdefault(item.value.id, set()).add(
                item.slice.value
            )

    unsafe = _mutated_names(tree)
    keys: set[str] = set()
    for item in ast.walk(tree):
        if not (isinstance(item, ast.Return) and isinstance(item.value, ast.Name)):
            continue
        name = item.value.id
        if name in unsafe or single_assign.get(name) != 1 or name not in literals:
            continue
        keys |= literals[name] | subscript_adds.get(name, set())
    return keys


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
    if id(fn) in visited or depth >= MAX_DELEGATE_DEPTH:
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


def _literal_state_keys_written(tree: ast.AST) -> set[str]:
    """AST 트리에서 상태에 실제로 쓰이는 것으로 확인 가능한 리터럴 키만 뽑는다.

    두 형태만 인식한다: `state["x"] = ...` (Subscript 의 Store 컨텍스트) 와,
    함수가 반환하는 dict 리터럴의 최상위 키(`return {"x": ..., "y": ...}`).
    `**other` 로 언패킹해 섞여 들어오는 키, 지역 변수에 먼저 담았다가
    이름으로 반환하는 키(`result = {...}; return result`), 위임 호출이
    돌려주는 dict 를 그대로 반환하는 경우(`return await self.x.y(state)`)는
    잡지 않는다 -- `reads` 추출기(`state_keys_read`)와 달리 위임 체인도
    따라가지 않는다. 이 저장소의 노드 30개 중 16개가 한 줄 위임이라, 그런
    노드는 이 함수가 `writes` 를 사실상 전혀 못 본다 -- 그래서
    `NodeContract.writes_hand_curated` 가 존재한다.
    """
    keys: set[str] = set()
    for item in ast.walk(tree):
        if (
            isinstance(item, ast.Subscript)
            and isinstance(item.value, ast.Name)
            and item.value.id == "state"
            and isinstance(item.ctx, ast.Store)
            and isinstance(item.slice, ast.Constant)
            and isinstance(item.slice.value, str)
        ):
            keys.add(item.slice.value)
        if isinstance(item, ast.Return) and isinstance(item.value, ast.Dict):
            for key_node in item.value.keys:
                if isinstance(key_node, ast.Constant) and isinstance(
                    key_node.value, str
                ):
                    keys.add(key_node.value)
    return keys


def _state_keys_written(
    fn: Callable, owner: type | None, depth: int, visited: set[int]
) -> set[str]:
    if id(fn) in visited or depth >= MAX_DELEGATE_DEPTH:
        return set()
    visited.add(id(fn))

    try:
        source = textwrap.dedent(inspect.getsource(fn))
    except (OSError, TypeError):
        return set()
    tree = ast.parse(source)
    keys = _literal_state_keys_written(tree) | _returned_local_dict_keys(tree)

    if owner is None:
        owner = _owning_class(fn)
    if owner is None:
        return keys

    attr_class_names = _attr_class_names(owner)
    for attr, method_name in _returned_delegate_calls(tree):
        class_name = attr_class_names.get(attr)
        if class_name is None:
            continue
        target_cls = _resolve_class(owner, class_name)
        if target_cls is None:
            continue
        target_fn = inspect.getattr_static(target_cls, method_name, None)
        if not callable(target_fn):
            continue
        keys |= _state_keys_written(target_fn, target_cls, depth + 1, visited)
    return keys


def state_keys_written(fn: Callable) -> set[str]:
    """소스에서 상태에 실제로 쓰이는 것으로 정적으로 확인 가능한 리터럴 키를 뽑는다.

    `state_keys_read` 와 짝을 이루지만 **여전히 더 보수적이다.** 셋을 본다:
    `return {...}` 최상위 dict 리터럴, `state["x"] = ...` 대입, 그리고
    `result = {...}; return result` 형태의 지역 리터럴. 위임 체인은
    따라가되 **반환 위치의 위임만** 따라간다(`_returned_delegate_calls`) --
    `reads` 가 모든 위임 호출을 따라가는 것과 다르다.

    비대칭의 이유는 두 필드가 계산에 쓰이는 방향이 정반대이기 때문이다:
    `reads` 는 "선언이 실제보다 적으면 위험"(`actual - declared`) 이지만,
    `writes` 는 "선언이 실제보다 많으면 위험"(`declared - actual`) 이다 --
    `_guaranteed_keys`(topology.py) 가 이 `writes` 를 그대로 믿고
    `unsatisfied_requires` 를 계산하므로, 실제로는 안 쓰는 키를 썼다고
    확인해 주면 검증기가 **깨진 토폴로지를 조용히 승인한다.** 그래서
    확신할 수 없는 모양에서는 아무 말도 하지 않는다.

    여전히 확인하지 못하는 declared write 는 `writes_hand_curated=True` 로
    명시해야 한다 -- §14.4 가 이 함수를 "다음 개선점" 으로 적은 이유이고,
    이 확장이 그 격차를 좁힌 만큼만 좁힌 것이지 없앤 것은 아니다.
    """
    return _state_keys_written(fn, owner=None, depth=0, visited=set())
