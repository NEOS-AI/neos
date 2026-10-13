# W1 Plan 1 — 안전망 · 배선 표 · 노드 갱신 정규화 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** LangGraph 를 걷어내기 전에, 지금 동작을 계약 테스트로 고정하고, 채팅 그래프의 배선을 데이터 하나(배선 표)로 옮기고, 노드가 전체 상태를 돌려줘 누적 필드가 불어나는 결함(R5)을 한 지점에서 닫는다.

**Architecture:** `neos/workflow/wiring.py` 가 노드·엣지·조건 분기를 플래그 조건과 함께 담는다. 정적 토폴로지(`topology_export.static_topology`)와 LangGraph 조립(`neos/workflow/runtime/langgraph_adapter.py`)이 모두 이 표를 읽고, AST 추출기는 지운다. 노드 경계에는 `neos/workflow/runtime/node_updates.py` 가 서서 노드 반환값을 "이번 노드의 갱신"으로 정규화하고 계약의 `writes` 밖 키를 정책에 따라 보고·버림·거절한다. 기본 런타임은 여전히 LangGraph 다.

**Tech Stack:** Python 3.12 · LangGraph 1.2 (아직 유지) · pytest(asyncio) · pydantic 설정 스키마 · prometheus_client

**Spec:** `docs/superpowers/specs/2026-10-13-langgraph-removal-native-runner-design.md` — 이 계획은 spec §6.1 의 **단계 1·2** 다. 단계 3·4 는 Plan 2, 단계 5~7 은 Plan 3 이다.

## Global Constraints

- 커밋 메시지에 `Co-Authored-By` 트레일러를 넣지 않는다(저장소 규칙)
- 문서·주석은 한국어. 기존 영문 문서는 그 언어를 따른다
- 기본 동작을 바꾸지 않는다 — 기본 런타임은 LangGraph, 새 설정의 스키마 기본값은 지금 동작과 같다
- `tests/workflow/test_ephemeral_graph_execution.py::test_the_compiled_static_graph_matches_its_pre_task_9_snapshot` 의 `_STATIC_GRAPH_SNAPSHOT_SHA256` 를 **바꾸지 않는다** — 바뀌면 배선이 바뀐 것이다
- `tests/standing` · `tests/jev` · `tests/api/channels` 는 이 계획에서 **한 줄도** 바꾸지 않는다
- 새 의존성 없음
- 테스트는 저장소 루트에서 `python -m pytest …` 로 돈다(`.venv`). DB 가 필요 없는 테스트는 `pytestmark = pytest.mark.no_db`
- 머지 전: DB 를 띄운 전체 스위트 + CI 의 Ruff 명령 그대로(`uv run --frozen ruff check <backend-ci.yml 의 경로 목록>`)
- 테스트 이름은 바꾸기 전후를 `python -m pytest --collect-only -qq tests > /tmp/names_<before|after>.txt` 로 비교하고, 사라진 이름은 이유와 함께 커밋 메시지에 적는다

## Review Focus

1. 노드가 누적 필드를 **재정렬·중복 제거한** 전체 리스트로 돌려준다(접두가 이전 값과 다르다) → 지금처럼 리스트 전체가 새 항목으로 붙는다(나빠지지 않는다). Task 6 의 `test_a_reordered_list_is_treated_as_new_items` 가 고정한다
2. 노드가 입력 상태를 **제자리에서 고친다**(`state["execution_steps"].append(...)`) → 그 변경이 갱신에 들어간다. Task 6 의 `test_in_place_mutation_becomes_an_update` 가 고정한다
3. 노드가 `None` 을 돌려준다 → 빈 갱신 `{}`. Task 6 의 `test_none_is_an_empty_update` 가 고정한다
4. 같은 분기 라벨에 켜진 경로가 둘인 플래그 조합 → 조용히 덮지 않고 `WiringError`. Task 2 의 `test_two_active_routes_for_one_label_are_rejected` 가 고정한다
5. 비교가 예외를 던지는 값(numpy 배열의 `==`)을 노드가 돌려준다 → 크래시하지 않고 "바뀜"으로 본다. Task 6 의 `test_values_whose_equality_raises_count_as_changed` 가 고정한다

## 이 계획에서 정한 spec 세부 (spec 과 다른 점)

- spec §4.1 은 "플래그별 대상은 같은 source 의 `Branch` 를 둘 둔다" 고 적었다. 셀렉터 분기의 라벨 아홉이 플래그 여섯에 따로 걸려 조합이 폭발하므로, **경로(`Route`)마다 `requires`** 를 둔다. "한 라벨에 켜진 경로는 하나" 는 `resolve_wiring` 이 강제한다. Task 2 에서 spec §4.1 문장을 고친다
- spec §4.1 은 `settings.SKILL_EXECUTION_ENABLED` 별칭을 지운다고 적었다. 여섯 배선 플래그가 모두 같은 별칭 지도(`settings.py` 의 `*_ENABLED`)로 읽히므로 하나만 지우면 비대칭이 된다. **별칭은 둔다.** Task 5 에서 spec 문장을 고친다
- spec §4.2 의 "그 밖에서는 버림" 은 Task 7 에서 켠다. Task 6 은 `report`(기록만) 로 착지한다 — 계약 목록을 고치기 전에 키를 버리면 동작이 바뀐다

---

## File Structure

| 파일 | 책임 | Task |
|---|---|---|
| `neos/workflow/distributed_graph.py` | 삭제 | 1 |
| `neos/workflow/checkpointers/` | 삭제 | 1 |
| `tests/workflow/test_import_boundaries.py` | Q·Jev·코딩·DA 가 채팅 그래프를 import 하지 않음 | 1 |
| `neos/workflow/wiring.py` | 배선 표 · `resolve_wiring` · `topology_of` · 플래그 지도 · 반복 상한 | 2 |
| `tests/workflow/test_wiring.py` | 표의 규칙과 AST 추출 결과와의 동등성 | 2, 5 |
| `tests/fixtures/static_topology_hashes.json` | 64개 플래그 조합의 토폴로지 해시(AST 시점에 캡처) | 2 |
| `tests/workflow/support/__init__.py`, `tests/workflow/support/stub_workflow.py` | 스텁 노드로 진짜 정적 그래프를 돌리는 하네스 | 3 |
| `tests/workflow/test_execute_workflow_contract.py` | `execute_workflow` 결과 계약 | 3 |
| `tests/workflow/test_langgraph_known_defects.py` | R1·R3·R4·R5 를 `xfail(strict=True)` 로 기록 | 3, 6 |
| `tests/workflow/test_approval_port_contract.py` | `RuntimeWorkflowApprovals` 의 지금 계약 | 4 |
| `neos/workflow/runtime/__init__.py`, `neos/workflow/runtime/langgraph_adapter.py` | 표 → `StateGraph` | 5 |
| `neos/workflow/topology_export.py` | 표에서 정적 토폴로지(AST 추출기 삭제) | 5 |
| `neos/workflow/graph.py` | `_create_workflow_graph` 가 어댑터 사용 · `_route_after_research_harness` · 설계 그래프 노드 감싸기 | 2, 5, 6 |
| `neos/workflow/execution_graph.py` | 플래그 지도 import 경로 | 5 |
| `neos/workflow/runtime/node_updates.py` | 노드 반환값 정규화 · `writes` 정책 | 6 |
| `tests/workflow/runtime/test_node_updates.py` | 정규화 규칙 | 6 |
| `neos/config/schema.py` | `WorkflowConfig.node_update_policy` | 6, 7 |
| `neos/observability/metrics.py` | `workflow_update_rejected_total` | 6 |
| `config/neos.development.yaml`, `tests/fixtures/config/test-session.yaml` | 정책 `raise` | 7 |
| `.github/workflows/backend-ci.yml`, `tests/config/test_test_environment_policy.py` | Ruff 대상에 새 경로 | 2 |

---

### Task 1: 죽은 코드 삭제와 import 가드

**Files:**
- Delete: `neos/workflow/distributed_graph.py`
- Delete: `neos/workflow/checkpointers/__init__.py`, `neos/workflow/checkpointers/hybrid_checkpointer.py`
- Modify: `neos/agents/autonomous_search_example.py` (주석 속 `distributed_graph` 언급 줄)
- Create: `tests/workflow/test_import_boundaries.py`

**Interfaces:**
- Consumes: 없음
- Produces: `_FORBIDDEN` 목록(`langgraph`, `neos.workflow.graph`, `neos.workflow.runtime`, `neos.workflow.wiring`) — Plan 2·3 이 같은 가드를 쓴다

- [ ] **Step 1: 지울 대상의 사용처가 없는지 확인한다**

Run:
```bash
grep -rn "distributed_graph\|workflow\.checkpointers\|from \.checkpointers\|HybridCheckpointer\|S3ClientFactory" neos tests --include='*.py'
```
Expected: `neos/agents/autonomous_search_example.py` 의 주석 줄과 지울 파일 자신만 나온다. 다른 사용처가 나오면 멈추고 보고한다.

- [ ] **Step 2: 가드 테스트를 쓴다**

`tests/workflow/test_import_boundaries.py`:
```python
"""채팅 그래프와 langgraph 를 import 하면 안 되는 패키지 (spec 2026-10-13 §5).

dots(트랙 Q)·Jev·코딩 루프·심층분석 루프는 채팅 워크플로 바깥에 있다. 이 경계가
지켜져야 런타임을 갈아도 그쪽이 영향을 받지 않는다. 런타임 import 가 아니라 소스를
AST 로 읽는다 -- 함수 안의 지연 import 도 잡기 위해서다.
"""

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.no_db

_ROOT = Path(__file__).resolve().parents[2]
_GUARDED = (
    "neos/coding",
    "neos/workflow/deep_analysis",
    "neos/standing",
    "neos/jev",
    "neos/subagent",
)
_FORBIDDEN = (
    "langgraph",
    "neos.workflow.graph",
    "neos.workflow.runtime",
    "neos.workflow.wiring",
)


def _imported_names(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            yield node.module
            for alias in node.names:
                yield f"{node.module}.{alias.name}"


def _is_forbidden(name: str) -> bool:
    return any(name == banned or name.startswith(banned + ".") for banned in _FORBIDDEN)


@pytest.mark.parametrize("package", _GUARDED)
def test_package_does_not_import_the_chat_graph(package: str) -> None:
    offenders = sorted(
        {
            f"{path.relative_to(_ROOT)}: {name}"
            for path in (_ROOT / package).rglob("*.py")
            for name in _imported_names(path)
            if _is_forbidden(name)
        }
    )
    assert not offenders, offenders


@pytest.mark.parametrize(
    "source",
    [
        "from neos.workflow.graph import multi_agent_workflow\n",
        "from neos.workflow import graph\n",
        "import langgraph.graph\n",
        "def f():\n    from neos.workflow.runtime.runner import WorkflowRunner\n",
    ],
)
def test_the_guard_sees_each_import_form(tmp_path: Path, source: str) -> None:
    """가드가 공허하지 않음을 보인다 -- 네 가지 import 모양을 다 잡아야 한다."""
    sample = tmp_path / "sample.py"
    sample.write_text(source, encoding="utf-8")
    assert any(_is_forbidden(name) for name in _imported_names(sample))


def test_every_guarded_package_exists() -> None:
    """경로가 옮겨지면 rglob 이 빈 목록을 돌려 가드가 조용히 꺼진다."""
    for package in _GUARDED:
        assert any((_ROOT / package).rglob("*.py")), package
```

- [ ] **Step 3: 가드를 돌린다**

Run: `python -m pytest tests/workflow/test_import_boundaries.py -v`
Expected: 전부 PASS(지금 경계는 이미 지켜진다 — 이 테스트는 회귀 가드다). FAIL 이면 위반 목록을 보고하고 멈춘다.

- [ ] **Step 4: 죽은 코드를 지운다**

```bash
git rm neos/workflow/distributed_graph.py neos/workflow/checkpointers/__init__.py neos/workflow/checkpointers/hybrid_checkpointer.py
```
`neos/agents/autonomous_search_example.py` 에서 `distributed_graph`·`distributed_workflow` 를 언급하는 주석 줄(현재 192·198·199 행 근처)을 지운다. 그 주석 블록이 그 두 이름만 설명한다면 블록째 지운다.

- [ ] **Step 5: 수집과 관련 테스트를 확인한다**

Run:
```bash
python -m pytest --collect-only -qq tests > /tmp/names_after_t1.txt; echo $?
python -m pytest tests/workflow/test_import_boundaries.py tests/test_checkpointer.py -q
```
Expected: 수집 종료 코드 0(삭제한 모듈을 import 하는 테스트가 없다), 테스트 PASS.

- [ ] **Step 6: 커밋**

```bash
git add -A neos/workflow neos/agents/autonomous_search_example.py tests/workflow/test_import_boundaries.py
git commit -m "chore(workflow): drop dead distributed graph and hybrid checkpointer; guard chat-graph imports

distributed_graph.py had no live caller and hybrid_checkpointer.py imported a
symbol langgraph no longer exports. The new guard pins that coding, deep
analysis, standing agents, Jev and the subagent runtime never import the
chat graph, langgraph, or the coming runtime package (spec 2026-10-13 §5)."
```

---

### Task 2: 배선 표와 토폴로지 동등성

**Files:**
- Create: `neos/workflow/wiring.py`
- Create: `tests/workflow/test_wiring.py`
- Create: `tests/fixtures/static_topology_hashes.json` (스크립트가 만든다)
- Modify: `neos/workflow/graph.py` (메서드 `_route_after_research_harness` 추가)
- Modify: `.github/workflows/backend-ci.yml`, `tests/config/test_test_environment_policy.py` (`_RUFF_KERNEL_DIRS`)
- Modify: `docs/superpowers/specs/2026-10-13-langgraph-removal-native-runner-design.md` §4.1 (경로별 `requires`)

**Interfaces:**
- Consumes: `neos.workflow.enums.WorkflowNode`, `WorkflowPathway`; `neos.workflow.topology.START`, `END`, `GRAPH_ENTRY_WRITES`, `GraphTopology`
- Produces:
  - `FLAG_ATTR_TO_KEY: dict[str, str]`, `DEFAULT_FLAGS: dict[str, bool]`, `LOOP_BOUNDS: dict[str, int]`
  - `NodeSpec(name: str, handler: str, requires: Requires = ())`
  - `Edge(source: str, target: str, requires: Requires = ())`
  - `Route(label: str, target: str, requires: Requires = ())`
  - `Branch(source: str, router: str, routes: tuple[Route, ...], requires: Requires = ())`
  - `Interrupt(node: str, requires: Requires = ())`
  - `Wiring(nodes, edges, branches, interrupt_before: tuple[str, ...])` + `Wiring.path_map(branch) -> dict[str, str]`
  - `WiringError(ValueError)`
  - `resolve_wiring(flags: Mapping[str, bool] | None = None) -> Wiring`
  - `topology_of(wiring: Wiring) -> GraphTopology`
  - `MultiAgentWorkflow._route_after_research_harness(state) -> str`

- [ ] **Step 1: 표의 규칙을 시험하는 테스트를 쓴다**

`tests/workflow/test_wiring.py`:
```python
"""배선 표 (spec 2026-10-13 §4.1).

표가 정적 그래프의 단일 원천이 된다. 이 파일은 (1) 표의 규칙과 (2) 표가 지금
`_create_workflow_graph` 의 배선과 같다는 것을 고정한다.
"""

import itertools
import json
from collections import Counter
from pathlib import Path

import pytest

from neos.workflow.enums import WorkflowNode as N
from neos.workflow.enums import WorkflowPathway as P
from neos.workflow.graph_design_ledger import topology_hash
from neos.workflow.topology import END, START
from neos.workflow.wiring import (
    DEFAULT_FLAGS,
    BRANCHES,
    Branch,
    Route,
    WiringError,
    resolve_wiring,
    topology_of,
)

pytestmark = pytest.mark.no_db

_HASHES = Path(__file__).resolve().parents[1] / "fixtures" / "static_topology_hashes.json"
_KEYS = sorted(DEFAULT_FLAGS)


def _all_flag_combinations():
    for bits in itertools.product([False, True], repeat=len(_KEYS)):
        yield dict(zip(_KEYS, bits))


def _flag_id(flags):
    return ",".join(f"{key}={int(flags[key])}" for key in _KEYS)


def test_unknown_flag_is_rejected() -> None:
    with pytest.raises(ValueError, match="알 수 없는 플래그"):
        resolve_wiring({"skill_execusion": True})


def test_start_edge_comes_first() -> None:
    """LangGraph 조립 순서를 고정한 기존 테스트가 첫 엣지가 START 에서 나가길 요구한다."""
    wiring = resolve_wiring()
    assert wiring.edges[0].source == START
    assert wiring.edges[0].target == N.REFINEMENT_CHECKER.value


def test_skill_execution_switches_the_selector_targets() -> None:
    off = resolve_wiring({"skill_execution": False})
    on = resolve_wiring({"skill_execution": True})
    sel = N.SKILL_TOOL_SELECTOR.value
    off_map = off.path_map(next(b for b in off.branches if b.source == sel))
    on_map = on.path_map(next(b for b in on.branches if b.source == sel))
    assert off_map[P.SKIP_ORCHESTRATORS.value] == N.DIRECT_RESPONSE.value
    assert on_map[P.SKIP_ORCHESTRATORS.value] == N.SKILL_EXECUTOR.value
    assert on_map[P.USE_ORCHESTRATORS.value] == N.SKILL_EXECUTOR.value


def test_interrupts_follow_the_approval_flag() -> None:
    assert resolve_wiring({"execution_approval": False}).interrupt_before == ()
    assert resolve_wiring({"execution_approval": True}).interrupt_before == (
        N.EXECUTION_APPROVAL.value,
        N.MISSION_APPROVAL.value,
    )


def test_two_active_routes_for_one_label_are_rejected(monkeypatch) -> None:
    """같은 라벨에 켜진 경로가 둘이면 어느 쪽이 이기는지 조용히 정하지 않는다."""
    import neos.workflow.wiring as wiring_module

    clash = Branch(
        source=N.REFINEMENT_CHECKER.value,
        router="_should_refine_or_continue",
        routes=(
            Route("skip_refinement", N.CONVERSATION_CTX_PROC.value),
            Route("skip_refinement", N.QUERY_CLS.value),
        ),
    )
    monkeypatch.setattr(wiring_module, "BRANCHES", (clash,) + tuple(BRANCHES[1:]))
    with pytest.raises(WiringError, match="skip_refinement"):
        resolve_wiring()


def test_a_dangling_target_is_rejected(monkeypatch) -> None:
    import neos.workflow.wiring as wiring_module

    dangling = Branch(
        source=N.REFINEMENT_CHECKER.value,
        router="_should_refine_or_continue",
        routes=(Route("skip_refinement", "no_such_node"),),
    )
    monkeypatch.setattr(wiring_module, "BRANCHES", (dangling,) + tuple(BRANCHES[1:]))
    with pytest.raises(WiringError, match="no_such_node"):
        resolve_wiring()


def test_every_handler_and_router_exists_on_the_workflow() -> None:
    from neos.workflow.graph import MultiAgentWorkflow

    wiring = resolve_wiring()
    for spec in wiring.nodes:
        assert callable(getattr(MultiAgentWorkflow, spec.handler, None)), spec.handler
    for branch in wiring.branches:
        assert callable(getattr(MultiAgentWorkflow, branch.router, None)), branch.router


@pytest.mark.parametrize("flags", list(_all_flag_combinations()), ids=_flag_id)
def test_the_table_hash_matches_the_captured_static_hash(flags) -> None:
    """AST 추출기가 살아 있을 때 캡처한 64개 해시. 추출기를 지운 뒤에도 남는 고정점이다."""
    captured = json.loads(_HASHES.read_text(encoding="utf-8"))
    assert topology_hash(topology_of(resolve_wiring(flags))) == captured[_flag_id(flags)]
```

이 Task 의 Step 5 에서 같은 파일 끝에 **AST 동등성 테스트**를 더한다(Task 5 에서 지운다).

- [ ] **Step 2: 테스트가 실패하는지 본다**

Run: `python -m pytest tests/workflow/test_wiring.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'neos.workflow.wiring'`

- [ ] **Step 3: 배선 표를 쓴다**

`neos/workflow/wiring.py`:
```python
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
    NodeSpec(N.DIRECT_RESPONSE.value, "_direct_response_node"),
    NodeSpec(N.SKILL_EXECUTOR.value, "_skill_executor_node", _on("skill_execution")),
    NodeSpec(N.RECURSIVE_ORCHESTRATOR.value, "_recursive_orchestrator_node", _on("recursive")),
    NodeSpec(N.HYPER_DEEP_ORCHESTRATOR.value, "_hyper_deep_orchestrator_node", _on("hyper_deep")),
    NodeSpec(N.DEEP_ANALYSIS_DISPATCH.value, "_deep_analysis_dispatch_node", _on("deep_analysis")),
    NodeSpec(N.EXECUTION_APPROVAL.value, "_execution_approval_node", _on("execution_approval")),
    NodeSpec(N.TASK_SCHEDULING_NODE.value, "_handle_task_scheduling_node"),
    NodeSpec(N.UI_FRAME_GENERATOR.value, "_ui_frame_generator_node", _on("a2ui")),
)

EDGES: tuple[Edge, ...] = (
    Edge(START, N.REFINEMENT_CHECKER.value),
    Edge(N.DIRECT_RESPONSE.value, N.RESP_GENERATOR.value),
    Edge(N.QUERY_REFINEMENT.value, N.CONVERSATION_CTX_PROC.value),
    Edge(N.RESEARCH_CONTINUATION.value, N.CONVERSATION_CTX_PROC.value),
    Edge(N.QUERY_CLS.value, N.SKILL_TOOL_SELECTOR.value),
    Edge(N.RECURSIVE_ORCHESTRATOR.value, N.RESP_GENERATOR.value, _on("recursive")),
    Edge(N.HYPER_DEEP_ORCHESTRATOR.value, N.RESP_GENERATOR.value, _on("hyper_deep")),
    # 디스패치 노드는 END 로 단락한다 -- 챗 턴은 job 핸들을 낸 뒤 즉시 끝난다(AC2).
    Edge(N.DEEP_ANALYSIS_DISPATCH.value, END, _on("deep_analysis")),
    Edge(N.UI_FRAME_GENERATOR.value, END, _on("a2ui")),
    Edge(N.TASK_SCHEDULING_NODE.value, N.RESP_GENERATOR.value),
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
            Route(P.SKIP_ORCHESTRATORS.value, N.DIRECT_RESPONSE.value, _off("skill_execution")),
            Route(P.SKIP_ORCHESTRATORS.value, N.SKILL_EXECUTOR.value, _on("skill_execution")),
            Route(P.USE_ORCHESTRATORS.value, N.HYPOTHESIS_GENERATION.value, _off("skill_execution")),
            Route(P.USE_ORCHESTRATORS.value, N.SKILL_EXECUTOR.value, _on("skill_execution")),
            Route("mission", N.MISSION_PLANNER.value),
            Route("recursive", N.RECURSIVE_ORCHESTRATOR.value, _on("recursive")),
            Route("hyper_deep", N.HYPER_DEEP_ORCHESTRATOR.value, _on("hyper_deep")),
            Route("deep_analysis", N.DEEP_ANALYSIS_DISPATCH.value, _on("deep_analysis")),
            Route("needs_approval", N.EXECUTION_APPROVAL.value, _on("execution_approval")),
            Route("task_scheduling", N.TASK_SCHEDULING_NODE.value),
            Route("ui_frame", N.UI_FRAME_GENERATOR.value, _on("a2ui")),
        ),
    ),
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

# 사람 승인 게이트. 체크포인터가 있는 경로에서만 쓰인다(호출자가 정한다).
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
```

`neos/workflow/graph.py` 의 `_route_after_skill_executor` 메서드 바로 뒤에 추가:
```python
    def _route_after_research_harness(self, state: AgentState) -> str:
        """배선 표의 분기 라우터는 메서드 이름으로 가리킨다 -- 모듈 함수에 이름을 준다."""
        return _should_route_to_harness_repair(state)
```

- [ ] **Step 4: 64개 해시를 AST 추출기로 캡처한다**

Run:
```bash
python - <<'EOF'
import itertools, json
from pathlib import Path
from neos.workflow.graph_design_ledger import topology_hash
from neos.workflow.topology_export import static_topology
from neos.workflow.wiring import DEFAULT_FLAGS

keys = sorted(DEFAULT_FLAGS)
captured = {}
for bits in itertools.product([False, True], repeat=len(keys)):
    flags = dict(zip(keys, bits))
    flag_id = ",".join(f"{k}={int(flags[k])}" for k in keys)
    captured[flag_id] = topology_hash(static_topology(flags=flags))
Path("tests/fixtures/static_topology_hashes.json").write_text(
    json.dumps(captured, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
print(len(captured))
EOF
```
Expected: `64`

- [ ] **Step 5: AST 동등성 테스트를 더한다**

`tests/workflow/test_wiring.py` 끝에 추가:
```python
# -- AST 추출기와의 동등성 (Task 5 에서 추출기와 함께 지운다) -----------------


@pytest.mark.parametrize("flags", list(_all_flag_combinations()), ids=_flag_id)
def test_the_table_equals_the_ast_extraction(flags) -> None:
    """노드 집합 · 엣지 다중집합 · 반복 상한이 옛 추출기와 같다. 해시만 보면 무엇이
    다른지 말하지 않으므로 집합으로 비교한다(메모리: 개수가 아니라 이름으로)."""
    from neos.workflow.topology_export import static_topology

    old = static_topology(flags=flags)
    new = topology_of(resolve_wiring(flags))
    assert set(new.nodes) == set(old.nodes)
    assert Counter(new.edges) == Counter(old.edges)
    assert dict(new.loop_bounds) == dict(old.loop_bounds)
```

- [ ] **Step 6: 테스트를 돌린다**

Run: `python -m pytest tests/workflow/test_wiring.py -q`
Expected: 전부 PASS. 동등성이 FAIL 이면 **표를 고친다**(추출기나 `graph.py` 를 고치지 않는다) — 실패 메시지의 차이 집합이 어느 항목이 빠졌는지 말한다.

- [ ] **Step 7: Ruff 대상에 새 경로를 넣는다**

`.github/workflows/backend-ci.yml` 의 Ruff `run:` 목록에서 `neos/workflow/deep_analysis` 다음 줄에 `neos/workflow/runtime` 과 `neos/workflow/wiring.py` 를, `tests/workflow/deep_analysis` 다음 줄에 `tests/workflow/runtime`, `tests/workflow/test_wiring.py`, `tests/workflow/test_import_boundaries.py` 를 더한다. `tests/config/test_test_environment_policy.py` 의 `_RUFF_KERNEL_DIRS` 에 같은 다섯 경로를 더한다. `neos/workflow/runtime/` 과 `tests/workflow/runtime/` 은 아직 없으므로 빈 패키지를 만든다:
```bash
mkdir -p neos/workflow/runtime tests/workflow/runtime
printf '"""채팅 워크플로 런타임 (spec 2026-10-13)."""\n' > neos/workflow/runtime/__init__.py
: > tests/workflow/runtime/__init__.py
```

Run:
```bash
uv run --frozen ruff check neos/workflow/runtime neos/workflow/wiring.py tests/workflow/runtime tests/workflow/test_wiring.py tests/workflow/test_import_boundaries.py
python -m pytest tests/config/test_test_environment_policy.py -q
```
Expected: Ruff 0건, 정책 테스트 PASS.

- [ ] **Step 8: spec §4.1 을 고친다**

`docs/superpowers/specs/2026-10-13-langgraph-removal-native-runner-design.md` §4.1 의 "경로 맵 안의 플래그별 대상(…)은 같은 `source` 의 `Branch` 를 플래그별로 둘 두어 표현하고, `build_static_wiring` 이 켜진 쪽 하나만 고른다 — 한 `source` 에 켜진 `Branch` 가 둘이면 조립 오류다" 를 다음으로 바꾼다:
"경로 맵 안의 플래그별 대상(예: 스킬 실행이 켜지면 skip·use 가 `SKILL_EXECUTOR` 로)은 **경로(`Route`)마다 `requires`** 를 두어 표현한다. `resolve_wiring` 은 켜진 경로만 남기고, 한 라벨에 켜진 경로가 둘이면 `WiringError` 다(Plan 1 에서 정함 — 라벨 아홉 × 플래그 여섯의 조합을 `Branch` 사본으로 적으면 폭발한다)."
같은 절의 `build_static_wiring(settings)` 를 `resolve_wiring(flags)` 로 바꾼다.

- [ ] **Step 9: 커밋**

```bash
git add neos/workflow/wiring.py neos/workflow/runtime/__init__.py neos/workflow/graph.py tests/workflow/test_wiring.py tests/workflow/runtime/__init__.py tests/fixtures/static_topology_hashes.json .github/workflows/backend-ci.yml tests/config/test_test_environment_policy.py docs/superpowers/specs/2026-10-13-langgraph-removal-native-runner-design.md
git commit -m "feat(workflow): wiring table as the single source of the static chat graph

neos/workflow/wiring.py holds nodes, edges and conditional branches with
per-item flag requirements. topology_of(resolve_wiring(flags)) equals the
AST extraction of _create_workflow_graph for all 64 flag combinations
(node set, edge multiset, loop bounds); the 64 hashes are captured so the
pin survives the extractor's removal. Nothing reads the table yet."
```

---

### Task 3: 스텁 하네스 · 실행 결과 계약 · 알려진 결함 기록

**Files:**
- Create: `tests/workflow/support/__init__.py`, `tests/workflow/support/stub_workflow.py`
- Create: `tests/workflow/test_execute_workflow_contract.py`
- Create: `tests/workflow/test_langgraph_known_defects.py`

**Interfaces:**
- Consumes: `resolve_wiring`, `FLAG_ATTR_TO_KEY` (Task 2); `MultiAgentWorkflow.execute_workflow(user_input, event_handler=None, use_checkpointer=True)`
- Produces (Task 4·Plan 2 가 쓴다):
  - `FLAGS_OFF: dict[str, bool]`
  - `StubPlan(nodes: Mapping[str, Callable[[dict], Mapping | None]] = {}, routes: Mapping[str, str] = {})` — `routes` 키는 **라우터 메서드 이름**
  - `stub_workflow(monkeypatch, plan: StubPlan, *, flags: Mapping[str, bool] = FLAGS_OFF, checkpointer=None, node_update_policy: str = "report") -> MultiAgentWorkflow`
  - `RecordingHandler` (속성 `starts: list[tuple[str, int, int]]`, `approvals: list[list]`, `errors: list`)
  - `SKIP_PATH_ROUTES: dict[str, str]`

- [ ] **Step 1: 하네스를 쓴다**

`tests/workflow/support/__init__.py`: 빈 파일.

`tests/workflow/support/stub_workflow.py`:
```python
"""스텁 노드로 **진짜** 정적 그래프를 돌리는 하네스 (spec 2026-10-13 §7.1).

노드 핸들러와 라우터만 인스턴스 속성으로 바꾸고, 배선·조립·`execute_workflow` 는
진짜를 쓴다. 그래서 같은 계약 테스트가 런타임을 갈아도 그대로 돈다(Plan 2 가
`runtime` 파라미터를 더한다).

라우터는 메서드 이름으로 고른다 -- `_should_continue_after_approval` 처럼 두 분기가
같은 라우터를 쓰기 때문이다. 계획에 없는 라우터가 불리면 실패한다: 기본 라벨을
추측하면 재생성 사이클 같은 루프로 조용히 빠진다.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from neos.workflow import graph as graph_module
from neos.workflow.wiring import FLAG_ATTR_TO_KEY, resolve_wiring

NodeFn = Callable[[dict], Mapping[str, Any] | None]

FLAGS_OFF: dict[str, bool] = dict.fromkeys(FLAG_ATTR_TO_KEY.values(), False)

# 정제·맥락·셀렉터를 skip 으로 지나 직접 응답 → 응답 생성 → 하네스 → 끝.
SKIP_PATH_ROUTES: dict[str, str] = {
    "_should_refine_or_continue": "skip_refinement",
    "_should_process_context": "skip_context",
    "_route_after_skill_tool_selector": "skip_orchestrators",
}

_SIDE_EFFECTS = (
    "_check_cached_response",
    "_load_memory_context",
    "_apply_research_template",
    "_record_session_start",
    "_save_episode_memory",
    "_record_session_complete",
    "_record_session_harness_blocked",
    "_record_session_failed",
    "_cache_workflow_result",
    "_auto_save_dataset",
)


class _AsyncNoop:
    async def __call__(self, *args, **kwargs):
        return None


class UnplannedRoute(AssertionError):
    pass


@dataclass
class StubPlan:
    nodes: Mapping[str, NodeFn] = field(default_factory=dict)
    routes: Mapping[str, str] = field(default_factory=dict)


class RecordingHandler:
    def __init__(self) -> None:
        self.starts: list[tuple[str, int, int]] = []
        self.approvals: list[list] = []
        self.errors: list = []

    async def on_workflow_start(self, workflow_input): ...

    async def on_node_start(
        self, node_name, step, total_steps, step_name=None, estimated_remaining_s=None
    ):
        self.starts.append((node_name, step, total_steps))

    async def on_node_progress(self, node_name, message, progress=0): ...

    async def on_node_complete(self, node_name, result): ...

    async def on_workflow_complete(self, result): ...

    async def on_workflow_error(self, error, node_name=None):
        self.errors.append(error)

    async def on_approval_request(self, pending_approvals, session_id):
        self.approvals.append(list(pending_approvals))


def _as_node(fn: NodeFn | None):
    async def node(state):
        if fn is None:
            return {}
        result = fn(state)
        return dict(result) if result is not None else None

    return node


def _as_router(router: str, label: str | None):
    def route(state):
        if label is None:
            raise UnplannedRoute(f"계획에 없는 라우터가 불렸다: {router}")
        return label

    return route


def stub_workflow(
    monkeypatch,
    plan: StubPlan,
    *,
    flags: Mapping[str, bool] = FLAGS_OFF,
    checkpointer: Any = None,
    node_update_policy: str = "report",
):
    """`node_update_policy` 기본값이 report 인 이유: 스텁은 계약 목록을 시험하지 않는다.
    테스트 세션이 raise 를 걸어도(Plan 1 Task 7) 스텁이 계약 밖 키를 써서 실패하면
    시험하려던 것(결과 계약·누적·승인)이 아니라 스텁 모양 때문에 깨진다. 정책 자체는
    `tests/workflow/runtime/test_node_updates.py` 가 시험한다. 이 설정은 Task 6 에서
    생긴다 -- 그 전에는 없는 필드라 건너뛴다(엄격한 설정 모델은 모르는 속성 대입을 거절한다)."""
    settings = graph_module.settings
    for attr, key in FLAG_ATTR_TO_KEY.items():
        monkeypatch.setattr(settings, attr, bool(flags.get(key, False)))
    monkeypatch.setattr(settings.config.workflow, "graph_design_enabled", False)
    if hasattr(settings.config.workflow, "node_update_policy"):
        monkeypatch.setattr(settings.config.workflow, "node_update_policy", node_update_policy)
    monkeypatch.setattr(settings, "SMART_CACHE_ENABLED", False)
    if checkpointer is not None:

        async def _get_checkpointer():
            return checkpointer

        monkeypatch.setattr(graph_module, "get_checkpointer", _get_checkpointer)

    workflow = graph_module.MultiAgentWorkflow()
    for name in _SIDE_EFFECTS:
        if hasattr(workflow, name):
            monkeypatch.setattr(workflow, name, _AsyncNoop())

    wiring = resolve_wiring({key: bool(flags.get(key, False)) for key in FLAG_ATTR_TO_KEY.values()})
    for spec in wiring.nodes:
        monkeypatch.setattr(workflow, spec.handler, _as_node(plan.nodes.get(spec.name)))
    for branch in wiring.branches:
        monkeypatch.setattr(
            workflow, branch.router, _as_router(branch.router, plan.routes.get(branch.router))
        )
    return workflow


def user_input(session_id: str = "s-contract", user_id: str = "u1", query: str = "안녕") -> dict:
    return {"query": query, "session_id": session_id, "user_id": user_id, "bypass_cache": True}
```

- [ ] **Step 2: 실행 결과 계약 테스트를 쓴다**

`tests/workflow/test_execute_workflow_contract.py`:
```python
"""`execute_workflow` 결과 계약 (spec 2026-10-13 §5 경계 1, §7.1).

웹 파이프라인·채널 게이트웨이(Q8 포함)·예약 러너가 이 dict 의 키를 읽는다. 런타임을
갈아도 이 키들이 같아야 dots(트랙 Q)가 영향을 받지 않는다.
"""

import pytest

from neos.workflow.enums import WorkflowNode as N
from tests.workflow.support.stub_workflow import (
    SKIP_PATH_ROUTES,
    RecordingHandler,
    StubPlan,
    stub_workflow,
    user_input,
)

pytestmark = [pytest.mark.no_db, pytest.mark.asyncio]

_SUCCESS_KEYS = {
    "success",
    "response",
    "metadata",
    "execution_time_ms",
    "quality_score",
    "errors",
    "cache_hit",
    "execution_steps",
    "retry_count",
    "channel_source",
}


def _answer(state):
    return {
        "final_response": "답",
        "response_metadata": {"k": "v"},
        "execution_time_ms": 7,
        "execution_steps": [{"step": "response_generation"}],
    }


def _harness_like_today(state):
    # 진짜 `_research_harness_node` 는 `{**state, **updates}` 를 돌려준다.
    return {**state, "harness_verdict": "pass", "harness_mode": "advisory"}


def _skip_plan(**nodes):
    base = {
        N.RESP_GENERATOR.value: _answer,
        N.RESEARCH_HARNESS.value: _harness_like_today,
    }
    base.update(nodes)
    return StubPlan(nodes=base, routes=SKIP_PATH_ROUTES)


async def test_a_successful_turn_returns_the_contract_keys(monkeypatch) -> None:
    workflow = stub_workflow(monkeypatch, _skip_plan())
    result = await workflow.execute_workflow(
        user_input(), event_handler=RecordingHandler(), use_checkpointer=False
    )
    assert _SUCCESS_KEYS <= set(result)
    assert result["success"] is True
    assert result["response"] == "답"
    assert result["metadata"] == {"k": "v"}
    assert result["cache_hit"] is False
    assert result["channel_source"] == "api"


async def test_a_gate_blocked_turn_reports_failure_with_the_blocked_text(monkeypatch) -> None:
    def blocked(state):
        return {
            **state,
            "harness_mode": "gate",
            "harness_verdict": "fail",
            "harness_failed_checks": ["citations"],
        }

    workflow = stub_workflow(monkeypatch, _skip_plan(**{N.RESEARCH_HARNESS.value: blocked}))
    result = await workflow.execute_workflow(
        user_input(), event_handler=RecordingHandler(), use_checkpointer=False
    )
    assert result["success"] is False
    assert "citations" in result["response"]
    assert result["blocked_response"] == "답"
    assert "research_harness_gate_failed" in result["errors"]


async def test_a_failing_node_returns_the_error_shape(monkeypatch) -> None:
    def boom(state):
        raise RuntimeError("노드 실패")

    workflow = stub_workflow(monkeypatch, _skip_plan(**{N.DIRECT_RESPONSE.value: boom}))
    handler = RecordingHandler()
    result = await workflow.execute_workflow(user_input(), event_handler=handler, use_checkpointer=False)
    assert result["success"] is False
    assert "노드 실패" in result["error"]
    assert {"partial_state", "cache_hit", "execution_time_ms"} <= set(result)
    assert handler.errors


async def test_progress_events_follow_the_nodes_actually_run(monkeypatch) -> None:
    workflow = stub_workflow(monkeypatch, _skip_plan())
    handler = RecordingHandler()
    await workflow.execute_workflow(user_input(), event_handler=handler, use_checkpointer=False)
    assert [name for name, _step, _max in handler.starts] == [
        N.REFINEMENT_CHECKER.value,
        N.CONVERSATION_CTX_PROC.value,
        N.QUERY_CLS.value,
        N.SKILL_TOOL_SELECTOR.value,
        N.DIRECT_RESPONSE.value,
        N.RESP_GENERATOR.value,
        N.RESEARCH_HARNESS.value,
    ]
    assert [step for _name, step, _max in handler.starts] == list(range(1, 8))
```

- [ ] **Step 3: 계약 테스트를 돌린다**

Run: `python -m pytest tests/workflow/test_execute_workflow_contract.py -v`
Expected: 4 PASS. 실패하면 하네스가 놓친 부작용(예: `_SIDE_EFFECTS` 에 없는 DB 호출)을 찾아 `_SIDE_EFFECTS` 에 더한다 — 계약 단언을 느슨하게 하지 않는다.

- [ ] **Step 4: 알려진 결함을 strict xfail 로 기록한다**

`tests/workflow/test_langgraph_known_defects.py`:
```python
"""LangGraph 런타임의 알려진 결함 (spec 2026-10-13 §1.2 R1·R3·R4·R5).

`xfail(strict=True)` 다 -- 결함이 실행되는 증거로 남고, 누가 고치면 XPASS 가
실패로 바뀌어 이 표시를 지우게 만든다. Plan 3 이 LangGraph 와 함께 이 파일을 지운다.
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from neos.workflow.enums import WorkflowNode as N
from neos.workflow.state import SearchResult
from tests.workflow.support.stub_workflow import (
    SKIP_PATH_ROUTES,
    RecordingHandler,
    StubPlan,
    stub_workflow,
    user_input,
)

pytestmark = [pytest.mark.no_db, pytest.mark.asyncio]


@pytest.mark.xfail(strict=True, reason="R1: aget_tuple 이 CheckpointTuple 이 아니라 튜플을 돌려준다")
async def test_r1_checkpointer_returns_a_checkpoint_tuple() -> None:
    from langgraph.checkpoint.base import CheckpointTuple

    from neos.workflow.checkpointer import PostgreSQLCheckpointer

    with patch("neos.workflow.checkpointer.create_async_engine"):
        checkpointer = PostgreSQLCheckpointer(
            database_url="postgresql+asyncpg://t:t@localhost/t", table_name="t_checkpoints"
        )
    checkpointer._initialized = True
    row = MagicMock()
    row.checkpoint_id = "cp-1"
    row.created_at = datetime.now()
    row.metadata = {}
    row.checkpoint_data = {"v": 1, "channel_values": {}, "channel_versions": {}, "versions_seen": {}}
    session = AsyncMock()
    session.execute.return_value = MagicMock(fetchone=MagicMock(return_value=row))
    with patch.object(checkpointer, "get_session") as get_session:
        get_session.return_value.__aenter__.return_value = session
        saved = await checkpointer.aget_tuple({"configurable": {"thread_id": "s"}})
    assert isinstance(saved, CheckpointTuple)


@pytest.mark.xfail(strict=True, reason="R3: interrupt_before 가 GraphInterrupt 를 던지지 않아 승인 이벤트가 안 나간다")
async def test_r3_an_approval_gate_interrupts_and_asks(monkeypatch) -> None:
    from langgraph.checkpoint.memory import MemorySaver

    pending = [{"request_id": "apr_1"}]
    plan = StubPlan(
        nodes={N.SKILL_TOOL_SELECTOR.value: lambda s: {"pending_approvals": pending, "approval_decision": None}},
        routes={**SKIP_PATH_ROUTES, "_route_after_skill_tool_selector": "needs_approval"},
    )
    workflow = stub_workflow(
        monkeypatch, plan, flags={"execution_approval": True}, checkpointer=MemorySaver()
    )
    handler = RecordingHandler()
    result = await workflow.execute_workflow(user_input(), event_handler=handler, use_checkpointer=True)
    assert result.get("interrupted") is True
    assert result["pending_approvals"] == pending
    assert handler.approvals == [pending]


@pytest.mark.xfail(strict=True, reason="R4: final_state 가 마지막 노드의 부분 갱신이다")
async def test_r4_the_result_reads_the_whole_state(monkeypatch) -> None:
    plan = StubPlan(
        nodes={
            N.RESP_GENERATOR.value: lambda s: {
                "final_response": "답",
                "response_metadata": {},
                "execution_time_ms": 1,
                "execution_steps": [],
            },
            # 갱신분만 돌려주는 하네스 -- 고쳐진 노드의 모양이다.
            N.RESEARCH_HARNESS.value: lambda s: {"harness_verdict": "pass"},
        },
        routes=SKIP_PATH_ROUTES,
    )
    workflow = stub_workflow(monkeypatch, plan)
    result = await workflow.execute_workflow(
        user_input(), event_handler=RecordingHandler(), use_checkpointer=False
    )
    assert result["success"] is True
    assert result["response"] == "답"


@pytest.mark.xfail(strict=True, reason="R5: 전체 상태를 돌려주는 노드가 operator.add 필드를 불린다")
async def test_r5_full_state_returns_do_not_duplicate_accumulated_results(monkeypatch) -> None:
    item = SearchResult(source="web", title="A", content="a", url="https://a")
    seen: list[list] = []

    def harness(state):
        seen.append(list(state["search_results"]))
        return {**state, "harness_verdict": "pass"}

    plan = StubPlan(
        nodes={
            N.DIRECT_RESPONSE.value: lambda s: {"search_results": [item]},
            # 진짜 응답 생성기처럼 전체 상태를 돌려준다.
            N.RESP_GENERATOR.value: lambda s: {
                **s,
                "final_response": "답",
                "response_metadata": {},
                "execution_time_ms": 1,
            },
            N.RESEARCH_HARNESS.value: harness,
        },
        routes=SKIP_PATH_ROUTES,
    )
    workflow = stub_workflow(monkeypatch, plan)
    await workflow.execute_workflow(user_input(), event_handler=RecordingHandler(), use_checkpointer=False)
    assert seen == [[item]]
```

- [ ] **Step 5: 결함 기록을 돌린다**

Run: `python -m pytest tests/workflow/test_langgraph_known_defects.py -v -rxX`
Expected: 4 XFAIL. **XPASS 가 하나라도 나오면** 그 결함은 재현되지 않는 것이다 — 멈추고 보고한다(spec §1.2 의 진단을 고쳐야 한다).

- [ ] **Step 6: 커밋**

```bash
git add tests/workflow/support tests/workflow/test_execute_workflow_contract.py tests/workflow/test_langgraph_known_defects.py
git commit -m "test(workflow): pin the execute_workflow result contract on stubbed real wiring

A stub harness replaces node handlers and routers on a real
MultiAgentWorkflow so the static graph, its assembly and execute_workflow
stay real. Contract: success, gate-blocked and error shapes plus the
progress-event sequence. R1/R3/R4/R5 (spec 2026-10-13 §1.2) are recorded
as strict xfails so a fix or a non-reproduction is loud."
```

---

### Task 4: 승인 포트 계약

**Files:**
- Create: `tests/workflow/test_approval_port_contract.py`

**Interfaces:**
- Consumes: `stub_workflow`, `StubPlan`, `SKIP_PATH_ROUTES`, `RecordingHandler`, `user_input` (Task 3); `neos.api.channels.workflow_approvals.RuntimeWorkflowApprovals(workflow)` 의 `interrupt_owner(session_id) -> str | None`, `decide(*, session_id, request_id, owner_id, approve) -> str`
- Produces: 채널 승인 포트의 지금 계약(Plan 2 가 같은 단언으로 새 서비스 위에서 돌린다)

- [ ] **Step 1: 테스트를 쓴다**

`tests/workflow/test_approval_port_contract.py`:
```python
"""채널 승인 포트의 계약 (spec 2026-10-13 §5 경계 2).

게이트웨이는 `interrupt_owner`·`decide` 의 이름·시그니처·반환 문자열에 기댄다.
Plan 2 가 안쪽을 승인 서비스로 바꿀 때 이 단언이 그대로 통과해야 한다.
"""

import asyncio

import pytest
from langgraph.checkpoint.memory import MemorySaver

from neos.workflow.enums import WorkflowNode as N
from tests.workflow.support.stub_workflow import (
    SKIP_PATH_ROUTES,
    RecordingHandler,
    StubPlan,
    stub_workflow,
    user_input,
)

pytestmark = [pytest.mark.no_db, pytest.mark.asyncio]

_SESSION = "s-approval"
_PENDING = [{"request_id": "apr_1"}]
_AFTER_APPROVAL_ROUTES = {
    "_should_continue_after_approval": "approved",
    "_should_replan": "skip_replan",
    "_should_regenerate": "proceed",
}


async def _drain_resumes() -> None:
    for _ in range(20):
        tasks = [
            task
            for task in asyncio.all_tasks()
            if task.get_name().startswith("channel_approval_resume_")
        ]
        if not tasks:
            return
        await asyncio.gather(*tasks, return_exceptions=True)


async def _interrupted_workflow(monkeypatch, reached: list[str]):
    import neos.api.channels.workflow_approvals as approvals_module

    async def _no_db(request_id, owner_id):
        return None

    monkeypatch.setattr(approvals_module, "_mark_resolved_best_effort", _no_db)

    def answer(state):
        reached.append(N.RESP_GENERATOR.value)
        return {"final_response": "승인 후 답", "response_metadata": {}, "execution_time_ms": 1, "execution_steps": []}

    plan = StubPlan(
        nodes={
            N.SKILL_TOOL_SELECTOR.value: lambda s: {"pending_approvals": _PENDING, "approval_decision": None},
            N.RESP_GENERATOR.value: answer,
        },
        routes={**SKIP_PATH_ROUTES, "_route_after_skill_tool_selector": "needs_approval", **_AFTER_APPROVAL_ROUTES},
    )
    workflow = stub_workflow(monkeypatch, plan, flags={"execution_approval": True}, checkpointer=MemorySaver())
    await workflow.execute_workflow(
        user_input(session_id=_SESSION), event_handler=RecordingHandler(), use_checkpointer=True
    )
    return workflow


async def test_the_interrupt_owner_is_the_turns_user(monkeypatch) -> None:
    from neos.api.channels.workflow_approvals import RuntimeWorkflowApprovals

    workflow = await _interrupted_workflow(monkeypatch, [])
    port = RuntimeWorkflowApprovals(workflow)
    assert await port.interrupt_owner(_SESSION) == "u1"


async def test_approving_returns_the_approved_line_and_resumes(monkeypatch) -> None:
    from neos.api.channels.workflow_approvals import RuntimeWorkflowApprovals

    reached: list[str] = []
    workflow = await _interrupted_workflow(monkeypatch, reached)
    port = RuntimeWorkflowApprovals(workflow)
    reply = await port.decide(session_id=_SESSION, request_id="apr_1", owner_id="u1", approve=True)
    assert reply == "apr_1 approved"
    await _drain_resumes()
    assert reached == [N.RESP_GENERATOR.value]


async def test_denying_returns_the_denied_line(monkeypatch) -> None:
    from neos.api.channels.workflow_approvals import RuntimeWorkflowApprovals

    workflow = await _interrupted_workflow(monkeypatch, [])
    port = RuntimeWorkflowApprovals(workflow)
    reply = await port.decide(session_id=_SESSION, request_id="apr_1", owner_id="u1", approve=False)
    assert reply == "apr_1 denied"
    await _drain_resumes()


async def test_an_unknown_request_is_not_claimed(monkeypatch) -> None:
    from neos.api.channels.workflow_approvals import _INVALID_REQUEST, RuntimeWorkflowApprovals

    workflow = await _interrupted_workflow(monkeypatch, [])
    port = RuntimeWorkflowApprovals(workflow)
    assert await port.decide(session_id=_SESSION, request_id="apr_x", owner_id="u1", approve=True) == _INVALID_REQUEST


async def test_the_same_decision_twice_is_claimed_once(monkeypatch) -> None:
    from neos.api.channels.workflow_approvals import _INVALID_REQUEST, RuntimeWorkflowApprovals

    workflow = await _interrupted_workflow(monkeypatch, [])
    port = RuntimeWorkflowApprovals(workflow)
    first = await port.decide(session_id=_SESSION, request_id="apr_1", owner_id="u1", approve=True)
    await _drain_resumes()
    second = await port.decide(session_id=_SESSION, request_id="apr_1", owner_id="u1", approve=True)
    assert first == "apr_1 approved"
    assert second == _INVALID_REQUEST
```

- [ ] **Step 2: 돌린다**

Run: `python -m pytest tests/workflow/test_approval_port_contract.py -v`
Expected: 5 PASS. `_INVALID_REQUEST` 의 실제 값이나 resume 이후 두 번째 `decide` 의 반환이 다르면, **지금 동작을 단언으로 옮긴다**(이 테스트는 현재 계약의 사진이다) — 단언을 바꾼 이유를 커밋 메시지에 적는다. 승인 경로 노드에서 `UnplannedRoute` 가 나오면 `_AFTER_APPROVAL_ROUTES` 에 그 라우터의 라벨을 더한다.

- [ ] **Step 3: 커밋**

```bash
git add tests/workflow/test_approval_port_contract.py
git commit -m "test(channels): pin the workflow approval port contract on a real interrupted run

interrupt_owner returns the turn's user; decide returns '<id> approved' or
'<id> denied', resumes in the background, refuses unknown ids and claims a
request once. Plan 2 runs the same assertions over the new approval service."
```

---

### Task 5: LangGraph 어댑터로 정적 그래프를 조립하고 AST 추출기를 지운다

**Files:**
- Create: `neos/workflow/runtime/langgraph_adapter.py`
- Modify: `neos/workflow/graph.py` (`_create_workflow_graph` 본문)
- Modify: `neos/workflow/topology_export.py` (전체 교체)
- Modify: `neos/workflow/execution_graph.py` (플래그 지도 import)
- Modify: `tests/workflow/test_wiring.py` (AST 동등성 테스트 삭제, 조립 동등성 테스트 추가)
- Modify: `tests/workflow/test_direct_response_path.py` (`test_the_skip_pathway_no_longer_points_at_the_summarizer`)
- Modify: `docs/superpowers/specs/2026-10-13-langgraph-removal-native-runner-design.md` §4.1 (별칭은 둔다)

**Interfaces:**
- Consumes: `Wiring`, `resolve_wiring`, `topology_of`, `FLAG_ATTR_TO_KEY`, `LOOP_BOUNDS` (Task 2); `current_static_flags()` (`neos/workflow/execution_graph.py`)
- Produces:
  - `compile_wiring(wiring: Wiring, owner: Any, *, graph_factory: Callable[[type], Any], state_schema: type, checkpointer: Any = None, interrupt_before: Sequence[str] = (), wrap: Callable[[str, Callable], Callable] | None = None) -> Any`
  - `topology_export.static_topology(*, flags=None) -> GraphTopology` (같은 시그니처, 표에서)

- [ ] **Step 1: 조립 동등성 테스트를 먼저 쓴다**

`tests/workflow/test_wiring.py` 끝에 추가(AST 동등성 테스트는 아직 둔다):
```python
# -- 조립된 LangGraph 그래프와 표의 동등성 -------------------------------------


@pytest.mark.parametrize("flags", list(_all_flag_combinations()), ids=_flag_id)
def test_the_compiled_graph_has_exactly_the_tables_edges(flags) -> None:
    """어댑터가 표를 빠짐없이 옮겼는가. LangGraph 의 `get_graph()` 는 같은 쌍을 한 번만
    내므로 집합으로 비교한다(다중집합은 위의 해시 테스트가 지킨다)."""
    from langgraph.graph import StateGraph

    from neos.workflow.runtime.langgraph_adapter import compile_wiring
    from neos.workflow.state import AgentState

    class _Owner:
        def __getattr__(self, name):
            return lambda state: {}

    wiring = resolve_wiring(flags)
    compiled = compile_wiring(wiring, _Owner(), graph_factory=StateGraph, state_schema=AgentState)
    drawn = compiled.get_graph()
    lg_edges = {(edge.source, edge.target) for edge in drawn.edges}
    table_edges = set(topology_of(wiring).edges)
    assert lg_edges == table_edges
    assert set(drawn.nodes) - {START, END} == {spec.name for spec in wiring.nodes}
```

Run: `python -m pytest "tests/workflow/test_wiring.py::test_the_compiled_graph_has_exactly_the_tables_edges" -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'neos.workflow.runtime.langgraph_adapter'`

> `neos.workflow.topology.START`·`END` 문자열이 LangGraph 의 `"__start__"`·`"__end__"` 와 같다는 사실은 `graph.py` 상단 주석(147~150행)이 적는다. 어댑터는 그 우연에 기대지 않고 명시적으로 옮긴다(Step 2). `get_graph()` 의 노드에는 `__start__`·`__end__` 가 들어 있다.

- [ ] **Step 2: 어댑터를 쓴다**

`neos/workflow/runtime/langgraph_adapter.py`:
```python
"""배선 표 → LangGraph `StateGraph` (spec 2026-10-13 §4.1). Plan 3 에서 지운다.

`graph_factory` 를 인자로 받는 이유: 기존 테스트 다섯이 `neos.workflow.graph.StateGraph`
를 기록용 가짜로 바꿔 조립 호출을 본다. `_create_workflow_graph` 가 자기 모듈의
`StateGraph` 를 넘기면 그 테스트들이 바뀌지 않고 이 어댑터를 시험한다.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from langgraph.graph import END as LG_END
from langgraph.graph import START as LG_START

from neos.workflow.topology import END, START
from neos.workflow.wiring import Wiring

_ENDPOINTS = {START: LG_START, END: LG_END}


def _lg(name: str) -> str:
    return _ENDPOINTS.get(name, name)


def compile_wiring(
    wiring: Wiring,
    owner: Any,
    *,
    graph_factory: Callable[[type], Any],
    state_schema: type,
    checkpointer: Any = None,
    interrupt_before: Sequence[str] = (),
    wrap: Callable[[str, Callable], Callable] | None = None,
) -> Any:
    graph = graph_factory(state_schema)
    for spec in wiring.nodes:
        handler = getattr(owner, spec.handler)
        graph.add_node(spec.name, wrap(spec.name, handler) if wrap else handler)
    for edge in wiring.edges:
        graph.add_edge(_lg(edge.source), _lg(edge.target))
    for branch in wiring.branches:
        graph.add_conditional_edges(
            branch.source,
            getattr(owner, branch.router),
            {route.label: _lg(route.target) for route in branch.routes},
        )
    if checkpointer is not None:
        return graph.compile(checkpointer=checkpointer, interrupt_before=list(interrupt_before))
    return graph.compile()
```

- [ ] **Step 3: 정적 토폴로지를 표에서 내고 AST 추출기를 지운다 (조립을 바꾸기 **전에** — 추출기가 새 소스를 읽으면 토폴로지가 비어 진행 추적이 깨진다)**

`neos/workflow/topology_export.py` 전체를 다음으로 바꾼다:
```python
"""정적 그래프의 `GraphTopology` -- 배선 표(`neos.workflow.wiring`)에서 낸다.

예전에는 `_create_workflow_graph` 의 `workflow.add_*` 호출을 AST 로 읽었다. 그 소스가
배선 표를 조립하는 몇 줄이 된 뒤로는 표가 원천이다(spec 2026-10-13 §4.1).
`flags` 에 없는 키는 켜짐 -- 가장 넓은 그래프가 가장 많은 위반을 드러낸다.
"""

from collections.abc import Mapping

from neos.workflow.topology import GraphTopology
from neos.workflow.wiring import resolve_wiring, topology_of


def static_topology(*, flags: Mapping[str, bool] | None = None) -> GraphTopology:
    return topology_of(resolve_wiring(flags))
```

`neos/workflow/execution_graph.py` 의 `from neos.workflow.topology_export import _FLAG_ATTR_TO_KEY, static_topology` 를
```python
from neos.workflow.topology_export import static_topology
from neos.workflow.wiring import FLAG_ATTR_TO_KEY
```
로 바꾸고, 본문의 `_FLAG_ATTR_TO_KEY` 를 `FLAG_ATTR_TO_KEY` 로 바꾼다. `current_static_flags` docstring 의 "`_FLAG_ATTR_TO_KEY` 를 재사용한다" 를 "`wiring.FLAG_ATTR_TO_KEY` 를 재사용한다" 로, `_static_topology_facts` docstring 의 "`inspect.getsource` + `ast.parse` 를 돈다" 문장을 "표를 해석한다 -- 플래그 조합은 64개라 캐시한다" 로 고친다.

Run: `grep -rn "_FLAG_ATTR_TO_KEY\|_Extractor\|_StaticExtractionError\|_LOOP_BOUND_BY_NODE" neos tests --include='*.py'`
Expected: 결과 없음. 남아 있으면 그 사용처를 `neos.workflow.wiring` 의 이름으로 옮긴다.

`tests/workflow/test_wiring.py` 에서 `test_the_table_equals_the_ast_extraction` 와 그 위 구분 주석을 지운다(해시 고정점과 조립 동등성이 대신 지킨다).

Run:
```bash
python -m pytest tests/workflow/test_wiring.py tests/workflow/test_static_graph_contract.py tests/workflow/test_skill_executor_wiring.py tests/workflow/test_execution_graph.py tests/workflow/test_subagent_node_rules.py tests/workflow/test_execute_workflow_contract.py -q
```
Expected: 전부 PASS — 표가 64개 조합에서 추출기와 같았으므로(Task 2) 토폴로지를 읽는 테스트는 바뀌지 않는다. `_create_workflow_graph` 는 아직 그대로다.

- [ ] **Step 4: `_create_workflow_graph` 를 어댑터로 바꾼다**

`neos/workflow/graph.py` 의 `_create_workflow_graph` 본문 전체(현재 `workflow = StateGraph(AgentState)` 부터 마지막 `return workflow.compile()` 까지)를 다음으로 바꾼다. docstring 은 첫 줄을 "정적 그래프를 배선 표(`neos.workflow.wiring`)에서 조립한다" 로 바꾸고 `use_checkpointer` 설명은 둔다. 지워지는 인라인 주석 중 배선의 **이유**를 적은 것(G1-a·G1-b·AC2·Phase 4·Phase 8)은 `wiring.py` 의 해당 항목 위 주석으로 옮긴다(G1-b 는 `RECURSIVE_ORCHESTRATOR`/`HYPER_DEEP_ORCHESTRATOR` → `RESP_GENERATOR` 엣지 위, G1-a 는 `DIRECT_RESPONSE` 엣지 위).
```python
        from neos.workflow.runtime.langgraph_adapter import compile_wiring
        from neos.workflow.wiring import resolve_wiring

        wiring = resolve_wiring(current_static_flags())
        if use_checkpointer:
            checkpointer = await get_checkpointer()
            logger.debug("[WorkflowGraph] Created with PostgreSQL checkpointer for horizontal scaling")
            # 승인 게이트(interrupt_before)는 체크포인터 경로에만 건다 -- stateless 경로에서는
            # 중단해도 재개할 지점이 없다.
            return compile_wiring(
                wiring,
                self,
                graph_factory=StateGraph,
                state_schema=AgentState,
                checkpointer=checkpointer,
                interrupt_before=wiring.interrupt_before,
            )
        logger.debug("[WorkflowGraph] Created without checkpointer (stateless mode)")
        return compile_wiring(wiring, self, graph_factory=StateGraph, state_schema=AgentState)
```
`current_static_flags` 가 `graph.py` 에 import 돼 있지 않으면 `from neos.workflow.execution_graph import current_static_flags` 를 기존 `execution_graph` import 줄에 더한다.

Run:
```bash
python -m pytest tests/workflow/test_wiring.py tests/test_workflow_graph.py tests/workflow/test_harness_graph_routing.py tests/workflow/test_deep_analysis_node.py tests/workflow/test_ephemeral_graph_execution.py tests/workflow/test_execute_workflow_contract.py tests/workflow/test_approval_port_contract.py -q
```
Expected: 전부 PASS — 특히 `test_the_compiled_static_graph_matches_its_pre_task_9_snapshot`(해시 불변), `StateGraph` 를 기록용 가짜로 바꾸는 기존 테스트 다섯(첫 `add_edge` 가 START 에서 나간다), 조립 동등성 64개. FAIL 이면 멈추고 보고한다 — 스냅샷 해시를 다시 캡처하지 않는다.

- [ ] **Step 5: 공허해진 소스 grep 테스트를 표 기준으로 옮긴다**

`tests/workflow/test_direct_response_path.py` 의 `test_the_skip_pathway_no_longer_points_at_the_summarizer` 를 다음으로 바꾼다(소스 줄을 훑던 테스트는 이제 매칭되는 줄이 없어 언제나 통과한다):
```python
def test_the_skip_pathway_no_longer_points_at_the_summarizer():
    """배선 자체를 고정한다 -- 누가 되돌리면 여기서 걸린다. 배선의 원천은 표다."""
    from neos.workflow.wiring import resolve_wiring

    wiring = resolve_wiring({"skill_execution": False})
    selector = next(b for b in wiring.branches if b.source == WorkflowNode.SKILL_TOOL_SELECTOR.value)
    assert wiring.path_map(selector)[WorkflowPathway.SKIP_ORCHESTRATORS.value] == WorkflowNode.DIRECT_RESPONSE.value
```

- [ ] **Step 6: spec §4.1 의 별칭 문장을 고친다**

spec §4.1 의 "AST 추출기와 `settings.SKILL_EXECUTION_ENABLED` 별칭(추출기 때문에 있던 것)을 지운다" 를 "AST 추출기를 지운다. `settings.SKILL_EXECUTION_ENABLED` 별칭은 **둔다** — 여섯 배선 플래그가 모두 같은 별칭 지도(`wiring.FLAG_ATTR_TO_KEY`)로 실행 시점 값을 읽으므로 하나만 지우면 비대칭이 된다(Plan 1 에서 정함)" 로 바꾼다. §13 S 불변식 5 를 옮기는 §11 의 문장은 그대로다.

- [ ] **Step 7: 워크플로 테스트 전체를 돈다**

Run:
```bash
python -m pytest tests/workflow tests/test_workflow_graph.py -q -p no:cacheprovider
python -m pytest --collect-only -qq tests > /tmp/names_after_t5.txt
diff <(sort /tmp/names_after_t1.txt) <(sort /tmp/names_after_t5.txt) | grep '^<' || true
```
Expected: 테스트 PASS(DB 가 필요한 것은 DB 를 띄우고). 이름 diff 의 `<` 줄은 `test_the_table_equals_the_ast_extraction[...]` 64개뿐이다.

- [ ] **Step 8: 커밋**

```bash
git add neos/workflow/runtime/langgraph_adapter.py neos/workflow/graph.py neos/workflow/topology_export.py neos/workflow/execution_graph.py neos/workflow/wiring.py tests/workflow/test_wiring.py tests/workflow/test_direct_response_path.py docs/superpowers/specs/2026-10-13-langgraph-removal-native-runner-design.md
git commit -m "refactor(workflow): assemble the static graph from the wiring table; drop the AST extractor

_create_workflow_graph now compiles resolve_wiring(current_static_flags())
through runtime/langgraph_adapter.compile_wiring, and static_topology reads
the same table. The compiled-graph snapshot hash is unchanged, and the
compiled edges equal the table for all 64 flag combinations.

Removed test names: test_the_table_equals_the_ast_extraction[*] (64) -- the
extractor it compared against is gone; the captured hashes and the compiled
graph equality replace it. test_the_skip_pathway_no_longer_points_at_the_summarizer
now reads the table instead of grepping source lines, which had become vacuous."
```

---

### Task 6: 노드 갱신 정규화 (R5) 와 `writes` 보고

**Files:**
- Create: `neos/workflow/runtime/node_updates.py`
- Create: `tests/workflow/runtime/test_node_updates.py`
- Modify: `neos/config/schema.py` (`WorkflowConfig.node_update_policy`)
- Modify: `neos/observability/metrics.py` (`workflow_update_rejected_total`)
- Modify: `neos/workflow/graph.py` (`_create_workflow_graph` 의 `wrap=` · `build_ephemeral_workflow` 의 `add_node`)
- Modify: `tests/workflow/test_langgraph_known_defects.py` (R5 xfail 제거)

**Interfaces:**
- Consumes: `compile_wiring(..., wrap=...)` (Task 5); `NODE_CONTRACTS` (`neos/workflow/contracts.py`)
- Produces (Plan 2 의 네이티브 러너가 같은 함수를 쓴다):
  - `UpdatePolicy = Literal["report", "drop", "raise"]`
  - `class NodeUpdateRejected(ValueError)` — 속성 `node: str`, `keys: tuple[str, ...]`
  - `reducer_kinds() -> dict[str, Literal["append", "merge"]]`
  - `working_copy(state: Mapping[str, Any]) -> dict[str, Any]`
  - `normalize_update(node: str, before: Mapping[str, Any], result: Mapping[str, Any] | None, *, writes: frozenset[str] | None, policy: UpdatePolicy) -> dict[str, Any]`
  - `wrap_node(node: str, handler: Callable, *, policy: UpdatePolicy) -> Callable`

- [ ] **Step 1: 정규화 규칙의 테스트를 쓴다**

`tests/workflow/runtime/test_node_updates.py`:
```python
"""노드 반환값 → 이번 노드의 갱신 (spec 2026-10-13 §4.2, R5)."""

import numpy as np
import pytest

from neos.workflow.runtime.node_updates import (
    NodeUpdateRejected,
    normalize_update,
    reducer_kinds,
    working_copy,
    wrap_node,
)
from neos.workflow.state import SearchResult

pytestmark = pytest.mark.no_db

A = SearchResult(source="web", title="A", content="a", url="https://a")
B = SearchResult(source="web", title="B", content="b", url="https://b")
_ALL = frozenset({"search_results", "final_response", "execution_steps", "errors", "quality_score", "x"})


def _norm(before, result, writes=_ALL, policy="raise"):
    return normalize_update("node", before, result, writes=writes, policy=policy)


def test_reducer_kinds_come_from_the_state_annotations() -> None:
    kinds = reducer_kinds()
    assert kinds["search_results"] == "append"
    assert kinds["errors"] == "append"
    assert kinds["subagent_runs"] == "merge"
    assert "final_response" not in kinds


def test_a_full_state_return_keeps_only_what_changed() -> None:
    before = {"search_results": [A], "final_response": None, "quality_score": 0.5}
    result = {**before, "final_response": "답"}
    assert _norm(before, result) == {"final_response": "답"}


def test_an_appended_full_list_becomes_the_new_items() -> None:
    before = {"search_results": [A]}
    assert _norm(before, {"search_results": [A, B]}) == {"search_results": [B]}


def test_a_delta_list_is_kept_as_is() -> None:
    before = {"search_results": [A]}
    assert _norm(before, {"search_results": [B]}) == {"search_results": [B]}


def test_an_unchanged_full_list_is_no_update() -> None:
    before = {"search_results": [A, B]}
    assert _norm(before, {"search_results": [A, B]}) == {}


def test_a_reordered_list_is_treated_as_new_items() -> None:
    """접두가 다르면 무엇이 새 것인지 모른다 -- 지금처럼 전부 붙는다(나빠지지 않는다)."""
    before = {"search_results": [A, B]}
    assert _norm(before, {"search_results": [B, A]}) == {"search_results": [B, A]}


def test_none_is_an_empty_update() -> None:
    assert _norm({"x": 1}, None) == {}


def test_runtime_keys_are_never_updates() -> None:
    assert _norm({}, {"_event_handler": object(), "x": 1}) == {"x": 1}


def test_values_whose_equality_raises_count_as_changed() -> None:
    before = {"x": np.array([1, 2])}
    result = {"x": np.array([1, 2])}
    assert "x" in _norm(before, result)


def test_in_place_mutation_becomes_an_update() -> None:
    before = {"execution_steps": [{"step": 1}]}

    async def node(state):
        state["execution_steps"].append({"step": 2})
        return state

    import asyncio

    update = asyncio.run(wrap_node("node", node, policy="raise")(before))
    assert update == {"execution_steps": [{"step": 1}, {"step": 2}]}
    assert before == {"execution_steps": [{"step": 1}]}


def test_raise_policy_rejects_keys_outside_writes() -> None:
    with pytest.raises(NodeUpdateRejected) as error:
        _norm({}, {"x": 1, "final_response": "답"}, writes=frozenset({"x"}))
    assert error.value.keys == ("final_response",)


def test_drop_policy_removes_keys_outside_writes() -> None:
    assert _norm({}, {"x": 1, "final_response": "답"}, writes=frozenset({"x"}), policy="drop") == {"x": 1}


def test_report_policy_keeps_keys_outside_writes() -> None:
    update = _norm({}, {"x": 1, "final_response": "답"}, writes=frozenset({"x"}), policy="report")
    assert update == {"x": 1, "final_response": "답"}


def test_unchanged_keys_outside_writes_are_not_violations() -> None:
    """전체 상태를 돌려주는 노드가 건드리지 않은 키로 위반이 되면 안 된다."""
    before = {"x": 1, "final_response": "답"}
    assert _norm(before, {**before, "x": 2}, writes=frozenset({"x"})) == {"x": 2}


def test_working_copy_isolates_lists_and_dicts() -> None:
    state = {"l": [1], "d": {"k": 1}, "o": object()}
    copy = working_copy(state)
    copy["l"].append(2)
    copy["d"]["k2"] = 2
    assert state == {"l": [1], "d": {"k": 1}, "o": state["o"]}
    assert copy["o"] is state["o"]
```

Run: `python -m pytest tests/workflow/runtime/test_node_updates.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'neos.workflow.runtime.node_updates'`

- [ ] **Step 2: 정규화 모듈을 쓴다**

`neos/workflow/runtime/node_updates.py`:
```python
"""노드 반환값을 "이번 노드의 갱신" 하나로 만든다 (spec 2026-10-13 §4.2, R5).

응답 생성기·하네스·오케스트레이터 등 여러 노드가 갱신분이 아니라 **전체 상태**를
돌려준다. LangGraph 는 그것을 갱신으로 받아 `operator.add` 필드에 리스트 전체를
다시 붙인다 -- 노드 셋짜리 프로브에서 `search_results` 가 네 배가 됐다. 서른 개
노드를 하나씩 고치는 대신 노드 경계 한 곳에서 정규화한다. LangGraph 어댑터와
Plan 2 의 네이티브 러너가 같은 함수를 쓴다.

규칙
- `_` 로 시작하는 런타임 주입 키는 갱신이 아니다
- 누적(`append`) 필드: 반환 리스트가 이전 값으로 시작하면 그 뒤만 새 항목이다.
  접두가 다르면(재정렬·중복 제거) 무엇이 새 것인지 모르므로 전부 새 항목으로 본다
  -- 지금 동작과 같고 나빠지지 않는다
- 그 밖의 필드: 이전 값과 같으면(동일 객체이거나 `==`) 갱신이 아니다. 비교가 예외를
  던지면 바뀐 것으로 본다
- 노드에는 상태의 **작업 사본**을 넘긴다 -- 제자리 변경(`append`)이 이전 값을 바꾸면
  변경이 보이지 않는다
- 계약의 `writes` 밖 키: `report` 는 기록만, `drop` 은 버림, `raise` 는 거절
"""

from __future__ import annotations

import functools
import inspect
import logging
import operator
import typing
from collections.abc import Callable, Mapping
from typing import Any, Literal

logger = logging.getLogger(__name__)

UpdatePolicy = Literal["report", "drop", "raise"]
_MISSING = object()


class NodeUpdateRejected(ValueError):
    def __init__(self, node: str, keys: tuple[str, ...]) -> None:
        super().__init__(f"노드 {node!r} 가 계약의 writes 밖 키를 썼다: {list(keys)}")
        self.node = node
        self.keys = keys


@functools.lru_cache(maxsize=1)
def reducer_kinds() -> dict[str, Literal["append", "merge"]]:
    """`AgentState` 의 `Annotated` 메타데이터에서 리듀서 종류를 읽는다 -- 표에 다시 적지 않는다."""
    from neos.workflow.state import AgentState

    kinds: dict[str, Literal["append", "merge"]] = {}
    for key, hint in typing.get_type_hints(AgentState, include_extras=True).items():
        while typing.get_origin(hint) in (typing.NotRequired, typing.Required):
            hint = typing.get_args(hint)[0]
        if typing.get_origin(hint) is not typing.Annotated:
            continue
        metadata = typing.get_args(hint)[1:]
        if operator.add in metadata:
            kinds[key] = "append"
        elif any(callable(item) for item in metadata):
            kinds[key] = "merge"
    return kinds


def working_copy(state: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value.copy() if isinstance(value, (list, dict, set)) else value
        for key, value in state.items()
    }


def _same(left: Any, right: Any) -> bool:
    if left is right:
        return True
    try:
        return bool(left == right)
    except Exception:  # noqa: BLE001 -- numpy 배열처럼 진릿값이 모호한 비교
        return False


def _new_items(prior: Any, returned: Any) -> list:
    items = list(returned or [])
    old = list(prior or []) if prior is not _MISSING else []
    if old and len(items) >= len(old) and all(_same(a, b) for a, b in zip(items, old)):
        return items[len(old):]
    return items


def _count_rejected(node: str, key: str) -> None:
    try:
        from neos.observability.metrics import metrics

        metrics.workflow_update_rejected_total.labels(node=node, key=key).inc()
    except Exception:  # noqa: BLE001 -- 계측 실패가 노드를 막지 않는다
        logger.debug("workflow_update_rejected_total unavailable", exc_info=True)


def normalize_update(
    node: str,
    before: Mapping[str, Any],
    result: Mapping[str, Any] | None,
    *,
    writes: frozenset[str] | None,
    policy: UpdatePolicy,
) -> dict[str, Any]:
    if not result:
        return {}
    kinds = reducer_kinds()
    update: dict[str, Any] = {}
    for key, value in result.items():
        if key.startswith("_"):
            continue
        prior = before.get(key, _MISSING)
        if kinds.get(key) == "append":
            items = _new_items(prior, value)
            if items:
                update[key] = items
        elif prior is not _MISSING and _same(value, prior):
            continue
        else:
            update[key] = value

    if writes is None:
        return update
    outside = tuple(sorted(set(update) - writes))
    if not outside:
        return update
    if policy == "raise":
        raise NodeUpdateRejected(node, outside)
    for key in outside:
        _count_rejected(node, key)
    logger.warning("node %s wrote keys outside its contract: %s (policy=%s)", node, list(outside), policy)
    if policy == "drop":
        for key in outside:
            del update[key]
    return update


def wrap_node(node: str, handler: Callable, *, policy: UpdatePolicy) -> Callable:
    """계약이 있는 노드는 `writes` 로 검사하고, 없는 노드(서브에이전트 템플릿)는 정규화만 한다."""
    from neos.workflow.contracts import NODE_CONTRACTS

    contract = NODE_CONTRACTS.get(node)
    writes = frozenset(contract.writes) if contract is not None else None

    @functools.wraps(handler)
    async def run(state):
        result = handler(working_copy(state))
        if inspect.isawaitable(result):
            result = await result
        return normalize_update(node, state, result, writes=writes, policy=policy)

    return run
```

Run: `python -m pytest tests/workflow/runtime/test_node_updates.py -q`
Expected: 메트릭이 아직 없어 `_count_rejected` 가 debug 로 삼키므로 전부 PASS.

- [ ] **Step 3: 설정과 메트릭을 더한다**

`neos/config/schema.py` 의 `WorkflowConfig` 에서 `skill_execution` 필드 바로 아래에:
```python
    # 노드가 계약의 writes 밖 키를 쓸 때 (spec 2026-10-13 §4.2). report = 기록만,
    # drop = 버림, raise = 거절. 계약 목록을 고치기 전에는 report 로 둔다(Plan 1 Task 7).
    node_update_policy: Literal["report", "drop", "raise"] = "report"
```
(`Literal` 이 이미 import 돼 있지 않으면 `from typing import Literal` 을 더한다.)

`neos/observability/metrics.py` 의 `channel_voice_transcriptions_total` 정의 바로 아래에:
```python
        # 노드가 계약의 writes 밖 키를 썼다 (spec 2026-10-13 §4.2). 올리는 곳은
        # neos/workflow/runtime/node_updates.py 한 곳이다.
        self.workflow_update_rejected_total = Counter(
            "workflow_update_rejected_total",
            "Workflow node updates outside the node contract's writes",
            ["node", "key"],
            registry=self.registry,
        )
```

Run: `python -m pytest tests/config -q -k "schema or default or inventory"`
Expected: PASS. 설정 인벤토리 테스트가 새 키의 문서화를 요구하면 `docs/CONFIGURATION.md` 의 workflow 절과 `docs/CONFIG_INVENTORY.md` 에 `workflow.node_update_policy` 한 줄씩을 기존 표 형식대로 더한다.

- [ ] **Step 4: 조립 경로에 정규화를 건다**

`neos/workflow/graph.py` 의 `_create_workflow_graph` 에서 두 `compile_wiring(...)` 호출에 같은 인자를 더한다:
```python
                wrap=self._node_wrapper(),
```
그리고 `MultiAgentWorkflow` 에 메서드를 더한다(`_route_after_research_harness` 아래):
```python
    def _node_wrapper(self):
        """노드 경계의 정규화 (spec 2026-10-13 §4.2). 정책은 조립 시점에 읽는다."""
        from neos.workflow.runtime.node_updates import wrap_node

        policy = settings.config.workflow.node_update_policy
        return lambda node, handler: wrap_node(node, handler, policy=policy)
```

`build_ephemeral_workflow` 에서 계약 노드를 등록하는 두 줄
```python
        if node_name in deferred:
            graph.add_node(node_name, bound_handler, defer=True)
        else:
            graph.add_node(node_name, bound_handler)
```
을
```python
        wrapped = workflow._node_wrapper()(node_name, bound_handler)
        if node_name in deferred:
            graph.add_node(node_name, wrapped, defer=True)
        else:
            graph.add_node(node_name, wrapped)
```
로 바꾼다. 템플릿 노드(`subagent_host.handler_for`)는 감싸지 않는다 — 자기 걸음 상태를 스스로 관리하는 핸들러다.

- [ ] **Step 5: R5 가 닫혔는지 본다**

Run: `python -m pytest tests/workflow/test_langgraph_known_defects.py -v -rxX`
Expected: `test_r5_full_state_returns_do_not_duplicate_accumulated_results` 가 **XPASS(strict) → FAIL**. 나머지 셋은 XFAIL.

`tests/workflow/test_langgraph_known_defects.py` 에서 R5 테스트의 `@pytest.mark.xfail(...)` 줄을 지우고, 함수 이름은 그대로 두고 docstring 을 더한다:
```python
    """R5 는 노드 경계 정규화(neos/workflow/runtime/node_updates.py)로 닫혔다 -- 회귀 가드."""
```
모듈 docstring 의 "R1·R3·R4·R5" 를 "R1·R3·R4 (R5 는 닫혔다 — 아래 회귀 가드)" 로 고친다.

Run: `python -m pytest tests/workflow/test_langgraph_known_defects.py -v -rxX`
Expected: 1 PASS, 3 XFAIL.

- [ ] **Step 6: 워크플로 테스트 전체를 돈다**

Run:
```bash
python -m pytest tests/workflow tests/test_workflow_graph.py tests/skills -q
```
Expected: PASS. 노드 반환값의 **키 집합**을 단언하던 테스트가 실패하면(전체 상태를 기대했다), 그 테스트가 노드를 직접 부르는지(`await workflow._x_node(state)` — 정규화를 지나지 않으므로 영향 없음) 아니면 컴파일된 그래프를 지나는지 본다. 그래프를 지나며 "이전 턴 결과가 다시 붙는다" 를 기대하던 단언은 R5 를 고정하던 것이므로 고치고 커밋 메시지에 이름을 적는다.

- [ ] **Step 7: 커밋**

```bash
git add neos/workflow/runtime/node_updates.py tests/workflow/runtime/test_node_updates.py neos/config/schema.py neos/observability/metrics.py neos/workflow/graph.py tests/workflow/test_langgraph_known_defects.py docs/CONFIGURATION.md docs/CONFIG_INVENTORY.md
git commit -m "fix(workflow): normalize node returns at the node boundary (R5)

Nodes that return the whole state re-appended every operator.add list
(search_results x4 in a three-node probe). Every node now runs on a working
copy and its return is reduced to what changed: new list items only,
unchanged values dropped, runtime keys skipped. Keys outside the contract's
writes are reported (workflow.node_update_policy=report, counter
workflow_update_rejected_total). The R5 strict xfail is now a regression test."
```

---

### Task 7: `writes` 강제 전개

**Files:**
- Modify: `neos/workflow/graph.py` 및 노드 계약(`@node_contract(... writes=...)`) — 위반이 가리키는 곳만
- Modify: `config/neos.development.yaml`, `tests/fixtures/config/test-session.yaml`
- Modify: `neos/config/schema.py` (기본값 `report` → `drop`)
- Modify: `docs/CONFIGURATION.md`

**Interfaces:**
- Consumes: `node_update_policy`, `NodeUpdateRejected` (Task 6)
- Produces: 스키마 기본값 `drop`, development·테스트 세션 `raise` — spec §4.2 의 최종 상태

- [ ] **Step 1: 테스트 세션을 `raise` 로 바꾼다**

`tests/fixtures/config/test-session.yaml` 의 `workflow:` 블록에 더한다:
```yaml
  # spec 2026-10-13 §4.2: 노드가 계약 밖 키를 쓰면 테스트에서 실패시킨다.
  node_update_policy: raise
```

- [ ] **Step 2: 위반을 모은다**

Run (DB 를 띄운 상태):
```bash
python -m pytest tests/workflow tests/test_workflow_graph.py tests/skills tests/api -q -p no:cacheprovider 2>&1 | grep -o "노드 '[^']*' 가 계약의 writes 밖 키를 썼다: \[[^]]*\]" | sort | uniq -c
```
Expected: 위반 (노드, 키) 목록. 비어 있으면 Step 4 로 간다.

- [ ] **Step 3: 위반마다 고친다**

각 (노드, 키) 에 대해 다음 규칙 하나를 적용한다:
1. 그 노드가 그 키를 **의도적으로** 쓴다(노드나 그 프로세서 코드가 그 키에 값을 대입한다) → 그 노드의 `@node_contract(... writes={...})` 에 키를 더한다. `writes_hand_curated=True` 인 계약도 같다. 계약 주석에 어느 헬퍼가 쓰는지 한 줄 적는다(기존 `RESP_GENERATOR` 계약 주석 형식)
2. 그 노드가 그 키를 쓰는 것이 **실수**다(다른 노드의 몫을 덮는다) → 노드를 고쳐 그 키를 돌려주지 않게 한다

규칙 1·2 를 고른 이유를 커밋 메시지에 (노드, 키, 규칙) 줄로 적는다. 고친 뒤 Step 2 의 명령을 다시 돌려 목록이 빌 때까지 반복한다. 계약 변경 뒤에는 `python -m pytest tests/workflow/test_static_graph_contract.py -q` 로 알려진 위반 집합이 바뀌지 않았는지 본다 — 바뀌었으면 그 테스트의 기대 집합을 고치지 말고 멈추고 보고한다.

- [ ] **Step 4: 기본값을 바꾼다**

`neos/config/schema.py`: `node_update_policy: Literal["report", "drop", "raise"] = "drop"` 로 바꾸고 주석의 "계약 목록을 고치기 전에는 report 로 둔다" 를 "기본은 버림, development·테스트 세션은 거절" 로 고친다.

`config/neos.development.yaml` 의 `workflow:` 블록에 더한다:
```yaml
  # spec 2026-10-13 §4.2: development 에서는 계약 밖 키를 쓰는 노드가 바로 실패한다.
  node_update_policy: raise
```

`docs/CONFIGURATION.md` 의 해당 줄에 기본값 `drop` 과 development·테스트 세션 `raise` 를 적는다.

- [ ] **Step 5: 전체 스위트를 돈다**

Run (DB 를 띄운 상태):
```bash
python -m pytest tests -q -p no:cacheprovider
uv run --frozen ruff check neos/workflow/deep_analysis neos/workflow/runtime neos/workflow/wiring.py neos/coding neos/subagent neos/fsi neos/univer neos/config neos/learn neos/jev tests/workflow/deep_analysis tests/workflow/runtime tests/workflow/test_wiring.py tests/workflow/test_import_boundaries.py tests/coding tests/subagent tests/fsi tests/univer tests/k_skill tests/security_audit tests/learn tests/jev tests/config tests/conftest.py
python -m pytest --collect-only -qq tests > /tmp/names_after_t7.txt
diff <(sort /tmp/names_after_t5.txt) <(sort /tmp/names_after_t7.txt) | grep '^<' || true
git diff --stat adbae5da -- tests/standing tests/jev tests/api/channels
```
Expected: 테스트 PASS(알려진 flaky — 메모리 `managed-secret-truncated-tail-flake` — 하나뿐이면 그 파일만 다시 돌린다), Ruff 0건, 이름 diff 의 `<` 없음, 마지막 diff 출력 없음(Q·Jev·채널 테스트 변경 0줄).

- [ ] **Step 6: 커밋**

```bash
git add -A neos/workflow neos/config/schema.py config/neos.development.yaml tests/fixtures/config/test-session.yaml docs/CONFIGURATION.md
git commit -m "feat(workflow): enforce node contract writes (drop by default, raise in development and tests)

<(노드, 키, 규칙) 줄을 Step 3 의 결과로 채운다 -- 규칙 1: 계약에 더함, 규칙 2: 노드를 고침>"
```

> 이 커밋 메시지의 둘째 문단은 Step 3 에서 실제로 고친 목록으로 쓴다. 위반이 없었다면 "No contract violations were found under raise." 한 줄로 쓴다.
