# 서브에이전트 그래프 엔지니어링 루프 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 서브에이전트가 질의별로 워크플로우 그래프의 배선을 제안하고, 검증기가 통과시킨 토폴로지로만 실행한다.

**Architecture:** 노드 25개의 암묵적 `AgentState` 계약을 데이터로 선언하고(C1), 그 계약에 비춰 토폴로지를 검사하는 검증기를 만들고(C2), 그 뒤에야 설계 서브에이전트를 붙인다(C3). 실행은 ephemeral이며 모든 폴백이 원장 이벤트를 남긴다(C4). C1·C2는 서브에이전트 없이도 손으로 쓴 그래프의 순서 버그를 잡는다.

**Tech Stack:** Python 3.12+ · LangGraph `StateGraph` · `AgentState` (`TypedDict`, 필드 100개) · pytest · ruff

**스펙:** [2026-08-14-subagent-graph-engineering-loop-design.md](../specs/2026-08-14-subagent-graph-engineering-loop-design.md)

## Global Constraints

- **작업 위치:** `/Users/ywsung/Desktop/neos` (메인 워크트리, 브랜치 `dev`). 격리가 필요하면 착수 전에 워크트리를 만든다.
- **Python:** `/Users/ywsung/Desktop/neos/.venv/bin/python3` · `pytest` · `ruff`
- **테스트 환경변수:** `GOOGLE_API_KEY=test-key`를 붙여 실행한다.
- **커밋 메시지에 `Co-Authored-By` 트레일러를 넣지 않는다.** (사용자 지침 — 기본 하네스 지침보다 우선)
- **주석·문서는 한국어로 쓴다.** 코드 식별자는 영어.
- **매직넘버 금지** — 임계값·상한은 `neos/config/schema.py`의 설정으로 낸다.
- **기본은 정적 그래프.** 설계 서브에이전트는 기능 플래그 뒤에 있고 기본값은 꺼짐이다.
- **모든 폴백은 원장 이벤트를 남긴다.** 이벤트 없는 조용한 degrade를 만들지 않는다.
- **노드 코드를 생성하지 않는다.** 서브에이전트는 토폴로지(노드 부분집합 + 엣지)만 낸다.
- **재설계 루프를 만들지 않는다.** 한 번 제안하고, 통과하면 쓰고, 아니면 정적 경로로 간다.

## ⚠️ 이름 충돌 — 먼저 읽을 것

이 저장소에는 `WorkflowNode`가 **둘** 있다:

| 위치 | 정체 | 이 계획에서 |
|---|---|---|
| `neos/workflow/enums.py:4` | `Enum`, 멤버 56개. **`graph.py`가 쓰는 것** | ✅ **이것을 쓴다** |
| `neos/workflow/builder/nodes.py:6` | dict 직렬화용 클래스. `graph.py`가 **전혀 참조하지 않는다** | ❌ 건드리지 않는다 |

`neos/workflow/builder/` 패키지 전체가 `graph.py`와 무관하다(`grep -n "builder" neos/workflow/graph.py` → 출력 없음). **계약을 그쪽에 붙이지 말 것.**

---

### Task 1: 노드 계약 선언 기구 + 파일럿 3개

**Files:**
- Create: `neos/workflow/contracts.py`
- Modify: `neos/workflow/graph.py` (노드 메서드 3개에 데코레이터 부착)
- Create: `tests/workflow/test_node_contracts.py`

**Interfaces:**
- Produces:
  - `NodeContract(node: str, reads: frozenset[str], writes: frozenset[str], requires: frozenset[str])` — frozen dataclass
  - `node_contract(*, node: WorkflowNode, reads=(), writes=(), requires=())` — 데코레이터
  - `NODE_CONTRACTS: dict[str, NodeContract]` — 노드 이름(enum `.value`) → 계약
  - `state_keys_read(fn) -> set[str]` — 소스에서 실제로 읽는 키를 뽑는 검사용 헬퍼

> **`reads`와 `requires`는 다르다.** `reads`는 "이 키를 읽는다"이고, `requires`는 **"없으면 이 노드의 실행이 무의미하다"**이다. `state.get()`이 기본값을 돌려줘 조용히 통과하던 자리가 `requires`에서 드러난다 — 이 구분이 이 기능 전체의 존재 이유다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/workflow/test_node_contracts.py`:

```python
import pytest

from neos.workflow.contracts import NODE_CONTRACTS, NodeContract, state_keys_read
from neos.workflow.enums import WorkflowNode
from neos.workflow.state import AgentState


PILOT_NODES = (
    WorkflowNode.QUERY_CLS.value,
    WorkflowNode.SEARCH_ORCHESTRATOR.value,
    WorkflowNode.RESULT_INTEGRATOR.value,
)


def test_pilot_nodes_declare_contracts() -> None:
    for name in PILOT_NODES:
        assert name in NODE_CONTRACTS, f"{name} 에 계약 선언이 없다"


@pytest.mark.parametrize("name", PILOT_NODES)
def test_declared_keys_exist_on_agent_state(name: str) -> None:
    """오타난 키를 선언하면 검증기가 허구를 검사하게 된다."""
    contract = NODE_CONTRACTS[name]
    fields = set(AgentState.__annotations__)
    unknown = (contract.reads | contract.writes | contract.requires) - fields
    assert unknown == set(), f"{name}: AgentState 에 없는 키 {sorted(unknown)}"


@pytest.mark.parametrize("name", PILOT_NODES)
def test_requires_is_a_subset_of_reads(name: str) -> None:
    """요구하는데 읽지 않는 키는 선언이 잘못된 것이다."""
    contract = NODE_CONTRACTS[name]
    assert contract.requires <= contract.reads


@pytest.mark.parametrize("name", PILOT_NODES)
def test_declared_reads_cover_what_the_source_actually_reads(name: str) -> None:
    """선언하지 않고 읽는 키가 있으면 검증기가 그 의존을 못 본다.

    그 방향의 드리프트가 정확히 위험하다 -- 검증기는 선언된 것만 검사하므로,
    선언 밖에서 읽는 키는 순서가 틀려도 통과하고 노드는 빈 값으로 조용히 돈다.
    """
    contract = NODE_CONTRACTS[name]
    actual = state_keys_read(contract.handler)
    undeclared = actual - contract.reads
    assert undeclared == set(), f"{name}: 선언되지 않은 읽기 {sorted(undeclared)}"
```

- [ ] **Step 2: 실패를 확인한다**

```bash
GOOGLE_API_KEY=test-key /Users/ywsung/Desktop/neos/.venv/bin/pytest -q \
  tests/workflow/test_node_contracts.py
```

Expected: FAIL — `ModuleNotFoundError: neos.workflow.contracts`

- [ ] **Step 3: 계약 기구를 만든다**

`neos/workflow/contracts.py`:

```python
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
```

- [ ] **Step 4: 파일럿 노드 3개에 계약을 붙인다**

`neos/workflow/graph.py`의 `_classify_query_node` · `_orchestrate_search_node` ·
`_integrate_results_node`에 데코레이터를 붙인다. **값은 소스를 읽어 실측으로 채운다.**
아래 명령으로 각 메서드가 실제로 읽는 키를 먼저 뽑아 그대로 옮겨 적는다:

```bash
GOOGLE_API_KEY=test-key /Users/ywsung/Desktop/neos/.venv/bin/python3 -c "
from neos.workflow.graph import *
import neos.workflow.graph as g, inspect, ast, textwrap
from neos.workflow.contracts import state_keys_read
cls = [o for _, o in inspect.getmembers(g, inspect.isclass) if hasattr(o, '_classify_query_node')][0]
for m in ('_classify_query_node', '_orchestrate_search_node', '_integrate_results_node'):
    print(m, sorted(state_keys_read(getattr(cls, m))))
"
```

`writes`는 그 메서드가 반환하는 dict의 키에서 뽑고, `requires`는 그중 **없으면 산출물이
무의미해지는 것**만 고른다 — `reads` 전체를 그대로 `requires`에 넣지 않는다.

- [ ] **Step 5: 통과를 확인하고 커밋한다**

```bash
GOOGLE_API_KEY=test-key /Users/ywsung/Desktop/neos/.venv/bin/pytest -q \
  tests/workflow/test_node_contracts.py
/Users/ywsung/Desktop/neos/.venv/bin/ruff check neos/workflow/contracts.py tests/workflow/test_node_contracts.py
git add neos/workflow/contracts.py neos/workflow/graph.py tests/workflow/test_node_contracts.py
git commit -m "feat(workflow): declare node state contracts

노드 간 계약이 graph.py 의 배선 순서에만 존재했다 -- 코드에 적혀 있지 않아 순서가
틀려도 state.get() 이 기본값을 돌려주고 노드가 빈 산출물을 냈다. reads/writes/requires
를 데이터로 선언하고, 소스에서 실제 읽는 키를 뽑아 선언과 대조하는 드리프트 가드를 건다."
```

---

### Task 2: 나머지 노드 전부에 계약 부착

**Files:**
- Modify: `neos/workflow/graph.py` (남은 노드 메서드 전부)
- Modify: `tests/workflow/test_node_contracts.py`

**Interfaces:**
- Consumes: Task 1의 `node_contract` · `NODE_CONTRACTS` · `state_keys_read`
- Produces: `graph.py`가 `add_node`로 등록하는 **모든** 노드에 대한 계약

- [ ] **Step 1: 커버리지 테스트를 쓴다 (실패 확인)**

`tests/workflow/test_node_contracts.py`에서 `PILOT_NODES`를 전수로 바꾸고 추가한다:

```python
def _graph_node_names() -> tuple[str, ...]:
    """graph.py 가 add_node 로 등록하는 노드 이름을 소스에서 뽑는다."""
    import ast
    import textwrap
    from pathlib import Path

    import neos.workflow.graph as graph_module

    source = Path(graph_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    names: set[str] = set()
    for item in ast.walk(tree):
        if (
            isinstance(item, ast.Call)
            and isinstance(item.func, ast.Attribute)
            and item.func.attr == "add_node"
            and item.args
            and isinstance(item.args[0], ast.Attribute)
            and item.args[0].attr == "value"
        ):
            names.add(item.args[0].value.attr)
    return tuple(sorted(names))


def test_every_graph_node_declares_a_contract() -> None:
    """계약 없는 노드가 하나라도 있으면 검증기는 그 노드의 의존을 못 본다."""
    from neos.workflow.enums import WorkflowNode

    declared = {
        member.name
        for member in WorkflowNode
        if member.value in NODE_CONTRACTS
    }
    missing = set(_graph_node_names()) - declared
    assert missing == set(), f"계약 미선언 노드: {sorted(missing)}"
```

그리고 기존 파라미터화 테스트들의 `PILOT_NODES`를 `tuple(NODE_CONTRACTS)`로 바꾼다.

```bash
GOOGLE_API_KEY=test-key /Users/ywsung/Desktop/neos/.venv/bin/pytest -q \
  tests/workflow/test_node_contracts.py::test_every_graph_node_declares_a_contract
```

Expected: FAIL — 파일럿 3개를 뺀 나머지가 `missing`에 나열된다.

- [ ] **Step 2: 남은 노드에 계약을 붙인다**

Task 1 Step 4의 추출 명령을 나머지 노드에 대해 돌려 `reads`를 채우고, 반환 dict에서
`writes`를 채운다. `requires`는 노드마다 판단한다.

**`requires` 판정 기준:** 그 키가 비어 있을 때 노드가 (a) 예외를 내면 → `requires`,
(b) 의미 있는 기본 동작을 하면 → `requires` 아님, (c) **조용히 빈 산출물을 내면 →
`requires`**. (c)가 이 작업의 핵심이다.

- [ ] **Step 3: 전체 통과 확인**

```bash
GOOGLE_API_KEY=test-key /Users/ywsung/Desktop/neos/.venv/bin/pytest -q tests/workflow/
```

Expected: 전부 PASS. 기존 워크플로우 테스트에 회귀가 없어야 한다 — 데코레이터는 동작을
바꾸지 않는다.

- [ ] **Step 4: 커밋**

```bash
/Users/ywsung/Desktop/neos/.venv/bin/ruff check neos/workflow tests/workflow
git add neos/workflow/graph.py tests/workflow/test_node_contracts.py
git commit -m "feat(workflow): contract every graph node

add_node 로 등록되는 모든 노드가 계약을 선언하게 하고, 소스에서 노드 목록을 뽑아
누락을 막는 커버리지 가드를 건다."
```

---

### Task 3: 토폴로지 표현과 도달성·종료성 규칙

**Files:**
- Create: `neos/workflow/topology.py`
- Create: `tests/workflow/test_topology_validator.py`

**Interfaces:**
- Consumes: Task 1–2의 `NODE_CONTRACTS`
- Produces:
  - `GraphTopology(nodes: tuple[str, ...], edges: tuple[tuple[str, str], ...], loop_bounds: Mapping[str, int] = ...)` — frozen dataclass. `START` / `END`는 센티널 문자열. **`loop_bounds`는 기본값이 빈 매핑**이어야 한다 — 이 태스크의 테스트들이 그 인자 없이 생성한다
  - `TopologyViolation(rule: str, node: str | None, detail: str)` — frozen dataclass
  - `validate_topology(topology, *, contracts) -> tuple[TopologyViolation, ...]` — 빈 튜플이면 유효. **Task 4가 `mandatory` · `budget` · `node_costs` 인자를 덧붙인다**

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/workflow/test_topology_validator.py`:

```python
from neos.workflow.topology import (
    END,
    START,
    GraphTopology,
    validate_topology,
)


def _rules(violations) -> set[str]:
    return {v.rule for v in violations}


def test_a_linear_topology_is_valid() -> None:
    topology = GraphTopology(
        nodes=("a", "b"),
        edges=((START, "a"), ("a", "b"), ("b", END)),
    )
    assert validate_topology(topology, contracts={}) == ()


def test_an_unreachable_node_is_rejected() -> None:
    topology = GraphTopology(
        nodes=("a", "orphan"),
        edges=((START, "a"), ("a", END)),
    )
    violations = validate_topology(topology, contracts={})
    assert "unreachable_node" in _rules(violations)
    assert any(v.node == "orphan" for v in violations)


def test_a_node_that_cannot_reach_end_is_rejected() -> None:
    topology = GraphTopology(
        nodes=("a", "sink"),
        edges=((START, "a"), ("a", "sink")),
    )
    assert "dead_end" in _rules(validate_topology(topology, contracts={}))


def test_an_unbounded_cycle_is_rejected() -> None:
    topology = GraphTopology(
        nodes=("a", "b"),
        edges=((START, "a"), ("a", "b"), ("b", "a"), ("b", END)),
    )
    assert "unbounded_cycle" in _rules(validate_topology(topology, contracts={}))


def test_an_edge_to_an_undeclared_node_is_rejected() -> None:
    topology = GraphTopology(
        nodes=("a",),
        edges=((START, "a"), ("a", "ghost"), ("a", END)),
    )
    assert "unknown_node" in _rules(validate_topology(topology, contracts={}))
```

- [ ] **Step 2: 실패를 확인한다**

```bash
GOOGLE_API_KEY=test-key /Users/ywsung/Desktop/neos/.venv/bin/pytest -q \
  tests/workflow/test_topology_validator.py
```

Expected: FAIL — `ModuleNotFoundError: neos.workflow.topology`

- [ ] **Step 3: 토폴로지와 네 규칙을 구현한다**

`neos/workflow/topology.py`에 `START = "__start__"`, `END = "__end__"` 센티널,
두 dataclass, 그리고 `validate_topology`를 만든다. 이 스텝의 규칙 넷:

- `unknown_node` — 엣지가 `nodes`에도 센티널에도 없는 이름을 가리킨다
- `unreachable_node` — `START`에서 전방 도달 불가
- `dead_end` — 그 노드에서 `END`로 도달 불가
- `unbounded_cycle` — 사이클에 속하는데 반복 상한이 선언되지 않았다

사이클 탐지는 `nodes ∪ {START, END}` 위의 방향 그래프에서 강결합 성분을 구해, 크기가
2 이상이거나 자기 루프를 가진 성분을 사이클로 본다. 반복 상한 선언은 다음 스텝의
`GraphTopology.loop_bounds: Mapping[str, int]` 필드로 받는다 — **지금은 빈 매핑이므로
모든 사이클이 거부된다.**

- [ ] **Step 4: 통과 확인 및 커밋**

```bash
GOOGLE_API_KEY=test-key /Users/ywsung/Desktop/neos/.venv/bin/pytest -q \
  tests/workflow/test_topology_validator.py
/Users/ywsung/Desktop/neos/.venv/bin/ruff check neos/workflow/topology.py tests/workflow/test_topology_validator.py
git add neos/workflow/topology.py tests/workflow/test_topology_validator.py
git commit -m "feat(workflow): validate topology reachability and termination

토폴로지 표현과 구조 규칙 넷을 만든다 -- 미지 노드, 도달 불가 노드, END 에 못 닿는
경로, 상한 없는 사이클."
```

---

### Task 4: 계약 충족 규칙 — 이 기능의 존재 이유

**Files:**
- Modify: `neos/workflow/topology.py`
- Modify: `tests/workflow/test_topology_validator.py`

**Interfaces:**
- Consumes: Task 3의 `validate_topology`, Task 1–2의 `NodeContract`
- Produces: `unsatisfied_requires` · `missing_mandatory` · `budget_exceeded` 규칙

> **의미론이 핵심이다.** 노드 N이 키 K를 `requires`한다면, **START에서 N에 이르는 모든
> 경로**에 K를 `writes`하는 노드가 있어야 한다. 어느 한 경로에만 있으면 그 나머지 경로로
> 들어온 실행이 조용히 빈 값을 읽는다 — 정확히 이 기능이 막으려는 것이다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
from neos.workflow.contracts import NodeContract


def _contract(node, *, reads=(), writes=(), requires=()) -> NodeContract:
    return NodeContract(
        node=node,
        reads=frozenset(reads) | frozenset(requires),
        writes=frozenset(writes),
        requires=frozenset(requires),
        handler=lambda state: state,
    )


def test_a_requires_key_written_upstream_is_satisfied() -> None:
    contracts = {
        "search": _contract("search", writes=("search_results",)),
        "integrate": _contract("integrate", requires=("search_results",)),
    }
    topology = GraphTopology(
        nodes=("search", "integrate"),
        edges=((START, "search"), ("search", "integrate"), ("integrate", END)),
    )
    assert validate_topology(topology, contracts=contracts) == ()


def test_a_requires_key_never_written_is_rejected() -> None:
    contracts = {"integrate": _contract("integrate", requires=("search_results",))}
    topology = GraphTopology(
        nodes=("integrate",),
        edges=((START, "integrate"), ("integrate", END)),
    )
    violations = validate_topology(topology, contracts=contracts)
    assert "unsatisfied_requires" in _rules(violations)
    assert any("search_results" in v.detail for v in violations)


def test_a_key_written_on_only_one_branch_is_rejected() -> None:
    """분기 하나에만 있으면, 다른 분기로 들어온 실행은 빈 값을 읽는다.

    이것이 이 검증기의 존재 이유다 -- 예외가 나지 않고 조용히 빈 산출물이 나온다.
    """
    contracts = {
        "search": _contract("search", writes=("search_results",)),
        "skip": _contract("skip"),
        "integrate": _contract("integrate", requires=("search_results",)),
    }
    topology = GraphTopology(
        nodes=("search", "skip", "integrate"),
        edges=(
            (START, "search"),
            (START, "skip"),
            ("search", "integrate"),
            ("skip", "integrate"),
            ("integrate", END),
        ),
    )
    assert "unsatisfied_requires" in _rules(
        validate_topology(topology, contracts=contracts)
    )


def test_a_missing_mandatory_node_is_rejected() -> None:
    topology = GraphTopology(nodes=("a",), edges=((START, "a"), ("a", END)))
    violations = validate_topology(
        topology, contracts={}, mandatory=("resp_generator",)
    )
    assert "missing_mandatory" in _rules(violations)


def test_a_topology_over_budget_is_rejected() -> None:
    contracts = {"a": _contract("a"), "b": _contract("b")}
    topology = GraphTopology(nodes=("a", "b"), edges=((START, "a"), ("a", "b"), ("b", END)))
    violations = validate_topology(
        topology, contracts=contracts, budget=1, node_costs={"a": 1, "b": 1}
    )
    assert "budget_exceeded" in _rules(violations)
```

- [ ] **Step 2: 실패를 확인한다**

```bash
GOOGLE_API_KEY=test-key /Users/ywsung/Desktop/neos/.venv/bin/pytest -q \
  tests/workflow/test_topology_validator.py -k "requires or mandatory or budget"
```

Expected: FAIL — 규칙이 아직 없어 위반이 비어 있다.

- [ ] **Step 3: "모든 경로에서 반드시 쓰인 키" 분석을 구현한다**

각 노드에 대해 **모든 선행 경로에서 보장되는 키 집합**을 고정점 반복으로 구한다:

```python
def _guaranteed_keys(
    topology: "GraphTopology",
    writes: Mapping[str, frozenset[str]],
) -> dict[str, frozenset[str]]:
    """노드 진입 시점에 **모든 경로에서** 이미 쓰였음이 보장되는 키.

    선행 노드들의 보장 집합을 **교집합** 한다 -- 어느 한 경로에만 있는 키는
    보장이 아니다. 사이클이 있어도 수렴하도록 비-START 노드를 전체 집합으로
    낙관적으로 초기화하고 줄여 나간다(must-analysis 의 표준 형태).
    """
    universe = frozenset().union(*writes.values()) if writes else frozenset()
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
                        merged = frozenset()
                        break
                    merged &= guaranteed.get(pred, frozenset()) | writes.get(
                        pred, frozenset()
                    )
            if merged != guaranteed[node]:
                guaranteed[node] = merged
                changed = True
    return guaranteed
```

그 뒤 각 노드의 `requires - guaranteed[node]`가 비어 있지 않으면
`unsatisfied_requires` 위반을 낸다. `missing_mandatory`는 `mandatory` 인자의 각 이름이
`topology.nodes`에 있는지 보고, `budget_exceeded`는 `node_costs`의 합을 `budget`과 비교한다.

`validate_topology`의 시그니처를 `mandatory: Sequence[str] = ()`,
`budget: int | None = None`, `node_costs: Mapping[str, int] | None = None`으로 확장한다.

- [ ] **Step 4: 통과 확인 및 커밋**

```bash
GOOGLE_API_KEY=test-key /Users/ywsung/Desktop/neos/.venv/bin/pytest -q \
  tests/workflow/test_topology_validator.py
/Users/ywsung/Desktop/neos/.venv/bin/ruff check neos/workflow/topology.py tests/workflow/test_topology_validator.py
git add neos/workflow/topology.py tests/workflow/test_topology_validator.py
git commit -m "feat(workflow): reject topologies that break node contracts

노드가 requires 하는 키는 START 에서 그 노드에 이르는 **모든 경로**에서 쓰여 있어야
한다. 한 분기에만 있으면 다른 분기로 들어온 실행이 조용히 빈 값을 읽는다 -- 예외가
나지 않으므로 이 검사가 유일한 방어선이다."
```

---

### Task 5: 정적 그래프를 검증기에 통과시킨다 — 단독 가치 회수

**Files:**
- Create: `neos/workflow/topology_export.py`
- Create: `tests/workflow/test_static_graph_contract.py`

**Interfaces:**
- Consumes: Task 3–4의 `validate_topology`, Task 1–2의 `NODE_CONTRACTS`
- Produces: `static_topology() -> GraphTopology` — `graph.py`의 현재 배선을 `GraphTopology`로 뽑아낸다

> **이 태스크가 C1·C2의 단독 가치를 회수한다.** 서브에이전트를 영영 만들지 않아도, 지금
> 손으로 쓴 배선이 자기 계약을 만족하는지 증명하는 회귀 가드가 남는다.

- [ ] **Step 1: 회귀 가드 테스트를 쓴다**

`tests/workflow/test_static_graph_contract.py`:

```python
from neos.workflow.contracts import NODE_CONTRACTS
from neos.workflow.topology import validate_topology
from neos.workflow.topology_export import static_topology


def test_the_static_graph_satisfies_its_own_contracts() -> None:
    """손으로 쓴 배선이 자기 계약을 만족하는지 증명한다.

    실패하면 검증기 버그이거나, 계약 선언이 틀렸거나, **정적 그래프에 실제 순서
    버그가 있는 것**이다. 셋 다 고칠 가치가 있다.
    """
    violations = validate_topology(static_topology(), contracts=NODE_CONTRACTS)
    assert violations == (), "\n".join(
        f"{v.rule} @ {v.node}: {v.detail}" for v in violations
    )
```

- [ ] **Step 2: 실패를 확인한다**

```bash
GOOGLE_API_KEY=test-key /Users/ywsung/Desktop/neos/.venv/bin/pytest -q \
  tests/workflow/test_static_graph_contract.py
```

Expected: FAIL — `ModuleNotFoundError: neos.workflow.topology_export`

- [ ] **Step 3: 정적 배선을 뽑아낸다**

`neos/workflow/topology_export.py`에서 `graph.py`의 `add_node` / `add_edge` /
`add_conditional_edges` 호출을 `ast`로 읽어 `GraphTopology`를 만든다. 조건부 엣지는
**가능한 모든 대상으로 향하는 엣지**로 펼친다 — 검증기의 "모든 경로" 의미론이 그것을
요구한다.

기능 플래그로 켜고 꺼지는 노드가 있으므로(`recursive` · `hyper_deep` · `deep_analysis` ·
`execution_approval`), 플래그 조합마다 토폴로지가 다르다. `static_topology(*, flags)` 로
받아 기본값은 **전부 켠 상태**로 둔다(가장 넓은 그래프가 가장 많은 위반을 드러낸다).

- [ ] **Step 4: 실패를 판정한다 — 이 스텝이 이 태스크의 본론**

테스트가 통과하면 그대로 커밋한다. **실패하면 세 갈래를 구분해 보고한다:**

1. 검증기 버그 → 검증기를 고친다
2. 계약 선언 오류 → 계약을 고친다
3. **정적 그래프의 실제 순서 버그** → 고치지 말고 **보고한다.** 프로덕션 동작을 바꾸는
   일이므로 별도 판단이 필요하다. 그 경우 이 테스트를 `xfail(strict=True)`로 두고
   위반 내용을 이유에 적는다.

- [ ] **Step 5: 커밋**

```bash
/Users/ywsung/Desktop/neos/.venv/bin/ruff check neos/workflow/topology_export.py tests/workflow/test_static_graph_contract.py
git add neos/workflow/topology_export.py tests/workflow/test_static_graph_contract.py
git commit -m "test(workflow): prove the static graph satisfies its contracts

서브에이전트가 없어도 남는 회귀 가드다 -- 손으로 쓴 배선의 순서 버그도 같은 검사기가
잡는다."
```

---

### Task 6: 설계 서브에이전트의 출력 계약과 결정론적 fake

**Files:**
- Create: `neos/workflow/graph_designer.py`
- Create: `neos/workflow/prompts/graph_design.md`
- Create: `tests/workflow/test_graph_designer.py`

**Interfaces:**
- Consumes: Task 3–4의 `GraphTopology` · `validate_topology`
- Produces:
  - `GraphDesigner` 프로토콜 — `async def design(self, request: DesignRequest) -> GraphTopology`
  - `DesignRequest(query: str, catalog: tuple[NodeContract, ...], budget: int)` — frozen dataclass
  - `FakeGraphDesigner(topology)` — 주어진 토폴로지를 그대로 돌려주는 테스트용 구현
  - `parse_topology(payload: Mapping) -> GraphTopology` — LLM JSON → 토폴로지, 미지 노드명은 거부

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
import pytest

from neos.workflow.graph_designer import (
    DesignRequest,
    FakeGraphDesigner,
    InvalidDesignPayload,
    parse_topology,
)
from neos.workflow.topology import END, START, GraphTopology


def test_parse_topology_accepts_a_well_formed_payload() -> None:
    topology = parse_topology(
        {"nodes": ["a", "b"], "edges": [[START, "a"], ["a", "b"], ["b", END]]},
        known_nodes=frozenset({"a", "b"}),
    )
    assert topology.nodes == ("a", "b")


def test_parse_topology_rejects_an_unknown_node() -> None:
    """서브에이전트가 없는 노드를 지어내면 여기서 막는다."""
    with pytest.raises(InvalidDesignPayload, match="unknown_node"):
        parse_topology(
            {"nodes": ["ghost"], "edges": [[START, "ghost"], ["ghost", END]]},
            known_nodes=frozenset({"a"}),
        )


def test_parse_topology_rejects_a_malformed_edge() -> None:
    with pytest.raises(InvalidDesignPayload):
        parse_topology(
            {"nodes": ["a"], "edges": [["a"]]},
            known_nodes=frozenset({"a"}),
        )


async def test_the_fake_designer_returns_what_it_was_given() -> None:
    topology = GraphTopology(nodes=("a",), edges=((START, "a"), ("a", END)))
    designer = FakeGraphDesigner(topology)

    result = await designer.design(
        DesignRequest(query="q", catalog=(), budget=1000)
    )

    assert result == topology
    assert designer.design_calls == 1
```

- [ ] **Step 2: 실패 확인 → 구현 → 통과 확인**

```bash
GOOGLE_API_KEY=test-key /Users/ywsung/Desktop/neos/.venv/bin/pytest -q \
  tests/workflow/test_graph_designer.py
```

`parse_topology`는 `nodes`가 문자열 리스트인지, `edges`가 2원소 리스트의 리스트인지,
모든 이름이 `known_nodes ∪ {START, END}`에 있는지 검사하고 아니면
`InvalidDesignPayload`를 올린다. **프롬프트는 파일로 둔다** (`prompts/graph_design.md`) —
매직 문자열 금지 규칙이 프롬프트에도 적용된다.

- [ ] **Step 3: 커밋**

```bash
/Users/ywsung/Desktop/neos/.venv/bin/ruff check neos/workflow/graph_designer.py tests/workflow/test_graph_designer.py
git add neos/workflow/graph_designer.py neos/workflow/prompts/graph_design.md \
  tests/workflow/test_graph_designer.py
git commit -m "feat(workflow): define the graph design contract

서브에이전트는 토폴로지만 낸다 -- 코드는 쓰지 않는다. 미지 노드명과 형식 오류를
파싱 단계에서 거부하고, 결정론적 fake 로 이후 태스크가 LLM 없이 테스트되게 한다."
```

---

### Task 7: 실제 설계 서브에이전트 (기능 플래그 뒤)

**Files:**
- Create: `neos/workflow/graph_designer_llm.py`
- Modify: `neos/config/schema.py`
- Create: `tests/workflow/test_graph_designer_llm.py`

**Interfaces:**
- Consumes: Task 6의 `GraphDesigner` · `parse_topology` · `DesignRequest`
- Produces: `LlmGraphDesigner(model, prompt_path)` — `GraphDesigner` 구현

- [ ] **Step 1: 설정을 추가한다**

`neos/config/schema.py`의 워크플로우 설정에:

```python
    graph_design_enabled: bool = Field(
        default=False,
        description="설계 서브에이전트로 질의별 그래프를 짤지 여부. 기본은 정적 그래프다.",
    )
    graph_design_timeout_sec: float = Field(
        default=20.0, gt=0, le=120,
        description="설계 서브에이전트 호출 타임아웃. 넘으면 정적 그래프로 폴백한다.",
    )
```

- [ ] **Step 2: 테스트를 쓴다 (fake 모델로)**

LLM 호출은 fake로 대체하고, **응답이 깨졌을 때 예외가 새지 않는지**를 고정한다:

```python
async def test_a_malformed_model_response_raises_invalid_design_payload() -> None:
    designer = LlmGraphDesigner(model=_FakeModel("not json"), prompt_path=PROMPT)
    with pytest.raises(InvalidDesignPayload):
        await designer.design(DesignRequest(query="q", catalog=(), budget=1000))


async def test_the_designer_never_invents_a_node() -> None:
    designer = LlmGraphDesigner(
        model=_FakeModel('{"nodes": ["ghost"], "edges": []}'), prompt_path=PROMPT
    )
    with pytest.raises(InvalidDesignPayload, match="unknown_node"):
        await designer.design(
            DesignRequest(query="q", catalog=(_contract_for("a"),), budget=1000)
        )
```

- [ ] **Step 3: 구현 → 통과 확인 → 커밋**

`LlmGraphDesigner`는 카탈로그(계약 포함)를 프롬프트에 넣고 JSON을 받아
`parse_topology`에 넘긴다. **검증은 하지 않는다** — 검증기는 호출자(Task 8)가 돌린다.
`judge ≠ worker` 원칙과 같은 이유로, 만든 쪽이 스스로 통과 판정을 내리지 않게 한다.

```bash
git add neos/workflow/graph_designer_llm.py neos/config/schema.py tests/workflow/test_graph_designer_llm.py
git commit -m "feat(workflow): add the llm graph designer behind a flag

기본은 꺼짐이다. 설계자는 검증을 스스로 하지 않는다 -- 만든 쪽이 통과 판정을 내리면
judge != worker 가 깨진다."
```

---

### Task 8: 원장 이벤트와 폴백 4경로

**Files:**
- Create: `neos/workflow/graph_design_ledger.py`
- Create: `tests/workflow/test_graph_design_ledger.py`

**Interfaces:**
- Consumes: Task 6–7의 `GraphDesigner` · `InvalidDesignPayload`, Task 3–4의 `validate_topology`
- Produces:
  - `LedgerEvent(kind: str, payload: Mapping[str, Any])` — frozen dataclass. **이 태스크에서 새로 정의한다** (기존 `deep_analysis` 이벤트 타입을 재사용하지 않는다 — 그쪽은 run 원장에 묶여 있고 이 경로는 아직 run이 없다)
  - `DesignOutcome(topology: GraphTopology | None, events: tuple[LedgerEvent, ...])` — frozen dataclass. `topology`가 `None`이면 호출자는 정적 그래프를 쓴다
  - `async def design_graph_or_fallback(*, designer, request, contracts, mandatory=(), timeout_sec=...) -> DesignOutcome`

> **스펙 §5의 규칙:** 폴백은 조용히 일어나지 않는다. 네 경로가 각각 지정된 이벤트를 남긴다.

- [ ] **Step 1: 네 경로를 고정하는 테스트를 쓴다**

```python
KINDS = ("graph_design_requested", "graph_design_rejected",
         "graph_design_accepted", "graph_design_fallback")


async def test_a_valid_design_is_accepted_and_recorded() -> None:
    outcome = await design_graph_or_fallback(
        designer=FakeGraphDesigner(_valid_topology()), request=_request(),
        contracts=_contracts(), mandatory=(),
    )
    kinds = [e.kind for e in outcome.events]
    assert kinds == ["graph_design_requested", "graph_design_accepted"]
    assert outcome.topology is not None


async def test_a_rejected_design_records_the_rule_and_node() -> None:
    """거부 이벤트는 어느 규칙이 어느 노드에서 깨졌는지 실어야 한다.

    사유 없는 폴백은 '조용한 degrade' 와 구별되지 않는다.
    """
    outcome = await design_graph_or_fallback(
        designer=FakeGraphDesigner(_topology_missing_requires()), request=_request(),
        contracts=_contracts(), mandatory=(),
    )
    rejected = next(e for e in outcome.events if e.kind == "graph_design_rejected")
    assert rejected.payload["violations"]
    assert "unsatisfied_requires" in {v["rule"] for v in rejected.payload["violations"]}
    assert outcome.topology is None


async def test_a_designer_error_falls_back_with_a_reason() -> None:
    outcome = await design_graph_or_fallback(
        designer=_RaisingDesigner(InvalidDesignPayload("unknown_node: ghost")),
        request=_request(), contracts=_contracts(), mandatory=(),
    )
    fallback = next(e for e in outcome.events if e.kind == "graph_design_fallback")
    assert "unknown_node" in fallback.payload["reason"]
    assert outcome.topology is None


async def test_a_designer_timeout_falls_back_with_a_reason() -> None:
    outcome = await design_graph_or_fallback(
        designer=_HangingDesigner(), request=_request(),
        contracts=_contracts(), mandatory=(), timeout_sec=0.01,
    )
    fallback = next(e for e in outcome.events if e.kind == "graph_design_fallback")
    assert fallback.payload["reason"] == "timeout"
```

- [ ] **Step 2: 실패 확인 → 구현 → 통과 확인**

`design_graph_or_fallback`은 `graph_design_requested`를 먼저 남기고, 설계를
`asyncio.wait_for`로 감싸고, 성공하면 `validate_topology`를 돌린다. 위반이 있으면
`graph_design_rejected`(위반 목록 포함)를, 예외·타임아웃이면 `graph_design_fallback`
(사유 포함)을 남긴다. `topology`가 `None`이면 호출자는 정적 그래프를 쓴다.

**재설계하지 않는다** — 실패한 토폴로지를 서브에이전트에게 되돌려주지 않는다.

- [ ] **Step 3: 커밋**

```bash
git add neos/workflow/graph_design_ledger.py tests/workflow/test_graph_design_ledger.py
git commit -m "feat(workflow): make graph design failures visible

설계·검증·폴백을 한 곳에 모으고 네 경로가 각각 이벤트를 남기게 한다. 거부는 위반한
규칙과 노드를, 폴백은 사유를 싣는다 -- 사유 없는 폴백은 조용한 degrade 와 구별되지 않는다."
```

---

### Task 9: ephemeral 실행 배선

**Files:**
- Modify: `neos/workflow/graph.py`
- Create: `tests/workflow/test_ephemeral_graph_execution.py`

**Interfaces:**
- Consumes: Task 8의 `design_graph_or_fallback`, Task 3의 `GraphTopology`
- Produces: `build_ephemeral_workflow(topology) -> StateGraph` — 토폴로지대로 `add_node`/`add_edge`를 부르고 컴파일한다

- [ ] **Step 1: 테스트를 쓴다**

```python
def test_an_ephemeral_graph_wires_only_the_designed_nodes() -> None:
    topology = GraphTopology(
        nodes=(WorkflowNode.QUERY_CLS.value, WorkflowNode.RESP_GENERATOR.value),
        edges=(
            (START, WorkflowNode.QUERY_CLS.value),
            (WorkflowNode.QUERY_CLS.value, WorkflowNode.RESP_GENERATOR.value),
            (WorkflowNode.RESP_GENERATOR.value, END),
        ),
    )
    compiled = build_ephemeral_workflow(_harness(), topology)
    assert set(compiled.get_graph().nodes) >= set(topology.nodes)


def test_the_static_path_is_unchanged_when_the_flag_is_off() -> None:
    """graph_design_enabled=False 에서 기존 동작이 바이트 단위로 같아야 한다."""
    harness = _harness(graph_design_enabled=False)
    assert harness._designed_topology is None
```

- [ ] **Step 2: 실패 확인 → 구현 → 통과 확인**

`build_ephemeral_workflow`는 `NODE_CONTRACTS[name].handler`로 핸들러를 찾아
`add_node`하고, `topology.edges`대로 `add_edge`한다. 조건부 엣지는 이번 범위 밖이다 —
**설계된 토폴로지는 정적 엣지만 갖는다** (분기가 필요하면 검증기가 모든 경로를 보므로
정적 엣지로 표현된다).

플래그가 꺼져 있으면 이 경로를 **전혀 타지 않는다.**

- [ ] **Step 3: 전체 스위트 확인 및 커밋**

```bash
GOOGLE_API_KEY=test-key /Users/ywsung/Desktop/neos/.venv/bin/pytest -q tests/workflow/
/Users/ywsung/Desktop/neos/.venv/bin/ruff check neos/workflow tests/workflow
git add neos/workflow/graph.py tests/workflow/test_ephemeral_graph_execution.py
git commit -m "feat(workflow): execute a designed topology ephemerally

검증을 통과한 토폴로지로만 그래프를 조립한다. 플래그가 꺼져 있으면 이 경로를 전혀
타지 않으므로 기존 동작이 그대로다."
```

---

## 완료 확인 (스펙 §7)

```bash
cd /Users/ywsung/Desktop/neos
GOOGLE_API_KEY=test-key .venv/bin/pytest -q tests/workflow/
.venv/bin/ruff check neos/workflow tests/workflow
```

1. `add_node`로 등록되는 모든 노드가 계약을 선언한다 → `test_every_graph_node_declares_a_contract`
2. 검증기가 다섯 규칙을 구현하고 **정적 그래프가 그 검증을 통과한다** → `test_the_static_graph_satisfies_its_own_contracts`
3. 설계 서브에이전트가 기능 플래그 뒤에 있고 기본은 꺼짐 → `graph_design_enabled` 기본값 `False`
4. 폴백 4경로가 각각 사유를 실은 이벤트를 남긴다 → `test_graph_design_ledger.py` 4건
5. 토폴로지 해시로 설계된 run과 정적 run을 비교할 수 있다 → `graph_design_accepted` 페이로드

> **D3b(langgraph 런타임 교체)와 동시 진행하지 않는다.** Task 3–5·9는 그래프 표현 위에
> 서 있으므로 런타임이 바뀌면 다시 써야 한다. Task 1–2(노드 계약)는 런타임과 무관하므로
> 어느 쪽이든 살아남는다.
