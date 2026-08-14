"""노드가 `AgentState` 의 무엇을 읽고·쓰고·요구하는지 데이터로 선언한다.

이 저장소의 노드 간 계약은 `graph.py` 의 배선 순서에만 존재했다 -- 코드 어디에도
적혀 있지 않았다. 그래서 순서가 틀려도 예외가 나지 않고 `state.get()` 이 기본값을
돌려줘 노드가 빈 산출물을 낸다. 그 암묵적 약속을 여기로 끌어낸다.
"""

import ast
import inspect
import textwrap
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from neos.workflow.enums import WorkflowNode


@dataclass(frozen=True, slots=True)
class NodeContract:
    node: str
    reads: frozenset[str]
    writes: frozenset[str]
    requires: frozenset[str]
    handler: Callable

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
):
    """노드 메서드에 계약을 붙이고 전역 레지스트리에 등록한다."""

    def decorate(fn: Callable) -> Callable:
        contract = NodeContract(
            node=node.value,
            reads=frozenset(reads),
            writes=frozenset(writes),
            requires=frozenset(requires),
            handler=fn,
        )
        if contract.node in NODE_CONTRACTS:
            raise ValueError(f"{contract.node}: 계약이 두 번 선언됐다")
        NODE_CONTRACTS[contract.node] = contract
        fn.__node_contract__ = contract
        return fn

    return decorate


def state_keys_read(fn: Callable) -> set[str]:
    """소스에서 `state.get("x")` 와 `state["x"]` 의 리터럴 키를 뽑는다.

    변수를 통한 접근은 잡지 못한다 -- 그런 접근이 있으면 계약이 불완전해지므로,
    노드는 리터럴 키로 읽는 것을 유지해야 한다.
    """
    source = textwrap.dedent(inspect.getsource(fn))
    tree = ast.parse(source)
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
