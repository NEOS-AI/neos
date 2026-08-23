# 설계자 배선 (트랙 G의 G2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `design_graph_or_fallback`과 `build_ephemeral_workflow`에 프로덕션 호출자를 주어, `workflow.graph_design_enabled`를 켜면 실제로 질의별 그래프가 설계·실행되게 한다.

**Architecture:** `execute_workflow`가 그래프를 인스턴스 속성(`self.graph`)에서 읽는 대신, 호출 스코프의 값 객체 `ExecutionGraph`로 받는다. 그 값은 정적 그래프이거나 설계된 ephemeral 그래프이며, 진행 추적·ETA·토폴로지 해시가 전부 그 값에서 유도된다. 설계 경로의 모든 실패는 정적 폴백 + 사유 기록으로 끝나고 요청을 죽이지 않는다.

**Tech Stack:** Python 3.12 · LangGraph 1.0.8 (`StateGraph`, `astream`) · pytest (+`pytest-randomly`) · OpenTelemetry (`add_span_event`)

**Spec:** `docs/superpowers/specs/2026-08-23-graph-designer-wiring-g2-design.md`

## Global Constraints

이 절의 요구는 **모든 태스크에 암묵적으로 포함된다.**

- **`workflow.graph_design_enabled`의 기본값은 `False`다. 바꾸지 않는다.** 이 계획이 파는 것은 "켜면 달라진다"이지 "켜자"가 아니다.
- **`MultiAgentWorkflow._create_workflow_graph`를 한 줄도 바꾸지 않는다.** `test_the_compiled_static_graph_matches_its_pre_task_9_snapshot`의 스냅샷 해시가 이것을 강제한다. 이 테스트가 깨지면 되돌린다.
- **설계된 토폴로지를 인스턴스 속성에 두지 않는다.** `graph.py:376-383`의 주석과 `test_the_static_path_does_not_carry_a_shared_designed_topology_slot`이 요구한다. `multi_agent_workflow`는 모듈 레벨 싱글턴이다(`graph.py:3398`).
- **`design_graph_or_fallback`에 `budget`·`node_costs`를 넘기지 않는다 (둘 다 `None` 유지).** `node_costs` 없이 `budget`만 넘기면 fail-closed 규칙이 모든 노드를 "비용 미선언" 위반으로 잡아 **모든 설계가 거부된다**(`graph_design_ledger.py:41-44`).
- **`mandatory` 기본값을 오버라이드하지 않는다.** 기본값 `(response_generator,)`가 I1 불변식이다.
- **`asyncio.CancelledError`는 잡지 않고 전파한다.** `BaseException`이라 `except Exception`에 안 걸린다. 취소 신호를 폴백으로 오인해 삼키면 안 된다(`graph_design_ledger.py:176-178`).
- **재설계 루프를 만들지 않는다.** 위반이 나와도 설계자를 다시 부르지 않는다(`graph_design_ledger.py:20-25`).
- **매직넘버 금지.** 상수는 전부 `neos/config/schema.py`로.
- **커밋 메시지에 `Co-Authored-By` 트레일러를 넣지 않는다.** (이 저장소의 규약)
- **검증 명령:** `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow -q` (전체는 `.venv/bin/python -m pytest`. bare `pytest`는 asyncio 마커 수집에 실패한다)
- **전체 스위트 기준선:** 2,938 passed / 23 skipped / 0 failed. 실패가 하나라도 보이면 실제 회귀로 취급한다.

---

## File Structure

| 파일 | 책임 | 변경 |
|---|---|---|
| `neos/config/schema.py` | 설정 스키마 | `WorkflowConfig`에 두 칸 추가 (Task 1) |
| `neos/workflow/graph_design_ledger.py` | 설계·검증·폴백 관문 | `_topology_hash` → `topology_hash` 공용 승격 (Task 2) |
| `neos/workflow/execution_graph.py` | **신규** — `ExecutionGraph` 값 객체와 정적 해시 계산 | 생성 (Task 2·3) |
| `neos/workflow/graph.py` | 워크플로우 본체 | `_resolve_execution_graph` 추가, `execute_workflow` 수정 (Task 3~7) |
| `neos/workflow/events.py` | 진행 이벤트·ETA | `estimate_remaining_time` 시그니처 변경 (Task 5) |
| `tests/workflow/test_execution_graph.py` | **신규** — 값 객체·정적 해시 | 생성 (Task 2·3) |
| `tests/workflow/test_progress_tracking.py` | **신규** — 진행 추적 (G2-b) | 생성 (Task 5) |
| `tests/workflow/test_graph_design_wiring.py` | **신규** — 배선·폴백 (G2-a·d) | 생성 (Task 6·7) |

**신규 모듈을 하나 만드는 이유:** `graph.py`는 이미 3,200줄이 넘는다. `ExecutionGraph`와 정적 토폴로지 해시는 `graph.py`를 **읽기만** 하는 순수 계산이라 분리하면 단위 테스트가 `MultiAgentWorkflow` 인스턴스 없이 돈다.

---

## Task 1: 설정 두 칸

**Files:**
- Modify: `neos/config/schema.py:245-255` (`WorkflowConfig`의 `graph_design_*` 옆)
- Test: `tests/config/test_workflow_graph_design_config.py` (신규)

**Interfaces:**
- Consumes: 없음 (첫 태스크)
- Produces: `settings.config.workflow.graph_design_model: str | None`, `settings.config.workflow.graph_design_budget_hint: int`

- [ ] **Step 1: Write the failing test**

`tests/config/test_workflow_graph_design_config.py` 생성:

```python
"""`graph_design_*` 설정 — 기본값이 계약이다.

`graph_design_model` 의 기본값 `None` 은 "역할 기본값으로 해석하라"는 뜻이며
(`deep_analysis.models.*` · `coding_model.model` · `recursive_agent.planner_model`
이 쓰는 것과 같은 계약), 문자열은 기능 오버라이드다.
"""

from neos.config.schema import WorkflowConfig


def test_graph_design_model_defaults_to_none_meaning_role_default() -> None:
    assert WorkflowConfig().graph_design_model is None


def test_graph_design_budget_hint_has_a_default_matching_the_existing_tests() -> None:
    # 기존 테스트(`test_graph_designer_llm.py`)가 전부 1000 을 쓴다. 프로덕션
    # 기본값을 같게 두어 배선이 동작 차이를 만들지 않게 한다.
    assert WorkflowConfig().graph_design_budget_hint == 1000


def test_graph_design_enabled_stays_off_by_default() -> None:
    # 이 계획 전체의 Global Constraint. 켜는 것은 별도 결정이다.
    assert WorkflowConfig().graph_design_enabled is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `HOME=/tmp/neos-test-home .venv/bin/pytest tests/config/test_workflow_graph_design_config.py -v`
Expected: FAIL — `AttributeError: 'WorkflowConfig' object has no attribute 'graph_design_model'`

- [ ] **Step 3: Write minimal implementation**

`neos/config/schema.py`의 `graph_design_timeout_sec` 정의 **바로 아래**에 추가:

```python
    graph_design_model: str | None = Field(
        default=None,
        description=(
            "설계 서브에이전트가 쓸 모델. None 이면 프로바이더 × everyday 역할 "
            "기본값으로 해석한다 (deep_analysis.models.* 와 같은 계약)."
        ),
    )
    # `DesignRequest.budget` 에 실려 프롬프트의 {budget} 으로 치환되는 값이다.
    # **강제되지 않는다** -- `prompts/graph_design.md` 자신이 그렇게 적었다:
    # "이 예산 제약은 현재 노드별 비용 표가 없어 검증기가 자동으로 강제하지
    # 않는다 -- 비용 표가 추가되기 전까지는 참고용 상한이다." 이름에 `_hint`
    # 를 단 이유가 그것이다: `budget` 이라고만 부르면 다음 사람이 이 값을
    # `validate_topology(budget=...)` 로 흘려보내고, 그러면 node_costs 가
    # 없으므로 fail-closed 규칙이 **모든 설계를 거부**한다.
    # 기본값 1000 은 근거가 없다 -- 기존 테스트가 쓰는 값과 같게 두어 배선이
    # 동작 차이를 만들지 않게 한 것뿐이다. 근거 있는 값은 노드별 비용 표가
    # 생겨야 나온다.
    graph_design_budget_hint: int = Field(
        default=1000,
        gt=0,
        description="설계 프롬프트에 박히는 참고용 노드 비용 상한. 검증기가 강제하지 않는다.",
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `HOME=/tmp/neos-test-home .venv/bin/pytest tests/config/test_workflow_graph_design_config.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Run the config suite for regressions**

Run: `HOME=/tmp/neos-test-home .venv/bin/pytest tests/config -q`
Expected: 기존 전부 PASS. `StrictConfigModel`이라 YAML에 없는 새 키는 기본값으로 채워진다.

- [ ] **Step 6: Commit**

```bash
git add neos/config/schema.py tests/config/test_workflow_graph_design_config.py
git commit -m "feat(workflow): add graph design model and budget hint settings

The budget field carries a name that tells the truth. The prompt itself
admits the constraint is advisory -- there is no node cost table, so
validate_topology never enforces it. Calling the setting `budget` would
invite the next reader to pass it to validate_topology(budget=...), and
without node_costs that fail-closed rule rejects every design."
```

---

## Task 2: 토폴로지 해시를 공용으로 (G2-e 절반)

**Files:**
- Modify: `neos/workflow/graph_design_ledger.py:60-63, 206, 213-235`
- Test: `tests/workflow/test_graph_design_ledger.py` (기존 파일에 추가)

**Interfaces:**
- Consumes: 없음
- Produces: `neos.workflow.graph_design_ledger.topology_hash(topology: GraphTopology) -> str` — 공개 함수. Task 3이 정적 그래프에 이것을 쓴다.

- [ ] **Step 1: Write the failing test**

`tests/workflow/test_graph_design_ledger.py` 끝에 추가:

```python
def test_topology_hash_is_public_so_static_and_designed_runs_share_one_formula() -> None:
    """설계된 run 과 정적 run 이 **같은 산식**으로 해시를 계산해야 조인이
    성립한다. 산식이 둘로 갈리면 조인은 조용히 깨진다 -- 해시는 다르기만
    하면 되므로 아무도 눈치채지 못한다."""

    from neos.workflow.graph_design_ledger import topology_hash

    topology = GraphTopology(
        nodes=("response_generator",),
        edges=(("__start__", "response_generator"), ("response_generator", "__end__")),
    )
    assert topology_hash(topology) == topology_hash(topology)
    assert len(topology_hash(topology)) == 16


def test_topology_hash_ignores_the_order_nodes_and_edges_arrived_in() -> None:
    """모델이 같은 그래프를 두 번 제안해도 JSON 순서는 그때그때 다르다.
    논리적으로 같은 설계가 다른 해시를 받으면 비교 자체가 무의미해진다."""

    from neos.workflow.graph_design_ledger import topology_hash

    forward = GraphTopology(
        nodes=("a", "b"),
        edges=(("__start__", "a"), ("a", "b"), ("b", "__end__")),
    )
    shuffled = GraphTopology(
        nodes=("b", "a"),
        edges=(("b", "__end__"), ("__start__", "a"), ("a", "b")),
    )
    assert topology_hash(forward) == topology_hash(shuffled)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/test_graph_design_ledger.py -k topology_hash -v`
Expected: FAIL — `ImportError: cannot import name 'topology_hash'`

- [ ] **Step 3: Write minimal implementation**

`neos/workflow/graph_design_ledger.py`에서 `_topology_hash`를 `topology_hash`로 개명하고 docstring 앞에 한 문단을 추가한다. 호출부(206줄 `"topology_hash": _topology_hash(topology)`)도 함께 고친다.

```python
def topology_hash(topology: GraphTopology) -> str:
    """토폴로지의 **논리적** 정체성을 나타내는 안정적 해시.

    **공개 함수인 이유:** 설계된 run 과 정적 run 을 이 해시로 조인한다
    (§14.3 G2-e). 정적 경로가 자기 산식을 따로 두면 두 값은 다르기만 하고
    아무도 그것이 틀렸다는 것을 알 수 없다 -- 해시의 실패는 조용하다.
    그래서 산식을 하나로 두고 양쪽이 이 함수를 부른다.

    노드가 나열된 순서, 엣지가 나열된 순서는 우연이다 -- 설계 서브에이전트가
    같은 그래프를 두 번 제안해도 모델이 그때그때 다른 순서로 JSON 을 낼 수
    있다. 튜플이 도착한 순서 그대로 해시하면 논리적으로 동일한 두 설계가
    다른 해시를 받아, 스펙 §7-5 가 원하는 "토폴로지 해시로 설계된 run 과
    정적 run 을 비교" 가 무의미해진다. 그래서 정렬된 노드 집합과 정렬된 엣지
    집합 위에서 계산한다.

    `loop_bounds` 도 포함한다 -- 노드·엣지 집합이 완전히 같아도 반복 상한이
    다르면 실행 시 실제로 다른 그래프다(같은 사이클이 3회로 도는 설계와 5회로
    도는 설계는 도달 가능한 상태 공간이 다르다). 그래서 이 필드도 논리적
    정체성의 일부로 본다.
    """

    canonical = {
        "nodes": sorted(topology.nodes),
        "edges": sorted(topology.edges),
        "loop_bounds": sorted(topology.loop_bounds.items()),
    }
    encoded = json.dumps(canonical, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:_TOPOLOGY_HASH_HEX_LENGTH]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/test_graph_design_ledger.py -q`
Expected: PASS 전부 (기존 + 신규 2건). 개명이 놓친 호출부가 있으면 `NameError`로 드러난다.

- [ ] **Step 5: Commit**

```bash
git add neos/workflow/graph_design_ledger.py tests/workflow/test_graph_design_ledger.py
git commit -m "refactor(workflow): make topology_hash public for the static join

G2-e needs the static path to carry a hash comparable to a designed
run's. Two formulas would fail silently -- hashes only have to differ,
so nobody would notice the join was broken."
```

---

## Task 3: `ExecutionGraph`와 정적 해석 (G2-c 절반 · G2-e 나머지)

**Files:**
- Create: `neos/workflow/execution_graph.py`
- Create: `tests/workflow/test_execution_graph.py`

**Interfaces:**
- Consumes: `topology_hash` (Task 2)
- Produces:
  - `ExecutionGraph(compiled: Any, nodes: tuple[str, ...], topology_hash: str, source: Literal["static", "designed"])` — frozen dataclass
  - `current_static_flags() -> dict[str, bool]` — 실행 시점 `settings`를 `topology_export`의 플래그 키로 옮긴다
  - `static_execution_graph(compiled: Any, flags: Mapping[str, bool]) -> ExecutionGraph`

- [ ] **Step 1: Write the failing test**

`tests/workflow/test_execution_graph.py` 생성:

```python
"""`ExecutionGraph` -- 이번 호출이 실제로 쓰는 그래프를 값 하나로 들고 다닌다.

`MultiAgentWorkflow` 는 모듈 레벨 싱글턴이고(`graph.py:3398`) 요청들이
공유한다. 그래서 이 값은 **인스턴스 속성이 아니라 호출 스코프**로만 흐른다
(`graph.py:376-383` 의 요구).
"""

import dataclasses

import pytest

from neos.workflow.execution_graph import (
    ExecutionGraph,
    current_static_flags,
    static_execution_graph,
)
from neos.workflow.topology_export import _FLAG_ATTR_TO_KEY


def test_execution_graph_is_frozen_so_a_request_cannot_mutate_anothers_view() -> None:
    graph = ExecutionGraph(
        compiled=object(), nodes=("a",), topology_hash="deadbeefdeadbeef", source="static"
    )
    assert dataclasses.is_dataclass(graph)
    with pytest.raises(dataclasses.FrozenInstanceError):
        graph.source = "designed"  # type: ignore[misc]


def test_current_static_flags_covers_every_flag_the_extractor_knows() -> None:
    """`static_topology` 는 알 수 없는 키가 오면 즉시 실패하고, **빠진** 키는
    기본값('전부 켬')으로 조용히 채운다. 후자가 위험하다 -- 실제로 꺼진
    기능이 켜진 것으로 계산되면 해시가 그 run 의 그래프를 서술하지 않는다.
    그래서 매핑 전체를 덮는지 길이로 단언한다."""

    flags = current_static_flags()
    assert set(flags) == set(_FLAG_ATTR_TO_KEY.values())
    assert len(flags) == 5


def test_static_execution_graph_reports_static_source_and_a_stable_hash() -> None:
    compiled = object()
    flags = dict.fromkeys(_FLAG_ATTR_TO_KEY.values(), True)

    first = static_execution_graph(compiled=compiled, flags=flags)
    second = static_execution_graph(compiled=compiled, flags=flags)

    assert first.source == "static"
    assert first.compiled is compiled
    assert first.topology_hash == second.topology_hash
    assert len(first.topology_hash) == 16
    # 정적 그래프의 노드는 실제 배선에서 나온다 -- 손으로 나열한 목록이 아니다.
    assert "response_generator" in first.nodes


def test_a_disabled_flag_changes_the_static_hash() -> None:
    """플래그가 그래프를 바꾸면 해시도 바뀌어야 한다. 안 바뀌면 서로 다른
    배포의 run 이 같은 해시로 조인돼 비교가 거짓이 된다."""

    all_on = dict.fromkeys(_FLAG_ATTR_TO_KEY.values(), True)
    recursive_off = {**all_on, "recursive": False}

    assert (
        static_execution_graph(compiled=object(), flags=all_on).topology_hash
        != static_execution_graph(compiled=object(), flags=recursive_off).topology_hash
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/test_execution_graph.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'neos.workflow.execution_graph'`

- [ ] **Step 3: Write minimal implementation**

`neos/workflow/execution_graph.py` 생성:

```python
"""이번 호출이 실제로 쓰는 그래프를 값 하나로 묶는다.

`execute_workflow` 가 그래프를 `self.graph` 에서 읽던 것을 이 값으로
바꾸는 이유는 `graph.py:376-383` 이 이미 적어 뒀다: `MultiAgentWorkflow` 는
오래 살고 요청들이 공유하는 객체라, 질의 하나에 종속된 값을 인스턴스
속성에 얹으면 동시 요청 두 개가 서로의 그래프를 실행한다.

`graph.py` 를 임포트하지 않는다 -- `topology_export` 만 쓴다. 그래야 이
모듈의 단위 테스트가 `MultiAgentWorkflow` 인스턴스 없이 돈다.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Literal

from neos.config.settings import settings
from neos.workflow.graph_design_ledger import topology_hash
from neos.workflow.topology_export import _FLAG_ATTR_TO_KEY, static_topology


@dataclass(frozen=True, slots=True)
class ExecutionGraph:
    """이번 호출이 실행할 그래프와, 그것을 서술하는 데 필요한 전부.

    `nodes` 가 진행 추적의 유일한 근거다(G2-b) -- 손으로 나열한 목록을
    쓰지 않는 이유는 그 목록이 이 그래프를 서술한다는 보장이 없기 때문이다.
    `source` 를 싣는 이유는 로그가 "이 run 이 설계된 것인가" 를 추측하지
    않게 하기 위해서다.
    """

    compiled: Any
    nodes: tuple[str, ...]
    topology_hash: str
    source: Literal["static", "designed"]


def current_static_flags() -> dict[str, bool]:
    """실행 시점 `settings` 를 `topology_export` 의 플래그 키로 옮긴다.

    매핑을 손으로 다시 쓰지 않고 `_FLAG_ATTR_TO_KEY` 를 재사용한다 -- 키가
    하나라도 빠지면 `static_topology` 가 그 자리를 기본값('켬')으로 조용히
    채우고, 실제로 꺼진 기능이 켜진 것으로 계산된 해시가 나온다.
    """

    return {
        key: bool(getattr(settings, attr))
        for attr, key in _FLAG_ATTR_TO_KEY.items()
    }


@lru_cache(maxsize=32)
def _static_topology_facts(flags_items: tuple[tuple[str, bool], ...]) -> tuple[tuple[str, ...], str]:
    """`static_topology` 는 `inspect.getsource` + `ast.parse` 를 돈다 --
    요청마다 하면 안 된다. 플래그 조합은 5비트라 상한이 32개이고, 배포 중
    플래그가 바뀌지 않으므로 실질 1회다. `lru_cache` 를 쓰려고 인자를
    해시 가능한 튜플로 받는다."""

    topology = static_topology(flags=dict(flags_items))
    return topology.nodes, topology_hash(topology)


def static_execution_graph(
    *, compiled: Any, flags: Mapping[str, bool]
) -> ExecutionGraph:
    """정적 그래프를 `ExecutionGraph` 로 감싼다.

    `flags` 를 명시적으로 받는 이유: `static_topology()` 의 기본값은 "전부
    켬" 이고 그것은 **회귀 가드의 의도**("배포 설정과 무관하게 항상 같은
    토폴로지를 검증한다")에 맞춰진 것이다. G2-e 의 의도는 정반대다 -- 그
    run 이 **실제로 쓴** 그래프를 식별해야 조인이 성립한다. 같은 함수를
    다른 의도로 쓰므로 인자를 생략하지 않는다.
    """

    nodes, digest = _static_topology_facts(tuple(sorted(flags.items())))
    return ExecutionGraph(
        compiled=compiled, nodes=nodes, topology_hash=digest, source="static"
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/test_execution_graph.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add neos/workflow/execution_graph.py tests/workflow/test_execution_graph.py
git commit -m "feat(workflow): carry the executing graph as a call-scoped value

MultiAgentWorkflow is a module-level singleton shared across requests,
so a per-query graph cannot live on the instance. This value object is
what execute_workflow will hold instead of reading self.graph.

The flags argument is not optional on purpose. static_topology defaults
to all-on because that serves the regression guard -- always validate
the same topology regardless of deployment. G2-e wants the opposite: the
graph this run actually used."
```

---

## Task 4: `execute_workflow`가 `ExecutionGraph`를 쓴다 (G2-c 완성)

**Files:**
- Modify: `neos/workflow/graph.py` — import 추가, `_resolve_execution_graph` 신설, `execute_workflow:2487` / `:2542` / `:2663`
- Test: `tests/workflow/test_execution_graph.py` (추가)

**Interfaces:**
- Consumes: `ExecutionGraph`, `current_static_flags`, `static_execution_graph` (Task 3)
- Produces: `MultiAgentWorkflow._resolve_execution_graph(self, *, user_input: Dict[str, Any], use_checkpointer: bool, span: Any) -> ExecutionGraph` — Task 6이 이 안에 설계 분기를 넣는다.

- [ ] **Step 1: Write the failing test**

`tests/workflow/test_execution_graph.py` 끝에 추가:

```python
@pytest.mark.asyncio
async def test_resolve_execution_graph_returns_the_static_graph_when_design_is_off() -> None:
    """플래그가 꺼져 있으면(기본값) 설계 경로를 아예 타지 않고, 컴파일된
    정적 그래프가 그대로 실려 나온다."""

    from neos.config import settings as settings_module
    from neos.workflow.graph import MultiAgentWorkflow

    workflow = MultiAgentWorkflow()
    settings_module.settings.config.workflow.graph_design_enabled = False
    await workflow._ensure_graph_initialized(use_checkpointer=False)

    resolved = await workflow._resolve_execution_graph(
        user_input={"query": "안녕", "session_id": "s1"},
        use_checkpointer=False,
        span=None,
    )

    assert resolved.source == "static"
    assert resolved.compiled is workflow.graph
    assert resolved.nodes


@pytest.mark.asyncio
async def test_two_concurrent_resolutions_do_not_share_a_designed_slot() -> None:
    """G2-c 의 경합 가드. 두 호출이 각자의 값을 받고, 그 값이 인스턴스
    속성에 남지 않는다 -- 남으면 나중 요청이 앞 요청의 그래프를 덮어쓴다."""

    import asyncio as _asyncio

    from neos.config import settings as settings_module
    from neos.workflow.graph import MultiAgentWorkflow

    workflow = MultiAgentWorkflow()
    settings_module.settings.config.workflow.graph_design_enabled = False
    await workflow._ensure_graph_initialized(use_checkpointer=False)

    before = set(vars(workflow))
    first, second = await _asyncio.gather(
        workflow._resolve_execution_graph(
            user_input={"query": "q1", "session_id": "s1"},
            use_checkpointer=False,
            span=None,
        ),
        workflow._resolve_execution_graph(
            user_input={"query": "q2", "session_id": "s2"},
            use_checkpointer=False,
            span=None,
        ),
    )

    assert first.topology_hash == second.topology_hash  # 둘 다 정적이므로 같다
    # 핵심 단언: 해석이 인스턴스에 새 슬롯을 남기지 않았다.
    assert set(vars(workflow)) == before
```

- [ ] **Step 2: Run test to verify it fails**

Run: `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/test_execution_graph.py -k resolve -v`
Expected: FAIL — `AttributeError: 'MultiAgentWorkflow' object has no attribute '_resolve_execution_graph'`

- [ ] **Step 3: Write minimal implementation**

`neos/workflow/graph.py` 상단 import에 추가 (22줄 `from .topology import ...` 아래):

```python
from .execution_graph import ExecutionGraph, current_static_flags, static_execution_graph
```

`_ensure_graph_initialized` 메서드 **바로 아래**(`graph.py:748` 부근)에 추가:

```python
    async def _resolve_execution_graph(
        self,
        *,
        user_input: Dict[str, Any],
        use_checkpointer: bool,
        span: Any,
    ) -> ExecutionGraph:
        """이번 호출이 실행할 그래프를 정한다.

        반환값을 **호출 스코프로만** 흘린다 -- 인스턴스 속성에 얹으면
        동시 요청 두 개가 서로의 그래프를 실행한다(`__init__` 의 주석 참고).
        `self.graph` 와 `_graphs_by_checkpointer` 는 정적 그래프의 컴파일
        캐시로 그대로 남는다: 없애면 매 요청 재컴파일이다. 바뀌는 것은
        "`execute_workflow` 가 그것을 직접 읽는가" 뿐이다.

        지금은 정적 분기 하나뿐이고, 설계 분기는 다음 태스크가 넣는다.
        """

        await self._ensure_graph_initialized(use_checkpointer=use_checkpointer)
        return static_execution_graph(
            compiled=self.graph, flags=current_static_flags()
        )
```

`execute_workflow` 수정 — `graph.py:2486-2487`의

```python
            # Ensure graph is initialized only after cache paths miss.
            await self._ensure_graph_initialized(use_checkpointer=use_checkpointer)
```

를 다음으로 교체:

```python
            # 캐시가 전부 빗나간 뒤에만 그래프를 정한다. 반환값은 이 호출의
            # 로컬이며 인스턴스에 남지 않는다(G2-c).
            execution_graph = await self._resolve_execution_graph(
                user_input=user_input,
                use_checkpointer=use_checkpointer,
                span=span,
            )
```

`graph.py:2542`의 `self.graph.astream(...)`을 `execution_graph.compiled.astream(...)`으로,
`graph.py:2663`의 `await self.graph.aget_state(config)`을
`await execution_graph.compiled.aget_state(config)`로 바꾼다.

- [ ] **Step 4: Run tests to verify they pass**

Run: `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/test_execution_graph.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Run the two standing guards**

Run: `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/test_ephemeral_graph_execution.py tests/workflow/test_static_graph_contract.py -q`
Expected: PASS 전부. 특히 `test_the_compiled_static_graph_matches_its_pre_task_9_snapshot`이 통과해야 한다 — 실패하면 `_create_workflow_graph`를 건드린 것이므로 되돌린다.

- [ ] **Step 6: Commit**

```bash
git add neos/workflow/graph.py tests/workflow/test_execution_graph.py
git commit -m "refactor(workflow): resolve the execution graph per call

execute_workflow now receives the graph as a local value instead of
reading self.graph. The compile cache stays -- dropping it would
recompile the static graph on every request. What changes is only who
reads it, which is the precondition for a per-query designed graph."
```

---

## Task 5: 진행 추적을 실행에서 읽기 (G2-b)

**Files:**
- Modify: `neos/workflow/events.py:136-146` (`estimate_remaining_time`)
- Modify: `neos/workflow/graph.py:2517-2594` (astream 루프)
- Create: `tests/workflow/test_progress_tracking.py`

**Interfaces:**
- Consumes: `ExecutionGraph.nodes` (Task 3)
- Produces: `estimate_remaining_time(current_node: str, *, candidates: Sequence[str]) -> float`

- [ ] **Step 1: Write the failing test**

`tests/workflow/test_progress_tracking.py` 생성:

```python
"""진행 추적 -- 손으로 나열한 목록이 아니라 이번 실행에서 읽는다 (G2-b).

고치기 전의 결함 셋:
  1. `total_steps` 가 항상 19 -- 분기로 절반을 건너뛰어도 그대로였다
  2. `workflow_nodes.index(node) - 1` 로 "이전 노드" 를 추정 -- 실행 순서가
     아니라 **목록 순서**라, 건너뛴 노드의 종료 시각이 기록됐다
  3. `estimate_remaining_time` 이 목록에 없는 노드에 0.0 을 돌려줬다 --
     설계된 그래프의 모든 노드가 그러므로 사용자는 매 단계 "남은 시간 0초"
     를 봤다. 이벤트가 안 나가는 것보다 나쁘다: 틀린 것을 안다고 믿는다.
"""

from neos.workflow.events import estimate_remaining_time


def test_eta_counts_only_nodes_this_graph_can_still_reach() -> None:
    known = estimate_remaining_time("search_orchestrator", candidates=("fact_check",))
    wider = estimate_remaining_time(
        "search_orchestrator", candidates=("fact_check", "quality_validator")
    )
    assert known > 0
    assert wider > known


def test_eta_is_not_zero_for_a_node_absent_from_the_legacy_order() -> None:
    """설계된 그래프의 노드는 `WORKFLOW_NODE_ORDER` 에 없다. 옛 구현은
    `ValueError` 를 잡아 0.0 을 돌려줬다 -- '곧 끝남' 으로 읽히는 거짓말이다."""

    eta = estimate_remaining_time("a_designed_node", candidates=("fact_check",))
    assert eta > 0


def test_eta_of_an_empty_candidate_set_is_zero() -> None:
    """남은 노드가 정말 없으면 0 이 맞다 -- 위 두 테스트와 구별되는
    유일한 경우다."""

    assert estimate_remaining_time("fact_check", candidates=()) == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/test_progress_tracking.py -v`
Expected: FAIL — `TypeError: estimate_remaining_time() got an unexpected keyword argument 'candidates'`

- [ ] **Step 3: Write minimal implementation**

`neos/workflow/events.py:136-146`을 교체:

```python
def estimate_remaining_time(
    current_node: str, *, candidates: Sequence[str]
) -> float:
    """아직 도달하지 않은 노드들의 예상 소요 시간 합.

    `candidates` 를 호출자가 넘기는 이유: 옛 구현은 모듈 전역
    `WORKFLOW_NODE_ORDER` 를 기준으로 `index(current_node)` 이후를 셌다.
    그 목록에 없는 노드에는 `ValueError` 를 잡아 **0.0** 을 돌려줬는데,
    설계된 그래프(`graph_design_enabled`)의 노드는 전부 그 목록 밖이라
    사용자가 매 단계 "남은 시간 0초" 를 보게 된다. 이벤트가 아예 안 나가는
    것보다 나쁘다 -- 사용자는 틀린 값을 안다고 믿는다.

    ⚠️ **여전히 과대추정이다.** 조건부 분기로 실제로는 가지 않을 노드가
    `candidates` 에 섞여 있다. 정확히 하려면 런타임 상태에 의존하는 분기
    조건을 실행 전에 알아야 하는데 그럴 수 없다. 이 값은 **상한**이며,
    지금과 달라진 것은 (a) 이 그래프에 없는 노드가 빠지고 (b) 0 이라
    거짓말하지 않는다는 두 가지다.
    """

    return sum(get_estimated_duration(node) for node in candidates)
```

`events.py` 상단 import에 `Sequence`가 없으면 추가한다:

```python
from collections.abc import Sequence
```

`neos/workflow/graph.py:2517-2594`의 astream 블록을 교체:

```python
                # 진행 추적의 근거는 **이번 실행의 그래프**다. 손으로 나열한
                # 목록을 쓰지 않는 이유는 그 목록이 이 그래프를 서술한다는
                # 보장이 없기 때문이다 -- 조건부 분기로 절반을 건너뛰어도
                # `total_steps` 가 19 로 고정돼 있었고, 설계된 그래프의 노드는
                # 목록에 아예 없었다.
                from .events import (
                    get_node_label, estimate_remaining_time,
                    record_node_start, record_node_end,
                )

                trackable_nodes = set(execution_graph.nodes)
                # 분기 때문에 실제 실행 수는 이보다 적을 수 있다 -- 이름이
                # 그 사실을 말하게 둔다. `total_steps` 라고 부르면 다음 사람이
                # 이것을 정확한 총계로 읽는다.
                max_steps = len(execution_graph.nodes)

                current_step = 0
                final_state = None
                wf_id = user_input.get("session_id", "")
                # 실제로 직전 chunk 에서 본 노드들. 목록 인덱스로 추정하지
                # 않는다 -- 옛 코드는 `workflow_nodes.index(node) - 1` 로
                # "이전 노드" 를 골라, 이 run 이 건너뛴 노드의 종료 시각을
                # 기록했다.
                previous_nodes: list[str] = []
                seen_nodes: set[str] = set()

                async for chunk in self.graph_astream_source(execution_graph, initial_state, config):
                    chunk_nodes = [
                        name for name in chunk if name in trackable_nodes
                    ]

                    for finished in previous_nodes:
                        record_node_end(finished, wf_id)

                    for node_name in chunk_nodes:
                        current_step += 1
                        seen_nodes.add(node_name)

                        add_span_event(span, f"node_{node_name}_start", {
                            "step": current_step,
                            "max_steps": max_steps,
                        })

                        record_node_start(node_name, wf_id)

                        remaining = tuple(
                            node for node in execution_graph.nodes
                            if node not in seen_nodes
                        )
                        await event_handler.on_node_start(
                            node_name,
                            current_step,
                            max_steps,
                            step_name=get_node_label(node_name),
                            estimated_remaining_s=estimate_remaining_time(
                                node_name, candidates=remaining
                            ),
                        )

                        await event_handler.on_node_complete(
                            node_name, {"node": node_name, "step": current_step}
                        )
                        add_span_event(span, f"node_{node_name}_complete")

                    previous_nodes = chunk_nodes

                    for _node_name, state in chunk.items():
                        final_state = state

                # 마지막으로 **실제로 본** 노드의 종료를 기록한다. 옛 코드는
                # `workflow_nodes[-1]`(목록의 마지막)을 썼는데, 그 노드는 이
                # run 에서 돌지 않았을 수 있다.
                for finished in previous_nodes:
                    record_node_end(finished, wf_id)
```

그리고 `MultiAgentWorkflow`에 작은 헬퍼를 추가한다(`_resolve_execution_graph` 아래):

```python
    def graph_astream_source(
        self, execution_graph: ExecutionGraph, initial_state: AgentState, config: Dict[str, Any]
    ):
        """`astream` 을 한 겹 감싸 테스트가 chunk 시퀀스를 주입할 수 있게 한다.

        진행 추적의 계약(어느 노드가 몇 번째로 나오는가)을 검증하려면 실제
        LLM 없이 chunk 를 흘려보낼 수 있어야 한다. 프로덕션 동작은 그대로
        `compiled.astream` 이다.
        """

        return execution_graph.compiled.astream(initial_state, config)
```

- [ ] **Step 4: Add the skip-branch guard test**

`tests/workflow/test_progress_tracking.py`에 추가:

```python
import pytest


class _RecordingHandler:
    """`on_node_start` 로 들어온 (노드, step, max_steps) 를 그대로 모은다."""

    def __init__(self) -> None:
        self.starts: list[tuple[str, int, int]] = []

    async def on_workflow_start(self, workflow_input): ...
    async def on_node_start(
        self, node_name, step, total_steps, step_name=None, estimated_remaining_s=None
    ):
        self.starts.append((node_name, step, total_steps))
    async def on_node_progress(self, node_name, message, progress=0): ...
    async def on_node_complete(self, node_name, result): ...
    async def on_workflow_complete(self, result): ...
    async def on_workflow_error(self, error, node_name=None): ...
    async def on_approval_request(self, pending_approvals, session_id): ...


@pytest.mark.asyncio
async def test_node_end_is_recorded_for_the_node_actually_seen_not_the_list_neighbour(
    monkeypatch,
) -> None:
    """🔴 **분기가 노드를 건너뛰는 실행에서 검증해야 한다.** 모든 노드를
    순서대로 지나는 그래프에서는 옛 코드와 새 코드가 똑같이 통과한다 --
    §8.1.2 가 적은 그 교훈(`after <= before` 가 양쪽 0 이라 공허하게 성립해
    버그를 되살려도 통과했다)이 여기 그대로 걸린다."""

    from neos.config import settings as settings_module
    from neos.workflow import events as events_module
    from neos.workflow.graph import MultiAgentWorkflow

    ended: list[str] = []
    monkeypatch.setattr(
        events_module, "record_node_end",
        lambda node, wf_id="": ended.append(node),
    )

    workflow = MultiAgentWorkflow()
    settings_module.settings.config.workflow.graph_design_enabled = False
    await workflow._ensure_graph_initialized(use_checkpointer=False)

    # 실행이 `query_classifier` 다음에 `response_generator` 로 **건너뛴다**.
    # 옛 코드였다면 목록상 `response_generator` 의 앞 항목을 종료시켰다.
    async def _fake_stream(execution_graph, initial_state, config):
        for name in ("query_classifier", "response_generator"):
            yield {name: {"final_response": "ok"}}

    monkeypatch.setattr(workflow, "graph_astream_source", _fake_stream)

    handler = _RecordingHandler()
    await workflow.execute_workflow(
        {"query": "안녕", "session_id": "s-skip", "user_id": "u1", "bypass_cache": True},
        event_handler=handler,
        use_checkpointer=False,
    )

    assert [name for name, _step, _max in handler.starts] == [
        "query_classifier",
        "response_generator",
    ]
    assert ended == ["query_classifier", "response_generator"]
    # 건너뛴 노드는 하나도 종료 기록을 받지 않았다.
    assert "search_orchestrator" not in ended
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/test_progress_tracking.py -v`
Expected: PASS (4 passed)

- [ ] **Step 6: Run the workflow suite for regressions**

Run: `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow -q`
Expected: 기존 전부 PASS. `estimate_remaining_time` 호출자가 `graph.py` 하나뿐이므로 시그니처 변경이 다른 곳을 깨지 않는다.

- [ ] **Step 7: Commit**

```bash
git add neos/workflow/events.py neos/workflow/graph.py tests/workflow/test_progress_tracking.py
git commit -m "fix(workflow): derive progress and ETA from the running graph

Three lies fixed at once. total_steps was always 19 no matter how many
nodes a branch skipped. The 'previous node' was picked by list index, so
a skipped node got an end timestamp -- and that fed the ETA history.
And estimate_remaining_time returned 0.0 for any node outside its
hardcoded order, which is every node of a designed graph: the user would
have seen '0 seconds remaining' at every step.

The regression test skips a node on purpose. A run that visits every
node in order passes under the old code too."
```

---

## Task 6: 설계 경로 배선과 승인 게이트 (G2-a · G2-d)

**Files:**
- Modify: `neos/workflow/graph.py` (`_resolve_execution_graph`에 설계 분기 추가)
- Create: `tests/workflow/test_graph_design_wiring.py`

**Interfaces:**
- Consumes: `_resolve_execution_graph` (Task 4), `ExecutionGraph` (Task 3), `settings.config.workflow.graph_design_model` / `graph_design_budget_hint` (Task 1)
- Produces: `MultiAgentWorkflow._build_graph_designer(self) -> GraphDesigner`

- [ ] **Step 1: Write the failing test**

`tests/workflow/test_graph_design_wiring.py` 생성:

```python
"""설계 경로의 배선 -- 승인되면 그 그래프가 돌고, 아니면 정적으로 내려간다.

**요청은 절대 죽지 않는다.** 설계 실패 네 갈래(타임아웃·예외·위반·게이트
거부)가 전부 정적 폴백으로 끝난다. 조용히 끝나지도 않는다 --
`graph_design_ledger` 의 존재 이유가 "이벤트를 하나도 남기지 않는 폴백은
성공과 구별되지 않는다" 이기 때문이다.
"""

import pytest

from neos.config import settings as settings_module
from neos.workflow.graph import MultiAgentWorkflow
from neos.workflow.topology import GraphTopology


class _FakeDesigner:
    def __init__(self, result):
        self._result = result

    async def design(self, request):
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


_MINIMAL = GraphTopology(
    nodes=("response_generator",),
    edges=(("__start__", "response_generator"), ("response_generator", "__end__")),
    initial_writes=frozenset({"original_query"}),
)


async def _resolve_with(monkeypatch, designer, *, use_checkpointer=False):
    workflow = MultiAgentWorkflow()
    settings_module.settings.config.workflow.graph_design_enabled = True
    monkeypatch.setattr(workflow, "_build_graph_designer", lambda: designer)
    await workflow._ensure_graph_initialized(use_checkpointer=use_checkpointer)
    return await workflow._resolve_execution_graph(
        user_input={"query": "테스트 질의", "session_id": "s1"},
        use_checkpointer=use_checkpointer,
        span=None,
    )


@pytest.mark.asyncio
async def test_an_approved_design_is_what_actually_runs(monkeypatch) -> None:
    resolved = await _resolve_with(monkeypatch, _FakeDesigner(_MINIMAL))

    assert resolved.source == "designed"
    assert resolved.nodes == ("response_generator",)


@pytest.mark.asyncio
async def test_a_designer_exception_falls_back_to_static(monkeypatch) -> None:
    resolved = await _resolve_with(
        monkeypatch, _FakeDesigner(RuntimeError("model exploded"))
    )

    assert resolved.source == "static"


@pytest.mark.asyncio
async def test_a_timeout_falls_back_to_static(monkeypatch) -> None:
    resolved = await _resolve_with(monkeypatch, _FakeDesigner(TimeoutError()))

    assert resolved.source == "static"


@pytest.mark.asyncio
async def test_a_topology_that_violates_the_rules_falls_back_to_static(
    monkeypatch,
) -> None:
    """`response_generator` 가 없는 설계는 mandatory 규칙에 걸린다 -- 구조적
    으로 성립해도 사용자에게 돌려줄 응답을 만들지 않는 그래프다."""

    no_response = GraphTopology(
        nodes=("query_classifier",),
        edges=(("__start__", "query_classifier"), ("query_classifier", "__end__")),
        initial_writes=frozenset({"original_query"}),
    )
    resolved = await _resolve_with(monkeypatch, _FakeDesigner(no_response))

    assert resolved.source == "static"


@pytest.mark.asyncio
async def test_an_approval_gate_without_a_checkpointer_falls_back_instead_of_raising(
    monkeypatch,
) -> None:
    """`use_checkpointer=False`(챗 경로)인데 설계가 승인 게이트 노드를
    포함하면 `build_ephemeral_workflow` 가
    `EphemeralApprovalGateUnsupported` 를 던진다. 그것을 밖으로 흘리면
    설계 실패가 **사용자 요청을 죽인다** -- 기본 꺼짐인 기능이 할 일이
    아니다."""

    gated = GraphTopology(
        nodes=("execution_approval", "response_generator"),
        edges=(
            ("__start__", "execution_approval"),
            ("execution_approval", "response_generator"),
            ("response_generator", "__end__"),
        ),
        initial_writes=frozenset({"original_query"}),
    )
    resolved = await _resolve_with(monkeypatch, _FakeDesigner(gated))

    assert resolved.source == "static"


@pytest.mark.asyncio
async def test_the_flag_being_off_skips_the_designer_entirely(monkeypatch) -> None:
    called = False

    class _Tripwire:
        async def design(self, request):
            nonlocal called
            called = True
            return _MINIMAL

    workflow = MultiAgentWorkflow()
    settings_module.settings.config.workflow.graph_design_enabled = False
    monkeypatch.setattr(workflow, "_build_graph_designer", lambda: _Tripwire())
    await workflow._ensure_graph_initialized(use_checkpointer=False)

    resolved = await workflow._resolve_execution_graph(
        user_input={"query": "q", "session_id": "s1"},
        use_checkpointer=False,
        span=None,
    )

    assert resolved.source == "static"
    assert called is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/test_graph_design_wiring.py -v`
Expected: FAIL — `AttributeError: ... has no attribute '_build_graph_designer'`

- [ ] **Step 3: Write minimal implementation**

`neos/workflow/graph.py` 상단 import에 추가:

```python
from pathlib import Path

from neos.config.model_routing import resolve_model
from neos.utils.llm_factory import LLMFactory
from .graph_designer import DesignRequest
from .graph_design_ledger import design_graph_or_fallback, topology_hash
from .graph_designer_llm import LlmGraphDesigner
```

`_resolve_execution_graph` 아래에 추가:

```python
    def _build_graph_designer(self) -> Any:
        """설계 서브에이전트를 조립한다. 모델은 **여기서 한 번만** 해석한다.

        provider 를 모델명으로 추측하지 않는다 -- `"claude" in model` 같은
        판정은 카탈로그 조회로 대체된 안티패턴이다(라우팅 작업이 잡은
        프로덕션 버그 중 하나). 배포가 정한 프로바이더를 쓰고, 모델은
        `resolve_model` 이 `None` 을 역할 기본값으로 푼다.
        """

        provider = settings.LLM_PROVIDER
        model_name = resolve_model(
            config=settings.config.model_routing,
            provider=provider,
            role="everyday",
            feature_override=settings.config.workflow.graph_design_model,
        ).model
        llm = LLMFactory.create_llm(provider=provider, model=model_name)
        prompt_path = Path(__file__).parent / "prompts" / "graph_design.md"
        return LlmGraphDesigner(model=llm, prompt_path=prompt_path)
```

`_resolve_execution_graph`의 본문을 교체:

```python
    async def _resolve_execution_graph(
        self,
        *,
        user_input: Dict[str, Any],
        use_checkpointer: bool,
        span: Any,
    ) -> ExecutionGraph:
        """이번 호출이 실행할 그래프를 정한다.

        반환값을 **호출 스코프로만** 흘린다 -- 인스턴스 속성에 얹으면
        동시 요청 두 개가 서로의 그래프를 실행한다(`__init__` 의 주석 참고).

        분기는 셋뿐이고 **재설계 루프는 없다**: 위반이든 예외든 타임아웃이든
        반응은 항상 정적 폴백이다. 되돌려 다시 설계시키면 질의 하나가 LLM
        설계를 여러 번 태워 지연이 상한 없이 늘어난다
        (`graph_design_ledger.py:20-25`).
        """

        await self._ensure_graph_initialized(use_checkpointer=use_checkpointer)
        static = static_execution_graph(
            compiled=self.graph, flags=current_static_flags()
        )

        if not settings.config.workflow.graph_design_enabled:
            return static

        outcome = await design_graph_or_fallback(
            designer=self._build_graph_designer(),
            request=DesignRequest(
                query=user_input["query"],
                catalog=tuple(NODE_CONTRACTS.values()),
                budget=settings.config.workflow.graph_design_budget_hint,
            ),
            contracts=NODE_CONTRACTS,
            # `mandatory` 는 기본값(response_generator)을 쓴다 -- 덮으면
            # "응답 없는 설계를 허용한다" 는 뜻이고 챗 경로에서 그것은
            # 언제나 오답이다.
            # `budget`/`node_costs` 는 넘기지 않는다: node_costs 없이
            # budget 만 주면 fail-closed 규칙이 모든 노드를 "비용 미선언"
            # 위반으로 잡아 **모든 설계가 거부된다**.
        )
        self._record_design_events(outcome.events, span)

        if outcome.topology is None:
            return static

        # G2-d: 게이트할 노드를 토폴로지에서 계산한다. 하드코딩 목록을 다시
        # 쓰지 않는 이유는 G2-b 와 같다 -- 이번 그래프에 실제로 있는 노드만
        # 게이트한다.
        interrupt_before = sorted(
            set(outcome.topology.nodes) & _INTERRUPT_GATED_NODES
        )
        checkpointer = await get_checkpointer() if use_checkpointer else None

        try:
            compiled = build_ephemeral_workflow(
                self,
                outcome.topology,
                checkpointer=checkpointer,
                interrupt_before=interrupt_before,
            )
        except EphemeralApprovalGateUnsupported as exc:
            # `design_graph_or_fallback` 은 검증까지만 하고 컴파일은 여기서
            # 한다 -- 그래서 이 실패는 그 함수의 이벤트 4종에 잡히지 않는다.
            # 밖으로 흘리면 설계 실패가 사용자 요청을 죽이고, 조용히 삼키면
            # "모든 실패가 성공처럼 보였다" 를 되풀이한다. 기존 kind 를
            # 사유로 구분해 재사용한다(새 kind 는 FE 라벨 부채를 만든다).
            self._record_design_events(
                (
                    LedgerEvent(
                        kind="graph_design_fallback",
                        payload={"reason": f"ephemeral_approval_gate_unsupported: {exc}"},
                    ),
                ),
                span,
            )
            return static

        return ExecutionGraph(
            compiled=compiled,
            nodes=outcome.topology.nodes,
            topology_hash=topology_hash(outcome.topology),
            source="designed",
        )
```

`LedgerEvent` import를 추가한다:

```python
from .graph_design_ledger import LedgerEvent, design_graph_or_fallback, topology_hash
```

`_record_design_events`는 Task 7이 구현한다. 이 태스크에서는 통과만 시키는 최소 구현을 넣는다:

```python
    def _record_design_events(self, events: Sequence[Any], span: Any) -> None:
        """설계 이벤트를 기록한다. Task 7 이 로그·span 목적지를 채운다."""

        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/test_graph_design_wiring.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Run the standing guards again**

Run: `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow -q`
Expected: PASS 전부. 스냅샷 해시 가드가 특히 중요하다.

- [ ] **Step 6: Commit**

```bash
git add neos/workflow/graph.py tests/workflow/test_graph_design_wiring.py
git commit -m "feat(workflow): give the graph designer a production caller

Turning on workflow.graph_design_enabled now actually designs and runs a
per-query graph. Every failure path -- timeout, exception, rule
violation, approval gate without a checkpointer -- falls back to the
static graph. A feature that is off by default has no business killing a
user request when it misbehaves.

The gate rejection happens outside design_graph_or_fallback, which only
designs and validates; compiling is the caller's job. It reuses the
existing fallback kind with a reason rather than minting a new one."
```

---

## Task 7: 이벤트를 로그와 span에 기록한다

**Files:**
- Modify: `neos/workflow/graph.py` (`_record_design_events` 구현)
- Modify: `tests/workflow/test_graph_design_wiring.py` (추가)

**Interfaces:**
- Consumes: `LedgerEvent` (기존), `add_span_event` (기존 import)
- Produces: 없음 (마지막 태스크)

- [ ] **Step 1: Write the failing test**

`tests/workflow/test_graph_design_wiring.py` 끝에 추가:

```python
class _SpanSpy:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []


@pytest.mark.asyncio
async def test_a_fallback_records_its_reason(monkeypatch) -> None:
    """"이벤트를 하나도 남기지 않는 폴백은 성공과 구별되지 않는다" --
    `graph_design_ledger` 모듈의 존재 이유다. 목적지를 붙이는 것이 배선의
    절반이다."""

    from neos.workflow import graph as graph_module

    recorded: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        graph_module,
        "add_span_event",
        lambda span, name, attrs=None: recorded.append((name, dict(attrs or {}))),
    )

    await _resolve_with(monkeypatch, _FakeDesigner(RuntimeError("model exploded")))

    kinds = [name for name, _attrs in recorded]
    assert "graph_design_requested" in kinds
    assert "graph_design_fallback" in kinds
    reason = next(
        attrs["reason"] for name, attrs in recorded if name == "graph_design_fallback"
    )
    assert "RuntimeError" in reason


@pytest.mark.asyncio
async def test_the_query_is_truncated_before_it_reaches_logs_and_traces(
    monkeypatch,
) -> None:
    """`graph_design_requested.payload["query"]` 는 질의 **전문**이다
    (`graph_design_ledger.py:143`). 그대로 흘리면 사용자 질의가 로그와
    트레이스에 통째로 남는다. 이 저장소에는 이미 자르는 규율이 있다 --
    `graph.py:2444` 의 `query_preview` 가 100자다."""

    from neos.workflow import graph as graph_module

    recorded: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        graph_module,
        "add_span_event",
        lambda span, name, attrs=None: recorded.append((name, dict(attrs or {}))),
    )

    long_query = "가" * 500
    workflow = MultiAgentWorkflow()
    settings_module.settings.config.workflow.graph_design_enabled = True
    monkeypatch.setattr(workflow, "_build_graph_designer", lambda: _FakeDesigner(_MINIMAL))
    await workflow._ensure_graph_initialized(use_checkpointer=False)
    await workflow._resolve_execution_graph(
        user_input={"query": long_query, "session_id": "s1"},
        use_checkpointer=False,
        span=None,
    )

    requested = next(
        attrs for name, attrs in recorded if name == "graph_design_requested"
    )
    assert "query" not in requested
    assert len(requested["query_preview"]) <= 100
```

- [ ] **Step 2: Run test to verify it fails**

Run: `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/test_graph_design_wiring.py -k "records_its_reason or truncated" -v`
Expected: FAIL — `_record_design_events`가 아무것도 하지 않으므로 `recorded`가 비어 `StopIteration`/`AssertionError`

- [ ] **Step 3: Write minimal implementation**

`graph.py`의 상수 자리(`_INTERRUPT_GATED_NODES` 근처)에 추가:

```python
# 설계 이벤트에 싣는 질의 미리보기 길이. `execute_workflow` 의
# `query_preview`(`add_span_event(span, "workflow_started", ...)`)와 같은 값을
# 쓴다 -- 같은 span 에 두 길이의 미리보기가 섞이면 읽는 사람이 어느 쪽이
# 잘린 것인지 모른다.
_DESIGN_QUERY_PREVIEW_CHARS = 100
```

`_record_design_events`를 교체:

```python
    def _record_design_events(self, events: Sequence[Any], span: Any) -> None:
        """설계 이벤트를 구조적 로그와 OTel span 두 곳에 남긴다.

        목적지가 이 둘인 이유: `execute_workflow` 가 이미
        `trace_workflow_node` span 을 쥐고 있어 새 배관이 필요 없고,
        마이그레이션이 0건이라 SCHEMA1(마이그레이션 44개 중 7개가 신선한
        DB 에서 실패한다)을 악화시키지 않는다.

        payload 는 `design_graph_or_fallback` 이 정한다 -- 이벤트의 내용을
        정하는 자리와 목적지를 정하는 자리를 섞지 않는다. **다만 질의만
        예외다**: `graph_design_requested.payload["query"]` 는 전문이라
        그대로 흘리면 사용자 질의가 로그에 통째로 남는다. 축약은 원본을
        고치는 것이 아니라 *기록하는 쪽* 의 책임이다.
        """

        for event in events:
            payload = dict(event.payload)
            query = payload.pop("query", None)
            if query is not None:
                payload["query_preview"] = str(query)[:_DESIGN_QUERY_PREVIEW_CHARS]

            add_span_event(span, event.kind, payload)
            logger.info("[GraphDesign] %s %s", event.kind, payload)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/test_graph_design_wiring.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: Run the full workflow suite**

Run: `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow -q`
Expected: PASS 전부.

- [ ] **Step 6: Run the whole suite against the baseline**

Run: `.venv/bin/python -m pytest -q 2>&1 | tail -5`
Expected: 2,938 + 신규 (약 20건) passed / 0 failed. 실패가 하나라도 있으면 실제 회귀로 취급한다. 회귀 비교 시 `grep '^FAILED tests/'`로 거른다 — `'^FAILED'`만 쓰면 진행 표시(`FAILED  [ 7%]`)까지 걸린다.

- [ ] **Step 7: Commit**

```bash
git add neos/workflow/graph.py tests/workflow/test_graph_design_wiring.py
git commit -m "feat(workflow): record graph design events to logs and the span

A fallback that leaves no event is indistinguishable from success --
that sentence is why graph_design_ledger exists, and until now its four
events were returned to nobody.

The query is truncated at the recording site, not in the ledger. The
ledger decides what an event contains; the caller decides where it goes
and is responsible for not spilling a user's full query into traces."
```

---

## Self-Review

**1. Spec coverage**

| 스펙 절 | 태스크 |
|---|---|
| §3.1 `ExecutionGraph` (G2-c) | Task 3·4 |
| §3.2 `_resolve_execution_graph` (G2-a) | Task 6 |
| §3.3 승인 게이트 · 다섯 번째 실패 경로 (G2-d) | Task 6 |
| §3.4 진행 추적 (G2-b) | Task 5 |
| §3.5 정적 토폴로지 해시 (G2-e) | Task 2·3 |
| §3.6 설정 두 칸 | Task 1 |
| §4 이벤트와 관측 | Task 7 |
| §5 에러 처리 (`CancelledError` 전파) | Global Constraints + Task 6(기존 `design_graph_or_fallback`이 이미 지킨다) |
| §6 테스트 6종 | Task 3(4·5) · Task 4(4) · Task 5(1·6) · Task 6(2·3) · Task 7 |
| §7 하지 않는 것 | Global Constraints |
| §8 미결 (G2-f) | 계획 밖 — 스펙 §8이 기록만 한다 |

빠진 것 없음.

**2. Placeholder scan**

"TBD"·"TODO"·"적절히 처리"·"Task N과 비슷하게" 없음. Task 6의 `_record_design_events` 최소 구현은 placeholder가 아니라 **의도적 스텁**이며 Task 7이 같은 계획 안에서 채운다 — 그 사실을 코드 주석과 Task 6 Step 3에 명시했다.

**3. Type consistency**

- `topology_hash(topology: GraphTopology) -> str` — Task 2 정의, Task 3·6 사용. 일치.
- `ExecutionGraph(compiled, nodes, topology_hash, source)` — Task 3 정의, Task 4·5·6 사용. 필드명 일치.
- `current_static_flags() -> dict[str, bool]` / `static_execution_graph(*, compiled, flags)` — Task 3 정의, Task 4·6 사용. 키워드 전용 인자 일치.
- `estimate_remaining_time(current_node, *, candidates)` — Task 5 정의·사용. 일치.
- `_resolve_execution_graph(*, user_input, use_checkpointer, span)` — Task 4 정의, Task 6 교체, 테스트 전부 같은 시그니처로 호출. 일치.
- `_build_graph_designer(self)` — Task 6 정의, 같은 태스크의 테스트가 monkeypatch. 일치.
- `_record_design_events(self, events, span)` — Task 6 스텁, Task 7 구현. 시그니처 동일.
