# Deep Analysis Phase 3b — 챗을 job 소비자로 전환 (구현 계획)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 챗 워크플로우가 deep analysis를 **인라인 완주**시키는 대신 **job으로 제출**하고 즉시 반환하게 만들어, 챗과 전용 API가 동일한 이벤트 스트림 계약을 소비하도록 한다.

**Architecture:** Phase 3a가 만든 durable job 서비스(`jobs.py` + `neos/tasks/deep_analysis_job_task.py` + `/api/v1/deep-analysis/{run_id}/events`) 위에 챗을 얹는다. `graph.py`의 `_deep_analysis_orchestrator_node`(블로킹 완주 + wall-clock 캡)를 **디스패치 노드**로 교체한다: run 생성 → job 제출 → `neos:deep_analysis_started` SSE 이벤트 발행 → `END`. 리포트는 job 완료 시 실행자 계층(`_persist_assistant_message`)이 어시스턴트 메시지로 영속화한다 — 이 계층은 Celery/inline 두 실행자가 공유하는 `_execute`에 이미 걸려 있으므로 `jobs.py`의 프레임워크 프리 성질을 깨지 않는다.

**Tech Stack:** Python 3.12, LangGraph StateGraph, FastAPI SSE, SQLAlchemy 2.0 async, Celery 5.4, pytest/pytest-asyncio.

## Global Constraints

- **`web/`을 절대 수정하지 않는다.** 프론트 에이전트가 동시에 작업 중이다.
- `neos/workflow/deep_analysis/jobs.py`는 프레임워크 프리를 유지한다 — `langchain`/`langgraph`/`fastapi`/`starlette`/`celery`/`ChatService`를 임포트하지 않는다. `tests/workflow/test_deep_analysis_job_no_regression.py`가 AST로 강제한다.
- **확정된 계약(프론트와 공유 — 임의 변경 금지):**
  - `POST /api/v1/deep-analysis` → `202 {run_id, status, executor, events_url}`
  - `GET /api/v1/deep-analysis/{run_id}/events?after=<seq>` (SSE, `after=0`이면 전체 이력)
  - `POST /api/v1/deep-analysis/{run_id}/resume`
  - job 이벤트 4종: `job_started` / `job_resumed` / `job_completed`(payload에 `report_markdown`) / `job_failed`
  - **3b 신규 챗 SSE 이벤트:** `event: neos:deep_analysis_started`, `data: {"run_id","events_url","assistant_message_id"}`
- `DEEP_ANALYSIS_ENABLED=false`(기본값)일 때 라우팅 맵에 `"deep_analysis"` 키가 없고 노드도 등록되지 않는 **구조적 무회귀 보장**을 유지한다 (AC7).
- cassette 우회 금지 — D19 golden 게이트 유지.
- `docs/DIRECTION_260717.md`, `docs/ROADMAP.md`, `docs/FE_AUDIT_260717.md` 수정 금지.
- 커밋 메시지에 `Co-Authored-By` 트레일러를 넣지 않는다.

## 테스트 환경 (사전 존재 결함 3건 — 고치지 않는다)

```bash
# workflow (mission/harness 분리 — basename 충돌로 단일 실행 불가)
.venv/bin/pytest tests/workflow/ -q --ignore=tests/workflow/mission --ignore=tests/workflow/harness
.venv/bin/pytest tests/workflow/mission tests/workflow/harness -q
.venv/bin/pytest tests/api/ -q
```

**측정된 기준선 (2026-07-19, 구현 전):**

| 스위트 | 결과 |
|---|---|
| `tests/workflow/` (mission/harness 제외) | **287 passed, 37 failed** (Postgres 미기동 → `deep_analysis` DB 테스트) |
| `tests/workflow/mission tests/workflow/harness` | **103 passed** |
| `tests/api/` | **317 passed, 1 failed** (`test_query_authorization.py::test_production_app_exposes_only_authenticated_coding_websocket` — 전체 실행 시 스위트 오염) |

**기준 대비 신규 실패 0**이 완료 조건이다.

## File Structure

| 파일 | 책임 | 변경 |
|---|---|---|
| `neos/api/models/open_responses.py` | 챗 SSE 확장 이벤트 Pydantic 모델 | 추가: `NeosDeepAnalysisStartedEvent` |
| `neos/api/models/query_models.py` | 워크플로우 스트림 이벤트 타입 상수 | 추가: `WorkflowStreamEventType.DEEP_ANALYSIS_STARTED` |
| `neos/api/handlers/workflow_stream_handlers.py` | 노드 → 이벤트 큐 콜백 | 추가: `on_deep_analysis_started()` |
| `neos/workflow/state.py` | `AgentState` TypedDict | 추가: `conversation_id` |
| `neos/workflow/enums.py` | 노드 이름 상수 | `DEEP_ANALYSIS_ORCHESTRATOR` → `DEEP_ANALYSIS_DISPATCH` |
| `neos/workflow/graph.py` | 그래프 조립 + 노드 구현 | **제거**: `_deep_analysis_orchestrator_node`, `_persist_deep_analysis_failure`. **추가**: `_deep_analysis_dispatch_node`. 엣지 → `END` |
| `neos/api/handlers/chat_handlers.py` | 챗 SSE 스트리밍 루프 | `deep_analysis_started` 큐 이벤트 → `NeosDeepAnalysisStartedEvent`. `conversation_id`를 `user_input`에 전달 |
| `neos/api/adapters/stream_adapter.py` | legacy → OpenResponses 변환 | `deep_analysis_started` 매핑 |
| `neos/tasks/deep_analysis_job_task.py` | 실행자 계층 (리포트 영속화 소재지) | 변경 없음 — 회귀 테스트로 고정만 |
| `neos/workflow/deep_analysis/DECISIONS.md` | 결정 기록 | 추가: D23 (D18 대체) |
| `tests/workflow/test_deep_analysis_node.py` | 노드 테스트 | **전면 재작성** (디스패치 노드 기준) |
| `tests/workflow/test_deep_analysis_job_no_regression.py` | 3a/3b 경계 + 프레임워크 프리 고정 | 경계 어서션 반전 (3b 완료 기준) |
| `tests/workflow/routing/test_deep_analysis_routing.py` | 라우팅 상수 고정 | 노드 이름 상수 갱신 |
| `tests/tasks/test_deep_analysis_report_persistence.py` | 리포트 영속화 회귀 (신규) | 생성 |

---

## Task 1: `conversation_id`를 AgentState로 나른다

디스패치 노드가 `create_run(conversation_id=...)`을 채우려면 대화 ID가 상태에 있어야 한다. 현재 챗은 `session_id`에 `conversation_id`를 실어 보내지만, `/api/v1/query` 등 다른 호출자는 `session_id`를 진짜 세션으로 쓴다 — 두 의미를 겹쳐 쓰면 대화가 아닌 run에 엉뚱한 `conversation_id`가 박힌다. 명시 필드를 추가한다.

**Files:**
- Modify: `neos/workflow/state.py`
- Modify: `neos/workflow/graph.py` (`_create_initial_state`, 약 1721행)
- Modify: `neos/api/handlers/chat_handlers.py` (약 830행 `user_input` 딕셔너리)
- Test: `tests/workflow/test_deep_analysis_node.py`

**Interfaces:**
- Produces: `AgentState["conversation_id"]: Optional[str]` — 챗 경로에서만 채워진다. 다른 호출자는 `None`.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/workflow/test_deep_analysis_node.py`를 아래 내용으로 **새로 만든다**(기존 내용은 Task 3에서 완전히 대체되므로 지금 통째로 덮어쓴다):

```python
"""Phase 3b: 챗은 deep analysis job의 제출자다 (D23).

D18의 블로킹 완주 노드는 사라졌다. 이 파일은 디스패치 노드의 계약을 고정한다.
"""

import pytest

pytestmark = pytest.mark.no_db


def test_initial_state_carries_conversation_id():
    """챗 경로가 run에 conversation_id를 심으려면 상태에 그 필드가 있어야 한다.

    session_id를 재사용하지 않는다 -- /api/v1/query 호출자에게 session_id는
    대화가 아니라 세션이라, 겹쳐 쓰면 run이 없는 대화를 가리킨다.
    """
    from neos.workflow import graph as graph_mod

    state = graph_mod.multi_agent_workflow._create_initial_state(
        {
            "user_id": "u1",
            "session_id": "s1",
            "query": "q",
            "conversation_id": "conv-1",
        }
    )
    assert state["conversation_id"] == "conv-1"


def test_initial_state_conversation_id_defaults_to_none():
    """대화가 아닌 호출자(/api/v1/query)는 None이어야 한다."""
    from neos.workflow import graph as graph_mod

    state = graph_mod.multi_agent_workflow._create_initial_state(
        {"user_id": "u1", "session_id": "s1", "query": "q"}
    )
    assert state["conversation_id"] is None
```

- [ ] **Step 2: 실패를 확인한다**

Run: `.venv/bin/pytest tests/workflow/test_deep_analysis_node.py -q`
Expected: FAIL — `KeyError: 'conversation_id'`

- [ ] **Step 3: 상태 필드를 추가한다**

`neos/workflow/state.py`의 `deep_analysis_run_id` 선언(175행 근처) **바로 위**에 추가:

```python
    # Phase 3b: 챗에서 시작된 run을 대화에 되묶기 위한 대화 ID.
    # session_id와 별도다 -- /api/v1/query는 session_id를 대화가 아닌
    # 세션으로 쓰므로 의미를 겹쳐 쓰면 안 된다.
    conversation_id: Optional[str]
```

`neos/workflow/graph.py`의 `_create_initial_state` 안, `session_id=user_input["session_id"],` 줄 **바로 아래**에 추가:

```python
            conversation_id=user_input.get("conversation_id"),
```

- [ ] **Step 4: 테스트 통과를 확인한다**

Run: `.venv/bin/pytest tests/workflow/test_deep_analysis_node.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: 챗 핸들러가 실제로 전달하게 한다**

`neos/api/handlers/chat_handlers.py`의 `multi_agent_workflow.execute_workflow(user_input={...})` 딕셔너리(약 836행)에서 `"session_id": conversation_id,` 줄 **바로 아래**에 추가:

```python
                                "conversation_id": conversation_id,
```

- [ ] **Step 6: 회귀 없음을 확인한다**

Run: `.venv/bin/pytest tests/workflow/ -q --ignore=tests/workflow/mission --ignore=tests/workflow/harness 2>&1 | tail -3`
Expected: `37 failed, 289 passed` (기준선 287 + 신규 2)

- [ ] **Step 7: 커밋**

```bash
git add neos/workflow/state.py neos/workflow/graph.py neos/api/handlers/chat_handlers.py tests/workflow/test_deep_analysis_node.py
git commit -m "feat: carry conversation_id through agent state"
```

---

## Task 2: 챗 SSE 이벤트 모델과 콜백

프론트가 구독할 `neos:deep_analysis_started`를 정의한다. 기존 `Neos*Event` 패턴(`NeosUIFrameEvent`, `NeosWorkflowProgressEvent`)을 그대로 따른다.

**Files:**
- Modify: `neos/api/models/open_responses.py` (`NeosUIFrameEvent` 정의 뒤, 약 340행)
- Modify: `neos/api/models/query_models.py` (`WorkflowStreamEventType`, 약 104행)
- Modify: `neos/api/handlers/workflow_stream_handlers.py` (`on_ui_frame` 뒤, 약 300행)
- Test: `tests/api/models/test_deep_analysis_started_event.py` (신규)

**Interfaces:**
- Consumes: 없음
- Produces:
  - `NeosDeepAnalysisStartedEvent(run_id: str, events_url: str, assistant_message_id: str | None)`, `type == "neos:deep_analysis_started"`
  - `WorkflowStreamEventType.DEEP_ANALYSIS_STARTED == "deep_analysis_started"`
  - `WorkflowStreamCallback.on_deep_analysis_started(run_id: str, events_url: str, assistant_message_id: str | None) -> None`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/api/models/test_deep_analysis_started_event.py` 생성:

```python
"""Phase 3b 챗 SSE 계약 고정 (D23).

이 이벤트의 필드 이름은 프론트엔드와 공유된 계약이다. 바꾸려면 FE와 동기화가
필요하므로 테스트로 못 박는다.
"""

import pytest

pytestmark = pytest.mark.no_db


def test_deep_analysis_started_event_shape():
    from neos.api.models.open_responses import NeosDeepAnalysisStartedEvent

    event = NeosDeepAnalysisStartedEvent(
        run_id="run00001",
        events_url="/api/v1/deep-analysis/run00001/events",
        assistant_message_id="msg-1",
    )
    dumped = event.model_dump()
    assert dumped == {
        "type": "neos:deep_analysis_started",
        "run_id": "run00001",
        "events_url": "/api/v1/deep-analysis/run00001/events",
        "assistant_message_id": "msg-1",
    }


def test_assistant_message_id_is_optional():
    """대화 밖에서 시작된 run(예: /api/v1/query)은 메시지가 없다."""
    from neos.api.models.open_responses import NeosDeepAnalysisStartedEvent

    event = NeosDeepAnalysisStartedEvent(
        run_id="run00002",
        events_url="/api/v1/deep-analysis/run00002/events",
    )
    assert event.assistant_message_id is None


def test_stream_event_type_constant():
    from neos.api.models.query_models import WorkflowStreamEventType

    assert WorkflowStreamEventType.DEEP_ANALYSIS_STARTED == "deep_analysis_started"


@pytest.mark.asyncio
async def test_callback_enqueues_deep_analysis_started():
    import asyncio

    from neos.api.handlers.workflow_stream_handlers import WorkflowStreamCallback

    queue = asyncio.Queue()
    cb = WorkflowStreamCallback(
        session_id="conv-1", event_queue=queue, enable_db_logging=False
    )
    await cb.on_deep_analysis_started(
        run_id="run00003",
        events_url="/api/v1/deep-analysis/run00003/events",
        assistant_message_id="msg-3",
    )

    event = queue.get_nowait()
    assert event.event == "deep_analysis_started"
    assert event.data == {
        "run_id": "run00003",
        "events_url": "/api/v1/deep-analysis/run00003/events",
        "assistant_message_id": "msg-3",
    }
```

- [ ] **Step 2: 실패를 확인한다**

Run: `.venv/bin/pytest tests/api/models/test_deep_analysis_started_event.py -q`
Expected: FAIL — `ImportError: cannot import name 'NeosDeepAnalysisStartedEvent'`

- [ ] **Step 3: 모델을 추가한다**

`neos/api/models/open_responses.py`에서 `NeosUIFrameEvent` 클래스 정의가 끝난 뒤(`# ── Inline Visualization Data Models ──` 주석 **바로 위**)에 추가:

```python
class NeosDeepAnalysisStartedEvent(BaseModel):
    """
    Event: neos:deep_analysis_started — Phase 3b(D23) deep analysis job 핸들

    챗 턴은 이 이벤트를 낸 뒤 **블로킹 없이 정상 종료한다**. 클라이언트는
    `events_url`로 별도 SSE를 열어 진행을 관찰한다 — 챗과 전용 API가 같은
    이벤트 스트림을 소비하게 만드는 것이 이 이벤트의 존재 이유다(스펙 §5 AC4).

    `assistant_message_id`는 job 완료 시 리포트가 채워질 대화 메시지의 ID다.
    대화 밖에서 시작된 run(예: /api/v1/query)에서는 None이다.
    """
    type: Literal["neos:deep_analysis_started"] = "neos:deep_analysis_started"
    run_id: str
    events_url: str
    assistant_message_id: Optional[str] = None


```

- [ ] **Step 4: 스트림 이벤트 타입 상수를 추가한다**

`neos/api/models/query_models.py`의 `UI_FRAME_UPDATE = "ui_frame_update"  # 향후 점진적 업데이트` 줄 **바로 아래**에 추가:

```python
    # Phase 3b (D23): deep analysis job이 제출됐음을 알리는 핸들 이벤트.
    # 클라이언트는 이 이벤트의 events_url로 별도 SSE를 열어 진행을 관찰한다.
    DEEP_ANALYSIS_STARTED = "deep_analysis_started"
```

- [ ] **Step 5: 콜백을 추가한다**

`neos/api/handlers/workflow_stream_handlers.py`의 `on_ui_frame` 메서드 **바로 아래**(`# =====` HDR 섹션 주석 위)에 추가:

```python
    async def on_deep_analysis_started(
        self,
        run_id: str,
        events_url: str,
        assistant_message_id: Optional[str] = None,
    ) -> None:
        """Phase 3b(D23): deep analysis job 제출 핸들을 클라이언트로 발행한다.

        챗 턴은 이 이벤트 뒤 즉시 종료한다. 진행 상황은 events_url의 전용
        SSE 스트림이 전달한다 -- 챗과 전용 API가 같은 계약을 쓴다.
        """
        event = self._create_event(
            event_type=WorkflowStreamEventType.DEEP_ANALYSIS_STARTED,
            data={
                "run_id": run_id,
                "events_url": events_url,
                "assistant_message_id": assistant_message_id,
            },
        )
        await self.event_queue.put(event)
```

`Optional`이 이 파일에 임포트돼 있지 않으면 상단 `from typing import ...` 줄에 추가한다. 확인:

```bash
grep -n "^from typing" neos/api/handlers/workflow_stream_handlers.py
```

- [ ] **Step 6: 테스트 통과를 확인한다**

Run: `.venv/bin/pytest tests/api/models/test_deep_analysis_started_event.py -q`
Expected: PASS (4 passed)

- [ ] **Step 7: 커밋**

```bash
git add neos/api/models/open_responses.py neos/api/models/query_models.py neos/api/handlers/workflow_stream_handlers.py tests/api/models/test_deep_analysis_started_event.py
git commit -m "feat: define deep analysis started chat event"
```

---

## Task 3: 블로킹 노드를 디스패치 노드로 교체한다 (AC2 + AC3)

이 태스크가 3b의 본체다. `_deep_analysis_orchestrator_node`(`asyncio.wait_for(orch.run(...), timeout=cap)`)와 `_persist_deep_analysis_failure`를 제거한다. `9763eb5`의 wall-clock 바운드는 **노드와 함께 사라진다** — 실행이 요청 밖으로 나가면 노드가 붙들 자원 자체가 없다(스펙 §5.2).

**Files:**
- Modify: `neos/workflow/enums.py:37`
- Modify: `neos/workflow/graph.py:357-358`, `:417-418`, `:439-441`, `:1050-1136`
- Modify: `tests/workflow/routing/test_deep_analysis_routing.py:18`
- Test: `tests/workflow/test_deep_analysis_node.py` (Task 1에서 만든 파일에 이어 붙인다)

**Interfaces:**
- Consumes: `AgentState["conversation_id"]` (Task 1), `WorkflowStreamCallback.on_deep_analysis_started` (Task 2)
- Produces:
  - `WorkflowNode.DEEP_ANALYSIS_DISPATCH == "deep_analysis_dispatch"`
  - `MultiAgentWorkflow._deep_analysis_dispatch_node(state) -> {"final_response": str, "deep_analysis_run_id": str | None, "execution_steps": list}`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/workflow/test_deep_analysis_node.py`의 **끝에** 추가:

```python
class _FakeSessionCtx:
    def __init__(self):
        self.committed = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def commit(self):
        self.committed += 1


class _RecordingHandler:
    def __init__(self):
        self.calls = []

    async def on_deep_analysis_started(self, **kwargs):
        self.calls.append(kwargs)


def _patch_dispatch(monkeypatch, *, submit=None, create_run=None):
    """디스패치 노드의 외부 의존 3개(세션/create_run/job 제출)를 대체한다."""
    sessions = []

    async def fake_get_session():
        s = _FakeSessionCtx()
        sessions.append(s)
        return s

    async def default_create_run(session, question, profile, **kw):
        default_create_run.kwargs = kw
        return "runDISP1"

    default_create_run.kwargs = {}

    submitted = []

    def default_submit(run_id, question="", profile="dev", **kw):
        submitted.append((run_id, question, profile))
        return "inline"

    monkeypatch.setattr(
        "neos.database.connection.db_manager.get_session", fake_get_session
    )
    monkeypatch.setattr(
        "neos.workflow.deep_analysis.ledger.create_run",
        create_run or default_create_run,
    )
    monkeypatch.setattr(
        "neos.tasks.deep_analysis_job_task.submit_deep_analysis_job",
        submit or default_submit,
    )
    return sessions, submitted, default_create_run


@pytest.mark.asyncio
async def test_dispatch_node_submits_job_and_returns_immediately(monkeypatch):
    """AC2: 챗 턴이 하네스 완주를 기다리지 않는다.

    노드는 run을 만들고 job을 제출한 뒤 곧바로 상태 diff를 돌려줘야 한다.
    """
    from neos.workflow import graph as graph_mod

    _sessions, submitted, _cr = _patch_dispatch(monkeypatch)
    handler = _RecordingHandler()

    out = await graph_mod.multi_agent_workflow._deep_analysis_dispatch_node(
        {
            "original_query": "GLM-5.2 MoE 영향?",
            "user_id": "u1",
            "conversation_id": "conv-1",
            "_event_handler": handler,
        }
    )

    assert submitted == [("runDISP1", "GLM-5.2 MoE 영향?", "default")]
    assert out["deep_analysis_run_id"] == "runDISP1"
    assert out["final_response"]  # 사용자에게 보일 안내 문구가 있어야 한다


@pytest.mark.asyncio
async def test_dispatch_node_emits_started_event_with_shared_contract(monkeypatch):
    """AC4: 챗이 받는 핸들은 전용 API와 같은 events_url을 가리킨다."""
    from neos.workflow import graph as graph_mod

    _patch_dispatch(monkeypatch)
    handler = _RecordingHandler()

    await graph_mod.multi_agent_workflow._deep_analysis_dispatch_node(
        {
            "original_query": "q",
            "user_id": "u1",
            "conversation_id": "conv-1",
            "_event_handler": handler,
        }
    )

    assert len(handler.calls) == 1
    call = handler.calls[0]
    assert call["run_id"] == "runDISP1"
    assert call["events_url"] == "/api/v1/deep-analysis/runDISP1/events"
    assert call["assistant_message_id"]  # 리포트가 채워질 메시지 ID


@pytest.mark.asyncio
async def test_dispatch_node_binds_run_to_conversation(monkeypatch):
    """리포트 영속화(실행자 계층)가 동작하려면 run이 대화/메시지를 알아야 한다."""
    from neos.workflow import graph as graph_mod

    _sessions, _submitted, create_run = _patch_dispatch(monkeypatch)
    handler = _RecordingHandler()

    await graph_mod.multi_agent_workflow._deep_analysis_dispatch_node(
        {
            "original_query": "q",
            "user_id": "u1",
            "conversation_id": "conv-1",
            "_event_handler": handler,
        }
    )

    assert create_run.kwargs["user_id"] == "u1"
    assert create_run.kwargs["conversation_id"] == "conv-1"
    assert (
        create_run.kwargs["assistant_message_id"]
        == handler.calls[0]["assistant_message_id"]
    )


@pytest.mark.asyncio
async def test_dispatch_node_skips_message_binding_outside_conversation(monkeypatch):
    """대화 밖 호출자(/api/v1/query)는 어시스턴트 메시지가 없다."""
    from neos.workflow import graph as graph_mod

    _sessions, _submitted, create_run = _patch_dispatch(monkeypatch)
    handler = _RecordingHandler()

    await graph_mod.multi_agent_workflow._deep_analysis_dispatch_node(
        {"original_query": "q", "user_id": "u1", "_event_handler": handler}
    )

    assert create_run.kwargs["conversation_id"] is None
    assert create_run.kwargs["assistant_message_id"] is None
    assert handler.calls[0]["assistant_message_id"] is None


@pytest.mark.asyncio
async def test_dispatch_node_graceful_when_submission_fails(monkeypatch):
    """제출이 깨져도 챗 턴은 살아 있어야 한다 -- 사용자는 답을 받는다."""
    from neos.workflow import graph as graph_mod

    async def boom_get_session():
        raise RuntimeError("db down")

    monkeypatch.setattr(
        "neos.database.connection.db_manager.get_session", boom_get_session
    )

    out = await graph_mod.multi_agent_workflow._deep_analysis_dispatch_node(
        {"original_query": "q", "user_id": "u1"}
    )
    assert out["final_response"] == "심층 분석을 시작하지 못했습니다."
    assert out["deep_analysis_run_id"] is None


@pytest.mark.asyncio
async def test_dispatch_node_works_without_event_handler(monkeypatch):
    """/api/v1/query 등 이벤트 핸들러 없는 호출자에서도 죽지 않는다."""
    from neos.workflow import graph as graph_mod

    _sessions, submitted, _cr = _patch_dispatch(monkeypatch)

    out = await graph_mod.multi_agent_workflow._deep_analysis_dispatch_node(
        {"original_query": "q", "user_id": "u1"}
    )
    assert submitted == [("runDISP1", "q", "default")]
    assert out["deep_analysis_run_id"] == "runDISP1"


@pytest.mark.asyncio
async def test_blocking_orchestrator_node_is_gone():
    """AC3: 블로킹 완주 노드와 그 실패 영속화 헬퍼가 제거됐다.

    9763eb5의 wall-clock 캡도 함께 사라진다 -- 실행이 요청 밖으로 나가면
    노드가 붙들 자원이 없으므로 바운드할 대상 자체가 없다(스펙 §5.2).
    """
    from neos.workflow import graph as graph_mod

    wf = graph_mod.multi_agent_workflow
    assert not hasattr(wf, "_deep_analysis_orchestrator_node")
    assert not hasattr(wf, "_persist_deep_analysis_failure")


@pytest.mark.asyncio
async def test_no_regression_deep_analysis_off_by_default_node_not_registered(
    monkeypatch,
):
    """AC7 구조적 보장: 플래그가 꺼져 있으면 노드가 등록조차 되지 않는다."""
    from neos.workflow import graph as graph_mod
    from neos.workflow.enums import WorkflowNode

    class RecordingGraph:
        def __init__(self, state_type):
            self.nodes = []

        def add_node(self, name, handler):
            self.nodes.append(name)

        def add_edge(self, *a, **kw):
            pass

        def add_conditional_edges(self, *a, **kw):
            pass

        def compile(self, **kwargs):
            return self

    monkeypatch.setattr(graph_mod, "StateGraph", RecordingGraph)
    monkeypatch.setattr(graph_mod.settings, "DEEP_ANALYSIS_ENABLED", False)

    compiled = await graph_mod.multi_agent_workflow._create_workflow_graph(
        use_checkpointer=False
    )
    assert WorkflowNode.DEEP_ANALYSIS_DISPATCH.value not in compiled.nodes


@pytest.mark.asyncio
async def test_dispatch_node_registered_and_terminal_when_flag_on(monkeypatch):
    """플래그가 켜지면 노드가 등록되고 END로 단락된다 -- 챗 턴이 여기서 끝난다.

    RESULT_INTEGRATOR로 합류하면 후속 노드들이 리포트를 기다리게 되므로
    AC2가 깨진다.
    """
    from langgraph.graph import END

    from neos.workflow import graph as graph_mod
    from neos.workflow.enums import WorkflowNode

    class RecordingGraph:
        def __init__(self, state_type):
            self.nodes = []
            self.edges = []

        def add_node(self, name, handler):
            self.nodes.append(name)

        def add_edge(self, src, dst):
            self.edges.append((src, dst))

        def add_conditional_edges(self, *a, **kw):
            pass

        def compile(self, **kwargs):
            return self

    monkeypatch.setattr(graph_mod, "StateGraph", RecordingGraph)
    monkeypatch.setattr(graph_mod.settings, "DEEP_ANALYSIS_ENABLED", True)

    compiled = await graph_mod.multi_agent_workflow._create_workflow_graph(
        use_checkpointer=False
    )
    assert WorkflowNode.DEEP_ANALYSIS_DISPATCH.value in compiled.nodes
    assert (WorkflowNode.DEEP_ANALYSIS_DISPATCH.value, END) in compiled.edges
```

- [ ] **Step 2: 실패를 확인한다**

Run: `.venv/bin/pytest tests/workflow/test_deep_analysis_node.py -q`
Expected: FAIL — `AttributeError: ... has no attribute '_deep_analysis_dispatch_node'`

- [ ] **Step 3: 노드 이름 상수를 바꾼다**

`neos/workflow/enums.py:37`을 교체:

```python
    DEEP_ANALYSIS_DISPATCH = "deep_analysis_dispatch"
```

`tests/workflow/routing/test_deep_analysis_routing.py:18`을 교체:

```python
    assert WorkflowNode.DEEP_ANALYSIS_DISPATCH.value == "deep_analysis_dispatch"
```

- [ ] **Step 4: 노드 구현을 교체한다**

`neos/workflow/graph.py`에서 `_deep_analysis_orchestrator_node`와 `_persist_deep_analysis_failure` **전체**(1050~1136행, `async def _deep_analysis_orchestrator_node`부터 `_should_use_recursive_agent` 정의 **직전**까지)를 아래로 교체:

```python
    async def _deep_analysis_dispatch_node(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Phase 3b(D23): 심층 분석을 job으로 제출하고 즉시 반환한다.

        D18의 블로킹 완주 노드를 대체한다. 세 예산을 나란히 놓으면 프론트
        maxDuration 60s < 노드 캡 300s < dig 하나의 wall_clock_cap 600s이므로,
        **가장 작은 예산이 클라이언트 쪽에 있다** -- 라운드를 여러 번 도는 run은
        어떤 동기 요청 예산에도 애초에 맞지 않는다. 노드 레벨 캡(9763eb5)은
        호출자가 떠난 뒤 자원을 붙드는 것만 막았을 뿐 사용자가 결과를 받게 하지
        못했다. 여기서 캡이 사라지는 것은 퇴행이 아니라, 붙들 자원이 없어진
        것이다(스펙 §5.2).

        진행 상황과 최종 리포트는 `events_url`의 전용 SSE 스트림이 전달한다 --
        챗과 전용 API가 **같은 이벤트 스트림 계약**을 쓴다(AC4).
        """
        import uuid

        from neos.config.settings import settings
        from neos.database.connection import db_manager
        from neos.tasks.deep_analysis_job_task import submit_deep_analysis_job
        from neos.workflow.deep_analysis.ledger import create_run

        query = state.get("refined_query") or state.get("original_query", "")
        profile = "default"
        conversation_id = state.get("conversation_id")
        # 대화에 묶인 run만 어시스턴트 메시지를 예약한다. job이 완료되면
        # 실행자 계층(neos/tasks/deep_analysis_job_task.py)이 이 ID로 리포트를
        # 영속화하므로, 프론트가 그 순간 접속해 있지 않아도 대화에 남는다.
        assistant_message_id = str(uuid.uuid4()) if conversation_id else None

        try:
            async with await db_manager.get_session() as session:
                run_id = await create_run(
                    session,
                    query,
                    profile,
                    user_id=state.get("user_id") or None,
                    conversation_id=conversation_id,
                    assistant_message_id=assistant_message_id,
                )
                # 커밋이 필수다 -- job이 다른 태스크/프로세스에서 이 run을 읽는다.
                await session.commit()

            executor = submit_deep_analysis_job(run_id, query, profile)
        except Exception as exc:
            logger.error(f"[DeepAnalysisDispatchNode] submission failed: {exc}")
            return {
                "final_response": "심층 분석을 시작하지 못했습니다.",
                "deep_analysis_run_id": None,
            }

        events_url = f"{settings.API_V1_PREFIX}/deep-analysis/{run_id}/events"
        event_handler = state.get("_event_handler")
        if event_handler and hasattr(event_handler, "on_deep_analysis_started"):
            await event_handler.on_deep_analysis_started(
                run_id=run_id,
                events_url=events_url,
                assistant_message_id=assistant_message_id,
            )

        logger.info(
            f"[DeepAnalysisDispatchNode] run {run_id} submitted via {executor}"
        )
        return {
            "final_response": (
                "심층 분석을 시작했습니다. 진행 상황과 최종 리포트는 "
                "분석이 끝나는 대로 이 대화에 표시됩니다."
            ),
            "deep_analysis_run_id": run_id,
            "execution_steps": state.get("execution_steps", [])
            + [
                {
                    "step": "deep_analysis_dispatch",
                    "result": f"run {run_id} submitted via {executor}",
                }
            ],
        }

```

- [ ] **Step 5: 그래프 조립을 갱신한다**

`neos/workflow/graph.py:357-358`을 교체:

```python
        # Phase 3b(D23): Deep Analysis 디스패치 노드 (피처 플래그로 격리)
        if settings.DEEP_ANALYSIS_ENABLED:
            workflow.add_node(WorkflowNode.DEEP_ANALYSIS_DISPATCH.value, self._deep_analysis_dispatch_node)
```

`neos/workflow/graph.py:417-418`을 교체:

```python
            if settings.DEEP_ANALYSIS_ENABLED:
                _routing_map["deep_analysis"] = WorkflowNode.DEEP_ANALYSIS_DISPATCH.value
```

`neos/workflow/graph.py:439-441`을 교체:

```python
            if settings.DEEP_ANALYSIS_ENABLED:
                # 디스패치 노드는 END로 단락한다 -- 챗 턴은 job 핸들을 낸 뒤
                # 즉시 끝나야 하며(AC2), 후속 노드가 기다릴 결과가 없다.
                workflow.add_edge(WorkflowNode.DEEP_ANALYSIS_DISPATCH.value, END)
```

- [ ] **Step 6: 테스트 통과를 확인한다**

Run: `.venv/bin/pytest tests/workflow/test_deep_analysis_node.py tests/workflow/routing/ -q`
Expected: PASS (모두 통과)

- [ ] **Step 7: 커밋**

```bash
git add neos/workflow/enums.py neos/workflow/graph.py tests/workflow/test_deep_analysis_node.py tests/workflow/routing/test_deep_analysis_routing.py
git commit -m "feat: submit deep analysis as job from chat"
```

---

## Task 4: 챗 SSE 배관 — 큐 이벤트를 클라이언트로 흘린다

노드가 큐에 넣은 `deep_analysis_started`를 챗 SSE와 OpenResponses 어댑터가 각각 `neos:deep_analysis_started`로 변환한다. 두 경로 모두 필요하다 — 챗 핸들러는 직접 루프를 돌고, `stream_adapter`는 `/api/v1/query` 계열 legacy 스트림을 변환한다.

**Files:**
- Modify: `neos/api/handlers/chat_handlers.py` (약 898행 `elif event.event == "ui_frame":` 블록 뒤)
- Modify: `neos/api/adapters/stream_adapter.py` (약 262행 `elif event_type == "ui_frame":` 블록 뒤)
- Test: `tests/api/adapters/test_deep_analysis_stream_adapter.py` (신규)

**Interfaces:**
- Consumes: `NeosDeepAnalysisStartedEvent` (Task 2), 큐 이벤트 `event.event == "deep_analysis_started"` (Task 2·3)
- Produces: 없음 (배관)

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/api/adapters/test_deep_analysis_stream_adapter.py` 생성:

```python
"""legacy 스트림 이벤트 → neos:deep_analysis_started 변환 고정 (D23)."""

import pytest

pytestmark = pytest.mark.no_db


def test_adapter_converts_deep_analysis_started():
    from neos.api.adapters.stream_adapter import (
        StreamAdapterState,
        convert_legacy_event,
    )

    state = StreamAdapterState()
    events = convert_legacy_event(
        {
            "type": "deep_analysis_started",
            "data": {
                "run_id": "run00009",
                "events_url": "/api/v1/deep-analysis/run00009/events",
                "assistant_message_id": "msg-9",
            },
        },
        state,
    )

    assert len(events) == 1
    dumped = events[0].model_dump()
    assert dumped["type"] == "neos:deep_analysis_started"
    assert dumped["run_id"] == "run00009"
    assert dumped["events_url"] == "/api/v1/deep-analysis/run00009/events"
    assert dumped["assistant_message_id"] == "msg-9"


def test_chat_handler_maps_deep_analysis_started():
    """챗 SSE 루프가 이 이벤트를 흘려보내는지 소스 수준으로 고정한다.

    챗 스트리밍 루프는 LLM/DB에 깊이 얽혀 있어 단위 실행이 비싸다. 배관이
    빠지면 프론트가 job 핸들을 아예 못 받으므로(AC4 파손) 최소한 존재는
    강제한다.
    """
    from pathlib import Path

    source = Path("neos/api/handlers/chat_handlers.py").read_text(encoding="utf-8")
    assert 'event.event == "deep_analysis_started"' in source
    assert "NeosDeepAnalysisStartedEvent" in source
```

- [ ] **Step 2: 실패를 확인한다**

Run: `.venv/bin/pytest tests/api/adapters/test_deep_analysis_stream_adapter.py -q`
Expected: FAIL

> 참고: `convert_legacy_event` / `StreamAdapterState`의 실제 이름이 다르면
> `grep -n "^def \|^class " neos/api/adapters/stream_adapter.py`로 확인하고
> 테스트의 임포트만 실제 이름에 맞춘다. 변환 로직 자체는 그대로 둔다.

- [ ] **Step 3: 어댑터 매핑을 추가한다**

`neos/api/adapters/stream_adapter.py`의 `elif event_type == "ui_frame":` 블록 **바로 뒤**에 추가:

```python
    # ================================================================
    # deep_analysis_started -> neos:deep_analysis_started (Phase 3b, D23)
    # ================================================================
    elif event_type == "deep_analysis_started":
        data = legacy_event.get("data", {}) or {}
        events.append(NeosDeepAnalysisStartedEvent(
            run_id=data.get("run_id", ""),
            events_url=data.get("events_url", ""),
            assistant_message_id=data.get("assistant_message_id"),
        ))
```

같은 파일 상단의 `from neos.api.models.open_responses import (...)` 임포트 목록에 `NeosDeepAnalysisStartedEvent,`를 추가한다.

- [ ] **Step 4: 챗 핸들러 배관을 추가한다**

`neos/api/handlers/chat_handlers.py`의 `elif event.event == "ui_frame":` 블록 **바로 뒤**에 추가:

```python
                            # Phase 3b (D23): deep analysis job 핸들 → 챗 SSE
                            # 이 이벤트 뒤 챗 턴은 블로킹 없이 종료된다.
                            # 진행 상황은 events_url의 전용 스트림이 전달한다.
                            elif event.event == "deep_analysis_started":
                                da_event = NeosDeepAnalysisStartedEvent(
                                    run_id=event.data.get("run_id", ""),
                                    events_url=event.data.get("events_url", ""),
                                    assistant_message_id=event.data.get(
                                        "assistant_message_id"
                                    ),
                                )
                                yield format_sse_event(da_event)
```

같은 파일의 `NeosUIFrameEvent`를 임포트하는 줄에 `NeosDeepAnalysisStartedEvent`를 추가한다. 위치 확인:

```bash
grep -n "NeosUIFrameEvent" neos/api/handlers/chat_handlers.py
```

- [ ] **Step 5: 테스트 통과를 확인한다**

Run: `.venv/bin/pytest tests/api/adapters/test_deep_analysis_stream_adapter.py -q`
Expected: PASS (2 passed)

- [ ] **Step 6: 임포트가 실제로 성립하는지 확인한다**

```bash
.venv/bin/python -c "import neos.api.handlers.chat_handlers, neos.api.adapters.stream_adapter; print('ok')"
```
Expected: `ok`

- [ ] **Step 7: 커밋**

```bash
git add neos/api/handlers/chat_handlers.py neos/api/adapters/stream_adapter.py tests/api/adapters/test_deep_analysis_stream_adapter.py
git commit -m "feat: stream deep analysis job handle to chat clients"
```

---

## Task 5: 리포트 영속화를 회귀로 고정한다

**설계 판단:** 리포트를 어시스턴트 메시지로 쓰는 계층은 **실행자 계층**
(`neos/tasks/deep_analysis_job_task.py::_persist_assistant_message`)이다. Phase 3a가 이미 이 위치에 구현했다 — 이번 태스크는 신규 구현이 아니라 **두 실행자 모두에서 동작함을 회귀로 못 박는 것**이다.

근거: `_persist_assistant_message`는 Celery 태스크(`run_deep_analysis_job`)와 inline asyncio 태스크가 **공유하는 `_execute` 본문**에 걸려 있다. 따라서 실행자별로 코드를 복제하지 않고도 두 경로가 자동으로 커버된다. 동시에 `ChatService` 임포트가 `neos/tasks/` 안에 머무르므로 `jobs.py`의 프레임워크 프리 성질이 유지된다.

**Files:**
- Test: `tests/tasks/test_deep_analysis_report_persistence.py` (신규)
- Modify: 없음 (구현이 이미 존재한다. 테스트가 실패하면 그때 고친다)

**Interfaces:**
- Consumes: `neos.tasks.deep_analysis_job_task._execute(run_id, question, profile, resume)`
- Produces: 없음

- [ ] **Step 1: 실패를 검출하는 테스트를 쓴다**

`tests/tasks/test_deep_analysis_report_persistence.py` 생성:

```python
"""리포트 영속화 계층 고정 (D23).

리포트가 job_completed 이벤트 페이로드로만 나가면, 프론트가 그 순간
연결돼 있지 않은 run은 대화에 아무것도 남기지 않는다. 영속화는 ChatService를
아는 계층 -- 실행자 계층 -- 이 맡고, Celery/inline 두 실행자가 공유하는
`_execute`에 걸려야 한다.
"""

import pytest

pytestmark = pytest.mark.no_db


@pytest.mark.asyncio
async def test_execute_persists_report_to_assistant_message(monkeypatch):
    from neos.tasks import deep_analysis_job_task as task_mod

    async def fake_execute_run(session_factory, run_id, question, profile, **kw):
        return {"report_markdown": "# 리포트\n본문", "run_id": run_id}

    persisted = []

    async def fake_persist(run_id, report_markdown):
        persisted.append((run_id, report_markdown))

    monkeypatch.setattr(
        "neos.workflow.deep_analysis.jobs.execute_run", fake_execute_run
    )
    monkeypatch.setattr(task_mod, "_persist_assistant_message", fake_persist)

    result = await task_mod._execute("runPERSIST", "q", "dev", False)

    assert result["report_markdown"] == "# 리포트\n본문"
    assert persisted == [("runPERSIST", "# 리포트\n본문")]


@pytest.mark.asyncio
async def test_resume_path_also_persists_report(monkeypatch):
    """재개된 run도 리포트를 대화에 남긴다 -- 두 진입점이 같은 본문을 탄다."""
    from neos.tasks import deep_analysis_job_task as task_mod

    async def fake_resume_run(session_factory, run_id, **kw):
        return {"report_markdown": "# 재개 리포트", "run_id": run_id}

    persisted = []

    async def fake_persist(run_id, report_markdown):
        persisted.append((run_id, report_markdown))

    monkeypatch.setattr(
        "neos.workflow.deep_analysis.jobs.resume_run", fake_resume_run
    )
    monkeypatch.setattr(task_mod, "_persist_assistant_message", fake_persist)

    await task_mod._execute("runRESUME", "q", "dev", True)

    assert persisted == [("runRESUME", "# 재개 리포트")]


def test_both_executors_share_the_persistence_path():
    """Celery 태스크와 inline 제출이 모두 `_execute`를 거쳐야 한다.

    한쪽만 영속화하면 운영 설정(CELERY_ENABLED)에 따라 대화에 리포트가
    남기도 하고 안 남기도 하는 유령 버그가 된다.
    """
    import inspect

    from neos.tasks import deep_analysis_job_task as task_mod

    assert "_execute(" in inspect.getsource(task_mod.run_deep_analysis_job)
    assert "_execute(" in inspect.getsource(task_mod.submit_deep_analysis_job)


def test_persistence_layer_is_not_inside_the_framework_free_package():
    """ChatService는 deep_analysis 패키지 밖에 머물러야 한다."""
    from pathlib import Path

    source = Path("neos/workflow/deep_analysis/jobs.py").read_text(encoding="utf-8")
    assert "chat_service" not in source
    assert "ChatService" not in source
```

- [ ] **Step 2: 실행해 현 상태를 확인한다**

Run: `.venv/bin/pytest tests/tasks/test_deep_analysis_report_persistence.py -q`
Expected: PASS (4 passed) — Phase 3a 구현이 이미 계약을 만족한다.

**FAIL이 나오면** 실패 내용을 읽고 `neos/tasks/deep_analysis_job_task.py`를 최소 수정한 뒤 다시 돌린다. `jobs.py`는 건드리지 않는다.

- [ ] **Step 3: 커밋**

```bash
git add tests/tasks/test_deep_analysis_report_persistence.py
git commit -m "test: pin deep analysis report persistence layer"
```

---

## Task 6: 3a/3b 경계 어서션을 3b 완료 기준으로 반전한다

`tests/workflow/test_deep_analysis_job_no_regression.py::test_chat_node_is_untouched_by_phase_3a`는 "3a에서 노드가 사라지면 범위 이탈"을 강제했다. 3b가 바로 그 제거이므로 어서션 방향을 뒤집는다. 나머지 프레임워크 프리 어서션은 **그대로 둔다**.

**Files:**
- Modify: `tests/workflow/test_deep_analysis_job_no_regression.py:33-42`

**Interfaces:**
- Consumes: 없음
- Produces: 없음

- [ ] **Step 1: 어서션을 반전한다**

파일 상단 docstring을 교체:

```python
"""AC3/AC7 + 프레임워크 프리 경계 고정.

3a는 job 서비스를 만들었고, 3b(D23)가 챗을 그 소비자로 바꿨다. 이 파일은
"블로킹 노드가 돌아오지 않는다"와 "deep_analysis 패키지가 프레임워크 프리로
남는다"를 함께 고정한다.
"""
```

`test_chat_node_is_untouched_by_phase_3a` 함수 전체를 교체:

```python
def test_blocking_chat_node_is_gone_after_phase_3b():
    """AC3: 챗 노드가 하네스를 완주시키던 구조가 제거됐다.

    9763eb5의 wall-clock 캡도 함께 사라진다 -- 실행이 요청 밖으로 나가면
    노드가 붙들 자원이 없다(스펙 §5.2). 캡이 돌아온다는 것은 블로킹 실행이
    돌아왔다는 뜻이므로 함께 금지한다.
    """
    source = Path("neos/workflow/graph.py").read_text(encoding="utf-8")

    assert "_deep_analysis_orchestrator_node" not in source
    assert "_persist_deep_analysis_failure" not in source
    assert "node_wall_clock_cap" not in source
    # 대체 노드는 존재해야 한다 -- 라우팅 대상이 사라지면 그래프가 깨진다.
    assert "_deep_analysis_dispatch_node" in source
```

- [ ] **Step 2: 테스트 통과를 확인한다**

Run: `.venv/bin/pytest tests/workflow/test_deep_analysis_job_no_regression.py -q`
Expected: PASS (5 passed)

- [ ] **Step 3: 전체 스위트로 회귀를 확인한다**

```bash
.venv/bin/pytest tests/workflow/ -q --ignore=tests/workflow/mission --ignore=tests/workflow/harness 2>&1 | tail -3
.venv/bin/pytest tests/workflow/mission tests/workflow/harness -q 2>&1 | tail -3
.venv/bin/pytest tests/api/ -q 2>&1 | tail -3
```
Expected: 실패 목록이 기준선(workflow 37 / mission+harness 0 / api 1)과 **동일**. 통과 수는 신규 테스트만큼 증가.

- [ ] **Step 4: 커밋**

```bash
git add tests/workflow/test_deep_analysis_job_no_regression.py
git commit -m "test: flip phase 3 boundary assertion to 3b"
```

---

## Task 7: D23을 DECISIONS.md에 기록한다

**Files:**
- Modify: `neos/workflow/deep_analysis/DECISIONS.md` (파일 끝에 추가)

**Interfaces:** 없음

- [ ] **Step 1: D23을 추가한다**

`neos/workflow/deep_analysis/DECISIONS.md` **맨 끝**에 아래를 덧붙인다:

```markdown

---

## D23. 챗은 job의 제출자다 — D18을 대체한다 (3b: 노드 제거·핸들 이벤트·리포트 영속화)

**결정:** **D18을 대체한다.** D18은 스스로를 "챗 경로의 라우팅 대상만 교체하는 첫 이동"이라
규정하고 per-claim 스트리밍의 챗 편입을 "그 다음 단계"로 예고했다 — 이 결정이 그 단계다.
`_deep_analysis_orchestrator_node`(하네스를 `asyncio.wait_for`로 완주시키던 노드)와
`_persist_deep_analysis_failure`를 **제거**하고, 라우팅 키 `"deep_analysis"`를
`_deep_analysis_dispatch_node`로 돌린다. 이 노드는 run을 만들고 job을 제출한 뒤
`neos:deep_analysis_started {run_id, events_url, assistant_message_id}` 챗 SSE 이벤트를
발행하고 **END로 단락한다**. 진행 상황과 리포트는 전용 스트림
`GET /api/v1/deep-analysis/{run_id}/events`가 전달한다 — 챗과 전용 API가 같은 계약을 쓴다.

**근거 — 캡이 사라지는 것은 퇴행이 아니다:** `9763eb5`의 `node_wall_clock_cap`이 이 결정과
함께 사라진다. D22가 정리했듯 세 예산은 프론트 `maxDuration` 60s < 노드 캡 300s < `dig`
하나의 `wall_clock_cap` 600s이고, **가장 작은 예산이 클라이언트 쪽에 있다.** 노드 캡은
"호출자가 떠난 뒤 백엔드가 자원을 붙들고 있는 것"만 막았을 뿐 사용자가 결과를 받게 하지
못했다. 실행이 요청 밖으로 나간 지금 노드가 붙들 자원 자체가 없으므로 바운드할 대상이 없다.
스펙 §5.2가 "Phase 3이 이걸 구조적으로 없앤다"고 규정한 그대로다. 회귀 고정:
`tests/workflow/test_deep_analysis_job_no_regression.py::test_blocking_chat_node_is_gone_after_phase_3b`가
`node_wall_clock_cap`의 재등장을 금지한다 — 그것이 돌아온다는 것은 블로킹 실행이 돌아왔다는 뜻이다.

**근거 — 챗 턴을 END로 단락하는 이유:** 디스패치 노드를 `RESULT_INTEGRATOR`로 합류시키면
후속 노드(fact-check·품질 검증·응답 생성)가 아직 존재하지 않는 리포트를 기다리게 된다.
A2UI의 `UI_FRAME_GENERATOR → END` 단락이 이미 같은 형태의 선례다. 회귀 고정:
`test_dispatch_node_registered_and_terminal_when_flag_on`.

**결정 — 리포트 영속화는 실행자 계층에 둔다:** `jobs.py`는 프레임워크 프리이므로
(LangChain/LangGraph/FastAPI/Celery/ChatService 미임포트) 리포트를 대화 메시지로 쓰는 일을
할 수 없다. 그대로 두면 리포트는 `job_completed` 이벤트 페이로드로만 나가고, **프론트가 그
순간 연결돼 있지 않은 run은 대화에 아무것도 남기지 않는다.** 영속화는
`neos/tasks/deep_analysis_job_task.py::_persist_assistant_message`가 맡는다. 이 함수는
Celery 태스크와 inline asyncio 태스크가 **공유하는 `_execute` 본문**에 걸려 있어, 실행자별
코드 복제 없이 두 경로가 자동으로 커버된다 — 한쪽만 영속화하면 `CELERY_ENABLED` 값에 따라
리포트가 남기도 하고 안 남기도 하는 유령 버그가 된다. 콜백 주입 대신 이 위치를 고른 이유는
경계가 이미 거기 있기 때문이다: `neos/tasks/`는 정의상 통합 계층이고, 주입은 호출자마다
어댑터를 요구해 실행자 두 개가 서로 다른 어댑터를 쓸 여지를 만든다. 회귀 고정:
`tests/tasks/test_deep_analysis_report_persistence.py`.

**결정 — `conversation_id`를 `AgentState`에 명시 필드로 추가한다:** 챗은 `session_id`에
`conversation_id`를 실어 보내지만 `/api/v1/query`는 `session_id`를 진짜 세션으로 쓴다.
두 의미를 겹쳐 쓰면 대화가 아닌 run에 엉뚱한 `conversation_id`가 박혀 `add_message`가 없는
대화를 가리킨다. 대화 밖에서 시작된 run은 `conversation_id`/`assistant_message_id`가 모두
`None`이고, 리포트는 이벤트 스트림으로만 전달된다.

**이탈 — 챗 API 계약이 바뀐다(스펙 §5.4, K4):** 챗 응답이 "완성된 리포트 1건"에서
"job 핸들 + 별도 스트림"으로 바뀐다. 프론트엔드 변경이 필수다. 계약 필드는
`{run_id, events_url, assistant_message_id}`로 고정했고
`tests/api/models/test_deep_analysis_started_event.py`가 이를 못 박는다.

**영향 — AC7 무회귀는 그대로다:** `DEEP_ANALYSIS_ENABLED=false`(기본)이면 라우팅 맵에
`"deep_analysis"` 키가 없고 `WorkflowNode.DEEP_ANALYSIS_DISPATCH` 노드도 등록되지 않는다.
구조적 보장의 형태는 D18과 동일하고 노드 이름만 바뀌었다. 회귀 고정:
`tests/workflow/test_deep_analysis_node.py::test_no_regression_deep_analysis_off_by_default_node_not_registered`.

**영향 — 스트림 해상도는 여전히 라운드 단위다:** D22가 기록했듯 `Ledger.log()`는 flush만
하고 커밋은 `Orchestrator._checkpoint()`가 라운드 경계에서 한다. 챗이 전용 스트림을 구독하게
된 지금도 claim 단위 실시간성은 나오지 않는다 — 이는 하네스의 커밋 주기 문제이지 소비
경로의 문제가 아니며, 스펙 §5의 어떤 AC도 이를 요구하지 않는다.

**영향 — D18 선결 조건 3건의 최종 상태:** (1) wall-clock 바운드 → 노드 제거로 **무의미해짐**,
(2) fail_run 내구성 → 노드 제거로 사라졌고 job 쪽 `_record_failure`가 같은 역할을 이어받음,
(3) 분류기 intent 미도달 → **D21이 해소**(질의 유형 기반 라우팅).
```

- [ ] **Step 2: 커밋**

```bash
git add neos/workflow/deep_analysis/DECISIONS.md
git commit -m "docs: record D23 chat as deep analysis job consumer"
```

---

## Self-Review

**1. 스펙 커버리지 (§5.5 AC 중 3b 범위)**

| AC | 태스크 |
|---|---|
| AC2 챗 요청이 블로킹되지 않는다 | Task 3 (`test_dispatch_node_submits_job_and_returns_immediately`, END 단락) |
| AC3 `_deep_analysis_orchestrator_node` 제거 | Task 3 (`test_blocking_orchestrator_node_is_gone`), Task 6 (소스 수준 고정) |
| AC4 챗과 전용 API가 동일 이벤트 스트림 계약 | Task 2·3·4 (`events_url` 발행 + SSE 배관) |
| AC7 플래그 OFF 무회귀 | Task 3 (`test_no_regression_...node_not_registered`) |
| §5.4 챗 계약 변경 문서화 | Task 7 (D23) |
| D18 대체 명시 | Task 7 (D23 첫 문단) |
| 리포트 영속화 (프레임워크 프리 유지) | Task 5 |

AC1·AC5·AC6은 Phase 3a(D22)가 이미 이행했다 — 이 계획의 범위 밖이다.

**2. 플레이스홀더:** 없음. 모든 코드 블록은 실제 삽입 내용이고, 모든 명령은 실행 가능한 형태다. Task 4 Step 2의 이름 확인 지침은 플레이스홀더가 아니라 **기존 코드 확인 절차**다.

**3. 타입 일관성:**
- `WorkflowNode.DEEP_ANALYSIS_DISPATCH = "deep_analysis_dispatch"` — Task 3에서 정의, Task 3 테스트·라우팅 테스트에서 동일하게 사용
- `_deep_analysis_dispatch_node(state) -> Dict[str, Any]` — Task 3에서 정의, Task 3·6 테스트에서 동일 이름
- `NeosDeepAnalysisStartedEvent(run_id, events_url, assistant_message_id)` — Task 2에서 정의, Task 4에서 동일 시그니처로 생성
- `on_deep_analysis_started(run_id=, events_url=, assistant_message_id=)` — Task 2에서 키워드 인자로 정의, Task 3 노드가 키워드로 호출, Task 3 테스트 `_RecordingHandler`가 `**kwargs`로 수용
- `WorkflowStreamEventType.DEEP_ANALYSIS_STARTED == "deep_analysis_started"` — Task 2에서 정의, Task 3·4에서 문자열로 일치
- `AgentState["conversation_id"]` — Task 1에서 정의, Task 3 노드가 소비
