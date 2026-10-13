# W1 Plan 2 — 네이티브 런타임 코어 (단계 3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** LangGraph 없이 채팅 워크플로를 돌리는 네이티브 런타임(러너 · 세션 저장소 · 작업 기록 · 승인 서비스)을 `workflow.runtime: native` 플래그 뒤에 착지시킨다. 기본값은 `langgraph` 그대로다.

**Architecture:** Plan 1 이 만든 배선 표(`neos/workflow/wiring.py`)와 노드 경계 함수(`neos/workflow/runtime/node_updates.py`)를 그대로 쓴다. 러너가 표를 해석해 LangGraph updates 모드와 같은 모양의 chunk 를 내므로 `execute_workflow` 의 진행 추적은 바뀌지 않는다. 턴의 앞뒤(세션 읽기·병합·저장, 작업 시작·중단·완료)는 `runtime/turns.py` 가 맡고, 런타임 선택은 `runtime/select.py` 한 곳이다. 승인은 그래프가 아니라 `workflow_runs` 행을 읽는 `WorkflowApprovals` 가 맡는다.

**Tech Stack:** Python 3.12 · SQLAlchemy 2.0 async(`text()` SQL) · PostgreSQL 16 · pytest(asyncio) · pydantic 설정 스키마 · prometheus_client

**Spec:** `docs/superpowers/specs/2026-10-13-langgraph-removal-native-runner-design.md` — 이 계획은 §6.1 **단계 3** 이다(§4.2 러너 · §4.3 세션 · §4.4 작업 기록 · §4.5 승인 · §4.10 순차 설계 그래프 · §4.4 코딩 연결). 단계 4(대화 기록 대체 · 리셋 · R10 · CH-RESUME · 결과 작성자 · 아웃박스 · 심층분석 lease · 멱등 키)는 Plan 2b 다.

## Global Constraints

- 커밋 메시지에 `Co-Authored-By` 트레일러를 넣지 않는다(저장소 규칙). 문서·주석은 한국어
- **기본 동작을 바꾸지 않는다** — `workflow.runtime` 기본값 `langgraph`. LangGraph 경로의 결과·이벤트·승인 동작은 이 계획 뒤에도 같다. 예외는 spec 이 정한 버그 수정 하나: `_create_initial_state` 가 `pending_approvals`·`approval_decision` 을 턴마다 리셋한다(§4.3, S-PEND)
- `tests/standing` · `tests/jev` · `tests/api/channels` 는 **한 줄도** 바꾸지 않는다
- 가드: `neos/coding` · `neos/workflow/deep_analysis` · `neos/standing` · `neos/jev` · `neos/subagent` 는 `neos.workflow.graph`·`neos.workflow.runtime`·`neos.workflow.wiring`·`langgraph` 를 import 하지 않는다(`tests/workflow/test_import_boundaries.py`)
- `tests/standing/test_agent_onboarding.py` 가 `CodingRunService(...)._on_completed is run_service._standing_agent_completion` 를 고정한다 — 그 기본값을 바꾸지 않는다
- 노드 갱신은 `node_updates.wrap_node`·`apply_update` 를 지난다 — 사본을 만들지 않는다(spec §4.2)
- 새 의존성 없음. 새 테이블은 `db/migrations/NNN_*.sql`(번호순 자동 포함, `db/BOOTSTRAP_ORDER.txt` 수정 불필요). 테스트 세션은 `tests/conftest.py` 가 마이그레이션을 번호순으로 적용한다
- 테스트: `NEOS_ENV=default GOOGLE_API_KEY=test-key python -m pytest …`(저장소 루트, DB `neos_test` 필요). DB 없는 테스트는 `pytestmark = pytest.mark.no_db`
- 머지 전: DB 를 띄운 전체 스위트 · CI Ruff 명령 그대로 · 테스트 이름 전후 비교(`--collect-only -qq`, `tests/...::` 줄만)
- 알려진 flaky: `tests/coding/sandbox/test_managed_secret_channel.py::test_a_truncated_tail_of_the_value_is_scrubbed_on_managed_output[*]` — 이것만 실패하면 그 파일을 다시 돌려 보고한다

## Review Focus

1. 저장된 세션이 디코드되지 않는다(옛 버전이 쓴 모르는 타입 태그·깨진 JSON) → 턴은 빈 이어받기로 진행하고 카운터를 올린다, 크래시하지 않는다. Task 6 `test_an_undecodable_session_starts_fresh`
2. 같은 승인에 웹과 채널이 동시에 결정을 보낸다 → 하나만 재개되고 다른 하나는 거절(`conflict`)을 받는다. Task 7 `test_two_concurrent_decisions_resume_once`
3. 승인 대기 중에 세션 행이 사라졌다(보존 정리·수동 삭제) → `resume` 이 명확한 오류 결과를 내고 작업은 `failed`, 크래시하지 않는다. Task 7 `test_resume_without_a_session_fails_the_work`
4. 라우터가 경로 표에 없는 라벨을 낸다(네이티브) → `WiringError` 로 그 턴이 에러 결과가 된다, 다른 노드로 흘러가지 않는다. Task 2 `test_an_unknown_label_is_a_wiring_error`
5. 상태 없는 호출(`use_checkpointer=False`, A2UI 제출)에서 승인 게이트 노드에 닿는다 → LangGraph 와 같이 중단하지 않고 지나간다(게이트는 체크포인터 경로에서만). Task 6 `test_a_stateless_turn_does_not_interrupt`

## 이 계획에서 정한 spec 세부

- **`workflow.session.max_carried_items` 기본값 200.** spec 은 "실측으로 정한다" 고 적었다. 한 턴의 검색 결과는 보통 수십 개라 200 은 몇 턴을 담는다. Plan 3 단계 5 의 라이브 dry run 에서 `workflow_session_trimmed_total` 을 보고 다시 정한다
- **병렬 설계 거절은 네이티브 런타임에서만 켠다.** spec §4.10 의 `parallel_unsupported` 규칙을 `validate_topology(..., allow_parallel=True)` 인자로 두고 네이티브 경로만 `False` 로 부른다 — 기본 런타임의 설계 그래프 동작은 바뀌지 않는다(Global Constraints). 단계 6 에서 기본이 네이티브가 되면 자연히 모두에 걸린다
- **승인 결정은 세션 행이 아니라 재개 티켓이 나른다.** spec §4.5 는 "`decide` 가 세션 상태에 `approval_decision` 을 쓴다" 고 적었다. 재개가 세션을 어차피 읽으므로 `decide` 는 작업 행만 CAS 로 바꾸고, `resume` 이 저장된 상태 위에 결정을 얹는다 — 쓰기 하나가 줄고 경합 지점이 작업 행 하나가 된다
- **`_interrupted_result` 는 대기 목록을 접힌 상태에서 읽는다**(LangGraph 경로 포함). `aget_state` 를 더 부르지 않으므로 PostgreSQL 체크포인터의 R1 이 승인 이벤트를 막지 않는다. 값은 같다 — 접힌 상태가 셀렉터의 갱신을 담는다
- **코딩 작업 기록은 `neos/coding` 이 정의한 포트로 주입한다.** 가드 때문에 `neos/coding` 은 `neos.workflow.runtime` 을 import 할 수 없다. 포트 등록은 네이티브 런타임일 때만 한다(기본 동작 불변)

---

## File Structure

| 파일 | 책임 | Task |
|---|---|---|
| `neos/workflow/runtime/state_codec.py` | `AgentState` 값 ↔ JSON (타입 태그) | 1 |
| `neos/workflow/wiring.py` | `NodeSpec.handler`·`Branch.router` 가 호출 가능 객체도 받는다 · `NodeSpec.wrapped` | 2 |
| `neos/workflow/runtime/runner.py` | `WorkflowRunner` · `Completed` · `Interrupted` · `StepLimitExceeded` | 2 |
| `neos/workflow/runtime/langgraph_adapter.py` | 참조 해석을 러너와 같은 함수로 | 2 |
| `neos/workflow/runtime/designed.py` | 승인된 `GraphTopology` → `Wiring`(순차) · 재개용 설계 그래프 복원 | 3 |
| `neos/workflow/topology.py` | `validate_topology(..., allow_parallel=True)` · 규칙 `parallel_unsupported` | 3 |
| `neos/workflow/graph_design_ledger.py` | `design_graph_or_fallback(..., allow_parallel=True)` 전달 | 3 |
| `neos/workflow/runtime/sessions.py` | `SessionStore`(메모리·Postgres) · `carry` · `trim` | 4 |
| `db/migrations/096_add_workflow_sessions.sql` | `workflow_sessions` | 4 |
| `neos/workflow/runtime/work.py` | `WorkRecord` · `WorkStore`(메모리·Postgres) · `WorkLifecycle` · `entry_and_delivery` | 5 |
| `db/migrations/097_add_workflow_runs.sql` | `workflow_runs` · `workflow_deliveries` | 5 |
| `neos/workflow/runtime/turns.py` | 턴 앞뒤: `NativeTurns` · `TurnStart` · `TurnHandle` · `NULL_TURN` | 6 |
| `neos/workflow/runtime/select.py` | 런타임 선택 · 싱글턴 · 테스트 주입 | 6, 7, 8 |
| `neos/workflow/execution_graph.py` | `ExecutionGraph.runner` | 6 |
| `neos/workflow/graph.py` | 네이티브 러너 부착 · `execute_workflow(resume=)` · 턴 훅 · 초기 상태 리셋 | 4, 6, 7 |
| `neos/config/schema.py` | `WorkflowConfig.runtime` · `WorkflowSessionConfig` | 4, 6 |
| `neos/observability/metrics.py` | 세션 카운터 셋 | 4 |
| `neos/workflow/runtime/approvals.py` | `WorkflowApprovals` · `PendingApproval` · `ResumeTicket` · `Refusal` | 7 |
| `neos/api/handlers/approval_handlers.py` · `neos/api/channels/workflow_approvals.py` · `neos/tasks/scheduled_task_runner.py` | 네이티브면 승인 서비스로 | 7 |
| `neos/coding/application/work_port.py` | 코딩 → 작업 기록 포트 | 8 |
| `neos/coding/application/task_service.py` · `neos/coding/persistence/postgres.py` · `neos/coding/application/run_service.py` | 포트 호출 | 8 |
| `neos/workflow/runtime/coding_link.py` | 포트 구현 · 등록 | 8 |
| `neos/main.py` · `neos/workflow/celery_app.py` | 등록 호출 | 8 |
| `tests/workflow/support/stub_workflow.py` | `runtime` 인자 · 메모리 저장소 주입 | 6 |
| `tests/workflow/test_execute_workflow_contract.py` · `tests/workflow/test_approval_port_contract.py` | 두 런타임 파라미터 | 6, 7 |

---

### Task 1: 상태 코덱

**Files:**
- Create: `neos/workflow/runtime/state_codec.py`
- Test: `tests/workflow/runtime/test_state_codec.py`

**Interfaces:**
- Consumes: `neos.workflow.state.{AgentState, SearchResult, AnalysisResult, GenerationResult}`, `neos.workflow.errors.{WorkflowError, ErrorCategory}`, `neos.workflow.metrics.PerformanceMetrics`
- Produces:
  - `class CodecError(TypeError)`
  - `encode_state(state: Mapping[str, Any]) -> dict[str, Any]` — `_` 로 시작하는 키 제외
  - `decode_state(payload: Mapping[str, Any]) -> dict[str, Any]`
  - `REGISTERED_TYPES: frozenset[type]`

- [ ] **Step 1: 테스트를 쓴다**

`tests/workflow/runtime/test_state_codec.py`:
```python
"""세션 상태 코덱 (spec 2026-10-13 §4.3). 등록된 타입만 원래 타입으로 돌아오고, 모르는 타입은 실패한다."""

import dataclasses
import enum
import json
import typing
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from neos.workflow.errors import ErrorCategory, WorkflowError
from neos.workflow.metrics import PerformanceMetrics
from neos.workflow.runtime.state_codec import (
    REGISTERED_TYPES,
    CodecError,
    decode_state,
    encode_state,
)
from neos.workflow.state import AgentState, AnalysisResult, GenerationResult, SearchResult

pytestmark = pytest.mark.no_db


def _roundtrip(state):
    return decode_state(json.loads(json.dumps(encode_state(state))))


def test_registered_values_come_back_as_their_types() -> None:
    state = {
        "search_results": [SearchResult(source="web", title="A", content="a", url="https://a", score=0.5, metadata={"k": 1})],
        "analysis_results": [AnalysisResult(analysis_type="t", data={"x": [1, 2]}, confidence=0.9, insights=["i"])],
        "generation_results": [GenerationResult(content_type="text", content={"body": "b"}, metadata=None)],
        "structured_errors": [WorkflowError(category=ErrorCategory.LLM_ERROR, message="m", node="n")],
        "execution_start": datetime(2026, 10, 14, 9, 0, tzinfo=UTC),
        "cumulative_cost": Decimal("0.0123"),
        "pair": (1, "two"),
        "plain": {"nested": [1, None, True, 1.5, "s"]},
    }
    back = _roundtrip(state)
    assert back == state
    assert isinstance(back["search_results"][0], SearchResult)
    assert back["structured_errors"][0].category is ErrorCategory.LLM_ERROR
    assert isinstance(back["pair"], tuple)


def test_performance_metrics_roundtrip() -> None:
    metrics = PerformanceMetrics(session_id="s")
    back = _roundtrip({"performance_metrics": metrics})
    assert back["performance_metrics"] == metrics


def test_runtime_keys_are_not_saved() -> None:
    assert "_event_handler" not in encode_state({"_event_handler": object(), "x": 1})


def test_an_unregistered_type_fails_with_its_path() -> None:
    class Stranger:
        pass

    with pytest.raises(CodecError, match=r"search_metadata\.thing"):
        encode_state({"search_metadata": {"thing": Stranger()}})


def test_a_dict_that_looks_like_a_tag_survives() -> None:
    state = {"meta": {"__t": "not-a-tag", "v": 1}}
    assert _roundtrip(state) == state


def test_non_string_dict_keys_fail() -> None:
    with pytest.raises(CodecError):
        encode_state({"x": {1: "a"}})


def test_an_unknown_tag_fails_on_decode() -> None:
    with pytest.raises(CodecError, match="dataclass_from_the_future"):
        decode_state({"x": {"__t": "dc", "c": "dataclass_from_the_future", "v": {}}})


def _classes_in(hint):
    origin = typing.get_origin(hint)
    if origin is None:
        if isinstance(hint, type):
            yield hint
        return
    for arg in typing.get_args(hint):
        yield from _classes_in(arg)


def test_every_dataclass_and_enum_in_the_state_is_registered() -> None:
    """새 dataclass 필드가 생기면 여기서 걸린다 -- 저장 실패를 운영에서 처음 보지 않게."""
    hints = typing.get_type_hints(AgentState, include_extras=True)
    found = {
        cls
        for hint in hints.values()
        for cls in _classes_in(hint)
        if dataclasses.is_dataclass(cls) or (isinstance(cls, type) and issubclass(cls, enum.Enum))
    }
    nested = {
        field.type
        for cls in list(found)
        if dataclasses.is_dataclass(cls)
        for field in dataclasses.fields(cls)
        if isinstance(field.type, type) and issubclass(field.type, enum.Enum)
    }
    assert found | nested <= REGISTERED_TYPES
```

Run: `NEOS_ENV=default GOOGLE_API_KEY=test-key python -m pytest tests/workflow/runtime/test_state_codec.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'neos.workflow.runtime.state_codec'`

> `WorkflowError` 의 `category` 필드 타입 주석이 문자열(`from __future__ import annotations`)이면 `nested` 가 비지만, `ErrorCategory` 는 등록 목록에 있으므로 단언은 그대로 성립한다. `PerformanceMetrics` 의 생성자 인자가 `session_id` 하나로 충분하지 않으면 실제 필수 필드를 채운다.

- [ ] **Step 2: 코덱을 쓴다**

`neos/workflow/runtime/state_codec.py`:
```python
"""세션 상태 코덱 -- `AgentState` 값을 JSON 으로, 다시 원래 타입으로 (spec 2026-10-13 §4.3).

옛 PostgreSQL 체크포인터는 모르는 객체를 문자열로 바꿔 저장했다 -- `SearchResult` 가 dict 로
돌아왔고 2턴째 노드의 `r.title` 에서야 드러났다(R2). 여기서는 등록된 타입만 태그를 달아 저장하고
나머지는 **실패한다**. 저장 실패는 턴을 막지 않는다(호출자가 경고와 카운터로 처리한다).

태그 모양: `{"__t": <종류>, ...}`. 사용자 dict 가 우연히 `__t` 키를 가지면 `{"__t": "dict", "v": …}`
로 감싸 구별한다.
"""

from __future__ import annotations

import dataclasses
import enum
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any

from neos.workflow.errors import ErrorCategory, WorkflowError
from neos.workflow.metrics import PerformanceMetrics
from neos.workflow.state import AnalysisResult, GenerationResult, SearchResult

_TAG = "__t"

_DATACLASSES: dict[str, type] = {
    cls.__name__: cls
    for cls in (SearchResult, AnalysisResult, GenerationResult, WorkflowError, PerformanceMetrics)
}
_ENUMS: dict[str, type[enum.Enum]] = {cls.__name__: cls for cls in (ErrorCategory,)}

REGISTERED_TYPES: frozenset[type] = frozenset(_DATACLASSES.values()) | frozenset(_ENUMS.values())


class CodecError(TypeError):
    pass


def encode_state(state: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: _encode(value, key)
        for key, value in state.items()
        if not str(key).startswith("_")
    }


def decode_state(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {key: _decode(value, key) for key, value in payload.items()}


def _encode(value: Any, path: str) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, enum.Enum):
        name = type(value).__name__
        if _ENUMS.get(name) is not type(value):
            raise CodecError(f"{path}: 등록되지 않은 enum {type(value)!r}")
        return {_TAG: "enum", "c": name, "v": value.value}
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        name = type(value).__name__
        if _DATACLASSES.get(name) is not type(value):
            raise CodecError(f"{path}: 등록되지 않은 dataclass {type(value)!r}")
        return {
            _TAG: "dc",
            "c": name,
            "v": {
                field.name: _encode(getattr(value, field.name), f"{path}.{field.name}")
                for field in dataclasses.fields(value)
            },
        }
    if isinstance(value, datetime):
        return {_TAG: "datetime", "v": value.isoformat()}
    if isinstance(value, Decimal):
        return {_TAG: "decimal", "v": str(value)}
    if isinstance(value, tuple):
        return {_TAG: "tuple", "v": [_encode(item, f"{path}[{i}]") for i, item in enumerate(value)]}
    if isinstance(value, list):
        return [_encode(item, f"{path}[{i}]") for i, item in enumerate(value)]
    if isinstance(value, Mapping):
        encoded: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise CodecError(f"{path}: 문자열이 아닌 dict 키 {key!r}")
            encoded[key] = _encode(item, f"{path}.{key}")
        if _TAG in encoded:
            return {_TAG: "dict", "v": encoded}
        return encoded
    raise CodecError(f"{path}: 등록되지 않은 타입 {type(value)!r}")


def _decode(value: Any, path: str) -> Any:
    if isinstance(value, list):
        return [_decode(item, f"{path}[{i}]") for i, item in enumerate(value)]
    if not isinstance(value, Mapping):
        return value
    tag = value.get(_TAG)
    if tag is None:
        return {key: _decode(item, f"{path}.{key}") for key, item in value.items()}
    if tag == "dict":
        return {key: _decode(item, f"{path}.{key}") for key, item in value["v"].items()}
    if tag == "datetime":
        return datetime.fromisoformat(value["v"])
    if tag == "decimal":
        return Decimal(value["v"])
    if tag == "tuple":
        return tuple(_decode(item, f"{path}[{i}]") for i, item in enumerate(value["v"]))
    if tag == "enum":
        cls = _ENUMS.get(value["c"])
        if cls is None:
            raise CodecError(f"{path}: 모르는 enum {value['c']!r}")
        return cls(value["v"])
    if tag == "dc":
        cls = _DATACLASSES.get(value["c"])
        if cls is None:
            raise CodecError(f"{path}: 모르는 dataclass {value['c']!r}")
        fields = {key: _decode(item, f"{path}.{key}") for key, item in value["v"].items()}
        instance = cls.__new__(cls)
        for key, item in fields.items():
            object.__setattr__(instance, key, item)
        return instance
    raise CodecError(f"{path}: 모르는 태그 {tag!r}")
```

> dataclass 는 `__init__` 을 거치지 않고 필드만 채운다 — `SearchResult.__post_init__` 의 `float()` 변환을 다시 돌릴 이유가 없고, 저장된 값이 이미 그 결과다.

Run: `NEOS_ENV=default GOOGLE_API_KEY=test-key python -m pytest tests/workflow/runtime/test_state_codec.py -q`
Expected: PASS

- [ ] **Step 3: 커밋**

```bash
git add neos/workflow/runtime/state_codec.py tests/workflow/runtime/test_state_codec.py
git commit -m "feat(workflow): session state codec with type tags that fails on unregistered types (spec §4.3)"
```

---

### Task 2: 러너

**Files:**
- Modify: `neos/workflow/wiring.py` (`NodeSpec`·`Branch` 의 참조 타입, `NodeSpec.wrapped`, `resolve_ref`)
- Modify: `neos/workflow/runtime/langgraph_adapter.py` (`resolve_ref` 사용)
- Create: `neos/workflow/runtime/runner.py`
- Test: `tests/workflow/runtime/test_runner.py`

**Interfaces:**
- Consumes: `Wiring`, `NodeSpec`, `Edge`, `Branch`, `Route`, `WiringError`, `resolve_wiring` (Plan 1); `node_updates.apply_update`
- Produces:
  - `wiring.Ref = str | Callable[..., Any]`; `NodeSpec(name, handler: Ref, requires=(), wrapped: bool = True)`; `Branch(source, router: Ref, routes, requires=())`
  - `wiring.resolve_ref(owner: Any, ref: Ref) -> Callable`
  - `runner.Completed(state: dict)`, `runner.Interrupted(next_node: str, state: dict)`, `runner.StepLimitExceeded(RuntimeError)`
  - `runner.WorkflowRunner(wiring: Wiring, owner: Any, *, step_limit: int, interrupt_before: Sequence[str] = (), wrap: Callable[[str, Callable], Callable] | None = None)` with `stream(state: Mapping, *, start_at: str | None = None) -> AsyncIterator[dict[str, Any]]` and property `outcome: Completed | Interrupted | None`
  - 중단 신호 chunk: `{"__interrupt__": (next_node,)}` — LangGraph 와 같은 키

- [ ] **Step 1: 러너 테스트를 쓴다**

`tests/workflow/runtime/test_runner.py`:
```python
"""네이티브 러너 (spec 2026-10-13 §4.2). 배선 표를 해석해 LangGraph updates 모드와 같은 chunk 를 낸다."""

import pytest

from neos.workflow.runtime.runner import Completed, Interrupted, StepLimitExceeded, WorkflowRunner
from neos.workflow.state import SearchResult
from neos.workflow.topology import END, START
from neos.workflow.wiring import Branch, Edge, NodeSpec, Route, Wiring, WiringError

pytestmark = [pytest.mark.no_db, pytest.mark.asyncio]

A = SearchResult(source="web", title="A", content="a", url="https://a")


class Owner:
    def __init__(self, label="end"):
        self.label = label
        self.calls: list[str] = []

    async def first(self, state):
        self.calls.append("first")
        return {"search_results": [A], "final_response": "draft"}

    async def second(self, state):
        self.calls.append("second")
        return {"final_response": state["final_response"] + "!"}

    def route(self, state):
        return self.label


def _wiring(**kw) -> Wiring:
    return Wiring(
        nodes=(NodeSpec("first", "first"), NodeSpec("second", "second")),
        edges=(Edge(START, "first"),),
        branches=(
            Branch("first", "route", (Route("again", "second"), Route("end", END))),
        )
        if kw.get("branch", True)
        else (),
        interrupt_before=kw.get("interrupt_before", ()),
    )


async def _drain(runner, state, **kw):
    return [chunk async for chunk in runner.stream(state, **kw)]


async def test_chunks_have_the_langgraph_updates_shape_and_state_folds() -> None:
    owner = Owner(label="again")
    wiring = Wiring(
        nodes=(NodeSpec("first", "first"), NodeSpec("second", "second")),
        edges=(Edge(START, "first"), Edge("second", END)),
        branches=(Branch("first", "route", (Route("again", "second"), Route("end", END))),),
    )
    runner = WorkflowRunner(wiring, owner, step_limit=10)
    chunks = await _drain(runner, {"search_results": [], "final_response": None})
    assert chunks == [
        {"first": {"search_results": [A], "final_response": "draft"}},
        {"second": {"final_response": "draft!"}},
    ]
    assert isinstance(runner.outcome, Completed)
    assert runner.outcome.state["search_results"] == [A]
    assert runner.outcome.state["final_response"] == "draft!"


async def test_accumulating_fields_append_across_nodes() -> None:
    class Twice(Owner):
        async def second(self, state):
            return {"search_results": [A]}

    wiring = Wiring(
        nodes=(NodeSpec("first", "first"), NodeSpec("second", "second")),
        edges=(Edge(START, "first"), Edge("first", "second"), Edge("second", END)),
        branches=(),
    )
    runner = WorkflowRunner(wiring, Twice(), step_limit=10)
    await _drain(runner, {"search_results": []})
    assert runner.outcome.state["search_results"] == [A, A]


async def test_an_interrupt_stops_before_the_gated_node() -> None:
    owner = Owner(label="again")
    runner = WorkflowRunner(_wiring(), owner, step_limit=10, interrupt_before=("second",))
    chunks = await _drain(runner, {"search_results": [], "final_response": None})
    assert chunks[-1] == {"__interrupt__": ("second",)}
    assert owner.calls == ["first"]
    assert isinstance(runner.outcome, Interrupted)
    assert runner.outcome.next_node == "second"
    assert runner.outcome.state["final_response"] == "draft"


async def test_resuming_at_the_gated_node_runs_it() -> None:
    owner = Owner()
    wiring = Wiring(
        nodes=(NodeSpec("first", "first"), NodeSpec("second", "second")),
        edges=(Edge(START, "first"), Edge("second", END)),
        branches=(Branch("first", "route", (Route("again", "second"), Route("end", END))),),
        interrupt_before=("second",),
    )
    runner = WorkflowRunner(wiring, owner, step_limit=10, interrupt_before=("second",))
    await _drain(runner, {"final_response": "kept"}, start_at="second")
    assert owner.calls == ["second"]
    assert runner.outcome.state["final_response"] == "kept!"


async def test_the_step_limit_stops_a_loop() -> None:
    class Loop(Owner):
        def route(self, state):
            return "again"

        async def second(self, state):
            return {}

    wiring = Wiring(
        nodes=(NodeSpec("first", "first"), NodeSpec("second", "second")),
        edges=(Edge(START, "first"), Edge("second", "first")),
        branches=(Branch("first", "route", (Route("again", "second"), Route("end", END))),),
    )
    runner = WorkflowRunner(wiring, Loop(), step_limit=5)
    with pytest.raises(StepLimitExceeded):
        await _drain(runner, {"search_results": []})


async def test_an_unknown_label_is_a_wiring_error() -> None:
    runner = WorkflowRunner(_wiring(), Owner(label="nowhere"), step_limit=10)
    with pytest.raises(WiringError, match="nowhere"):
        await _drain(runner, {"search_results": [], "final_response": None})


async def test_callable_refs_and_the_wrap_hook() -> None:
    seen: list[str] = []

    async def handler(state):
        return {"final_response": "x"}

    def wrap(node, fn):
        async def run(state):
            seen.append(node)
            return await fn(state)

        return run

    wiring = Wiring(
        nodes=(NodeSpec("solo", handler), NodeSpec("raw", handler, wrapped=False)),
        edges=(Edge(START, "solo"), Edge("solo", "raw"), Edge("raw", END)),
        branches=(),
    )
    runner = WorkflowRunner(wiring, object(), step_limit=10, wrap=wrap)
    await _drain(runner, {})
    assert seen == ["solo"]


async def test_two_unconditional_exits_are_rejected_as_parallel() -> None:
    wiring = Wiring(
        nodes=(NodeSpec("first", "first"), NodeSpec("second", "second")),
        edges=(Edge(START, "first"), Edge("first", "second"), Edge("first", END)),
        branches=(),
    )
    with pytest.raises(WiringError, match="parallel"):
        WorkflowRunner(wiring, Owner(), step_limit=10)


async def test_the_static_table_builds_a_runner() -> None:
    from neos.workflow.graph import MultiAgentWorkflow
    from neos.workflow.wiring import resolve_wiring

    for flags in ({}, {"skill_execution": False, "execution_approval": False}):
        WorkflowRunner(resolve_wiring(flags), MultiAgentWorkflow, step_limit=50)
```

> 마지막 테스트는 정적 표의 모든 핸들러·라우터 이름이 해석되는지만 본다(클래스에서 `getattr` — 바운드가 아니어도 된다).

Run: `NEOS_ENV=default GOOGLE_API_KEY=test-key python -m pytest tests/workflow/runtime/test_runner.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'neos.workflow.runtime.runner'`

- [ ] **Step 2: 배선 표의 참조를 넓힌다**

`neos/workflow/wiring.py`:
- `from collections.abc import Mapping` 줄을 `from collections.abc import Callable, Mapping` 로, `from dataclasses import dataclass` 아래에 `from typing import Any` 를 더한다
- `Requires = …` 아래에:
```python
# 노드 핸들러·분기 라우터를 가리키는 값. 정적 표는 `MultiAgentWorkflow` 의 메서드 이름(str)을,
# 설계 그래프(`runtime/designed.py`)는 이미 바인딩한 호출 가능 객체를 넣는다.
Ref = str | Callable[..., Any]
```
- `NodeSpec` 을:
```python
@dataclass(frozen=True)
class NodeSpec:
    name: str
    handler: Ref  # 메서드 이름 또는 호출 가능 객체
    requires: Requires = ()
    # 노드 경계 정규화(`node_updates.wrap_node`)로 감쌀지. 서브에이전트 템플릿 노드는 감싸지 않는다
    # -- 자기 걸음 상태를 스스로 관리한다(`build_ephemeral_workflow` 와 같은 규칙).
    wrapped: bool = True
```
- `Branch.router: str` 를 `router: Ref` 로, 주석을 "메서드 이름 또는 호출 가능 객체 -- 상태를 받아 라벨을 돌려준다" 로
- 파일 끝에:
```python
def resolve_ref(owner: Any, ref: Ref) -> Callable[..., Any]:
    """표의 참조를 호출 가능 객체로. LangGraph 어댑터와 네이티브 러너가 같은 규칙을 쓴다."""
    return getattr(owner, ref) if isinstance(ref, str) else ref
```

`neos/workflow/runtime/langgraph_adapter.py`: `from neos.workflow.wiring import Wiring` 를 `from neos.workflow.wiring import Wiring, resolve_ref` 로, `handler = getattr(owner, spec.handler)` 를 `handler = resolve_ref(owner, spec.handler)` 로, `graph.add_node(spec.name, wrap(spec.name, handler) if wrap else handler)` 를 `graph.add_node(spec.name, wrap(spec.name, handler) if wrap and spec.wrapped else handler)` 로, `getattr(owner, branch.router)` 를 `resolve_ref(owner, branch.router)` 로 바꾼다.

Run: `NEOS_ENV=default GOOGLE_API_KEY=test-key python -m pytest tests/workflow/test_wiring.py -q`
Expected: PASS(정적 표는 전부 str 이라 해시·동등성이 그대로다)

- [ ] **Step 3: 러너를 쓴다**

`neos/workflow/runtime/runner.py`:
```python
"""네이티브 러너 -- 배선 표를 해석해 노드를 차례로 돌린다 (spec 2026-10-13 §4.2).

- 한 걸음: 핸들러 → 갱신을 `apply_update`(리듀서 의미론)로 접기 → `{node: update}` chunk →
  `Edge` 또는 `Branch` 라우터로 다음 노드. `END` 면 멈춘다
- chunk 모양은 LangGraph updates 모드와 같다 -- `execute_workflow` 의 진행 추적이 그대로 읽는다
- `interrupt_before` 노드에 닿으면 **실행 전에** 멈춘다. 예외가 아니라 결과(`Interrupted`)이고,
  LangGraph 와 같은 `{"__interrupt__": (next_node,)}` chunk 를 마지막으로 낸다
- `start_at` 은 승인 재개용이다 -- 그 노드가 게이트여도 첫 걸음은 실행한다(사람이 이미 결정했다)
- 순차만 돈다(spec §4.10). 한 노드에서 무조건 출구가 둘이면 만들 때 거절한다
- 저장하지 않는다 -- 저장은 턴 경계(`runtime/turns.py`)가 한다
"""

from __future__ import annotations

import inspect
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from neos.workflow.runtime.node_updates import apply_update
from neos.workflow.topology import END, START
from neos.workflow.wiring import Wiring, WiringError, resolve_ref

INTERRUPT_KEY = "__interrupt__"


@dataclass(frozen=True)
class Completed:
    state: dict[str, Any]


@dataclass(frozen=True)
class Interrupted:
    next_node: str
    state: dict[str, Any]


class StepLimitExceeded(RuntimeError):
    pass


class WorkflowRunner:
    def __init__(
        self,
        wiring: Wiring,
        owner: Any,
        *,
        step_limit: int,
        interrupt_before: Sequence[str] = (),
        wrap: Callable[[str, Callable], Callable] | None = None,
    ) -> None:
        self._step_limit = step_limit
        self._interrupt_before = frozenset(interrupt_before)
        self._handlers: dict[str, Callable] = {}
        for spec in wiring.nodes:
            handler = resolve_ref(owner, spec.handler)
            self._handlers[spec.name] = wrap(spec.name, handler) if wrap and spec.wrapped else handler
        self._edges: dict[str, str] = {}
        for edge in wiring.edges:
            if edge.source in self._edges:
                raise WiringError(
                    f"{edge.source}: 무조건 출구가 둘 이상이다(parallel) -- 네이티브 러너는 순차만 돈다"
                )
            self._edges[edge.source] = edge.target
        self._branches: dict[str, tuple[Callable, dict[str, str]]] = {}
        for branch in wiring.branches:
            if branch.source in self._edges:
                raise WiringError(f"{branch.source}: 무조건 출구와 분기가 함께 있다(parallel)")
            self._branches[branch.source] = (
                resolve_ref(owner, branch.router),
                wiring.path_map(branch),
            )
        if START not in self._edges:
            raise WiringError("START 에서 나가는 엣지가 없다")
        self._entry = self._edges[START]
        self._outcome: Completed | Interrupted | None = None

    @property
    def outcome(self) -> Completed | Interrupted | None:
        return self._outcome

    async def stream(
        self, state: Mapping[str, Any], *, start_at: str | None = None
    ) -> AsyncIterator[dict[str, Any]]:
        self._outcome = None
        current = dict(state)
        node = start_at or self._entry
        steps = 0
        while node != END:
            resuming_here = start_at is not None and steps == 0
            if node in self._interrupt_before and not resuming_here:
                self._outcome = Interrupted(next_node=node, state=current)
                yield {INTERRUPT_KEY: (node,)}
                return
            steps += 1
            if steps > self._step_limit:
                raise StepLimitExceeded(f"걸음 상한 {self._step_limit} 을 넘었다 (마지막 노드 {node})")
            handler = self._handlers.get(node)
            if handler is None:
                raise WiringError(f"켜지지 않은 노드로 갔다: {node}")
            result = handler(current)
            if inspect.isawaitable(result):
                result = await result
            update = dict(result or {})
            current = apply_update(current, update)
            yield {node: update}
            node = self._next(node, current)
        self._outcome = Completed(state=current)

    def _next(self, node: str, state: Mapping[str, Any]) -> str:
        if node in self._branches:
            router, path_map = self._branches[node]
            label = router(state)
            if label not in path_map:
                raise WiringError(f"{node}: 라우터가 경로 표에 없는 라벨을 냈다: {label!r}")
            return path_map[label]
        if node in self._edges:
            return self._edges[node]
        raise WiringError(f"{node}: 출구가 없다")
```

Run: `NEOS_ENV=default GOOGLE_API_KEY=test-key python -m pytest tests/workflow/runtime/test_runner.py tests/workflow/test_wiring.py -q`
Expected: PASS

- [ ] **Step 4: 커밋**

```bash
git add neos/workflow/wiring.py neos/workflow/runtime/langgraph_adapter.py neos/workflow/runtime/runner.py tests/workflow/runtime/test_runner.py
git commit -m "feat(workflow): native sequential runner over the wiring table (spec §4.2)

The runner interprets the same wiring table the LangGraph adapter compiles,
folds updates with node_updates.apply_update, emits LangGraph-shaped update
chunks, stops before gated nodes with an Interrupted outcome, resumes with
start_at, and rejects parallel exits at construction. Wiring refs may now be
callables (designed graphs) as well as method names (static table)."
```

---

### Task 3: 설계 그래프를 순차 배선으로

**Files:**
- Create: `neos/workflow/runtime/designed.py`
- Modify: `neos/workflow/topology.py` (`validate_topology(..., allow_parallel: bool = True)` · 규칙 `parallel_unsupported`)
- Modify: `neos/workflow/graph_design_ledger.py` (`design_graph_or_fallback(..., allow_parallel: bool = True)` 를 `validate_topology` 로 전달)
- Test: `tests/workflow/runtime/test_designed.py`

**Interfaces:**
- Consumes: `GraphTopology`, `validate_topology`, `NODE_CONTRACTS`, `_INTERRUPT_GATED_NODES`(`neos.workflow.graph`), `SubagentNodeHost.template_names` · `handler_for(node)` · `route_for(node, done_targets)` (`neos/workflow/subagent_nodes.py`); `Wiring`, `NodeSpec`, `Edge`, `Branch`, `Route`, `WiringError`
- Produces:
  - `designed.designed_wiring(topology: GraphTopology, owner: Any, *, subagent_host: Any = None, gated_nodes: frozenset[str]) -> Wiring`
  - `topology.validate_topology(..., allow_parallel: bool = True)` — `False` 면 출구가 둘 이상인 노드(자기 반복 제외)마다 `TopologyViolation(rule="parallel_unsupported", node=…, detail=…)`
  - `graph_design_ledger.design_graph_or_fallback(..., allow_parallel: bool = True)`

- [ ] **Step 1: 테스트를 쓴다**

`tests/workflow/runtime/test_designed.py`:
```python
"""설계 그래프 → 순차 배선 (spec 2026-10-13 §4.10)."""

import pytest

from neos.workflow.contracts import NODE_CONTRACTS
from neos.workflow.enums import WorkflowNode as N
from neos.workflow.runtime.designed import designed_wiring
from neos.workflow.topology import END, GRAPH_ENTRY_WRITES, START, GraphTopology, validate_topology
from neos.workflow.wiring import WiringError

pytestmark = pytest.mark.no_db

_CHAIN = (N.QUERY_CLS.value, N.SEARCH_ORCHESTRATOR.value, N.RESP_GENERATOR.value)


def _chain() -> GraphTopology:
    return GraphTopology(
        nodes=_CHAIN,
        edges=((START, _CHAIN[0]), (_CHAIN[0], _CHAIN[1]), (_CHAIN[1], _CHAIN[2]), (_CHAIN[2], END)),
        initial_writes=GRAPH_ENTRY_WRITES,
    )


def _fanout() -> GraphTopology:
    return GraphTopology(
        nodes=_CHAIN,
        edges=((START, _CHAIN[0]), (_CHAIN[0], _CHAIN[1]), (_CHAIN[0], _CHAIN[2]), (_CHAIN[1], END), (_CHAIN[2], END)),
        initial_writes=GRAPH_ENTRY_WRITES,
    )


def _workflow():
    import neos.workflow.graph  # noqa: F401 -- 계약 등록

    from neos.workflow.graph import MultiAgentWorkflow

    return MultiAgentWorkflow.__new__(MultiAgentWorkflow)


def test_a_chain_becomes_bound_static_edges() -> None:
    wiring = designed_wiring(_chain(), _workflow(), gated_nodes=frozenset())
    assert [spec.name for spec in wiring.nodes] == list(_CHAIN)
    assert all(callable(spec.handler) for spec in wiring.nodes)
    assert [(e.source, e.target) for e in wiring.edges][0] == (START, _CHAIN[0])
    assert wiring.branches == ()


def test_gated_nodes_present_become_interrupts() -> None:
    gated = frozenset({N.SEARCH_ORCHESTRATOR.value})
    wiring = designed_wiring(_chain(), _workflow(), gated_nodes=gated)
    assert wiring.interrupt_before == (N.SEARCH_ORCHESTRATOR.value,)


def test_parallel_designs_are_violations_only_when_disallowed() -> None:
    allowed = validate_topology(_fanout(), contracts=NODE_CONTRACTS)
    disallowed = validate_topology(_fanout(), contracts=NODE_CONTRACTS, allow_parallel=False)
    assert not [v for v in allowed if v.rule == "parallel_unsupported"]
    assert [v.node for v in disallowed if v.rule == "parallel_unsupported"] == [_CHAIN[0]]


def test_a_template_node_routes_to_itself_or_its_single_follower() -> None:
    class Host:
        template_names = frozenset({"tpl"})

        def handler_for(self, node):
            async def run(state):
                return {}

            return run

        def route_for(self, node, done):
            done = list(done)
            return lambda state: [node] if state.get("again") else done

    topology = GraphTopology(
        nodes=(_CHAIN[0], "tpl", _CHAIN[2]),
        edges=((START, _CHAIN[0]), (_CHAIN[0], "tpl"), ("tpl", "tpl"), ("tpl", _CHAIN[2]), (_CHAIN[2], END)),
        initial_writes=GRAPH_ENTRY_WRITES,
    )
    wiring = designed_wiring(topology, _workflow(), subagent_host=Host(), gated_nodes=frozenset())
    tpl = next(spec for spec in wiring.nodes if spec.name == "tpl")
    assert tpl.wrapped is False
    branch = next(b for b in wiring.branches if b.source == "tpl")
    assert branch.router({"again": True}) == "tpl"
    assert branch.router({}) == _CHAIN[2]


def test_a_template_fanning_out_is_rejected() -> None:
    class Host:
        template_names = frozenset({"tpl"})

        def handler_for(self, node):
            return lambda state: {}

        def route_for(self, node, done):
            done = list(done)
            return lambda state: done

    topology = GraphTopology(
        nodes=("tpl", _CHAIN[1], _CHAIN[2]),
        edges=((START, "tpl"), ("tpl", _CHAIN[1]), ("tpl", _CHAIN[2]), (_CHAIN[1], END), (_CHAIN[2], END)),
        initial_writes=GRAPH_ENTRY_WRITES,
    )
    wiring = designed_wiring(topology, _workflow(), subagent_host=Host(), gated_nodes=frozenset())
    branch = next(b for b in wiring.branches if b.source == "tpl")
    with pytest.raises(WiringError, match="parallel"):
        branch.router({})
```

Run: `NEOS_ENV=default GOOGLE_API_KEY=test-key python -m pytest tests/workflow/runtime/test_designed.py -q`
Expected: FAIL — `ModuleNotFoundError` 와 `TypeError: validate_topology() got an unexpected keyword argument 'allow_parallel'`

- [ ] **Step 2: 병렬 규칙을 더한다**

`neos/workflow/topology.py` 의 `validate_topology` 시그니처에 키워드 인자를 더한다(기존 인자 뒤, 기본값 있음):
```python
    allow_parallel: bool = True,
```
docstring 에 한 문단을 더한다: "`allow_parallel=False` 면 출구가 둘 이상인 노드(자기 반복 간선 제외)를 `parallel_unsupported` 로 거절한다 -- 네이티브 러너는 순차만 돈다(spec 2026-10-13 §4.10). 기본값은 지금 동작(허용)이다." 그리고 함수가 `violations` 를 돌려주기 직전에:
```python
    if not allow_parallel:
        exits: dict[str, int] = {}
        for source, target in topology.edges:
            if source != target:
                exits[source] = exits.get(source, 0) + 1
        for source in sorted(name for name, count in exits.items() if count > 1):
            violations.append(
                TopologyViolation(
                    rule="parallel_unsupported",
                    node=source,
                    detail=f"출구 {exits[source]}개 -- 네이티브 러너는 순차만 돈다",
                )
            )
```
`TopologyViolation` 의 필수 필드가 `rule`·`node`·`detail` 외에 더 있으면 기존 위반 생성 코드와 같은 모양으로 채운다.

`neos/workflow/graph_design_ledger.py` 의 `design_graph_or_fallback` 에 같은 키워드 인자 `allow_parallel: bool = True` 를 더하고, 함수 안의 `validate_topology(...)` 호출(들)에 `allow_parallel=allow_parallel` 을 넘긴다.

- [ ] **Step 3: 설계 배선을 쓴다**

`neos/workflow/runtime/designed.py`:
```python
"""승인된 설계 토폴로지 → 순차 배선 (spec 2026-10-13 §4.10).

LangGraph 경로의 `build_ephemeral_workflow` 와 같은 규칙을 배선 표로 옮긴다.
- 계약 노드는 `NODE_CONTRACTS[name].handler` 를 `owner` 에 바인딩해 넣는다
- 서브에이전트 템플릿 노드는 호스트의 핸들러를 감싸지 않고 넣고, 나가는 간선을 분기로 바꾼다:
  자식이 살아 있으면 자기 자신, 끝났으면 후속 하나. 후속이 둘 이상이면 병렬이라 거절한다
- 게이트 노드가 토폴로지에 있으면 `interrupt_before` 가 된다
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from neos.workflow.contracts import NODE_CONTRACTS
from neos.workflow.topology import GraphTopology
from neos.workflow.wiring import Branch, Edge, NodeSpec, Route, Wiring, WiringError


def _label_router(node: str, route: Callable[[Any], list[str]]) -> Callable[[Any], str]:
    def router(state: Any) -> str:
        targets = list(route(state))
        if len(targets) != 1:
            raise WiringError(f"{node}: 템플릿 후속이 {len(targets)}개다(parallel) -- 네이티브 러너는 순차만 돈다")
        return targets[0]

    router.__name__ = f"route_{node}"
    return router


def designed_wiring(
    topology: GraphTopology,
    owner: Any,
    *,
    subagent_host: Any = None,
    gated_nodes: frozenset[str],
) -> Wiring:
    templates = frozenset(subagent_host.template_names) if subagent_host is not None else frozenset()
    nodes: list[NodeSpec] = []
    for name in topology.nodes:
        if name in templates:
            nodes.append(NodeSpec(name, subagent_host.handler_for(name), wrapped=False))
        else:
            handler = NODE_CONTRACTS[name].handler.__get__(owner, type(owner))
            nodes.append(NodeSpec(name, handler))
    edges = tuple(
        Edge(source, target) for source, target in topology.edges if source not in templates
    )
    branches: list[Branch] = []
    for name in topology.nodes:
        if name not in templates:
            continue
        done = [target for source, target in topology.edges if source == name and target != name]
        router = _label_router(name, subagent_host.route_for(name, done))
        branches.append(
            Branch(name, router, (Route(name, name), *(Route(target, target) for target in done)))
        )
    interrupts = tuple(sorted(set(topology.nodes) & gated_nodes))
    return Wiring(tuple(nodes), edges, tuple(branches), interrupts)
```

Run: `NEOS_ENV=default GOOGLE_API_KEY=test-key python -m pytest tests/workflow/runtime/test_designed.py tests/workflow/test_topology_validator.py tests/workflow/test_graph_design_wiring.py -q`
Expected: PASS(기존 검증기·설계 테스트는 기본값 `allow_parallel=True` 라 그대로다)

- [ ] **Step 4: 커밋**

```bash
git add neos/workflow/runtime/designed.py neos/workflow/topology.py neos/workflow/graph_design_ledger.py tests/workflow/runtime/test_designed.py
git commit -m "feat(workflow): designed topologies become sequential wiring; parallel designs are a violation when disallowed (spec §4.10)"
```

---

### Task 4: 세션 저장소와 상태 이어받기

**Files:**
- Create: `neos/workflow/runtime/sessions.py`
- Create: `db/migrations/096_add_workflow_sessions.sql`
- Modify: `neos/config/schema.py` (`WorkflowSessionConfig`, `WorkflowConfig.session`)
- Modify: `neos/observability/metrics.py` (카운터 셋)
- Modify: `neos/workflow/graph.py` (`_create_initial_state` 에 승인 필드 리셋)
- Test: `tests/workflow/runtime/test_sessions.py`, `tests/workflow/test_initial_state_resets.py`

**Interfaces:**
- Consumes: `state_codec.encode_state` · `decode_state` · `CodecError` (Task 1); `node_updates.apply_update` · `reducer_kinds`
- Produces:
  - `sessions.SessionSnapshot(session_id: str, user_id: str, state: dict, version: int)`
  - `sessions.SessionConflict(RuntimeError)`
  - `sessions.SessionStore` 프로토콜: `load(session_id) -> SessionSnapshot | None` · `save(session_id, *, user_id, state, expected_version: int | None) -> int` · `reset(session_id) -> bool` · `purge_older_than(cutoff: datetime) -> int`
  - `sessions.InMemorySessionStore()`, `sessions.PostgresSessionStore(session_factory)`
  - `sessions.carry(saved: Mapping | None, initial: Mapping) -> dict`
  - `sessions.trim(state: Mapping, max_items: int) -> tuple[dict, dict[str, int]]`
  - 설정 `settings.config.workflow.session.max_carried_items: int`(기본 200)
  - 메트릭 `workflow_session_trimmed_total{field}`, `workflow_session_conflicts_total`, `workflow_session_failures_total{op}`

- [ ] **Step 1: 저장소 계약 테스트를 쓴다**

`tests/workflow/runtime/test_sessions.py`:
```python
"""세션 저장소 (spec 2026-10-13 §4.3). 메모리 구현과 Postgres 구현이 같은 계약을 지난다."""

from datetime import UTC, datetime, timedelta

import pytest

from neos.workflow.runtime.sessions import (
    InMemorySessionStore,
    PostgresSessionStore,
    SessionConflict,
    carry,
    trim,
)
from neos.workflow.state import SearchResult

A = SearchResult(source="web", title="A", content="a", url="https://a")
B = SearchResult(source="web", title="B", content="b", url="https://b")


@pytest.fixture(params=["memory", "postgres"])
async def store(request):
    if request.param == "memory":
        yield InMemorySessionStore()
        return
    from sqlalchemy import text

    from neos.database.connection import db_manager

    yield PostgresSessionStore(db_manager.get_session)
    async with await db_manager.get_session() as session:
        await session.execute(text("DELETE FROM workflow_sessions WHERE session_id LIKE 'test-ws-%'"))
        await session.commit()


@pytest.mark.asyncio
async def test_first_save_then_load_roundtrips_types(store) -> None:
    version = await store.save("test-ws-1", user_id="u1", state={"search_results": [A], "q": "x"}, expected_version=None)
    snap = await store.load("test-ws-1")
    assert snap.version == version == 1
    assert snap.user_id == "u1"
    assert snap.state == {"search_results": [A], "q": "x"}
    assert isinstance(snap.state["search_results"][0], SearchResult)


@pytest.mark.asyncio
async def test_save_with_the_loaded_version_wins_and_stale_loses(store) -> None:
    await store.save("test-ws-2", user_id="u1", state={"n": 1}, expected_version=None)
    assert await store.save("test-ws-2", user_id="u1", state={"n": 2}, expected_version=1) == 2
    with pytest.raises(SessionConflict):
        await store.save("test-ws-2", user_id="u1", state={"n": 3}, expected_version=1)
    assert (await store.load("test-ws-2")).state == {"n": 2}


@pytest.mark.asyncio
async def test_a_second_first_save_conflicts(store) -> None:
    await store.save("test-ws-3", user_id="u1", state={}, expected_version=None)
    with pytest.raises(SessionConflict):
        await store.save("test-ws-3", user_id="u1", state={}, expected_version=None)


@pytest.mark.asyncio
async def test_reset_removes_the_session(store) -> None:
    await store.save("test-ws-4", user_id="u1", state={"n": 1}, expected_version=None)
    assert await store.reset("test-ws-4") is True
    assert await store.load("test-ws-4") is None
    assert await store.reset("test-ws-4") is False


@pytest.mark.asyncio
async def test_purge_removes_only_old_rows(store) -> None:
    await store.save("test-ws-5", user_id="u1", state={}, expected_version=None)
    assert await store.purge_older_than(datetime.now(UTC) - timedelta(days=1)) == 0
    assert await store.load("test-ws-5") is not None
    assert await store.purge_older_than(datetime.now(UTC) + timedelta(seconds=1)) >= 1
    assert await store.load("test-ws-5") is None


@pytest.mark.no_db
def test_carry_applies_the_turn_input_as_an_update() -> None:
    saved = {"search_results": [A], "skill_sources": [A], "kept": 1}
    initial = {"search_results": [], "skill_sources": None, "original_query": "q2"}
    merged = carry(saved, initial)
    assert merged["search_results"] == [A]  # 누적은 남는다
    assert merged["skill_sources"] is None  # 교체 필드는 이번 턴 값
    assert merged["kept"] == 1  # 입력이 건드리지 않는 키는 이어진다
    assert merged["original_query"] == "q2"
    assert carry(None, initial) == initial


@pytest.mark.no_db
def test_trim_keeps_the_newest_accumulated_items() -> None:
    state = {"search_results": [A, B, A], "errors": ["e"], "other": [1, 2, 3]}
    trimmed, cut = trim(state, max_items=2)
    assert trimmed["search_results"] == [B, A]
    assert trimmed["errors"] == ["e"]
    assert trimmed["other"] == [1, 2, 3]  # 누적 필드가 아니다
    assert cut == {"search_results": 1}
```

`tests/workflow/test_initial_state_resets.py`:
```python
"""턴 리셋 필드 (spec 2026-10-13 §4.3, S-PEND). 이어받은 승인이 다음 턴을 막지 않는다."""

import pytest

pytestmark = pytest.mark.no_db


def test_approval_fields_are_turn_scoped() -> None:
    from neos.workflow.graph import MultiAgentWorkflow

    workflow = MultiAgentWorkflow.__new__(MultiAgentWorkflow)
    state = workflow._create_initial_state({"user_id": "u", "session_id": "s", "query": "q"})
    assert state["pending_approvals"] == []
    assert state["approval_decision"] is None
```

Run: `NEOS_ENV=default GOOGLE_API_KEY=test-key python -m pytest tests/workflow/runtime/test_sessions.py tests/workflow/test_initial_state_resets.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'neos.workflow.runtime.sessions'`, 리셋 테스트는 `KeyError: 'pending_approvals'`

> `_create_initial_state` 가 `MultiAgentWorkflow.__new__` 인스턴스에서 다른 속성을 읽어 실패하면 `MultiAgentWorkflow()` 로 만든다(다른 워크플로 테스트처럼).

- [ ] **Step 2: 마이그레이션과 설정·메트릭**

`db/migrations/096_add_workflow_sessions.sql`:
```sql
-- 채팅 워크플로의 세션 상태 (spec 2026-10-13 §4.3, W1 Plan 2).
--
-- 세션(웹은 conversation_id, 채널은 세션 키)마다 최신 스냅샷 한 행. LangGraph 체크포인터
-- (`langgraph_checkpoints`)를 대신한다 -- 그쪽은 Plan 3 에서 지운다.
-- - `state` 는 `neos/workflow/runtime/state_codec.py` 의 출력(타입 태그 JSON)
-- - `version` 은 낙관적 잠금 -- 겹친 턴은 나중 저장이 진다
-- - `user_id` 에 FK 를 걸지 않는다: 채널 사용자는 users 행이 없을 수 있다
-- - 보존 정리는 `updated_at` 으로(30일)
--
-- 두 번 적용해도 같다.

CREATE TABLE IF NOT EXISTS workflow_sessions (
    session_id  TEXT         PRIMARY KEY,
    user_id     TEXT         NOT NULL,
    state       JSONB        NOT NULL,
    version     INTEGER      NOT NULL CHECK (version >= 1),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_workflow_sessions_updated_at
    ON workflow_sessions (updated_at);
```

`neos/config/schema.py` — `SkillExecutionConfig` 정의 바로 아래에:
```python
class WorkflowSessionConfig(StrictConfigModel):
    """채팅 워크플로 세션 상태 (spec 2026-10-13 §4.3)."""

    max_carried_items: int = Field(
        default=200,
        ge=1,
        description="저장 때 누적 필드(operator.add)마다 남길 최근 항목 수. Plan 3 라이브 dry run 에서 다시 정한다.",
    )
```
`WorkflowConfig` 의 `skill_execution` 필드 아래에:
```python
    session: WorkflowSessionConfig = Field(default_factory=WorkflowSessionConfig)
```

`neos/observability/metrics.py` — `workflow_update_rejected_total` 정의 바로 아래에:
```python
        # 세션 상태 (spec 2026-10-13 §4.3). 올리는 곳은 neos/workflow/runtime/turns.py 다.
        self.workflow_session_trimmed_total = Counter(
            "workflow_session_trimmed_total",
            "Accumulated items dropped from a saved workflow session by the carry cap",
            ["field"],
            registry=self.registry,
        )
        self.workflow_session_conflicts_total = Counter(
            "workflow_session_conflicts_total",
            "Workflow session saves that lost an optimistic-lock race",
            registry=self.registry,
        )
        self.workflow_session_failures_total = Counter(
            "workflow_session_failures_total",
            "Workflow session load/save failures (the turn continues)",
            ["op"],
            registry=self.registry,
        )
```

`neos/workflow/graph.py` `_create_initial_state` 의 `approval_outcome=None,` 바로 아래에:
```python
            # 턴 단위 승인 필드 (spec 2026-10-13 §4.3, S-PEND) -- 상태가 이어져도 버려진 승인이
            # 다음 턴의 라우터를 needs_approval 로 보내지 않게 한다. 승인 재개는 초기 상태를
            # 다시 만들지 않으므로 이 리셋을 지나지 않는다.
            pending_approvals=[],
            approval_decision=None,
```

- [ ] **Step 3: 저장소를 쓴다**

`neos/workflow/runtime/sessions.py`:
```python
"""세션 저장소와 상태 이어받기 (spec 2026-10-13 §4.3).

**규칙: 이번 턴의 입력은 이어받은 상태 위의 갱신이다** -- `carry(saved, initial)` 이 리듀서
의미론(`node_updates.apply_update`)으로 병합한다. 이어받을 필드 목록을 따로 두지 않는다.

세션당 최신 스냅샷 한 행. 저장은 낙관적 잠금이다 -- 겹친 턴은 나중 저장이 `SessionConflict` 로
진다. 턴 내내 행 잠금을 잡지 않는다.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import text

from neos.workflow.runtime.node_updates import apply_update, reducer_kinds
from neos.workflow.runtime.state_codec import decode_state, encode_state


@dataclass(frozen=True)
class SessionSnapshot:
    session_id: str
    user_id: str
    state: dict[str, Any]
    version: int


class SessionConflict(RuntimeError):
    pass


class SessionStore(Protocol):
    async def load(self, session_id: str) -> SessionSnapshot | None: ...

    async def save(
        self, session_id: str, *, user_id: str, state: Mapping[str, Any], expected_version: int | None
    ) -> int: ...

    async def reset(self, session_id: str) -> bool: ...

    async def purge_older_than(self, cutoff: datetime) -> int: ...


def carry(saved: Mapping[str, Any] | None, initial: Mapping[str, Any]) -> dict[str, Any]:
    if not saved:
        return dict(initial)
    return apply_update(saved, initial)


def trim(state: Mapping[str, Any], max_items: int) -> tuple[dict[str, Any], dict[str, int]]:
    kinds = reducer_kinds()
    trimmed = dict(state)
    cut: dict[str, int] = {}
    for key, kind in kinds.items():
        value = trimmed.get(key)
        if kind == "append" and isinstance(value, list) and len(value) > max_items:
            cut[key] = len(value) - max_items
            trimmed[key] = value[-max_items:]
    return trimmed, cut


class InMemorySessionStore:
    def __init__(self) -> None:
        self._rows: dict[str, tuple[str, str, int, datetime]] = {}
        self._lock = asyncio.Lock()

    async def load(self, session_id: str) -> SessionSnapshot | None:
        row = self._rows.get(session_id)
        if row is None:
            return None
        user_id, payload, version, _ = row
        return SessionSnapshot(session_id, user_id, decode_state(json.loads(payload)), version)

    async def save(
        self, session_id: str, *, user_id: str, state: Mapping[str, Any], expected_version: int | None
    ) -> int:
        payload = json.dumps(encode_state(state))
        async with self._lock:
            row = self._rows.get(session_id)
            current = row[2] if row is not None else None
            if current != expected_version:
                raise SessionConflict(f"{session_id}: version {current} != expected {expected_version}")
            version = 1 if current is None else current + 1
            self._rows[session_id] = (user_id, payload, version, datetime.now(UTC))
            return version

    async def reset(self, session_id: str) -> bool:
        async with self._lock:
            return self._rows.pop(session_id, None) is not None

    async def purge_older_than(self, cutoff: datetime) -> int:
        async with self._lock:
            old = [key for key, row in self._rows.items() if row[3] < cutoff]
            for key in old:
                del self._rows[key]
            return len(old)


class PostgresSessionStore:
    def __init__(self, session_factory: Callable[[], Awaitable[Any]]) -> None:
        self._session_factory = session_factory

    async def load(self, session_id: str) -> SessionSnapshot | None:
        async with await self._session_factory() as session:
            row = (
                await session.execute(
                    text("SELECT user_id, state, version FROM workflow_sessions WHERE session_id = :sid"),
                    {"sid": session_id},
                )
            ).first()
        if row is None:
            return None
        payload = row[1] if isinstance(row[1], Mapping) else json.loads(row[1])
        return SessionSnapshot(session_id, row[0], decode_state(payload), row[2])

    async def save(
        self, session_id: str, *, user_id: str, state: Mapping[str, Any], expected_version: int | None
    ) -> int:
        payload = json.dumps(encode_state(state))
        async with await self._session_factory() as session:
            async with session.begin():
                if expected_version is None:
                    result = await session.execute(
                        text(
                            """
                            INSERT INTO workflow_sessions (session_id, user_id, state, version, updated_at)
                            VALUES (:sid, :uid, CAST(:state AS JSONB), 1, now())
                            ON CONFLICT (session_id) DO NOTHING
                            RETURNING version
                            """
                        ),
                        {"sid": session_id, "uid": user_id, "state": payload},
                    )
                else:
                    result = await session.execute(
                        text(
                            """
                            UPDATE workflow_sessions
                            SET state = CAST(:state AS JSONB), user_id = :uid,
                                version = version + 1, updated_at = now()
                            WHERE session_id = :sid AND version = :expected
                            RETURNING version
                            """
                        ),
                        {"sid": session_id, "uid": user_id, "state": payload, "expected": expected_version},
                    )
                version = result.scalar_one_or_none()
        if version is None:
            raise SessionConflict(f"{session_id}: expected version {expected_version} lost")
        return int(version)

    async def reset(self, session_id: str) -> bool:
        async with await self._session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    text("DELETE FROM workflow_sessions WHERE session_id = :sid"), {"sid": session_id}
                )
        return bool(result.rowcount)

    async def purge_older_than(self, cutoff: datetime) -> int:
        async with await self._session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    text("DELETE FROM workflow_sessions WHERE updated_at < :cutoff"), {"cutoff": cutoff}
                )
        return int(result.rowcount or 0)
```

Run: `NEOS_ENV=default GOOGLE_API_KEY=test-key python -m pytest tests/workflow/runtime/test_sessions.py tests/workflow/test_initial_state_resets.py -q`
Expected: PASS(Postgres 파라미터 포함 — 테스트 세션이 096 을 적용한다)

Run: `NEOS_ENV=default GOOGLE_API_KEY=test-key python -m pytest tests/workflow tests/config -q -p no:cacheprovider`
Expected: PASS. 리셋으로 깨지는 테스트가 있으면, 그 테스트가 "버려진 승인이 다음 턴에 남는다" 를 기대했는지(S-PEND 를 고정) 본다 — 그렇다면 단언을 고치고 이름을 커밋 메시지에 적는다. 설정 인벤토리 테스트가 `workflow.session.max_carried_items` 문서화를 요구하면 `docs/CONFIGURATION.md`·`docs/CONFIG_INVENTORY.md` 에 기존 표 형식으로 한 줄씩 더한다.

- [ ] **Step 4: 커밋**

```bash
git add neos/workflow/runtime/sessions.py db/migrations/096_add_workflow_sessions.sql neos/config/schema.py neos/observability/metrics.py neos/workflow/graph.py tests/workflow/runtime/test_sessions.py tests/workflow/test_initial_state_resets.py
git commit -m "feat(workflow): session store with optimistic locking and reducer-based carry; approval fields reset per turn (spec §4.3)"
```
(문서를 고쳤으면 함께 `git add`.)

---

### Task 5: 작업 기록

**Files:**
- Create: `neos/workflow/runtime/work.py`
- Create: `db/migrations/097_add_workflow_runs.sql`
- Test: `tests/workflow/runtime/test_work.py`

**Interfaces:**
- Consumes: 없음(독립 저장소)
- Produces:
  - `work.WorkRecord(work_id, entry, kind, user_id, session_id, status, pending, result, delivery, ref_id, parent_work_id, version, created_at, updated_at)` — frozen dataclass
  - `work.WorkConflict(RuntimeError)`
  - `work.WorkStore` 프로토콜: `create(record)` · `get(work_id)` · `waiting_for_session(session_id) -> WorkRecord | None` · `by_ref(kind, ref_id) -> WorkRecord | None` · `transition(work_id, *, expected_version, status, pending=KEEP, result=KEEP) -> WorkRecord`
  - `work.KEEP` (센티널), `work.InMemoryWorkStore()`, `work.PostgresWorkStore(session_factory)`
  - `work.WorkLifecycle(store)` — `start(entry, kind, *, user_id, session_id, delivery, parent=None, ref_id=None) -> str` · `interrupt(work_id, pending: Mapping) -> None` · `complete(work_id, result: Mapping) -> None` · `fail(work_id, error: str) -> None` · `claim(work_id, *, expected_version) -> WorkRecord` · `expire(work_id, *, expected_version) -> WorkRecord`; 속성 `store`
  - `work.entry_and_delivery(user_input: Mapping) -> tuple[str, dict]`
  - 상태 전이: `running → waiting_approval | completed | failed`, `waiting_approval → running | expired`. 그 밖은 `WorkConflict`

- [ ] **Step 1: 테스트를 쓴다**

`tests/workflow/runtime/test_work.py`:
```python
"""작업 기록 (spec 2026-10-13 §4.4). 메모리 구현과 Postgres 구현이 같은 계약을 지난다."""

import pytest

from neos.workflow.runtime.work import (
    InMemoryWorkStore,
    PostgresWorkStore,
    WorkConflict,
    WorkLifecycle,
    entry_and_delivery,
)


@pytest.fixture(params=["memory", "postgres"])
async def lifecycle(request):
    if request.param == "memory":
        yield WorkLifecycle(InMemoryWorkStore())
        return
    from sqlalchemy import text

    from neos.database.connection import db_manager

    yield WorkLifecycle(PostgresWorkStore(db_manager.get_session))
    async with await db_manager.get_session() as session:
        await session.execute(text("DELETE FROM workflow_runs WHERE user_id = 'test-work-user'"))
        await session.commit()


async def _start(lifecycle, session_id="test-work-s1"):
    return await lifecycle.start(
        "web", "workflow", user_id="test-work-user", session_id=session_id,
        delivery={"kind": "sse", "conversation_id": session_id},
    )


@pytest.mark.asyncio
async def test_a_turn_runs_then_completes(lifecycle) -> None:
    work_id = await _start(lifecycle)
    assert work_id.startswith("wk_")
    await lifecycle.complete(work_id, {"final_response": "답", "author": None, "verified_by": None})
    record = await lifecycle.store.get(work_id)
    assert record.status == "completed"
    assert record.result["final_response"] == "답"
    assert record.delivery == {"kind": "sse", "conversation_id": "test-work-s1"}


@pytest.mark.asyncio
async def test_interrupt_claim_and_the_waiting_lookup(lifecycle) -> None:
    work_id = await _start(lifecycle, "test-work-s2")
    await lifecycle.interrupt(work_id, {"next_node": "execution_approval", "request_ids": ["apr_1"], "pending": [{"request_id": "apr_1"}]})
    waiting = await lifecycle.store.waiting_for_session("test-work-s2")
    assert waiting.work_id == work_id and waiting.status == "waiting_approval"
    claimed = await lifecycle.claim(work_id, expected_version=waiting.version)
    assert claimed.status == "running" and claimed.pending is None
    assert await lifecycle.store.waiting_for_session("test-work-s2") is None


@pytest.mark.asyncio
async def test_a_stale_claim_conflicts(lifecycle) -> None:
    work_id = await _start(lifecycle, "test-work-s3")
    await lifecycle.interrupt(work_id, {"next_node": "x", "request_ids": ["r"], "pending": []})
    version = (await lifecycle.store.get(work_id)).version
    await lifecycle.claim(work_id, expected_version=version)
    with pytest.raises(WorkConflict):
        await lifecycle.claim(work_id, expected_version=version)


@pytest.mark.asyncio
async def test_expire_closes_a_waiting_work(lifecycle) -> None:
    work_id = await _start(lifecycle, "test-work-s4")
    await lifecycle.interrupt(work_id, {"next_node": "x", "request_ids": ["r"], "pending": []})
    record = await lifecycle.store.get(work_id)
    expired = await lifecycle.expire(work_id, expected_version=record.version)
    assert expired.status == "expired"


@pytest.mark.asyncio
async def test_illegal_transitions_conflict(lifecycle) -> None:
    work_id = await _start(lifecycle, "test-work-s5")
    await lifecycle.complete(work_id, {"final_response": None})
    with pytest.raises(WorkConflict):
        await lifecycle.fail(work_id, "late")


@pytest.mark.asyncio
async def test_children_and_refs(lifecycle) -> None:
    parent = await _start(lifecycle, "test-work-s6")
    child = await lifecycle.start(
        "web", "coding", user_id="test-work-user", session_id=None, delivery={"kind": "none"},
        parent=parent, ref_id="ct_test_1",
    )
    record = await lifecycle.store.by_ref("coding", "ct_test_1")
    assert record.work_id == child and record.parent_work_id == parent


@pytest.mark.no_db
@pytest.mark.parametrize(
    ("user_input", "entry", "delivery"),
    [
        ({"session_id": "c1"}, "web", {"kind": "sse", "conversation_id": "c1"}),
        ({"session_id": "v2:x", "channel_source": "slack", "channel_type": "slack", "channel_id": "C1"}, "channel",
         {"kind": "channel", "channel_type": "slack", "channel_id": "C1"}),
        ({"session_id": "scheduled_1", "channel_source": "scheduler"}, "schedule", {"kind": "none"}),
    ],
)
def test_entry_and_delivery_come_from_existing_input_keys(user_input, entry, delivery) -> None:
    assert entry_and_delivery(user_input) == (entry, delivery)
```

Run: `NEOS_ENV=default GOOGLE_API_KEY=test-key python -m pytest tests/workflow/runtime/test_work.py -q`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 2: 마이그레이션**

`db/migrations/097_add_workflow_runs.sql`:
```sql
-- 작업 생명주기와 전달 아웃박스 (spec 2026-10-13 §4.4·§4.7, W1 Plan 2).
--
-- 작업(work) = 입구에서 실행 한 번: 웹 메시지 · 채널 메시지 · 예약 실행 · 트리거로 열린 코딩 태스크.
-- 세션(096)은 "무엇을 기억하나", 작업은 "누가 언제 무엇을 했고 결과를 어디로 보내나" 다.
-- - 승인 대기의 정본은 `status = 'waiting_approval'` + `pending` 이다 -- 그래프 상태가 아니다
-- - `version` 은 낙관적 잠금 -- 같은 승인에 두 결정이 오면 하나만 재개된다
-- - `workflow_deliveries` 는 Plan 2b(단계 4)가 쓴다: 워커는 적기만 하고 API 프로세스가 보낸다
--
-- 두 번 적용해도 같다.

CREATE TABLE IF NOT EXISTS workflow_runs (
    work_id         TEXT         PRIMARY KEY,
    entry           TEXT         NOT NULL CHECK (entry IN ('web', 'channel', 'schedule', 'trigger', 'api')),
    kind            TEXT         NOT NULL CHECK (kind IN ('workflow', 'deep_analysis', 'coding')),
    ref_id          TEXT         NULL,
    parent_work_id  TEXT         NULL REFERENCES workflow_runs(work_id) ON DELETE SET NULL,
    session_id      TEXT         NULL,
    user_id         TEXT         NOT NULL,
    status          TEXT         NOT NULL
                    CHECK (status IN ('running', 'waiting_approval', 'completed', 'failed', 'expired')),
    pending         JSONB        NULL,
    result          JSONB        NULL,
    delivery        JSONB        NOT NULL,
    version         INTEGER      NOT NULL CHECK (version >= 1),
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT ck_workflow_runs_pending
        CHECK ((status = 'waiting_approval') = (pending IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS idx_workflow_runs_waiting_session
    ON workflow_runs (session_id, updated_at DESC) WHERE status = 'waiting_approval';
CREATE INDEX IF NOT EXISTS idx_workflow_runs_ref
    ON workflow_runs (kind, ref_id) WHERE ref_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS workflow_deliveries (
    delivery_id      TEXT         PRIMARY KEY,
    work_id          TEXT         NOT NULL REFERENCES workflow_runs(work_id) ON DELETE CASCADE,
    target           JSONB        NOT NULL,
    body             TEXT         NOT NULL,
    status           TEXT         NOT NULL DEFAULT 'queued'
                     CHECK (status IN ('queued', 'sent', 'failed')),
    attempts         INTEGER      NOT NULL DEFAULT 0,
    next_attempt_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_workflow_deliveries_due
    ON workflow_deliveries (next_attempt_at) WHERE status = 'queued';
```

- [ ] **Step 3: 작업 기록 모듈**

`neos/workflow/runtime/work.py`:
```python
"""작업 생명주기 (spec 2026-10-13 §4.4).

입구에서 실행 한 번이 작업 하나다. 같은 ID 체계 · 같은 승인 상태 · 같은 결과 저장 위치를 모든
입구(웹·채널·예약·트리거)가 쓴다. 전달(아웃박스)은 Plan 2b 가 붙인다.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import uuid4

from sqlalchemy import text

_CHANNEL_SOURCES = frozenset({"slack", "discord", "telegram"})
_TRANSITIONS: dict[str, frozenset[str]] = {
    "running": frozenset({"waiting_approval", "completed", "failed"}),
    "waiting_approval": frozenset({"running", "expired"}),
}


class _Keep:
    def __repr__(self) -> str:
        return "KEEP"


KEEP: Any = _Keep()


@dataclass(frozen=True)
class WorkRecord:
    work_id: str
    entry: str
    kind: str
    user_id: str
    session_id: str | None
    status: str
    pending: dict[str, Any] | None
    result: dict[str, Any] | None
    delivery: dict[str, Any]
    ref_id: str | None
    parent_work_id: str | None
    version: int
    created_at: datetime
    updated_at: datetime


class WorkConflict(RuntimeError):
    pass


class WorkStore(Protocol):
    async def create(self, record: WorkRecord) -> None: ...

    async def get(self, work_id: str) -> WorkRecord | None: ...

    async def waiting_for_session(self, session_id: str) -> WorkRecord | None: ...

    async def by_ref(self, kind: str, ref_id: str) -> WorkRecord | None: ...

    async def transition(
        self, work_id: str, *, expected_version: int, status: str, pending: Any = KEEP, result: Any = KEEP
    ) -> WorkRecord: ...


def entry_and_delivery(user_input: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    """호출자가 이미 넘기는 키에서 입구와 전달 대상을 정한다 -- 입력 모양을 바꾸지 않는다(spec §4.4)."""
    source = str(user_input.get("channel_source") or "")
    if source in _CHANNEL_SOURCES or user_input.get("channel_type") in _CHANNEL_SOURCES:
        channel_type = str(user_input.get("channel_type") or source)
        return "channel", {
            "kind": "channel",
            "channel_type": channel_type,
            "channel_id": user_input.get("channel_id"),
        }
    if source == "scheduler":
        return "schedule", {"kind": "none"}
    return "web", {"kind": "sse", "conversation_id": user_input.get("session_id")}


def _check(record: WorkRecord | None, work_id: str, expected_version: int, status: str) -> WorkRecord:
    if record is None:
        raise WorkConflict(f"{work_id}: 없음")
    if record.version != expected_version:
        raise WorkConflict(f"{work_id}: version {record.version} != expected {expected_version}")
    if status not in _TRANSITIONS.get(record.status, frozenset()):
        raise WorkConflict(f"{work_id}: {record.status} → {status} 는 허용되지 않는다")
    return record


class InMemoryWorkStore:
    def __init__(self) -> None:
        self._rows: dict[str, WorkRecord] = {}
        self._lock = asyncio.Lock()

    async def create(self, record: WorkRecord) -> None:
        async with self._lock:
            self._rows[record.work_id] = record

    async def get(self, work_id: str) -> WorkRecord | None:
        return self._rows.get(work_id)

    async def waiting_for_session(self, session_id: str) -> WorkRecord | None:
        waiting = [r for r in self._rows.values() if r.session_id == session_id and r.status == "waiting_approval"]
        return max(waiting, key=lambda r: r.updated_at, default=None)

    async def by_ref(self, kind: str, ref_id: str) -> WorkRecord | None:
        return next((r for r in self._rows.values() if r.kind == kind and r.ref_id == ref_id), None)

    async def transition(
        self, work_id: str, *, expected_version: int, status: str, pending: Any = KEEP, result: Any = KEEP
    ) -> WorkRecord:
        async with self._lock:
            record = _check(self._rows.get(work_id), work_id, expected_version, status)
            updated = replace(
                record,
                status=status,
                pending=record.pending if pending is KEEP else pending,
                result=record.result if result is KEEP else result,
                version=record.version + 1,
                updated_at=datetime.now(UTC),
            )
            self._rows[work_id] = updated
            return updated


_COLUMNS = (
    "work_id, entry, kind, user_id, session_id, status, pending, result, delivery, "
    "ref_id, parent_work_id, version, created_at, updated_at"
)


def _json(value: Any) -> Any:
    if value is None or isinstance(value, (dict, list)):
        return value
    return json.loads(value)


def _row(row: Any) -> WorkRecord:
    return WorkRecord(
        work_id=row[0], entry=row[1], kind=row[2], user_id=row[3], session_id=row[4], status=row[5],
        pending=_json(row[6]), result=_json(row[7]), delivery=_json(row[8]) or {},
        ref_id=row[9], parent_work_id=row[10], version=row[11], created_at=row[12], updated_at=row[13],
    )


class PostgresWorkStore:
    def __init__(self, session_factory: Callable[[], Awaitable[Any]]) -> None:
        self._session_factory = session_factory

    async def create(self, record: WorkRecord) -> None:
        async with await self._session_factory() as session:
            async with session.begin():
                await session.execute(
                    text(
                        """
                        INSERT INTO workflow_runs
                            (work_id, entry, kind, user_id, session_id, status, pending, result,
                             delivery, ref_id, parent_work_id, version, created_at, updated_at)
                        VALUES
                            (:work_id, :entry, :kind, :user_id, :session_id, :status,
                             CAST(:pending AS JSONB), CAST(:result AS JSONB), CAST(:delivery AS JSONB),
                             :ref_id, :parent, :version, :created_at, :updated_at)
                        """
                    ),
                    {
                        "work_id": record.work_id, "entry": record.entry, "kind": record.kind,
                        "user_id": record.user_id, "session_id": record.session_id, "status": record.status,
                        "pending": json.dumps(record.pending) if record.pending is not None else None,
                        "result": json.dumps(record.result) if record.result is not None else None,
                        "delivery": json.dumps(record.delivery), "ref_id": record.ref_id,
                        "parent": record.parent_work_id, "version": record.version,
                        "created_at": record.created_at, "updated_at": record.updated_at,
                    },
                )

    async def _one(self, sql: str, params: Mapping[str, Any]) -> WorkRecord | None:
        async with await self._session_factory() as session:
            row = (await session.execute(text(sql), dict(params))).first()
        return _row(row) if row is not None else None

    async def get(self, work_id: str) -> WorkRecord | None:
        return await self._one(f"SELECT {_COLUMNS} FROM workflow_runs WHERE work_id = :w", {"w": work_id})

    async def waiting_for_session(self, session_id: str) -> WorkRecord | None:
        return await self._one(
            f"""SELECT {_COLUMNS} FROM workflow_runs
                WHERE session_id = :s AND status = 'waiting_approval'
                ORDER BY updated_at DESC LIMIT 1""",
            {"s": session_id},
        )

    async def by_ref(self, kind: str, ref_id: str) -> WorkRecord | None:
        return await self._one(
            f"SELECT {_COLUMNS} FROM workflow_runs WHERE kind = :k AND ref_id = :r ORDER BY created_at DESC LIMIT 1",
            {"k": kind, "r": ref_id},
        )

    async def transition(
        self, work_id: str, *, expected_version: int, status: str, pending: Any = KEEP, result: Any = KEEP
    ) -> WorkRecord:
        allowed_from = [src for src, targets in _TRANSITIONS.items() if status in targets]
        sets = ["status = :status", "version = version + 1", "updated_at = now()"]
        params: dict[str, Any] = {"w": work_id, "v": expected_version, "status": status, "from": allowed_from}
        if pending is not KEEP:
            sets.append("pending = CAST(:pending AS JSONB)")
            params["pending"] = json.dumps(pending) if pending is not None else None
        if result is not KEEP:
            sets.append("result = CAST(:result AS JSONB)")
            params["result"] = json.dumps(result) if result is not None else None
        async with await self._session_factory() as session:
            async with session.begin():
                row = (
                    await session.execute(
                        text(
                            f"""UPDATE workflow_runs SET {", ".join(sets)}
                                WHERE work_id = :w AND version = :v AND status = ANY(:from)
                                RETURNING {_COLUMNS}"""
                        ),
                        params,
                    )
                ).first()
        if row is None:
            raise WorkConflict(f"{work_id}: version {expected_version} 또는 {status} 로의 전이가 맞지 않는다")
        return _row(row)


class WorkLifecycle:
    def __init__(self, store: WorkStore, *, clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self.store = store
        self._clock = clock

    async def start(
        self,
        entry: str,
        kind: str,
        *,
        user_id: str,
        session_id: str | None,
        delivery: Mapping[str, Any],
        parent: str | None = None,
        ref_id: str | None = None,
    ) -> str:
        now = self._clock()
        record = WorkRecord(
            work_id=f"wk_{uuid4().hex}", entry=entry, kind=kind, user_id=user_id, session_id=session_id,
            status="running", pending=None, result=None, delivery=dict(delivery), ref_id=ref_id,
            parent_work_id=parent, version=1, created_at=now, updated_at=now,
        )
        await self.store.create(record)
        return record.work_id

    async def _move(self, work_id: str, status: str, **fields: Any) -> WorkRecord:
        record = await self.store.get(work_id)
        if record is None:
            raise WorkConflict(f"{work_id}: 없음")
        return await self.store.transition(work_id, expected_version=record.version, status=status, **fields)

    async def interrupt(self, work_id: str, pending: Mapping[str, Any]) -> None:
        await self._move(work_id, "waiting_approval", pending=dict(pending))

    async def complete(self, work_id: str, result: Mapping[str, Any]) -> None:
        await self._move(work_id, "completed", result=dict(result))

    async def fail(self, work_id: str, error: str) -> None:
        await self._move(work_id, "failed", result={"error": error})

    async def claim(self, work_id: str, *, expected_version: int) -> WorkRecord:
        return await self.store.transition(work_id, expected_version=expected_version, status="running", pending=None)

    async def expire(self, work_id: str, *, expected_version: int) -> WorkRecord:
        return await self.store.transition(work_id, expected_version=expected_version, status="expired", pending=None)
```

> `status = ANY(:from)` 의 리스트 바인딩이 asyncpg 에서 거절되면 `status IN :from` + `bindparam("from", expanding=True)` 로 바꾼다.

Run: `NEOS_ENV=default GOOGLE_API_KEY=test-key python -m pytest tests/workflow/runtime/test_work.py -q`
Expected: PASS(Postgres 포함)

- [ ] **Step 4: 커밋**

```bash
git add neos/workflow/runtime/work.py db/migrations/097_add_workflow_runs.sql tests/workflow/runtime/test_work.py
git commit -m "feat(workflow): work lifecycle records with versioned transitions; delivery outbox table (spec §4.4, §4.7)"
```

---

### Task 6: 네이티브 턴 — 런타임 선택과 `execute_workflow` 통합

**Files:**
- Create: `neos/workflow/runtime/turns.py`
- Create: `neos/workflow/runtime/select.py`
- Modify: `neos/config/schema.py` (`WorkflowConfig.runtime`)
- Modify: `neos/workflow/execution_graph.py` (`ExecutionGraph.runner: Any = None`)
- Modify: `neos/workflow/graph.py` (`_resolve_execution_graph` → 러너 부착, `graph_astream_source`, `execute_workflow` 의 턴 훅, `_interrupted_result`)
- Modify: `tests/workflow/support/stub_workflow.py` (`runtime` 인자)
- Modify: `tests/workflow/test_execute_workflow_contract.py` (두 런타임)
- Test: `tests/workflow/runtime/test_native_turns.py`

**Interfaces:**
- Consumes: Task 1~5 전부; `wrap_node` via `MultiAgentWorkflow._node_wrapper()`; `resolve_wiring`; `current_static_flags`; `_recursion_limit_for`
- Produces:
  - 설정 `settings.config.workflow.runtime: Literal["langgraph", "native"]`(기본 `"langgraph"`)
  - `turns.TurnStart(state: dict, start_at: str | None, handle: TurnHandle)`
  - `turns.TurnHandle` 프로토콜: 속성 `work_id: str | None`; `interrupted(state, next_node) -> None` · `completed(state, result) -> None` · `failed(error: str) -> None`
  - `turns.NULL_TURN` (아무것도 하지 않는 핸들, `work_id=None`)
  - `turns.NativeTurns(sessions: SessionStore, lifecycle: WorkLifecycle, *, max_carried_items: int)` — `begin(user_input, initial_state, *, stateful: bool) -> TurnStart` · `begin_resume(ticket, runtime_keys: Mapping) -> TurnStart`
  - `turns.ResumeUnavailable(RuntimeError)`
  - `select.runtime_name() -> str` · `select.native_turns() -> NativeTurns` · `select.set_native_turns(turns: NativeTurns | None) -> None`
  - `execute_workflow` 결과에 네이티브일 때 `work_id` 키
  - `stub_workflow(..., runtime: str = "langgraph")` — 네이티브면 메모리 저장소를 `select.set_native_turns` 로 주입하고 반환값에 `workflow.native_stores = (sessions, lifecycle)` 를 단다

- [ ] **Step 1: 턴과 선택 모듈을 쓴다**

`neos/workflow/runtime/turns.py`:
```python
"""턴의 앞뒤 -- 세션 읽기·병합·저장, 작업 시작·중단·완료 (spec 2026-10-13 §4.3·§4.4).

러너는 대화 개념을 모른다. 이 모듈이 `execute_workflow` 의 시작과 끝에 붙어 "이번 턴" 의 의미를
준다. LangGraph 런타임은 `NULL_TURN` 을 쓴다 -- 저장은 그쪽 체크포인터가 한다.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from neos.workflow.runtime.sessions import SessionConflict, SessionStore, carry, trim
from neos.workflow.runtime.work import WorkLifecycle, entry_and_delivery

logger = logging.getLogger(__name__)


class TurnHandle(Protocol):
    work_id: str | None

    async def interrupted(self, state: Mapping[str, Any], next_node: str) -> None: ...

    async def completed(self, state: Mapping[str, Any], result: Mapping[str, Any]) -> None: ...

    async def failed(self, error: str) -> None: ...


@dataclass(frozen=True)
class TurnStart:
    state: dict[str, Any]
    start_at: str | None
    handle: Any


class ResumeUnavailable(RuntimeError):
    pass


class _NullTurn:
    work_id = None

    async def interrupted(self, state, next_node) -> None:
        return None

    async def completed(self, state, result) -> None:
        return None

    async def failed(self, error) -> None:
        return None


NULL_TURN = _NullTurn()


def _count(name: str, **labels: str) -> None:
    try:
        from neos.observability.metrics import metrics

        counter = getattr(metrics, name)
        (counter.labels(**labels) if labels else counter).inc()
    except Exception:  # noqa: BLE001 -- 계측 실패가 턴을 막지 않는다
        logger.debug("%s unavailable", name, exc_info=True)


class _NativeHandle:
    def __init__(self, turns: "NativeTurns", *, session_id: str, user_id: str, version: int | None, work_id: str, stateful: bool) -> None:
        self._turns = turns
        self._session_id = session_id
        self._user_id = user_id
        self._version = version
        self.work_id = work_id
        self._stateful = stateful

    async def _save(self, state: Mapping[str, Any]) -> None:
        trimmed, cut = trim(state, self._turns.max_carried_items)
        for field, dropped in cut.items():
            for _ in range(dropped):
                _count("workflow_session_trimmed_total", field=field)
        self._version = await self._turns.sessions.save(
            self._session_id, user_id=self._user_id, state=trimmed, expected_version=self._version
        )

    async def interrupted(self, state: Mapping[str, Any], next_node: str) -> None:
        # 승인 대기 저장이 실패하면 재개할 지점이 없다 -- 예외를 올려 그 턴을 오류로 끝낸다(spec §4.3).
        await self._save(state)
        pending = list(state.get("pending_approvals") or [])
        await self._turns.lifecycle.interrupt(
            self.work_id,
            {
                "next_node": next_node,
                "request_ids": [str(item.get("request_id")) for item in pending if isinstance(item, Mapping)],
                "pending": pending,
            },
        )

    async def completed(self, state: Mapping[str, Any], result: Mapping[str, Any]) -> None:
        if self._stateful:
            try:
                await self._save(state)
            except SessionConflict:
                logger.warning("workflow session lost a save race: %s", self._session_id)
                _count("workflow_session_conflicts_total")
            except Exception:  # noqa: BLE001 -- 응답은 이미 만들어졌다
                logger.warning("workflow session save failed: %s", self._session_id, exc_info=True)
                _count("workflow_session_failures_total", op="save")
        await self._turns.lifecycle.complete(
            self.work_id,
            {"final_response": result.get("response"), "author": None, "verified_by": None},
        )

    async def failed(self, error: str) -> None:
        await self._turns.lifecycle.fail(self.work_id, error)


class NativeTurns:
    def __init__(self, sessions: SessionStore, lifecycle: WorkLifecycle, *, max_carried_items: int) -> None:
        self.sessions = sessions
        self.lifecycle = lifecycle
        self.max_carried_items = max_carried_items

    async def begin(self, user_input: Mapping[str, Any], initial_state: Mapping[str, Any], *, stateful: bool) -> TurnStart:
        session_id = str(user_input["session_id"])
        user_id = str(user_input.get("user_id") or "")
        saved = None
        if stateful:
            try:
                saved = await self.sessions.load(session_id)
            except Exception:  # noqa: BLE001 -- 디코드·DB 실패는 빈 이어받기로 진행한다(spec §4.3)
                logger.warning("workflow session load failed: %s", session_id, exc_info=True)
                _count("workflow_session_failures_total", op="load")
        state = carry(saved.state if saved else None, initial_state)
        entry, delivery = entry_and_delivery(user_input)
        work_id = await self.lifecycle.start(
            entry, "workflow", user_id=user_id, session_id=session_id, delivery=delivery
        )
        handle = _NativeHandle(
            self, session_id=session_id, user_id=user_id,
            version=saved.version if saved else None, work_id=work_id, stateful=stateful,
        )
        return TurnStart(state=state, start_at=None, handle=handle)

    async def begin_resume(self, ticket: Any, runtime_keys: Mapping[str, Any]) -> TurnStart:
        """초기 상태를 다시 만들지 않는다(불변식 3) -- 저장된 상태 위에 결정과 런타임 키만 얹는다."""
        saved = await self.sessions.load(ticket.session_id)
        if saved is None:
            raise ResumeUnavailable(f"{ticket.session_id}: 저장된 세션이 없다")
        pending = [
            item for item in (saved.state.get("pending_approvals") or [])
            if not (isinstance(item, Mapping) and str(item.get("request_id")) == ticket.request_id)
        ]
        state = {
            **saved.state,
            "approval_decision": ticket.decision,
            "pending_approvals": pending,
            **dict(runtime_keys),
        }
        handle = _NativeHandle(
            self, session_id=ticket.session_id, user_id=saved.user_id,
            version=saved.version, work_id=ticket.work_id, stateful=True,
        )
        return TurnStart(state=state, start_at=ticket.next_node, handle=handle)
```

`neos/workflow/runtime/select.py`:
```python
"""런타임 선택 -- 한 곳 (spec 2026-10-13 §6.1 단계 3).

`workflow.runtime` 이 `native` 일 때만 네이티브 저장소를 만든다. 테스트는 `set_native_turns` 로
메모리 저장소를 꽂는다.
"""

from __future__ import annotations

from neos.workflow.runtime.turns import NativeTurns

_turns: NativeTurns | None = None


def runtime_name() -> str:
    from neos.config.settings import settings

    return settings.config.workflow.runtime


def native_turns() -> NativeTurns:
    global _turns
    if _turns is None:
        from neos.config.settings import settings
        from neos.database.connection import db_manager
        from neos.workflow.runtime.sessions import PostgresSessionStore
        from neos.workflow.runtime.work import PostgresWorkStore, WorkLifecycle

        _turns = NativeTurns(
            PostgresSessionStore(db_manager.get_session),
            WorkLifecycle(PostgresWorkStore(db_manager.get_session)),
            max_carried_items=settings.config.workflow.session.max_carried_items,
        )
    return _turns


def set_native_turns(turns: NativeTurns | None) -> None:
    global _turns
    _turns = turns
```

`neos/config/schema.py` `WorkflowConfig` 의 `node_update_policy` 아래에:
```python
    # 채팅 워크플로 런타임 (spec 2026-10-13 §6.1). 단계 6 까지 기본은 LangGraph 다.
    runtime: Literal["langgraph", "native"] = "langgraph"
```

`neos/workflow/execution_graph.py` `ExecutionGraph` 의 `subagent_host: Any = None` 아래에:
```python
    # 네이티브 런타임(spec 2026-10-13 §4.2)의 러너. LangGraph 런타임이면 None.
    runner: Any = None
```

- [ ] **Step 2: 그래프에 러너를 붙인다**

`neos/workflow/graph.py`:

(a) 지금의 `async def _resolve_execution_graph(self, *, user_input, use_checkpointer, span, event_handler=None)` 의 **이름을** `_resolve_langgraph_execution_graph` 로 바꾸고 키워드 인자 `allow_parallel: bool = True` 를 더한다. 그 안의 `design_graph_or_fallback(...)` 호출에 `allow_parallel=allow_parallel,` 를 더한다.

(b) 그 위에 새 메서드를 둔다:
```python
    async def _resolve_execution_graph(
        self,
        *,
        user_input: Dict[str, Any],
        use_checkpointer: bool,
        span: Any,
        event_handler: Any = None,
    ) -> ExecutionGraph:
        """이번 호출이 실행할 그래프. 네이티브 런타임이면 같은 배선으로 러너를 붙인다(spec §4.2).

        네이티브에서는 병렬 설계를 거절해 정적 그래프로 폴백한다(§4.10) -- 러너는 순차만 돈다.
        """
        from neos.workflow.runtime.select import runtime_name

        native = runtime_name() == "native"
        execution_graph = await self._resolve_langgraph_execution_graph(
            user_input=user_input,
            use_checkpointer=use_checkpointer,
            span=span,
            event_handler=event_handler,
            allow_parallel=not native,
        )
        if not native:
            return execution_graph
        return dataclasses.replace(
            execution_graph, runner=self._native_runner(execution_graph, use_checkpointer=use_checkpointer)
        )

    def _native_runner(self, execution_graph: ExecutionGraph, *, use_checkpointer: bool):
        from neos.workflow.runtime.designed import designed_wiring
        from neos.workflow.runtime.runner import WorkflowRunner
        from neos.workflow.wiring import resolve_wiring

        if execution_graph.source == "designed" and execution_graph.topology is not None:
            wiring = designed_wiring(
                execution_graph.topology,
                self,
                subagent_host=execution_graph.subagent_host,
                gated_nodes=frozenset(_INTERRUPT_GATED_NODES),
            )
        else:
            wiring = resolve_wiring(current_static_flags())
        return WorkflowRunner(
            wiring,
            self,
            step_limit=_recursion_limit_for(execution_graph),
            # 승인 게이트는 상태를 저장하는 경로에서만 -- LangGraph 와 같다.
            interrupt_before=wiring.interrupt_before if use_checkpointer else (),
            wrap=self._node_wrapper(),
        )
```
`import dataclasses` 가 파일 상단에 없으면 더한다.

(c) `graph_astream_source` 본문을:
```python
        if execution_graph.runner is not None:
            return execution_graph.runner.stream(initial_state, start_at=config.get("neos_start_at"))
        return execution_graph.compiled.astream(initial_state, config)
```
docstring 끝에 "네이티브 런타임이면 러너의 chunk 를 낸다. `config["neos_start_at"]` 은 승인 재개 지점이다." 를 더한다.

- [ ] **Step 3: `execute_workflow` 에 턴 훅을 단다**

`execute_workflow` 에서(줄 번호는 Plan 1 머지 기준 2655~3013 근처):

(a) `trackable_nodes = set(execution_graph.nodes)` 바로 앞, `config` 를 만든 뒤에:
```python
                # 네이티브 런타임: 세션을 이어받아 시작 상태를 만들고 작업을 연다(spec §4.3·§4.4).
                if execution_graph.runner is not None:
                    from neos.workflow.runtime.select import native_turns

                    turn = await native_turns().begin(user_input, initial_state, stateful=use_checkpointer)
                    start_state, turn_handle = turn.state, turn.handle
                else:
                    from neos.workflow.runtime.turns import NULL_TURN

                    start_state, turn_handle = initial_state, NULL_TURN
```
(b) `final_state = dict(initial_state)` 를 `final_state = dict(start_state)` 로, `async for chunk in self.graph_astream_source(execution_graph, initial_state, config):` 를 `async for chunk in self.graph_astream_source(execution_graph, start_state, config):` 로 바꾼다.

(c) `if interrupted:` 블록을:
```python
                if interrupted:
                    if execution_graph.runner is not None:
                        await turn_handle.interrupted(final_state, execution_graph.runner.outcome.next_node)
                    interrupted_result = await self._interrupted_result(
                        final_state, user_input, initial_state, span, event_handler
                    )
                    if turn_handle.work_id is not None:
                        interrupted_result["work_id"] = turn_handle.work_id
                    return interrupted_result
```
(d) `result = self._create_workflow_result(final_state)` 바로 아래에:
```python
                await turn_handle.completed(final_state, result)
                if turn_handle.work_id is not None:
                    result["work_id"] = turn_handle.work_id
```
(e) `execution_graph = None` 바로 아래(`try:` 앞)에 `turn_handle = None` 을 둔다 — 턴이 시작되기 전에 실패하면 핸들이 없다. 그리고 `except Exception as e:` 블록의 `await event_handler.on_workflow_error(e)` 앞에:
```python
                if turn_handle is not None:
                    try:
                        await turn_handle.failed(str(e))
                    except Exception:  # noqa: BLE001 -- 실패 기록이 실패 보고를 막지 않는다
                        logger.warning("work failure could not be recorded", exc_info=True)
```

(f) `_interrupted_result` 를 접힌 상태에서 읽게 바꾼다:
```python
    async def _interrupted_result(
        self, final_state, user_input, initial_state, span, event_handler
    ) -> Dict[str, Any]:
        """승인 게이트에서 멈췄다 -- SSE approval_request 를 내보내고 중단 결과를 돌려준다.

        대기 목록은 접힌 상태에서 읽는다(spec §4.2) -- 그래프 상태를 다시 읽지 않으므로
        PostgreSQL 체크포인터의 R1 이 승인 이벤트를 막지 않고, 두 런타임이 같은 코드를 지난다.
        """
        add_span_event(span, "workflow_interrupted_for_approval")
        pending = list(final_state.get("pending_approvals") or [])
        ...  # 나머지는 지금과 같다(session_id, on_approval_request, logger, return dict)
```
(`...` 는 계획 표기다 — 지금 본문의 `session_id = …` 부터 `return {...}` 까지를 그대로 둔다. `current_graph_state = await execution_graph.compiled.aget_state(config)` 와 `pending = current_graph_state.values.get(...)` 두 줄만 위의 한 줄로 바뀐다.)

Run: `NEOS_ENV=default GOOGLE_API_KEY=test-key python -m pytest tests/workflow/test_execute_workflow_contract.py tests/workflow/test_approval_port_contract.py tests/workflow/test_langgraph_known_defects.py tests/workflow/test_progress_tracking.py -q`
Expected: PASS(LangGraph 런타임 그대로)

- [ ] **Step 4: 하네스에 런타임을 더하고 계약을 두 런타임으로 돌린다**

`tests/workflow/support/stub_workflow.py`:
- 시그니처에 `runtime: str = "langgraph",` 를 더한다(`node_update_policy` 뒤)
- `monkeypatch.setattr(settings.config.workflow, "graph_design_enabled", False)` 아래에:
```python
    monkeypatch.setattr(settings.config.workflow, "runtime", runtime)
    native_stores = None
    if runtime == "native":
        from neos.workflow.runtime import select
        from neos.workflow.runtime.sessions import InMemorySessionStore
        from neos.workflow.runtime.turns import NativeTurns
        from neos.workflow.runtime.work import InMemoryWorkStore, WorkLifecycle

        sessions, lifecycle = InMemorySessionStore(), WorkLifecycle(InMemoryWorkStore())
        monkeypatch.setattr(select, "_turns", NativeTurns(sessions, lifecycle, max_carried_items=200))
        native_stores = (sessions, lifecycle)
```
- `return workflow` 앞에 `workflow.native_stores = native_stores` 를 넣는다
- docstring 에 "`runtime='native'` 면 메모리 세션·작업 저장소를 꽂는다. `workflow.native_stores` 로 꺼내 본다." 를 더한다

`tests/workflow/test_execute_workflow_contract.py`:
- 파일 상단 `pytestmark` 아래에:
```python
@pytest.fixture(params=["langgraph", "native"])
def runtime(request):
    return request.param
```
- 네 테스트의 인자에 `runtime` 을 더하고 `stub_workflow(monkeypatch, …)` 호출마다 `runtime=runtime` 을 넘긴다. 단언은 바꾸지 않는다

- [ ] **Step 5: 네이티브 턴 테스트를 쓴다**

`tests/workflow/runtime/test_native_turns.py`:
```python
"""네이티브 턴 (spec 2026-10-13 §4.3·§4.4): 상태 이어받기 · 작업 기록 · 승인 대기 저장."""

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

A = SearchResult(source="web", title="A", content="a", url="https://a")
B = SearchResult(source="web", title="B", content="b", url="https://b")


def _answer(text):
    return lambda state: {"final_response": text, "response_metadata": {}, "execution_time_ms": 1, "execution_steps": []}


def _plan(direct, answer="답"):
    return StubPlan(
        nodes={N.DIRECT_RESPONSE.value: direct, N.RESP_GENERATOR.value: _answer(answer)},
        routes=SKIP_PATH_ROUTES,
    )


async def test_the_second_turn_carries_accumulated_state_and_resets_turn_fields(monkeypatch) -> None:
    seen: list[dict] = []

    def direct(state):
        seen.append({"search_results": list(state["search_results"]), "skill_sources": state.get("skill_sources")})
        return {"search_results": [A] if len(seen) == 1 else [B], "skill_sources": [A] if len(seen) == 1 else None}

    workflow = stub_workflow(monkeypatch, _plan(direct), runtime="native")
    first = await workflow.execute_workflow(user_input(session_id="s-carry"), event_handler=RecordingHandler())
    second = await workflow.execute_workflow(user_input(session_id="s-carry"), event_handler=RecordingHandler())
    assert first["success"] and second["success"]
    assert seen[1]["search_results"] == [A]  # 이어받았다
    assert seen[1]["skill_sources"] is None  # 턴 리셋 필드
    sessions, _ = workflow.native_stores
    assert (await sessions.load("s-carry")).state["search_results"] == [A, B]


async def test_a_turn_records_its_work(monkeypatch) -> None:
    workflow = stub_workflow(monkeypatch, _plan(lambda s: {}), runtime="native")
    result = await workflow.execute_workflow(user_input(session_id="s-work"), event_handler=RecordingHandler())
    _, lifecycle = workflow.native_stores
    record = await lifecycle.store.get(result["work_id"])
    assert record.status == "completed"
    assert record.result["final_response"] == "답"
    assert record.entry == "web" and record.session_id == "s-work"


async def test_a_failing_turn_marks_the_work_failed(monkeypatch) -> None:
    def boom(state):
        raise RuntimeError("노드 실패")

    workflow = stub_workflow(monkeypatch, _plan(boom), runtime="native")
    result = await workflow.execute_workflow(user_input(session_id="s-fail"), event_handler=RecordingHandler())
    assert result["success"] is False
    _, lifecycle = workflow.native_stores
    failed = [r for r in lifecycle.store._rows.values() if r.session_id == "s-fail"]
    assert [r.status for r in failed] == ["failed"]


async def test_an_approval_gate_saves_and_waits(monkeypatch) -> None:
    pending = [{"request_id": "apr_1", "skill_name": "x"}]
    plan = StubPlan(
        nodes={N.SKILL_TOOL_SELECTOR.value: lambda s: {"pending_approvals": pending, "approval_decision": None}},
        routes={**SKIP_PATH_ROUTES, "_route_after_skill_tool_selector": "needs_approval"},
    )
    workflow = stub_workflow(monkeypatch, plan, flags={"execution_approval": True}, runtime="native")
    handler = RecordingHandler()
    result = await workflow.execute_workflow(user_input(session_id="s-gate"), event_handler=handler)
    assert result["interrupted"] is True
    assert result["pending_approvals"] == pending
    assert handler.approvals == [pending]
    sessions, lifecycle = workflow.native_stores
    record = await lifecycle.store.waiting_for_session("s-gate")
    assert record.pending["next_node"] == N.EXECUTION_APPROVAL.value
    assert record.pending["request_ids"] == ["apr_1"]
    assert (await sessions.load("s-gate")).state["pending_approvals"] == pending


async def test_a_stateless_turn_does_not_interrupt(monkeypatch) -> None:
    plan = StubPlan(
        nodes={
            N.SKILL_TOOL_SELECTOR.value: lambda s: {"pending_approvals": [{"request_id": "r"}], "approval_decision": None},
            N.RESP_GENERATOR.value: _answer("통과"),
        },
        routes={
            **SKIP_PATH_ROUTES,
            "_route_after_skill_tool_selector": "needs_approval",
            "_should_continue_after_approval": "rejected",
        },
    )
    workflow = stub_workflow(monkeypatch, plan, flags={"execution_approval": True}, runtime="native")
    result = await workflow.execute_workflow(user_input(session_id="s-stateless"), event_handler=RecordingHandler(), use_checkpointer=False)
    assert result.get("interrupted") is not True
    assert result["response"] == "통과"
    sessions, _ = workflow.native_stores
    assert await sessions.load("s-stateless") is None


async def test_an_undecodable_session_starts_fresh(monkeypatch) -> None:
    workflow = stub_workflow(monkeypatch, _plan(lambda s: {}), runtime="native")
    sessions, _ = workflow.native_stores
    sessions._rows["s-bad"] = ("u1", '{"x": {"__t": "dc", "c": "Gone", "v": {}}}', 1, __import__("datetime").datetime.now(__import__("datetime").UTC))
    result = await workflow.execute_workflow(user_input(session_id="s-bad"), event_handler=RecordingHandler())
    assert result["success"] is True


async def test_a_parallel_design_falls_back_to_static_on_native(monkeypatch) -> None:
    from neos.workflow.contracts import NODE_CONTRACTS
    from neos.workflow.graph_design_ledger import design_graph_or_fallback
    from neos.workflow.topology import END, GRAPH_ENTRY_WRITES, START, GraphTopology

    chain = (N.QUERY_CLS.value, N.SEARCH_ORCHESTRATOR.value, N.RESP_GENERATOR.value)
    fanout = GraphTopology(
        nodes=chain,
        edges=((START, chain[0]), (chain[0], chain[1]), (chain[0], chain[2]), (chain[1], END), (chain[2], END)),
        initial_writes=GRAPH_ENTRY_WRITES,
    )

    class Designer:
        async def design(self, request):
            return fanout

    from neos.workflow.graph_design import DesignRequest  # 경로가 다르면 graph.py 의 import 를 따른다

    outcome = await design_graph_or_fallback(
        designer=Designer(),
        request=DesignRequest(query="q", catalog=tuple(NODE_CONTRACTS.values()), budget=None),
        contracts=NODE_CONTRACTS,
        allow_parallel=False,
    )
    assert outcome.topology is None
```

> 마지막 테스트의 `DesignRequest`·`design_graph_or_fallback` 호출 모양은 `neos/workflow/graph.py` 의 `_resolve_langgraph_execution_graph` 가 부르는 모양을 그대로 따른다(필수 인자가 더 있으면 같은 값으로 채운다). `test_an_undecodable_session_starts_fresh` 의 행 튜플은 `InMemorySessionStore._rows` 의 실제 모양(Task 4: `(user_id, payload, version, updated_at)`)에 맞춘다 — `__import__` 대신 파일 상단에서 `from datetime import UTC, datetime` 를 import 해 쓴다.

Run: `NEOS_ENV=default GOOGLE_API_KEY=test-key python -m pytest tests/workflow/runtime/test_native_turns.py tests/workflow/test_execute_workflow_contract.py -v`
Expected: 네이티브 턴 7개 PASS, 계약 테스트 8개(4 × 두 런타임) PASS

Run: `NEOS_ENV=default GOOGLE_API_KEY=test-key python -m pytest tests/workflow tests/test_workflow_graph.py tests/api/channels tests/config -q -p no:cacheprovider`
Expected: PASS

- [ ] **Step 6: 커밋**

```bash
git add neos/workflow/runtime/turns.py neos/workflow/runtime/select.py neos/config/schema.py neos/workflow/execution_graph.py neos/workflow/graph.py tests/workflow/support/stub_workflow.py tests/workflow/test_execute_workflow_contract.py tests/workflow/runtime/test_native_turns.py
git commit -m "feat(workflow): native runtime behind workflow.runtime -- session carry, work records, approval waits (spec §4.2-4.4)

execute_workflow attaches a WorkflowRunner when workflow.runtime=native and
wraps the turn with NativeTurns: load and carry the session, open a work
record, save on approval wait or completion, fail the work on error. The
interrupted result now reads pending approvals from the folded state on both
runtimes. Contract tests run on both runtimes. Default stays langgraph."
```

---

### Task 7: 승인 서비스와 세 호출부

**Files:**
- Create: `neos/workflow/runtime/approvals.py`
- Modify: `neos/workflow/runtime/select.py` (`native_approvals()`, `set_native_approvals()`)
- Modify: `neos/workflow/graph.py` (`execute_workflow(..., resume=None)`)
- Modify: `neos/api/handlers/approval_handlers.py` (`respond_to_approval` 네이티브 가지)
- Modify: `neos/api/channels/workflow_approvals.py` (`interrupt_owner`·`decide` 네이티브 가지)
- Modify: `neos/tasks/scheduled_task_runner.py` (`_inject_timeout_rejection` 네이티브 가지)
- Modify: `tests/workflow/test_approval_port_contract.py` (두 런타임)
- Test: `tests/workflow/runtime/test_approvals.py`

**Interfaces:**
- Consumes: `NativeTurns.begin_resume`, `ResumeUnavailable`, `WorkLifecycle.claim` · `expire`, `WorkStore.get` · `waiting_for_session`, `WorkConflict`
- Produces:
  - `approvals.PendingApproval(work_id, user_id, session_id, request_ids: tuple[str, ...], pending: list)`
  - `approvals.ResumeTicket(work_id, session_id, user_id, next_node, decision, request_id)`
  - `approvals.Refusal(reason: Literal["expired", "unknown_request", "not_owner", "conflict"])`
  - `approvals.WorkflowApprovals(workflow, lifecycle)` — `pending_for_session(session_id)` · `decide(work_id, request_id, decision, actor: str | None)` · `resume(ticket, event_handler=None) -> dict` · `expire(work_id, request_id) -> bool`
  - `select.native_approvals() -> WorkflowApprovals`, `select.set_native_approvals(value) -> None`
  - `MultiAgentWorkflow.execute_workflow(user_input, event_handler=None, use_checkpointer=True, *, resume: ResumeTicket | None = None)`

- [ ] **Step 1: 서비스 테스트를 쓴다**

`tests/workflow/runtime/test_approvals.py`:
```python
"""승인 서비스 (spec 2026-10-13 §4.5). 그래프가 아니라 작업 행을 읽는다."""

import asyncio

import pytest

from neos.workflow.enums import WorkflowNode as N
from neos.workflow.runtime.approvals import Refusal, ResumeTicket, WorkflowApprovals
from tests.workflow.support.stub_workflow import (
    SKIP_PATH_ROUTES,
    RecordingHandler,
    StubPlan,
    stub_workflow,
    user_input,
)

pytestmark = [pytest.mark.no_db, pytest.mark.asyncio]

PENDING = [{"request_id": "apr_1", "skill_name": "x"}]
AFTER = {"_should_continue_after_approval": "approved", "_should_replan": "skip_replan", "_should_regenerate": "proceed"}


async def _waiting(monkeypatch, session_id="s-appr", reached=None):
    reached = reached if reached is not None else []

    def answer(state):
        reached.append(state.get("approval_decision"))
        return {"final_response": "승인 후 답", "response_metadata": {}, "execution_time_ms": 1, "execution_steps": []}

    plan = StubPlan(
        nodes={
            N.SKILL_TOOL_SELECTOR.value: lambda s: {"pending_approvals": PENDING, "approval_decision": None},
            N.RESP_GENERATOR.value: answer,
        },
        routes={**SKIP_PATH_ROUTES, "_route_after_skill_tool_selector": "needs_approval", **AFTER},
    )
    workflow = stub_workflow(monkeypatch, plan, flags={"execution_approval": True}, runtime="native")
    await workflow.execute_workflow(user_input(session_id=session_id), event_handler=RecordingHandler())
    _, lifecycle = workflow.native_stores
    return workflow, WorkflowApprovals(workflow, lifecycle), reached


async def test_pending_for_session_reads_the_work_row(monkeypatch) -> None:
    _, approvals, _ = await _waiting(monkeypatch)
    pending = await approvals.pending_for_session("s-appr")
    assert pending.user_id == "u1"
    assert pending.request_ids == ("apr_1",)


async def test_decide_then_resume_runs_from_the_gate_with_the_decision(monkeypatch) -> None:
    _, approvals, reached = await _waiting(monkeypatch)
    pending = await approvals.pending_for_session("s-appr")
    ticket = await approvals.decide(pending.work_id, "apr_1", "approved", actor="u1")
    assert isinstance(ticket, ResumeTicket)
    result = await approvals.resume(ticket, RecordingHandler())
    assert result["success"] is True
    assert result["response"] == "승인 후 답"
    assert reached == ["approved"]
    assert await approvals.pending_for_session("s-appr") is None


async def test_refusals(monkeypatch) -> None:
    _, approvals, _ = await _waiting(monkeypatch)
    pending = await approvals.pending_for_session("s-appr")
    assert await approvals.decide(pending.work_id, "apr_x", "approved", actor="u1") == Refusal("unknown_request")
    assert await approvals.decide(pending.work_id, "apr_1", "approved", actor="intruder") == Refusal("not_owner")
    assert await approvals.decide("wk_missing", "apr_1", "approved", actor="u1") == Refusal("expired")


async def test_two_concurrent_decisions_resume_once(monkeypatch) -> None:
    _, approvals, _ = await _waiting(monkeypatch)
    pending = await approvals.pending_for_session("s-appr")
    first, second = await asyncio.gather(
        approvals.decide(pending.work_id, "apr_1", "approved", actor="u1"),
        approvals.decide(pending.work_id, "apr_1", "rejected", actor="u1"),
    )
    outcomes = sorted([type(first).__name__, type(second).__name__])
    assert outcomes == ["Refusal", "ResumeTicket"]


async def test_expire_closes_the_wait_without_resuming(monkeypatch) -> None:
    workflow, approvals, reached = await _waiting(monkeypatch)
    pending = await approvals.pending_for_session("s-appr")
    assert await approvals.expire(pending.work_id, "apr_1") is True
    assert await approvals.pending_for_session("s-appr") is None
    assert reached == []
    _, lifecycle = workflow.native_stores
    assert (await lifecycle.store.get(pending.work_id)).status == "expired"


async def test_resume_without_a_session_fails_the_work(monkeypatch) -> None:
    workflow, approvals, _ = await _waiting(monkeypatch)
    pending = await approvals.pending_for_session("s-appr")
    ticket = await approvals.decide(pending.work_id, "apr_1", "approved", actor="u1")
    sessions, lifecycle = workflow.native_stores
    await sessions.reset("s-appr")
    result = await approvals.resume(ticket, RecordingHandler())
    assert result["success"] is False
    assert (await lifecycle.store.get(pending.work_id)).status == "failed"
```

Run: `NEOS_ENV=default GOOGLE_API_KEY=test-key python -m pytest tests/workflow/runtime/test_approvals.py -q`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 2: 서비스를 쓴다**

`neos/workflow/runtime/approvals.py`:
```python
"""승인 서비스 (spec 2026-10-13 §4.5) -- 그래프 객체가 아니라 `workflow_runs` 행을 읽는다.

그래서 어느 프로세스에서든 동작한다(웹·채널·워커의 타임아웃이 같은 경로). 결정은 작업 행을 CAS
로 바꾸고(같은 결정 두 번은 하나만 이긴다), 재개 티켓이 결정을 나른다. 재개는 저장된 세션 위에서
게이트 노드부터 러너를 돌리고 `execute_workflow` 와 같은 결과 dict 를 낸다.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from neos.workflow.runtime.work import WorkConflict, WorkLifecycle


@dataclass(frozen=True)
class PendingApproval:
    work_id: str
    user_id: str
    session_id: str
    request_ids: tuple[str, ...]
    pending: list


@dataclass(frozen=True)
class ResumeTicket:
    work_id: str
    session_id: str
    user_id: str
    next_node: str
    decision: str
    request_id: str


@dataclass(frozen=True)
class Refusal:
    reason: Literal["expired", "unknown_request", "not_owner", "conflict"]


class WorkflowApprovals:
    def __init__(self, workflow: Any, lifecycle: WorkLifecycle) -> None:
        self._workflow = workflow
        self._lifecycle = lifecycle

    async def pending_for_session(self, session_id: str) -> PendingApproval | None:
        record = await self._lifecycle.store.waiting_for_session(session_id)
        if record is None or not record.pending:
            return None
        return PendingApproval(
            work_id=record.work_id,
            user_id=record.user_id,
            session_id=str(record.session_id),
            request_ids=tuple(str(item) for item in record.pending.get("request_ids") or ()),
            pending=list(record.pending.get("pending") or []),
        )

    async def decide(
        self, work_id: str, request_id: str, decision: str, actor: str | None
    ) -> ResumeTicket | Refusal:
        """`actor=None` 은 시스템(타임아웃)이다 -- 소유자 검사를 건너뛴다."""
        record = await self._lifecycle.store.get(work_id)
        if record is None or record.status != "waiting_approval" or not record.pending:
            return Refusal("expired")
        if request_id not in (record.pending.get("request_ids") or []):
            return Refusal("unknown_request")
        if actor is not None and actor != record.user_id:
            return Refusal("not_owner")
        try:
            await self._lifecycle.claim(work_id, expected_version=record.version)
        except WorkConflict:
            return Refusal("conflict")
        return ResumeTicket(
            work_id=work_id,
            session_id=str(record.session_id),
            user_id=record.user_id,
            next_node=str(record.pending["next_node"]),
            decision=decision,
            request_id=request_id,
        )

    async def resume(self, ticket: ResumeTicket, event_handler: Any = None) -> Mapping[str, Any]:
        return await self._workflow.execute_workflow(
            {"user_id": ticket.user_id, "session_id": ticket.session_id, "query": ""},
            event_handler,
            use_checkpointer=True,
            resume=ticket,
        )

    async def expire(self, work_id: str, request_id: str) -> bool:
        record = await self._lifecycle.store.get(work_id)
        if record is None or record.status != "waiting_approval" or not record.pending:
            return False
        if request_id not in (record.pending.get("request_ids") or []):
            return False
        try:
            await self._lifecycle.expire(work_id, expected_version=record.version)
        except WorkConflict:
            return False
        return True
```

`neos/workflow/runtime/select.py` 끝에:
```python
_approvals = None


def native_approvals():
    """네이티브 승인 서비스. 워크플로 싱글턴(`multi_agent_workflow`)과 같은 작업 저장소를 쓴다."""
    global _approvals
    if _approvals is None:
        from neos.workflow.graph import multi_agent_workflow
        from neos.workflow.runtime.approvals import WorkflowApprovals

        _approvals = WorkflowApprovals(multi_agent_workflow, native_turns().lifecycle)
    return _approvals


def set_native_approvals(value) -> None:
    global _approvals
    _approvals = value
```

- [ ] **Step 3: `execute_workflow` 에 재개를 단다**

`neos/workflow/graph.py` `execute_workflow` 시그니처를:
```python
    async def execute_workflow(
        self,
        user_input: Dict[str, Any],
        event_handler: Optional[WorkflowEventHandler] = None,
        use_checkpointer: bool = True,
        *,
        resume: Any = None,
    ) -> Dict[str, Any]:
```
docstring Args 에 `resume: 승인 재개 티켓(runtime/approvals.ResumeTicket). 주면 캐시·메모리·템플릿·세션 시작 기록을 건너뛰고 저장된 세션의 게이트 노드부터 돈다(네이티브 런타임 전용).` 를 더한다.

- `bypass_cache = …` 식에 `or resume is not None` 을 더한다
- `await self._load_memory_context(...)`, `await self._apply_research_template(...)`, `await self._record_session_start(...)` 세 줄을 `if resume is None:` 아래로 넣는다
- Task 6 (a) 블록을:
```python
                if execution_graph.runner is not None:
                    from neos.workflow.runtime.select import native_turns

                    if resume is not None:
                        turn = await native_turns().begin_resume(
                            resume,
                            {
                                "_event_handler": event_handler,
                                "execution_start": initial_state["execution_start"],
                            },
                        )
                        config["neos_start_at"] = turn.start_at
                    else:
                        turn = await native_turns().begin(user_input, initial_state, stateful=use_checkpointer)
                    start_state, turn_handle = turn.state, turn.handle
                elif resume is not None:
                    raise RuntimeError("승인 재개 티켓은 네이티브 런타임에서만 쓴다")
                else:
                    ...  # Task 6 의 NULL_TURN 가지 그대로
```
- 재개 턴이 `ResumeUnavailable` 로 실패하면 `except Exception` 가지가 받는다 — 그때 `turn_handle` 이 아직 없으므로, `except` 가지에서 `resume is not None` 이면 `native_turns().lifecycle.fail(resume.work_id, str(e))` 를 시도한다(예외는 경고로 삼킨다):
```python
                elif resume is not None:
                    try:
                        from neos.workflow.runtime.select import native_turns

                        await native_turns().lifecycle.fail(resume.work_id, str(e))
                    except Exception:  # noqa: BLE001
                        logger.warning("resumed work failure could not be recorded", exc_info=True)
```
(Task 6 (e) 의 `if turn_handle is not None:` 블록에 `elif` 로 잇는다.)

**설계 그래프로 멈춘 run 의 재개.** 재개 때 설계를 다시 하면 안 된다(질의마다 LLM 설계 + 다른 그래프). 저장된 세션의 `execution_topology` 로 그래프를 복원한다 — `resume_graph.py` 의 LangGraph 규칙과 같다.

`neos/workflow/runtime/designed.py` 끝에:
```python
async def resume_execution_graph(workflow: Any, saved_state: Any, *, use_checkpointer: bool) -> Any:
    """재개할 그래프를 저장된 상태에서 복원한다(spec §4.5). 설계를 다시 하지 않는다.

    토폴로지가 없으면 정적 그래프, 있으면 현재 계약으로 다시 검증한 뒤 순차 배선. 검증이 깨지면
    (배포가 노드를 지웠다 등) 재개하지 않는다 -- `ResumeUnavailable`.
    """
    from dataclasses import replace

    from neos.config.settings import settings
    from neos.workflow.execution_graph import ExecutionGraph, current_static_flags, static_execution_graph
    from neos.workflow.graph_design_ledger import _DEFAULT_MUST_WRITE, topology_hash
    from neos.workflow.runtime.turns import ResumeUnavailable
    from neos.workflow.topology import topology_from_payload, validate_topology

    payload = (saved_state or {}).get("execution_topology")
    if payload is None:
        await workflow._ensure_graph_initialized(use_checkpointer=use_checkpointer)
        static = static_execution_graph(compiled=workflow.graph, flags=current_static_flags())
        return replace(static, runner=workflow._native_runner(static, use_checkpointer=use_checkpointer))
    try:
        topology = topology_from_payload(payload)
    except Exception as error:  # noqa: BLE001 -- 읽을 수 없는 페이로드는 재개할 수 없다
        raise ResumeUnavailable(f"stored topology payload could not be read: {error}") from error
    contracts: Any = NODE_CONTRACTS
    subagent_host = None
    extra_nodes = set(topology.nodes) - set(NODE_CONTRACTS)
    if extra_nodes and settings.config.workflow.subagent_nodes_enabled:
        from neos.workflow.subagent_nodes import merged_contracts

        contracts = merged_contracts(NODE_CONTRACTS)
        if extra_nodes & set(contracts):
            subagent_host = workflow._build_subagent_host(None)
    violations = validate_topology(
        topology, contracts=contracts, must_write=_DEFAULT_MUST_WRITE, allow_parallel=False
    )
    if violations:
        raise ResumeUnavailable(f"stored topology is no longer valid: {violations}")
    designed = ExecutionGraph(
        compiled=None,
        nodes=topology.nodes,
        topology_hash=topology_hash(topology),
        source="designed",
        topology=topology,
        subagent_host=subagent_host,
    )
    return replace(designed, runner=workflow._native_runner(designed, use_checkpointer=use_checkpointer))
```

`execute_workflow` 에서 `execution_graph = await self._resolve_execution_graph(...)` 를:
```python
                if resume is not None:
                    from neos.workflow.runtime.designed import resume_execution_graph
                    from neos.workflow.runtime.select import native_turns
                    from neos.workflow.runtime.turns import ResumeUnavailable

                    saved = await native_turns().sessions.load(resume.session_id)
                    if saved is None:
                        raise ResumeUnavailable(f"{resume.session_id}: 저장된 세션이 없다")
                    execution_graph = await resume_execution_graph(self, saved.state, use_checkpointer=True)
                else:
                    execution_graph = await self._resolve_execution_graph(
                        user_input=user_input,
                        use_checkpointer=use_checkpointer,
                        span=span,
                        event_handler=event_handler,
                    )
```
로 바꾼다. 재개 때는 `initial_state["execution_topology"] = …` 와 `subagent_scope` 대입을 건너뛴다(저장된 상태가 이미 갖고 있다) — 두 대입을 `if resume is None:` 아래로 넣는다.

`tests/workflow/runtime/test_designed.py` 끝에:
```python
@pytest.mark.asyncio
async def test_resume_without_a_stored_topology_uses_the_static_runner(monkeypatch) -> None:
    from neos.workflow.runtime.designed import resume_execution_graph
    from tests.workflow.support.stub_workflow import StubPlan, stub_workflow

    workflow = stub_workflow(monkeypatch, StubPlan(), runtime="native")
    graph = await resume_execution_graph(workflow, {"x": 1}, use_checkpointer=True)
    assert graph.source == "static" and graph.runner is not None


@pytest.mark.asyncio
async def test_resume_with_a_stored_chain_uses_the_designed_runner(monkeypatch) -> None:
    from neos.workflow.runtime.designed import resume_execution_graph
    from neos.workflow.topology import topology_to_payload
    from tests.workflow.support.stub_workflow import StubPlan, stub_workflow

    workflow = stub_workflow(monkeypatch, StubPlan(), runtime="native")
    graph = await resume_execution_graph(
        workflow, {"execution_topology": topology_to_payload(_chain())}, use_checkpointer=True
    )
    assert graph.source == "designed"
    assert tuple(graph.nodes) == _CHAIN
```
> `_chain()` 의 토폴로지가 `_DEFAULT_MUST_WRITE`(응답 키 쓰기) 검증을 통과하지 못하면, 통과하는 기존 테스트 토폴로지(`tests/workflow/test_designed_resume_round_trip.py` 가 쓰는 것)를 가져다 쓴다. 테스트 모듈 상단의 `pytestmark = pytest.mark.no_db` 는 그대로 두고, 이 두 테스트만 `@pytest.mark.asyncio` 를 단다.

Run: `NEOS_ENV=default GOOGLE_API_KEY=test-key python -m pytest tests/workflow/runtime/test_approvals.py tests/workflow/runtime/test_designed.py -q`
Expected: PASS

- [ ] **Step 4: 세 호출부를 네이티브 가지로**

`neos/api/channels/workflow_approvals.py` — 모듈 상단에:
```python
def _native() -> bool:
    from neos.workflow.runtime.select import runtime_name

    return runtime_name() == "native"
```
`interrupt_owner` 본문 맨 앞에:
```python
        if _native():
            from neos.workflow.runtime.select import native_approvals

            pending = await native_approvals().pending_for_session(session_id)
            return pending.user_id if pending is not None else None
```
`decide` 본문 맨 앞(`decision = …` 바로 아래)에:
```python
        if _native():
            return await self._decide_native(
                session_id=session_id, request_id=request_id, owner_id=owner_id, approve=approve
            )
```
그리고 메서드를 더한다:
```python
    async def _decide_native(self, *, session_id: str, request_id: str, owner_id: str, approve: bool) -> str:
        """반환 문자열은 LangGraph 경로와 같다(게이트웨이·Q 계약, spec §5 경계 2)."""
        from neos.workflow.runtime.approvals import Refusal
        from neos.workflow.runtime.select import native_approvals

        approvals = native_approvals()
        pending = await approvals.pending_for_session(session_id)
        if pending is None or not request_id:
            return _INVALID_REQUEST
        ticket = await approvals.decide(
            pending.work_id,
            request_id,
            "approved" if approve else "rejected",
            actor=owner_id or pending.user_id,
        )
        if isinstance(ticket, Refusal):
            return _INVALID_REQUEST
        await _mark_resolved_best_effort(request_id, owner_id)

        async def _resume() -> None:
            try:
                await approvals.resume(ticket)
            except Exception as error:  # noqa: BLE001
                logger.error("[RuntimeWorkflowApprovals] native resume failed: session=%s: %s", session_id, error)

        asyncio.create_task(_resume(), name=f"channel_approval_resume_{session_id}")
        return f"{request_id} {'approved' if approve else 'denied'}"
```
(재개 결과를 채널로 보내는 것은 Plan 2b 의 CH-RESUME 이다 — 여기서는 지금처럼 버린다.)

`neos/api/handlers/approval_handlers.py` `respond_to_approval` — `pending_approval = await _require_pending_approval_owner(...)` 바로 아래에:
```python
    from neos.workflow.runtime.select import runtime_name

    if runtime_name() == "native":
        return await _respond_native(body, current_user, pending_approval)
```
그리고 모듈에 함수를 더한다(기존 import 를 쓴다 — `stream_manager`, `require_stream_session_owner`, `_mark_approval_resolved`, `HTTPException`, `status`, `asyncio`, `logger`, `ApprovalResponseResult`):
```python
class _StreamNodeEvents(NullEventHandler):
    """재개된 턴의 노드 완료를 승인 스트림으로 흘린다 -- LangGraph 가지의 node_complete 와 같은 모양."""

    def __init__(self, session_id: str) -> None:
        self._session_id = session_id

    async def on_node_complete(self, node_name, result) -> None:
        await stream_manager.add_event(self._session_id, "node_complete", {"node": node_name})


async def _respond_native(body, current_user, pending_approval) -> ApprovalResponseResult:
    from neos.workflow.runtime.approvals import Refusal
    from neos.workflow.runtime.select import native_approvals

    session_id = body.session_id
    approvals = native_approvals()
    pending = await approvals.pending_for_session(session_id)
    if pending is None or body.request_id not in pending.request_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="유효하지 않은 request_id입니다. 해당 세션의 pending approval이 아닙니다.",
        )
    if body.add_to_allowlist and body.skill_name and pending_approval["skill_name"] != body.skill_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="skill_name이 해당 request_id의 스킬과 일치하지 않습니다.",
        )
    session = stream_manager.get_session(session_id)
    if session:
        require_stream_session_owner(session, current_user)
    else:
        session = stream_manager.create_session(session_id, current_user.user_id)
        require_stream_session_owner(session, current_user)
    ticket = await approvals.decide(pending.work_id, body.request_id, body.decision, actor=current_user.user_id)
    if isinstance(ticket, Refusal):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT if ticket.reason == "conflict" else status.HTTP_400_BAD_REQUEST,
            detail=f"승인을 처리할 수 없습니다: {ticket.reason}",
        )
    await _mark_approval_resolved(body.request_id, current_user.user_id)

    async def _resume() -> None:
        try:
            result = await approvals.resume(ticket, _StreamNodeEvents(session_id))
            await stream_manager.add_event(session_id, "completed", {"response": result.get("response") or ""})
        except Exception as error:  # noqa: BLE001
            logger.error(f"[ApprovalHandler] native resume failed: session={session_id}: {error}")
            await stream_manager.add_event(session_id, "error", {"message": str(error)})

    asyncio.create_task(_resume(), name=f"approval_resume_{session_id}")
    return await _finish_response(body, current_user)


async def _finish_response(body, current_user) -> ApprovalResponseResult:
    """두 런타임 가지가 같은 꼬리를 쓴다 -- allowlist 등록과 응답 모양."""
    if body.add_to_allowlist and body.skill_name:
        await _add_to_allowlist(user_id=current_user.user_id, skill_name=body.skill_name)
    return ApprovalResponseResult(status="resumed", session_id=body.session_id, decision=body.decision)
```
그리고 `respond_to_approval` 의 마지막 블록(`# allowlist 등록 …` 부터 `return ApprovalResponseResult(...)` 까지)을 `return await _finish_response(body, current_user)` 한 줄로 바꾼다 — LangGraph 가지의 동작은 같다. `NullEventHandler` 는 `from neos.workflow.events import NullEventHandler` 로 가져온다.

`neos/tasks/scheduled_task_runner.py` `_inject_timeout_rejection` 본문 맨 앞(docstring 아래)에:
```python
    from neos.workflow.runtime.select import runtime_name

    if runtime_name() == "native":
        from neos.workflow.runtime.select import native_approvals

        approvals = native_approvals()
        pending = await approvals.pending_for_session(session_id)
        if pending is None:
            return False
        # 워커에서도 동작한다 -- 그래프 객체가 아니라 작업 행을 읽는다(spec §4.5, R6).
        return await approvals.expire(pending.work_id, request_id)
```

`tests/workflow/test_approval_port_contract.py` — 파일 상단에 런타임 픽스처를 두고(Task 6 의 계약 파일과 같은 모양) `_interrupted_workflow(monkeypatch, reached)` 를 `_interrupted_workflow(monkeypatch, reached, runtime)` 로 바꿔 `stub_workflow(..., runtime=runtime)` 에 넘긴다. 네이티브면 `checkpointer=` 인자는 무시된다. 다섯 테스트에 `runtime` 인자를 더하고 단언은 바꾸지 않는다. 네이티브에서도 `_drain_resumes` 가 `channel_approval_resume_` 이름의 태스크를 기다린다.

Run: `NEOS_ENV=default GOOGLE_API_KEY=test-key python -m pytest tests/workflow/test_approval_port_contract.py tests/workflow/runtime -q`
Expected: PASS(승인 포트 계약 10개 = 5 × 두 런타임)

Run: `NEOS_ENV=default GOOGLE_API_KEY=test-key python -m pytest tests/api tests/tasks tests/workflow -q -p no:cacheprovider`
Expected: PASS — 기본 런타임은 LangGraph 라 기존 승인 테스트는 그대로다

- [ ] **Step 5: 커밋**

```bash
git add neos/workflow/runtime/approvals.py neos/workflow/runtime/select.py neos/workflow/runtime/designed.py neos/workflow/graph.py neos/api/handlers/approval_handlers.py neos/api/channels/workflow_approvals.py neos/tasks/scheduled_task_runner.py tests/workflow/test_approval_port_contract.py tests/workflow/runtime/test_approvals.py tests/workflow/runtime/test_designed.py
git commit -m "feat(workflow): approval service over work records; web, channel and timeout callers use it on the native runtime (spec §4.5)

decide claims the work row with a version check, so concurrent decisions
resume once; resume runs execute_workflow from the saved gate node without
rebuilding the initial state; expire works from any process. The channel
port keeps its signature and reply strings. Default stays langgraph."
```

---

### Task 8: 코딩 태스크를 작업 기록에 잇는다 (결정 B)

**Files:**
- Create: `neos/coding/application/work_port.py`
- Modify: `neos/coding/application/task_service.py` (`create_task` 끝)
- Modify: `neos/coding/persistence/postgres.py` (`create_task` 커밋 뒤)
- Modify: `neos/coding/application/run_service.py` (`_after_completed`)
- Create: `neos/workflow/runtime/coding_link.py`
- Modify: `neos/main.py` (시작 시 등록), `neos/workflow/celery_app.py` (`init_worker` 에서 등록)
- Test: `tests/workflow/runtime/test_coding_link.py`

**Interfaces:**
- Consumes: `WorkLifecycle.start` · `complete`, `WorkStore.by_ref` (Task 5); `CodingTask`(`neos.coding.domain.models`)
- Produces:
  - `work_port.WorkPort` 프로토콜: `coding_task_created(task) -> None` · `coding_task_completed(task) -> None`
  - `work_port.set_work_port(port: WorkPort | None) -> None`, `work_port.notify_task_created(task) -> None`, `work_port.notify_task_completed(task) -> None` — 실패를 삼키고 로그만
  - `coding_link.CodingWorkLink(lifecycle: WorkLifecycle)`, `coding_link.install_coding_link() -> bool` (네이티브일 때만 등록하고 True)

- [ ] **Step 1: 테스트를 쓴다**

`tests/workflow/runtime/test_coding_link.py`:
```python
"""코딩 태스크 → 작업 기록 (spec 2026-10-13 §4.4, 결정 B). Q 코드를 건드리지 않는 포트 주입."""

from datetime import UTC, datetime

import pytest

from neos.coding.application import work_port
from neos.coding.domain.models import CodingTask, CodingTaskMode, CodingTaskStatus
from neos.workflow.runtime.coding_link import CodingWorkLink
from neos.workflow.runtime.work import InMemoryWorkStore, WorkLifecycle

pytestmark = [pytest.mark.no_db, pytest.mark.asyncio]


def _task(agent_id=None) -> CodingTask:
    now = datetime.now(UTC)
    return CodingTask(
        task_id="ct_link_1", owner_id="u1", prompt="p", status=CodingTaskStatus.QUEUED, version=1, last_seq=0,
        created_at=now, updated_at=now, mode=CodingTaskMode.AUTONOMOUS, agent_id=agent_id,
    )


@pytest.fixture
def link(monkeypatch):
    lifecycle = WorkLifecycle(InMemoryWorkStore())
    monkeypatch.setattr(work_port, "_port", CodingWorkLink(lifecycle))
    return lifecycle


async def test_a_trigger_task_opens_and_completes_a_coding_work(link) -> None:
    await work_port.notify_task_created(_task(agent_id="sa_1"))
    record = await link.store.by_ref("coding", "ct_link_1")
    assert (record.entry, record.kind, record.user_id, record.status) == ("trigger", "coding", "u1", "running")
    assert record.delivery == {"kind": "none"}
    await work_port.notify_task_completed(_task(agent_id="sa_1"))
    assert (await link.store.by_ref("coding", "ct_link_1")).status == "completed"


async def test_a_task_without_an_agent_is_an_api_entry(link) -> None:
    await work_port.notify_task_created(_task())
    assert (await link.store.by_ref("coding", "ct_link_1")).entry == "api"


async def test_a_broken_port_never_breaks_the_coding_path(monkeypatch) -> None:
    class Broken:
        async def coding_task_created(self, task):
            raise RuntimeError("down")

        async def coding_task_completed(self, task):
            raise RuntimeError("down")

    monkeypatch.setattr(work_port, "_port", Broken())
    await work_port.notify_task_created(_task())
    await work_port.notify_task_completed(_task())


async def test_no_port_is_a_no_op(monkeypatch) -> None:
    monkeypatch.setattr(work_port, "_port", None)
    await work_port.notify_task_created(_task())


def test_the_link_installs_only_on_the_native_runtime(monkeypatch) -> None:
    from neos.config.settings import settings
    from neos.workflow.runtime import coding_link

    monkeypatch.setattr(work_port, "_port", None)
    monkeypatch.setattr(settings.config.workflow, "runtime", "langgraph")
    assert coding_link.install_coding_link() is False
    assert work_port._port is None
```

> `CodingTask` 의 필수 필드가 더 있으면 `neos/coding/domain/models.py` 의 정의대로 채운다(`create_task` 의 생성 코드가 정본이다).

Run: `NEOS_ENV=default GOOGLE_API_KEY=test-key python -m pytest tests/workflow/runtime/test_coding_link.py -q`
Expected: FAIL — `ImportError: cannot import name 'work_port'`

- [ ] **Step 2: 포트를 쓰고 코딩 쪽에서 부른다**

`neos/coding/application/work_port.py`:
```python
"""코딩 태스크 → 작업 기록 포트 (spec 2026-10-13 §4.4, 결정 B).

`neos.coding` 은 채팅 워크플로 런타임을 import 하지 않는다(가드). 그래서 코딩 쪽은 이 포트만
정의하고, 구현(`neos.workflow.runtime.coding_link`)은 앱·워커 시작 때 꽂힌다. 포트가 없거나
실패해도 태스크 생성·완료는 그대로다 -- 로그 한 줄만 남긴다(Q13f 완료 훅과 같은 규율).
"""

from __future__ import annotations

import logging
from typing import Protocol

from neos.coding.domain.models import CodingTask

logger = logging.getLogger(__name__)


class WorkPort(Protocol):
    async def coding_task_created(self, task: CodingTask) -> None: ...

    async def coding_task_completed(self, task: CodingTask) -> None: ...


_port: WorkPort | None = None


def set_work_port(port: WorkPort | None) -> None:
    global _port
    _port = port


async def notify_task_created(task: CodingTask) -> None:
    if _port is None:
        return
    try:
        await _port.coding_task_created(task)
    except Exception:  # noqa: BLE001 -- 기록 실패가 태스크 생성을 막지 않는다
        logger.exception("work record for coding task creation failed task_id=%s", task.task_id)


async def notify_task_completed(task: CodingTask) -> None:
    if _port is None:
        return
    try:
        await _port.coding_task_completed(task)
    except Exception:  # noqa: BLE001
        logger.exception("work record for coding task completion failed task_id=%s", task.task_id)
```

`neos/coding/application/task_service.py` `create_task` 의 `self._notify_task_created(task.task_id)` 바로 아래에:
```python
        await notify_task_created(task)
```
(파일 상단에 `from neos.coding.application.work_port import notify_task_created`.)

`neos/coding/persistence/postgres.py` `create_task` — 트랜잭션 블록(`async with session.begin():`)이 끝난 **뒤**, `return` 바로 앞에 같은 한 줄과 import 를 더한다. 트랜잭션 안에 두지 않는다(기록 실패가 태스크 INSERT 를 되돌리면 안 된다).

`neos/coding/application/run_service.py` `_after_completed` 를:
```python
    async def _after_completed(self, task_id: str) -> None:
        """Both ways a run completes come here. Hook failures are logged and
        never fail the run -- the run is already committed as completed."""
        try:
            task = await self._tasks.get(task_id)
        except Exception:
            logger.exception("coding completion hook failed task_id=%s", task_id)
            return
        if task is None:
            return
        await notify_task_completed(task)
        if self._on_completed is None:
            return
        try:
            checkpoint = await self._runs.latest_checkpoint(task_id)
            await self._on_completed(
                task, checkpoint.loop_state if checkpoint is not None else None
            )
        except Exception:
            logger.exception("coding completion hook failed task_id=%s", task_id)
```
(파일 상단에 `from neos.coding.application.work_port import notify_task_completed`. `_on_completed` 의 기본값 `_standing_agent_completion` 은 바꾸지 않는다 — `tests/standing/test_agent_onboarding.py` 가 고정한다.)

- [ ] **Step 3: 구현과 등록**

`neos/workflow/runtime/coding_link.py`:
```python
"""코딩 태스크 포트의 구현 (spec 2026-10-13 §4.4, 결정 B).

트리거(에이전트 있음)로 열린 태스크는 entry=trigger, 그 밖은 api. 전달은 코딩 태스크의 기존 알림
경로(Q10b)가 그대로 맡으므로 `delivery={"kind": "none"}` -- 여기서는 같은 ID 체계와 결과 위치만 준다.
"""

from __future__ import annotations

from typing import Any

from neos.workflow.runtime.work import WorkConflict, WorkLifecycle


class CodingWorkLink:
    def __init__(self, lifecycle: WorkLifecycle) -> None:
        self._lifecycle = lifecycle

    async def coding_task_created(self, task: Any) -> None:
        await self._lifecycle.start(
            "trigger" if task.agent_id else "api",
            "coding",
            user_id=task.owner_id,
            session_id=None,
            delivery={"kind": "none"},
            ref_id=task.task_id,
        )

    async def coding_task_completed(self, task: Any) -> None:
        record = await self._lifecycle.store.by_ref("coding", task.task_id)
        if record is None or record.status != "running":
            return
        try:
            await self._lifecycle.complete(record.work_id, {"final_response": None, "author": None, "verified_by": None})
        except WorkConflict:
            return


def install_coding_link() -> bool:
    """네이티브 런타임일 때만 포트를 꽂는다 -- 기본 런타임의 동작은 바뀌지 않는다."""
    from neos.coding.application.work_port import set_work_port
    from neos.workflow.runtime.select import native_turns, runtime_name

    if runtime_name() != "native":
        return False
    set_work_port(CodingWorkLink(native_turns().lifecycle))
    return True
```

`neos/main.py` — `skill_manager.register_builtin_skills()` 를 부르는 시작 블록에(같은 try 스타일로):
```python
        from neos.workflow.runtime.coding_link import install_coding_link

        if install_coding_link():
            logger.info("[Startup] coding tasks are linked to workflow work records (native runtime)")
```
`neos/workflow/celery_app.py` `init_worker` 의 `sync_live_overlay(model_config.catalog)` 아래에:
```python
    # 네이티브 런타임이면 코딩 태스크를 작업 기록에 잇는다 (spec 2026-10-13 §4.4).
    from neos.workflow.runtime.coding_link import install_coding_link

    install_coding_link()
```

Run:
```bash
NEOS_ENV=default GOOGLE_API_KEY=test-key python -m pytest tests/workflow/runtime/test_coding_link.py tests/workflow/test_import_boundaries.py tests/standing/test_agent_onboarding.py tests/coding -q -p no:cacheprovider
```
Expected: PASS — 가드(코딩이 런타임을 import 하지 않음)와 Q 의 완료 훅 테스트가 그대로다

- [ ] **Step 4: 커밋**

```bash
git add neos/coding/application/work_port.py neos/coding/application/task_service.py neos/coding/persistence/postgres.py neos/coding/application/run_service.py neos/workflow/runtime/coding_link.py neos/main.py neos/workflow/celery_app.py tests/workflow/runtime/test_coding_link.py
git commit -m "feat(coding): coding tasks open and complete work records through an injected port (spec §4.4, decision B)

neos.coding defines WorkPort and calls it after task creation (outside the
insert transaction) and on completion; neos.workflow.runtime.coding_link
implements it and is installed at app and worker start only on the native
runtime. Port failures are logged and never affect the coding path. The
standing-agent completion hook default is unchanged."
```

---

### Task 9: 전체 확인

**Files:** 없음(확인만). 고칠 것이 나오면 해당 Task 의 파일을 고치고 그 Task 의 형식으로 커밋한다.

- [ ] **Step 1: CI 의 Ruff 명령 그대로**

`.github/workflows/backend-ci.yml` 의 Ruff `run:` 경로 목록을 그대로 쓴다(`neos/workflow/runtime` · `tests/workflow/runtime` 포함). 추가로:
```bash
uv run --frozen ruff check neos/workflow/graph.py neos/api/handlers/approval_handlers.py neos/api/channels/workflow_approvals.py neos/tasks/scheduled_task_runner.py neos/main.py --select F401,F841
```
Expected: 0건

- [ ] **Step 2: 전체 스위트와 이름 비교**

```bash
NEOS_ENV=default GOOGLE_API_KEY=test-key python -m pytest --collect-only -qq tests | grep "::" | sort > /tmp/names_after_plan2.txt
NEOS_ENV=default GOOGLE_API_KEY=test-key python -m pytest tests -q -p no:cacheprovider -rf
git diff --stat <PLAN2_BASE> -- tests/standing tests/jev tests/api/channels
```
`<PLAN2_BASE>` 는 이 계획을 시작한 커밋이다(SDD 원장에 적는다). 기준선 이름 목록도 그 커밋에서 같은 명령으로 떠 두고 비교한다 — 사라진 이름이 없어야 한다.
Expected: 0 failed(R1 xfail 하나), 사라진 이름 없음, 보호 경로 diff 없음.

- [ ] **Step 3: 네이티브로 전체 워크플로 테스트를 한 번 더**

설정에는 중첩 환경 변수 오버라이드가 없다 — 오버레이 파일로 건다. 테스트 세션 오버레이(`tests/fixtures/config/test-session.yaml`)를 그대로 복사해 `workflow:` 블록에 `runtime: native` 한 줄을 더한 임시 파일을 작업 디렉터리 밖(스크래치)에 만들고:
```bash
cp tests/fixtures/config/test-session.yaml "$SCRATCH/test-session-native.yaml"
# $SCRATCH/test-session-native.yaml 의 `workflow:` 블록에 `  runtime: native` 를 더한다
NEOS_ENV=default GOOGLE_API_KEY=test-key NEOS_CONFIG_PATH="$SCRATCH/test-session-native.yaml" \
  python -m pytest tests/workflow tests/api -q -p no:cacheprovider -rf
```
이 실행은 **기록용**이다: 네이티브 기본 전환(Plan 3)의 남은 차이를 이름으로 모은다. 실패 목록을 보고서에 남기고, 이 계획의 계약(네이티브 파라미터 테스트)에 걸리는 실패만 고친다. 임시 파일은 커밋하지 않는다.

- [ ] **Step 4: 로드맵·문서**

`docs/CONFIGURATION.md` 에 `workflow.runtime`(기본 `langgraph`, `native` 는 Plan 3 까지 시험용)과 `workflow.session.max_carried_items` 를 기존 표 형식으로 적는다(Task 4·6 에서 이미 적었으면 건너뛴다). 커밋:
```bash
git add docs/CONFIGURATION.md
git commit -m "docs(config): workflow.runtime and workflow.session settings"
```
