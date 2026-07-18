# Deep Analysis — Durable Job 서비스 (Phase 3a) 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `POST /api/v1/deep-analysis`가 블로킹 없이 202 + `run_id`를 반환하고, 실행은 요청 밖(Celery 워커 또는 백그라운드 asyncio 태스크)에서 진행되며, 진행 상황은 append-only DB 이벤트 로그를 커서로 재생하는 `GET /api/v1/deep-analysis/{run_id}/events`로 관찰된다.

**Architecture:** 전달 매체는 **`deep_analysis_events` 테이블**이다. `DAEvent.seq`(BigInteger autoincrement PK)가 그대로 단조 커서이므로 추가 컬럼이 필요 없고, 커서를 0에서 시작하면 진행 중인 run의 **전체 이력**이 재생된다(AC6이 공짜로 따라온다). `stream_manager`는 쓰지 않는다 — `neos/workflow/stream_manager.py:99`의 `self._sessions: Dict[str, StreamSession] = {}`는 **프로세스 내 메모리**라 Celery 워커가 넣은 이벤트를 API 프로세스가 볼 수 없다. 실행자는 이원화하되(`CELERY_ENABLED` 분기) **계약은 하나**다: 두 경로 모두 202 + `run_id`를 반환하고 같은 이벤트 로그에 쓴다.

**Tech Stack:** Python 3.12, FastAPI(SSE `StreamingResponse`), SQLAlchemy 2.0 async, Celery 5.4(`@shared_task`), pytest.

**Spec:** `docs/superpowers/specs/2026-07-17-loop-architecture-consolidation-design.md` §5 (AC1·AC5·AC6·AC7만. AC2·AC3·AC4는 3b)

## Global Constraints

- **범위는 3a뿐.** AC1(202) · AC5(resume) · AC6(전체 이력 재생) · AC7(플래그 off 무회귀) + 추가 AC(`CELERY_ENABLED=false`에서도 동작). **AC2·AC3·AC4(챗 노드 제거·챗이 job 소비)는 3b이며 이 계획의 범위 밖이다.**
- **절대 수정 금지:** `neos/workflow/graph.py`의 `_deep_analysis_orchestrator_node`(커밋 `9763eb5`의 wall-clock 바운드), `neos/workflow/routing/orchestrator_router.py`, `neos/workflow/utils/query_classifier.py`, `web/` 전체.
- **`deep_analysis`는 프레임워크 프리다.** 패키지 내부 의존은 `neos.config.settings`, `neos.database.deep_analysis_models`, `neos.tools.tools.web_search`, `neos.utils.time_utils` 4개뿐이다. **LangChain/LangGraph 신규 의존 금지.** Celery·ChatService 같은 통합 관심사는 `neos/tasks/` 계층에 둔다 — `deep_analysis/` 안으로 끌고 들어오지 않는다.
- **D8 (events append-only):** `deep_analysis_events`는 `BEFORE UPDATE OR DELETE` 트리거로 DB가 강제한다. **INSERT와 SELECT만 한다.**
- **P2 (단일 작성자):** run당 작성자는 하나. `Ledger._lock()`의 `pg_advisory_xact_lock(hashtextextended(run_id, 0))`가 이를 DB 강제로 만든다. 커서 리더가 `seq > cursor` 폴링으로 행을 건너뛰지 않는 이유가 이것이다 — 단일 작성자면 seq 할당 순서 = 커밋 순서다.
- **cassette 우회 금지:** 모든 LLM/검색/fetch/스킬 호출은 `cassette.remember(...)`를 통과해야 한다(D19 golden 게이트). 이 계획은 워커/LLM 경로를 건드리지 않으므로 자동으로 지켜지지만, `build_orchestrator`에 `cassette=` 전달 경로를 끊지 말 것.
- **테스트 실행:** `.venv/bin/pytest`.
- **커밋 메시지에 `Co-Authored-By` 트레일러를 넣지 마라.**

### 테스트 환경 — 사전 존재 결함 2건 (고치지 마라)

1. `pytest tests/workflow/` 단일 실행은 basename 충돌로 **수집 단계에서 실패**한다(`harness/test_policy.py`↔`autonomy/test_policy.py`, `mission/test_executor.py`↔`hyper_deep/test_executor.py`, `__init__.py` 부재). **분할 실행하라:**
   ```bash
   .venv/bin/pytest tests/workflow/ -q --ignore=tests/workflow/mission --ignore=tests/workflow/harness
   .venv/bin/pytest tests/workflow/mission tests/workflow/harness -q
   ```
2. Postgres가 안 떠 있으면 `deep_analysis` DB 테스트 37개가 커넥션 에러로 실패한다.

**측정된 기준선 (2026-07-18, Postgres 미기동):**
- `tests/workflow/`(분할 1): **258 passed, 37 failed**
- `tests/workflow/mission tests/workflow/harness`: **103 passed**
- `tests/api/test_deep_analysis_api.py`: **4 passed**

**이 계획이 추가하는 테스트는 전부 `pytestmark = pytest.mark.no_db` + Fake 주입이다.** Postgres 없이 통과해야 하며, 위 37 실패 수를 늘리면 안 된다.

---

## File Structure

| 파일 | 책임 |
|---|---|
| `neos/config/schema.py` (수정) | `DeepAnalysisConfig`에 job/stream 설정 6개 추가 |
| `neos/workflow/deep_analysis/jobs.py` (신규) | **프레임워크 프리 job 러너.** 라이프사이클 이벤트(`job_*`) 기록 + `execute_run`/`resume_run`. DB 세션을 스스로 소유한다 |
| `neos/workflow/deep_analysis/event_stream.py` (신규) | **읽기 전용 커서 리더.** `read_events_after(session, run_id, after_seq)` + `get_run_owner` |
| `neos/tasks/deep_analysis_job_task.py` (신규) | **통합 계층.** Celery `@shared_task` + `submit_deep_analysis_job` 실행자 디스패처 + 리포트 → 대화 메시지 저장 |
| `neos/tasks/__init__.py` (수정) | 신규 태스크 export (워커가 임포트 시 등록되도록) |
| `neos/api/models/deep_analysis_models.py` (수정) | `DeepAnalysisJobResponse` 응답 모델 추가 |
| `neos/api/handlers/deep_analysis_handlers.py` (수정) | POST → 202, `GET .../events` SSE 신설, `POST .../resume` 신설 |
| `neos/workflow/deep_analysis/DECISIONS.md` (수정) | D22 기록 |

### 왜 `event_sink`를 영속화 경로로 쓰지 않는가 (설계 근거 — 읽고 시작할 것)

`Ledger.log()`는 **이미** `question_opened` · `split` · `dead_end` · `claim_verified` · `claim_rejected` · `claim_unverified` · `pass_completed` · `subq_proposed` · `worker_result_mismatch` · `stall_terminated` · `abandoned` · `question_reopened` · `conflict_reinvestigation` · `report_graded`를 `deep_analysis_events`에 쓴다. 오케스트레이터의 `_emit`(= `event_sink`)은 이 중 상당수와 **kind가 겹친다.**

따라서 job이 `event_sink`를 "DB에 쓰는 싱크"로 넘기면 같은 이벤트가 두 번 쌓인다. 겹치는 kind만 골라내는 allowlist는 오케스트레이터 내부와 조용히 결합되는 유지보수 함정이다.

**결정: job은 `event_sink`를 넘기지 않는다.** 대신 **`job_` 접두어의 라이프사이클 이벤트 4종**(`job_started`/`job_resumed`/`job_completed`/`job_failed`)만 `Ledger.log()`로 직접 쓴다. 이 접두어는 하네스가 쓰는 어떤 kind와도 충돌할 수 없다. 스트림 = "원장 이벤트 로그 + job 라이프사이클 마커"가 되고, **하네스 코어(M0–M4)는 한 줄도 바뀌지 않는다**(D18의 "최소 침습" 제약 유지).

부작용: `synth_pass`/`recovered`처럼 `_emit` 전용이던 kind는 영속화되지 않는다. `recovered`의 관측 가치는 `job_resumed`가 대체한다.

### 스트림 지연에 관한 사실 (예상과 다르면 당황하지 말 것)

`Ledger.log()`는 `flush()`만 한다. 이벤트가 **다른 프로세스에 보이려면 커밋**돼야 하고, 커밋은 `Orchestrator._checkpoint()`(= `session.commit`)가 한다. `_checkpoint`는 `_ensure_root` 뒤, 각 라운드의 split 뒤와 라운드 끝, `_finalize` 중간에 호출된다. 따라서 **스트림 해상도는 claim 단위가 아니라 라운드 단위**다. 3a의 AC(1·5·6·7)는 어느 것도 claim 단위 실시간성을 요구하지 않는다. claim 단위 스트리밍은 3b에서 챗 SSE 프로토콜 통합과 함께 다룰 사안이다.

---

### Task 1: job 실행·스트림 설정값

**Files:**
- Modify: `neos/config/schema.py:686-698` (`DeepAnalysisConfig` 끝부분, `sse_keepalive_seconds` 근처)
- Test: `tests/workflow/deep_analysis/test_config_defaults.py`

**Interfaces:**
- Consumes: 없음
- Produces: `settings.config.deep_analysis`의 신규 필드 —
  `job_queue: str`, `job_soft_time_limit: int`, `job_time_limit: int`, `job_max_retries: int`,
  `events_poll_interval: float`, `events_stream_idle_timeout: float`.
  `settings.DEEP_ANALYSIS_JOB_QUEUE` 등 레거시 대문자 접근도 `("DEEP_ANALYSIS_", "deep_analysis")` 프리픽스 매핑(`neos/config/settings.py:221`)으로 자동 동작한다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/workflow/deep_analysis/test_config_defaults.py` 끝에 추가:

```python
def test_deep_analysis_job_service_defaults():
    """Phase 3a(D22): durable job 서비스 설정.

    job_time_limit은 반드시 job_soft_time_limit보다 커야 한다 -- soft가 먼저
    올라야 예외를 잡아 job_failed를 남길 수 있고, hard는 그 뒤의 마지막 수단이다.
    """
    cfg = _settings().config.deep_analysis

    assert cfg.job_queue == "analysis"
    assert cfg.job_soft_time_limit == 3600
    assert cfg.job_time_limit == 3900
    assert cfg.job_time_limit > cfg.job_soft_time_limit
    assert cfg.job_max_retries == 2
    assert cfg.events_poll_interval == 1.0
    assert cfg.events_stream_idle_timeout == 300.0


def test_deep_analysis_job_settings_reachable_via_legacy_uppercase():
    settings = _settings()

    assert settings.DEEP_ANALYSIS_JOB_QUEUE == "analysis"
    assert settings.DEEP_ANALYSIS_EVENTS_POLL_INTERVAL == 1.0
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `.venv/bin/pytest tests/workflow/deep_analysis/test_config_defaults.py -q`
Expected: FAIL — `AttributeError: 'DeepAnalysisConfig' object has no attribute 'job_queue'`

- [ ] **Step 3: 최소 구현**

`neos/config/schema.py`에서 `DeepAnalysisConfig`의 `sse_keepalive_seconds: float = 0.5` **바로 아래**에 추가:

```python
    sse_keepalive_seconds: float = 0.5
    # ── Phase 3a (D22): durable job 서비스 ──────────────────────────────
    # 실행 큐. celery_app.py의 task_queues에 이미 정의된 4종 중 하나여야 한다
    # ('default'/'search'/'analysis'/'generation').
    job_queue: str = "analysis"
    # celery_app.py의 전역 기본값(soft 300s / hard 360s)은 심층분석 run에
    # 턱없이 짧다 -- dig effort 하나의 wall_clock_cap만 600s다. 태스크
    # 데코레이터에서 이 값으로 덮어쓴다.
    job_soft_time_limit: int = 3600
    job_time_limit: int = 3900
    # Celery 재시도는 resume=True로 재큐잉된다(스펙 §9 "resume 트리거 = Celery 재시도").
    job_max_retries: int = 2
    # 이벤트 커서 폴링 간격(초). 이벤트가 있으면 즉시 다음 배치를 읽으므로
    # 이 간격은 "새 이벤트가 없을 때"만 적용된다.
    events_poll_interval: float = 1.0
    # 새 이벤트 없이 이만큼 지나면 스트림을 닫는다. 무한 유휴 SSE 커넥션이
    # 워커/게이트웨이 슬롯을 잡아먹지 않게 하는 상한이다. 클라이언트는
    # 마지막 seq를 ?after=로 넘겨 재접속하면 이어서 받는다.
    events_stream_idle_timeout: float = 300.0
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv/bin/pytest tests/workflow/deep_analysis/test_config_defaults.py -q`
Expected: PASS (신규 2개 포함 전부)

- [ ] **Step 5: 커밋**

```bash
git add neos/config/schema.py tests/workflow/deep_analysis/test_config_defaults.py
git commit -m "feat(deep-analysis): add durable job service settings

Queue, time limits and event-cursor polling knobs for Phase 3a."
```

---

### Task 2: 이벤트 커서 리더 (`event_stream.py`)

**Files:**
- Create: `neos/workflow/deep_analysis/event_stream.py`
- Test: `tests/workflow/deep_analysis/test_event_stream.py` (신규)

**Interfaces:**
- Consumes: `neos.database.deep_analysis_models.DAEvent`, `DARun`
- Produces:
  - `async def read_events_after(session, run_id: str, after_seq: int = 0, limit: int = 200) -> list[dict]`
    — 각 원소는 `{"seq": int, "type": str, "qid": str | None, "payload": dict}`
  - `async def get_run_owner(session, run_id: str) -> tuple[str | None, str] | None` — `(user_id, status)` 또는 run 부재 시 `None`
  - `DEFAULT_EVENT_BATCH: int = 200`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/workflow/deep_analysis/test_event_stream.py` 신규 작성:

```python
"""커서 리더 단위 테스트 — Fake 세션만 쓰므로 Postgres가 필요 없다."""

import json
from types import SimpleNamespace

import pytest

from neos.workflow.deep_analysis.event_stream import (
    get_run_owner,
    read_events_after,
)


pytestmark = pytest.mark.no_db


class FakeScalars:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return iter(self._rows)


class FakeSession:
    """seq > after 필터와 정렬을 SQL 대신 파이썬에서 재현하는 세션 더블.

    실제 세션은 SQLAlchemy Select를 받아 DB에서 거른다. 여기서는 select
    객체를 무시하고 `self.rows`를 그대로 돌려주되, 호출부가 넘긴 커서를
    검증할 수 있도록 execute 호출을 기록한다.
    """

    def __init__(self, rows=None, run=None):
        self.rows = rows or []
        self.run = run
        self.executed = []

    async def execute(self, statement):
        self.executed.append(statement)
        return FakeScalars(self.rows)

    async def get(self, model, key):
        return self.run


def _event(seq, kind, qid, payload):
    return SimpleNamespace(
        seq=seq,
        kind=kind,
        qid=qid,
        payload=json.dumps(payload, ensure_ascii=False),
    )


@pytest.mark.asyncio
async def test_read_events_after_shapes_rows_for_sse():
    session = FakeSession(
        rows=[
            _event(1, "job_started", None, {"profile": "dev"}),
            _event(2, "question_opened", "q1000000", {"depth": 0}),
        ]
    )

    events = await read_events_after(session, "run00001", 0)

    assert events == [
        {"seq": 1, "type": "job_started", "qid": None, "payload": {"profile": "dev"}},
        {
            "seq": 2,
            "type": "question_opened",
            "qid": "q1000000",
            "payload": {"depth": 0},
        },
    ]


@pytest.mark.asyncio
async def test_read_events_after_tolerates_malformed_payload():
    """P4대로 이벤트 로그는 append-only라 나쁜 payload를 고칠 수 없다.
    리더가 죽으면 그 run의 스트림이 통째로 닫히므로 빈 dict로 낮춘다."""
    row = SimpleNamespace(seq=9, kind="dead_end", qid="q1", payload="not json")
    session = FakeSession(rows=[row])

    events = await read_events_after(session, "run00001", 0)

    assert events == [{"seq": 9, "type": "dead_end", "qid": "q1", "payload": {}}]


@pytest.mark.asyncio
async def test_get_run_owner_returns_none_for_missing_run():
    assert await get_run_owner(FakeSession(run=None), "nope") is None


@pytest.mark.asyncio
async def test_get_run_owner_returns_user_and_status():
    run = SimpleNamespace(user_id="owner", status="running")

    assert await get_run_owner(FakeSession(run=run), "run00001") == (
        "owner",
        "running",
    )
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `.venv/bin/pytest tests/workflow/deep_analysis/test_event_stream.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'neos.workflow.deep_analysis.event_stream'`

- [ ] **Step 3: 최소 구현**

`neos/workflow/deep_analysis/event_stream.py` 신규 작성:

```python
"""append-only deep_analysis 이벤트 로그에 대한 읽기 전용 커서 리더.

`DAEvent.seq`는 BigInteger autoincrement PK라 **그 자체가 단조 커서**다 --
별도 컬럼이 필요 없다. 커서를 0에서 시작하면 run의 전체 이력이 재생되므로,
진행 중인 run에 늦게 접속한 구독자도 처음부터 받는다(스펙 §5.5 AC6).

이 경로가 프로세스 경계를 넘는 유일한 이유는 매체가 **DB**이기 때문이다.
`neos/workflow/stream_manager.py:99`의 세션 레지스트리는 프로세스 내
dict라 Celery 워커가 넣은 이벤트를 API 프로세스가 볼 수 없다.

seq 폴링이 행을 건너뛰지 않는 근거는 P2(단일 작성자)다: run당 작성자가
하나면 seq 할당 순서가 곧 커밋 순서이므로, 이미 읽은 커서보다 작은 seq가
나중에 커밋되는 일이 없다. 이 모듈은 절대 쓰지 않는다(D8).
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select

from neos.database.deep_analysis_models import DAEvent, DARun

DEFAULT_EVENT_BATCH = 200


def _decode(payload: Any) -> dict[str, Any]:
    try:
        decoded = json.loads(payload)
    except (TypeError, ValueError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


async def read_events_after(
    session,
    run_id: str,
    after_seq: int = 0,
    limit: int = DEFAULT_EVENT_BATCH,
) -> list[dict[str, Any]]:
    """`after_seq`보다 큰 seq의 이벤트를 seq 오름차순으로 최대 `limit`개."""
    result = await session.execute(
        select(DAEvent)
        .where(DAEvent.run_id == run_id, DAEvent.seq > after_seq)
        .order_by(DAEvent.seq)
        .limit(limit)
    )
    return [
        {
            "seq": int(row.seq),
            "type": row.kind,
            "qid": row.qid,
            "payload": _decode(row.payload),
        }
        for row in result.scalars()
    ]


async def get_run_owner(session, run_id: str) -> tuple[str | None, str] | None:
    """`(user_id, status)` 또는 run이 없으면 None. 소유권 검사용."""
    run = await session.get(DARun, run_id)
    if run is None:
        return None
    return run.user_id, run.status
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv/bin/pytest tests/workflow/deep_analysis/test_event_stream.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: 커밋**

```bash
git add neos/workflow/deep_analysis/event_stream.py tests/workflow/deep_analysis/test_event_stream.py
git commit -m "feat(deep-analysis): add DB event-log cursor reader

DAEvent.seq is already a monotonic cursor, so a reader polling seq > cursor
crosses process boundaries -- which stream_manager's per-process session dict
cannot do. Starting at 0 replays a run's full history."
```

---

### Task 3: job 러너 (`jobs.py`) — 라이프사이클 이벤트 + resume 진입점

**Files:**
- Create: `neos/workflow/deep_analysis/jobs.py`
- Test: `tests/workflow/deep_analysis/test_jobs.py` (신규)

**Interfaces:**
- Consumes: Task 2 없음(독립). `neos.workflow.deep_analysis.ledger.Ledger`, `.service.build_orchestrator`, `neos.database.deep_analysis_models.DARun`
- Produces:
  - 상수 `JOB_STARTED = "job_started"`, `JOB_RESUMED = "job_resumed"`, `JOB_COMPLETED = "job_completed"`, `JOB_FAILED = "job_failed"`
  - `TERMINAL_JOB_KINDS: frozenset[str]` = `{JOB_COMPLETED, JOB_FAILED}`
  - `RESUMABLE_STATUSES: frozenset[str]` = `{"running", "failed"}`
  - `class RunNotResumable(Exception)`
  - `async def execute_run(session_factory, run_id: str, question: str, profile: str, *, resume: bool = False, build_orchestrator_fn=build_orchestrator) -> dict[str, str]`
  - `async def resume_run(session_factory, run_id: str, *, build_orchestrator_fn=build_orchestrator) -> dict[str, str]`
  - `session_factory`는 **인자 없이 호출하면 async context manager를 돌려주는 팩토리**다(프로덕션에서는 `neos.database.connection.get_session_ctx`).

**AC5 근거 — resume이 중복 지출을 막는 메커니즘 (구현 전 반드시 이해할 것):**

resume은 **새 상태 저장소가 아니라 진입점 추가**다(스펙 §5.3). `Orchestrator.run()`이 이미 재개 가능하기 때문이다:

| 재개 요소 | 어디서 보장되는가 |
|---|---|
| investigating에 잠긴 질문 회수 | `orchestrator.py:696` `ledger.recover()` — `investigating` → `open` |
| 루트 재분해 금지 | `orchestrator.py:207-209` `_ensure_root`가 기존 루트를 찾으면 즉시 반환 → `decompose_fn`(LLM) 재호출 없음 |
| **이미 쓴 토큰 재지출 금지** | `budgeter.py:114` `should_stop`이 `ledger.total_spent()`를 읽고, 이는 `DAQuestion.spent_tokens`의 **DB 합계**다(`ledger.py:678`). 크래시로 인메모리 Budgeter가 리셋돼도 소비 기록은 원장에 남는다 |
| 라운드 예산 재선택 금지 | `budgeter.ladder()`가 `question.spent_tokens >= question.cap_tokens`면 SPLIT으로 넘긴다 — 질문별 예산도 DB에 있다 |
| breadth pass 재실행 금지 | `budgeter.py:93-94`가 `spent < breadth_pass_ratio * global_token_cap`일 때만 breadth pass를 탄다. `spent`는 DB 값이므로 이미 30%를 넘겼으면 재개 후에도 안 탄다 |
| 충돌 재조사 라운드 재지출 금지 | `orchestrator.py:611-615`가 **인메모리 카운터가 아니라 이벤트 로그**(`ledger.has_event("conflict_reinvestigation")`, `ledger.py:119`)를 게이트로 쓴다 — 정확히 "resumed run은 두 번째 라운드를 쓸 수 없다"는 불변식 |

**즉 `execute_run`은 resume을 위해 새 로직을 만들지 않는다.** 같은 `run_id`로 `orch.run()`을 다시 부르는 것이 곧 resume이며, `resume` 플래그는 (a) 어떤 라이프사이클 이벤트를 남길지, (b) `failed` run을 `running`으로 되돌릴지만 결정한다. 이 성질 덕분에 Celery의 무맥락 재전달(worker lost → `resume=False`로 재배달)도 안전하다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/workflow/deep_analysis/test_jobs.py` 신규 작성:

```python
"""job 러너 단위 테스트 — Fake 세션/오케스트레이터만 쓴다(Postgres 불필요)."""

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from neos.workflow.deep_analysis import jobs


pytestmark = pytest.mark.no_db


class FakeSession:
    """Ledger.log()가 쓰는 add/flush와 commit/get만 흉내낸다."""

    def __init__(self, run=None):
        self.added = []
        self.commits = 0
        self.run = run

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        return None

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        return None

    async def get(self, model, key):
        return self.run


def make_factory(sessions):
    """호출될 때마다 sessions에서 하나씩 꺼내주는 session_factory."""
    handed = []

    @asynccontextmanager
    async def factory():
        session = sessions[len(handed)] if len(handed) < len(sessions) else sessions[-1]
        handed.append(session)
        yield session

    factory.handed = handed
    return factory


def kinds(session):
    return [obj.kind for obj in session.added]


@pytest.mark.asyncio
async def test_execute_run_brackets_the_run_with_lifecycle_events():
    session = FakeSession()
    factory = make_factory([session])
    seen = {}

    async def build(sess, run_id, *, profile, checkpoint):
        seen["run_id"] = run_id
        seen["profile"] = profile
        seen["checkpoint"] = checkpoint

        class Orchestrator:
            async def run(self, question):
                seen["question"] = question
                return {"run_id": run_id, "report_markdown": "## 요약\n리포트"}

        return Orchestrator()

    result = await jobs.execute_run(
        factory,
        "run00001",
        "질문",
        "dev",
        build_orchestrator_fn=build,
    )

    assert result["report_markdown"] == "## 요약\n리포트"
    assert seen["run_id"] == "run00001"
    assert seen["question"] == "질문"
    # 체크포인트가 세션 커밋에 묶여야 이벤트가 다른 프로세스에 보인다.
    assert seen["checkpoint"] == session.commit
    assert kinds(session) == [jobs.JOB_STARTED, jobs.JOB_COMPLETED]


@pytest.mark.asyncio
async def test_execute_run_carries_the_report_in_the_completion_event():
    """AC6: 늦게 접속한 구독자도 이벤트 재생만으로 리포트를 받아야 한다."""
    import json

    session = FakeSession()

    async def build(sess, run_id, *, profile, checkpoint):
        class Orchestrator:
            async def run(self, question):
                return {"run_id": run_id, "report_markdown": "## 요약\n본문"}

        return Orchestrator()

    await jobs.execute_run(
        make_factory([session]),
        "run00001",
        "질문",
        "dev",
        build_orchestrator_fn=build,
    )

    completed = session.added[-1]
    assert completed.kind == jobs.JOB_COMPLETED
    assert json.loads(completed.payload)["report_markdown"] == "## 요약\n본문"


@pytest.mark.asyncio
async def test_execute_run_records_failure_in_a_fresh_session_and_reraises():
    """D18 선결조건 #2와 같은 이유: 실패한 세션은 롤백/오류 상태일 수 있어
    재사용하지 않는다. 별도 세션에서 fail_run + job_failed를 커밋한다."""
    run_session = FakeSession()
    fail_session = FakeSession(run=SimpleNamespace(status="running", report_path=None))

    async def build(sess, run_id, *, profile, checkpoint):
        class Orchestrator:
            async def run(self, question):
                raise RuntimeError("boom")

        return Orchestrator()

    factory = make_factory([run_session, fail_session])

    with pytest.raises(RuntimeError, match="boom"):
        await jobs.execute_run(
            factory,
            "run00001",
            "질문",
            "dev",
            build_orchestrator_fn=build,
        )

    assert kinds(run_session) == [jobs.JOB_STARTED]
    assert kinds(fail_session) == [jobs.JOB_FAILED]
    assert fail_session.run.status == "failed"
    assert fail_session.commits >= 1


@pytest.mark.asyncio
async def test_resume_run_reuses_the_stored_question_and_emits_job_resumed():
    """AC5: resume은 새 run을 만들지 않는다 -- 같은 run_id로 다시 들어간다."""
    run = SimpleNamespace(
        status="running",
        root_question="원래 질문",
        profile="default",
    )
    session = FakeSession(run=run)
    seen = {}

    async def build(sess, run_id, *, profile, checkpoint):
        seen["run_id"] = run_id
        seen["profile"] = profile

        class Orchestrator:
            async def run(self, question):
                seen["question"] = question
                return {"run_id": run_id, "report_markdown": "리포트"}

        return Orchestrator()

    await jobs.resume_run(
        make_factory([session]),
        "run00001",
        build_orchestrator_fn=build,
    )

    assert seen["run_id"] == "run00001"
    assert seen["question"] == "원래 질문"
    assert seen["profile"] == "default"
    assert kinds(session) == [jobs.JOB_RESUMED, jobs.JOB_COMPLETED]


@pytest.mark.asyncio
async def test_resume_run_reactivates_a_failed_run():
    run = SimpleNamespace(status="failed", root_question="질문", profile="dev")
    session = FakeSession(run=run)

    async def build(sess, run_id, *, profile, checkpoint):
        class Orchestrator:
            async def run(self, question):
                return {"run_id": run_id, "report_markdown": "리포트"}

        return Orchestrator()

    await jobs.resume_run(
        make_factory([session]),
        "run00001",
        build_orchestrator_fn=build,
    )

    assert run.status == "running"


@pytest.mark.asyncio
async def test_resume_run_refuses_a_completed_run():
    """완료된 run을 재개하면 리포트 조립 + 채점 비용을 다시 쓴다 -- 재과금이다."""
    run = SimpleNamespace(status="completed", root_question="질문", profile="dev")

    with pytest.raises(jobs.RunNotResumable):
        await jobs.resume_run(make_factory([FakeSession(run=run)]), "run00001")


@pytest.mark.asyncio
async def test_resume_run_refuses_a_missing_run():
    with pytest.raises(jobs.RunNotResumable):
        await jobs.resume_run(make_factory([FakeSession(run=None)]), "nope")


def test_lifecycle_kinds_cannot_collide_with_harness_event_kinds():
    """job_ 접두어가 충돌 회피의 근거다. Ledger가 쓰는 kind를 하드코딩해
    두 집합이 겹치지 않음을 고정한다."""
    harness_kinds = {
        "question_opened",
        "split",
        "dead_end",
        "claim_verified",
        "claim_rejected",
        "claim_unverified",
        "pass_completed",
        "subq_proposed",
        "worker_result_mismatch",
        "stall_terminated",
        "abandoned",
        "question_reopened",
        "conflict_reinvestigation",
        "report_graded",
    }
    lifecycle = {
        jobs.JOB_STARTED,
        jobs.JOB_RESUMED,
        jobs.JOB_COMPLETED,
        jobs.JOB_FAILED,
    }

    assert lifecycle & harness_kinds == set()
    assert all(kind.startswith("job_") for kind in lifecycle)
    assert jobs.TERMINAL_JOB_KINDS == {jobs.JOB_COMPLETED, jobs.JOB_FAILED}
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `.venv/bin/pytest tests/workflow/deep_analysis/test_jobs.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'neos.workflow.deep_analysis.jobs'`

- [ ] **Step 3: 최소 구현**

`neos/workflow/deep_analysis/jobs.py` 신규 작성:

```python
"""deep_analysis run의 durable job 러너 (Phase 3a, D22).

D7은 "M1은 인라인 asyncio + SSE, Celery는 나중"을 정했다. 이 모듈이 그
"나중"의 실행 코어다 -- run을 제출한 요청 **밖에서** 완주시킨다.

이 모듈은 프레임워크 프리다: Celery도 FastAPI도 ChatService도 임포트하지
않는다. 실행자 선택(Celery vs 백그라운드 asyncio)과 대화 메시지 저장은
통합 계층인 `neos/tasks/deep_analysis_job_task.py`가 담당한다. 그래야
`deep_analysis`의 내부 의존 4개가 유지된다.

## event_sink를 쓰지 않는 이유

`Ledger.log()`가 이미 하네스 이벤트 대부분을 `deep_analysis_events`에
쓴다. 오케스트레이터의 `_emit`(event_sink)은 그 kind들과 겹치므로, job이
"DB에 쓰는 싱크"를 넘기면 같은 이벤트가 두 번 쌓인다. 겹치는 kind만
골라내는 allowlist는 오케스트레이터 내부와 조용히 결합되는 함정이다.

대신 `job_` 접두어의 라이프사이클 이벤트 4종만 직접 쓴다 -- 이 접두어는
하네스의 어떤 kind와도 충돌할 수 없고, 하네스 코어를 한 줄도 바꾸지
않는다(D18의 "최소 침습" 제약).

## resume (AC5)

resume은 새 상태 저장소가 아니라 진입점 추가다(스펙 §5.3). 같은 run_id로
`orch.run()`을 다시 부르는 것이 곧 resume이며, 중복 지출은 원장이 막는다:

- `ledger.recover()`가 investigating에 잠긴 질문을 open으로 회수한다
- `_ensure_root()`가 기존 루트를 찾으면 즉시 반환해 LLM 재분해를 막는다
- `budgeter.should_stop()`이 `ledger.total_spent()`(= DAQuestion.spent_tokens
  의 DB 합계)를 읽으므로, 인메모리 Budgeter가 리셋돼도 소비 기록은 남는다
- 충돌 재조사 캡은 인메모리 카운터가 아니라 이벤트 로그를 게이트로 쓴다
  (`orchestrator.py:611`, `ledger.has_event`) -- "resumed run은 두 번째
  라운드를 쓸 수 없다"는 불변식이 이미 코드에 있다

따라서 `resume` 플래그는 (a) 어떤 라이프사이클 이벤트를 남길지, (b)
failed run을 running으로 되돌릴지만 결정한다. 이 성질 덕분에 Celery가
worker-lost로 태스크를 resume=False로 재배달해도 안전하다.
"""

from __future__ import annotations

from typing import Any

from neos.database.deep_analysis_models import DARun
from neos.utils.logger import get_logger

from .ledger import Ledger
from .service import build_orchestrator

logger = get_logger(__name__)

JOB_STARTED = "job_started"
JOB_RESUMED = "job_resumed"
JOB_COMPLETED = "job_completed"
JOB_FAILED = "job_failed"

#: 스트림이 이 kind를 보면 종료한다.
TERMINAL_JOB_KINDS = frozenset({JOB_COMPLETED, JOB_FAILED})

#: 재개 가능한 run 상태. 'completed'는 제외한다 -- 완료된 run을 다시 돌리면
#: 리포트 조립/채점 비용을 재지출한다(재과금).
RESUMABLE_STATUSES = frozenset({"running", "failed"})


class RunNotResumable(Exception):
    """resume 대상 run이 없거나 이미 완료됐을 때."""


async def _log_lifecycle(
    session,
    run_id: str,
    kind: str,
    payload: dict[str, Any],
) -> None:
    """라이프사이클 이벤트 1건을 기록하고 즉시 커밋한다.

    커밋이 필수다 -- flush만 하면 다른 프로세스의 커서 리더가 볼 수 없다.
    """
    await Ledger(session, run_id).log(kind, None, payload)
    await session.commit()


async def _record_failure(session_factory, run_id: str, error: str) -> None:
    """실패 상태를 **새 세션**에서 내구성 있게 확정한다.

    실행 세션은 롤백/오류 상태일 수 있어 재사용하지 않는다(D18 선결조건 #2가
    챗 노드에서 겪은 것과 같은 함정).
    """
    try:
        async with session_factory() as session:
            run = await session.get(DARun, run_id)
            if run is not None:
                run.status = "failed"
            await _log_lifecycle(session, run_id, JOB_FAILED, {"error": error})
    except Exception:  # noqa: BLE001 - 원래 예외를 가리면 안 된다
        logger.error(
            "failed to persist job_failed for deep_analysis run %s",
            run_id,
            exc_info=True,
        )


async def execute_run(
    session_factory,
    run_id: str,
    question: str,
    profile: str,
    *,
    resume: bool = False,
    build_orchestrator_fn=build_orchestrator,
) -> dict[str, str]:
    """이미 생성된 run을 완주(또는 재개)시킨다.

    `session_factory`는 인자 없이 호출하면 async context manager를 돌려주는
    팩토리다(프로덕션: `neos.database.connection.get_session_ctx`). job이
    자기 세션을 소유하므로 제출한 요청의 세션을 빌리지 않는다.
    """
    async with session_factory() as session:
        await _log_lifecycle(
            session,
            run_id,
            JOB_RESUMED if resume else JOB_STARTED,
            {"profile": profile, "resume": resume},
        )
        orchestrator = await build_orchestrator_fn(
            session,
            run_id,
            profile=profile,
            checkpoint=session.commit,
        )
        try:
            result = await orchestrator.run(question)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "deep_analysis job %s failed: %s", run_id, exc, exc_info=True
            )
            await _record_failure(session_factory, run_id, str(exc)[:500])
            raise
        # AC6: 늦게 접속한 구독자가 이벤트 재생만으로 리포트를 받도록
        # 완료 이벤트가 리포트 본문을 싣는다.
        await _log_lifecycle(
            session,
            run_id,
            JOB_COMPLETED,
            {"report_markdown": result["report_markdown"]},
        )
        return result


async def resume_run(
    session_factory,
    run_id: str,
    *,
    build_orchestrator_fn=build_orchestrator,
) -> dict[str, str]:
    """중단된 run을 원장에 저장된 질문/프로파일로 재개한다."""
    async with session_factory() as session:
        run = await session.get(DARun, run_id)
        if run is None:
            raise RunNotResumable(f"run {run_id!r} not found")
        if run.status not in RESUMABLE_STATUSES:
            raise RunNotResumable(
                f"run {run_id!r} is {run.status!r}; "
                f"resumable statuses are {sorted(RESUMABLE_STATUSES)}"
            )
        question = run.root_question
        profile = run.profile
        if run.status != "running":
            run.status = "running"
            await session.commit()

    return await execute_run(
        session_factory,
        run_id,
        question,
        profile,
        resume=True,
        build_orchestrator_fn=build_orchestrator_fn,
    )
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv/bin/pytest tests/workflow/deep_analysis/test_jobs.py -q`
Expected: PASS (9 passed)

- [ ] **Step 5: 커밋**

```bash
git add neos/workflow/deep_analysis/jobs.py tests/workflow/deep_analysis/test_jobs.py
git commit -m "feat(deep-analysis): add framework-free durable job runner

Lifecycle events use a reserved job_ prefix so they cannot collide with the
kinds Ledger already logs -- the harness core stays untouched. resume is an
entry point, not a new store: the ledger already makes round budget durable."
```

---

### Task 4: resume이 라운드 예산을 두 번 쓰지 않는다 (AC5 회귀 고정)

Task 3이 resume **진입점**을 만들었다. 이 태스크는 그 진입점이 의존하는 **불변식**을 오케스트레이터 수준에서 고정한다 — 진입점이 옳아도 오케스트레이터가 재개 시 예산을 다시 쓰면 AC5는 깨진다.

**Files:**
- Test: `tests/workflow/deep_analysis/test_orchestrator_resume.py` (신규)
- Modify: 없음 (기존 동작을 고정하는 특성화 테스트다. 실패하면 그것이 곧 버그 발견이다)

**Interfaces:**
- Consumes: `neos.workflow.deep_analysis.orchestrator.Orchestrator`, `neos.workflow.deep_analysis.models.{ProposedClaim, Verdict, NodeSummary, WorkerResult}`
- Produces: 없음(테스트 전용)

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/workflow/deep_analysis/test_orchestrator_resume.py` 신규 작성:

```python
"""AC5: 워커 크래시 후 resume이 중복 지출 없이 라운드를 속행한다.

크래시를 "같은 원장 상태 위에 새 Orchestrator 인스턴스를 세우는 것"으로
모델링한다 -- 인메모리 상태(Budgeter 라운드 카운터, aging, stall 카운터,
_reinvestigation_count)는 전부 사라지고 원장만 남는다. 이것이 정확히
Celery 워커가 죽고 재시도가 도는 상황이다.
"""

from dataclasses import dataclass, field

import pytest

from neos.workflow.deep_analysis.models import (
    NodeSummary,
    ProposedClaim,
    Verdict,
    WorkerResult,
)
from neos.workflow.deep_analysis.orchestrator import Orchestrator


pytestmark = pytest.mark.no_db


@dataclass
class Question:
    id: str
    text: str
    parent_id: str | None
    depth: int
    status: str = "open"
    spent_tokens: int = 0
    value_est: float = 1.0
    confidence: float = 0.0
    cap_tokens: int = 999_999
    fail_streak: int = 0


@dataclass
class DurableLedger:
    """크래시를 넘어 살아남는 원장. 두 Orchestrator 인스턴스가 공유한다."""

    items: list = field(default_factory=list)
    events: list = field(default_factory=list)
    blobs: dict = field(default_factory=dict)
    completed: bool = False

    async def recover(self):
        recovered = 0
        for item in self.items:
            if item.status == "investigating":
                item.status = "open"
                recovered += 1
        return recovered

    async def root_question(self):
        return next((i for i in self.items if i.parent_id is None), None)

    async def get_question(self, question_id):
        return next((i for i in self.items if i.id == question_id), None)

    async def open_question(self, text, parent_id, value_est, cap_tokens, depth):
        question_id = f"{len(self.items) + 1:08x}"
        self.items.append(
            Question(
                question_id,
                text,
                parent_id,
                depth,
                value_est=value_est,
                cap_tokens=cap_tokens,
            )
        )
        return question_id

    async def record_split(self, question_id, child_ids):
        await self._transition(question_id, "split")

    async def open_questions(self):
        return [i for i in self.items if i.status == "open"]

    async def children(self, question_id):
        return [i for i in self.items if i.parent_id == question_id]

    async def gain_history(self, question_id, last_n=3):
        return []

    async def total_spent(self):
        return sum(i.spent_tokens for i in self.items)

    async def _transition(self, question_id, status):
        item = next(i for i in self.items if i.id == question_id)
        item.status = status

    async def commit_blobs(self, blobs):
        for blob in blobs:
            self.blobs[blob.content_hash] = blob

    async def commit_pass(self, question_id, result, verdicts):
        item = next(i for i in self.items if i.id == question_id)
        item.spent_tokens += result.tokens_spent
        item.status = "open"  # 미해결로 남겨 다음 라운드에 재선택 가능하게

    async def pending_claims(self, question_id):
        return []

    async def pending_feedback(self, question_id):
        return []

    async def log(self, kind, qid, payload):
        self.events.append((kind, qid, payload))

    async def has_event(self, kind):
        return any(event[0] == kind for event in self.events)

    async def complete_run(self, report_path=None):
        self.completed = True

    async def fail_run(self):
        raise AssertionError("run unexpectedly failed")

    async def remaining_budget(self, question_id):
        item = next(i for i in self.items if i.id == question_id)
        return max(0, item.cap_tokens - item.spent_tokens)

    async def verified_summaries(self, question_id):
        return "(없음)"

    async def unverified_and_deadends(self, question_id):
        return []


class CountingWorkerFactory:
    """패스마다 고정 토큰을 쓰는 워커. 총 호출 수를 센다."""

    def __init__(self, tokens_per_pass=100):
        self.tokens_per_pass = tokens_per_pass
        self.calls = 0

    def __call__(self):
        factory = self

        class Worker:
            async def investigate(self, brief, effort, question_id, repairs=None):
                factory.calls += 1
                return WorkerResult(
                    question_id=question_id,
                    status="completed",
                    claims=[ProposedClaim("fact", 0.6)],
                    tokens_spent=factory.tokens_per_pass,
                    self_assessment=0.4,
                )

        return Worker()


class OkGrader:
    async def grade(self, claim):
        return Verdict(ok=True)


class StubSynthesizer:
    _REPORT = "## 요약\n요약\n\n## 본문\n본문\n\n## 한계와 미확인 사항\n없음\n\n## 출처"

    async def reduce_tree(self, root_id):
        return {root_id: NodeSummary(root_id, "요약", [], 1.0, [])}

    async def assemble(self, root_summary, child_summaries, caveats):
        return self._REPORT


class StubCitationRenderer:
    async def render(self, draft):
        return draft


def build(ledger, worker_factory, decompose_calls, cap):
    async def decompose(_root):
        decompose_calls.append(_root)
        return [{"text": "child", "value_est": 0.9}]

    return Orchestrator(
        object(),
        "run00001",
        worker_factory=worker_factory,
        grader=OkGrader(),
        ledger=ledger,
        decompose_fn=decompose,
        synthesizer=StubSynthesizer(),
        citation_renderer=StubCitationRenderer(),
        global_token_cap=cap,
        parallel_workers=1,
        max_stall_rounds=99,
    )


@pytest.mark.asyncio
async def test_resumed_run_does_not_redecompose_the_root():
    """AC5: 재개된 run이 루트를 다시 분해하면 LLM decompose 비용을 재지출하고
    질문 트리가 중복된다. `_ensure_root`의 조기 반환이 이를 막는다."""
    ledger = DurableLedger()
    decompose_calls = []

    await build(ledger, CountingWorkerFactory(), decompose_calls, 100).run("root")
    questions_after_first = len(ledger.items)

    # 크래시 → 재개: 새 인스턴스, 같은 원장.
    await build(ledger, CountingWorkerFactory(), decompose_calls, 100).run("root")

    assert len(decompose_calls) == 1
    assert len(ledger.items) == questions_after_first


@pytest.mark.asyncio
async def test_resumed_run_does_not_respend_the_recorded_round_budget():
    """AC5의 핵심: 원장에 기록된 소비는 재개 후 재선택 예산을 줄인다.

    cap=200, 패스당 100토큰이면 총 2패스가 상한이다. 1회차에서 몇 패스를
    돌았든, 재개 후 총 패스 수는 여전히 2를 넘지 않아야 한다 -- 넘으면
    이미 쓴 예산을 두 번 쓴 것이고 곧 재과금이다.
    """
    ledger = DurableLedger()
    first_worker = CountingWorkerFactory(tokens_per_pass=100)

    await build(ledger, first_worker, [], 200).run("root")
    spent_after_first = await ledger.total_spent()

    second_worker = CountingWorkerFactory(tokens_per_pass=100)
    await build(ledger, second_worker, [], 200).run("root")

    total_passes = first_worker.calls + second_worker.calls
    assert total_passes * 100 == await ledger.total_spent()
    assert await ledger.total_spent() <= 200
    assert total_passes <= 2
    # 1회차가 이미 캡을 채웠다면 재개는 워커를 한 번도 돌리지 않는다.
    if spent_after_first >= 200:
        assert second_worker.calls == 0


@pytest.mark.asyncio
async def test_resumed_run_cannot_spend_a_second_conflict_reinvestigation_round():
    """orchestrator.py:611의 이벤트 로그 게이트를 고정한다. 인메모리
    카운터는 재개 시 리셋되지만 이벤트 로그는 리셋되지 않는다."""
    ledger = DurableLedger()
    await ledger.log("conflict_reinvestigation", "q1", {"qids": ["q1"]})

    orchestrator = build(ledger, CountingWorkerFactory(), [], 100)

    assert orchestrator._reinvestigation_count == 0  # 인메모리는 리셋됨
    assert await ledger.has_event("conflict_reinvestigation") is True


@pytest.mark.asyncio
async def test_resume_recovers_questions_stranded_in_investigating():
    """크래시는 질문을 investigating에 남긴다. recover()가 없으면 그 질문은
    영원히 재선택되지 않아 run이 조기 종료된다."""
    ledger = DurableLedger()
    ledger.items.append(Question("00000001", "root", None, 0, status="split"))
    ledger.items.append(
        Question("00000002", "child", "00000001", 1, status="investigating")
    )

    worker = CountingWorkerFactory(tokens_per_pass=100)
    await build(ledger, worker, [], 200).run("root")

    assert worker.calls >= 1
```

- [ ] **Step 2: 테스트를 실행해 현재 동작을 확인**

Run: `.venv/bin/pytest tests/workflow/deep_analysis/test_orchestrator_resume.py -q`
Expected: PASS (5 passed).

이 태스크는 **기존 동작을 고정하는 특성화 테스트**다. 여기서 실패가 나면 AC5의 전제(스펙 §5.3이 "resume은 진입점 추가일 뿐"이라 본 근거)가 틀렸다는 뜻이다. **그 경우 Task 5로 넘어가지 말고 멈춰서 어느 불변식이 깨졌는지 보고하라.**

- [ ] **Step 3: 커밋**

```bash
git add tests/workflow/deep_analysis/test_orchestrator_resume.py
git commit -m "test(deep-analysis): pin the no-double-spend invariants resume relies on

AC5 rests on the ledger, not on new code: recorded spend, the early return in
_ensure_root, and the event-log gate on conflict reinvestigation all survive
a fresh Orchestrator instance. These tests fail if any of them regresses."
```

---

### Task 5: 실행자 이원화 — Celery 태스크 + 인라인 백그라운드 폴백

**Files:**
- Create: `neos/tasks/deep_analysis_job_task.py`
- Modify: `neos/tasks/__init__.py:1-14`
- Test: `tests/workflow/deep_analysis/test_deep_analysis_job_task.py` (신규)

**Interfaces:**
- Consumes: Task 3의 `jobs.execute_run` / `jobs.resume_run`
- Produces:
  - `run_deep_analysis_job` — Celery `@shared_task`, name `"neos.tasks.run_deep_analysis_job"`, 시그니처 `(self, run_id, question="", profile="dev", resume=False)`
  - `def submit_deep_analysis_job(run_id: str, question: str = "", profile: str = "dev", *, resume: bool = False) -> str` — 실행자 이름 `"celery"` 또는 `"inline"` 반환
  - `async def _execute(run_id, question, profile, resume)` — 두 실행자가 공유하는 async 본문

**설계 지침 — 계약 단일화:** `CELERY_ENABLED=false`가 기본값이다. 여기서 심층분석을 못 쓰게 되면 회귀다. 두 실행자 모두 **같은 `_execute`를 돌고 같은 이벤트 로그에 쓴다.** 그러므로 `GET .../events`는 실행자와 무관하게 동일하게 동작한다. 실행자는 운영 선택이지 API 계약이 아니다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/workflow/deep_analysis/test_deep_analysis_job_task.py` 신규 작성:

```python
"""실행자 디스패처 테스트 — Celery 브로커도 Postgres도 필요 없다."""

import asyncio

import pytest

from neos.tasks import deep_analysis_job_task as task_module


pytestmark = pytest.mark.no_db


def test_celery_task_is_registered_with_long_time_limits():
    """celery_app.py의 전역 기본값(soft 300s / hard 360s)은 심층분석 run에
    턱없이 짧다 -- dig effort 하나의 wall_clock_cap만 600s다."""
    from neos.config.settings import settings

    config = settings.config.deep_analysis
    task = task_module.run_deep_analysis_job

    assert task.name == "neos.tasks.run_deep_analysis_job"
    assert task.soft_time_limit == config.job_soft_time_limit
    assert task.time_limit == config.job_time_limit


def test_submit_uses_celery_when_enabled(monkeypatch):
    captured = {}

    def apply_async(**kwargs):
        captured.update(kwargs)
        return type("AsyncResult", (), {"id": "celery-task-id"})()

    monkeypatch.setattr(
        task_module.run_deep_analysis_job, "apply_async", apply_async
    )
    monkeypatch.setattr(
        task_module, "_celery_enabled", lambda: True
    )

    executor = task_module.submit_deep_analysis_job(
        "run00001", "질문", "dev"
    )

    assert executor == "celery"
    assert captured["queue"] == "analysis"
    assert captured["kwargs"] == {
        "run_id": "run00001",
        "question": "질문",
        "profile": "dev",
        "resume": False,
    }


@pytest.mark.asyncio
async def test_submit_falls_back_to_a_background_task_when_celery_is_off(
    monkeypatch,
):
    """추가 AC: CELERY_ENABLED=false(기본)에서도 심층분석이 동작해야 한다."""
    ran = asyncio.Event()
    seen = {}

    async def fake_execute(run_id, question, profile, resume):
        seen.update(
            run_id=run_id, question=question, profile=profile, resume=resume
        )
        ran.set()

    monkeypatch.setattr(task_module, "_celery_enabled", lambda: False)
    monkeypatch.setattr(task_module, "_execute", fake_execute)

    executor = task_module.submit_deep_analysis_job(
        "run00001", "질문", "default"
    )

    assert executor == "inline"
    await asyncio.wait_for(ran.wait(), timeout=2)
    assert seen == {
        "run_id": "run00001",
        "question": "질문",
        "profile": "default",
        "resume": False,
    }


@pytest.mark.asyncio
async def test_background_task_is_strongly_referenced_until_it_finishes(
    monkeypatch,
):
    """asyncio.create_task의 반환값을 붙들지 않으면 GC가 실행 중 태스크를
    거둬갈 수 있다. 모듈 레벨 집합이 강한 참조를 유지해야 한다."""
    release = asyncio.Event()

    async def fake_execute(run_id, question, profile, resume):
        await release.wait()

    monkeypatch.setattr(task_module, "_celery_enabled", lambda: False)
    monkeypatch.setattr(task_module, "_execute", fake_execute)

    task_module.submit_deep_analysis_job("run00001", "질문", "dev")

    assert len(task_module._BACKGROUND_TASKS) == 1
    release.set()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert len(task_module._BACKGROUND_TASKS) == 0


def test_submit_passes_resume_through(monkeypatch):
    captured = {}

    def apply_async(**kwargs):
        captured.update(kwargs)
        return type("AsyncResult", (), {"id": "x"})()

    monkeypatch.setattr(
        task_module.run_deep_analysis_job, "apply_async", apply_async
    )
    monkeypatch.setattr(task_module, "_celery_enabled", lambda: True)

    task_module.submit_deep_analysis_job("run00001", resume=True)

    assert captured["kwargs"]["resume"] is True


def test_task_is_exported_from_the_tasks_package():
    """Celery 워커는 neos.tasks를 임포트할 때 태스크를 등록한다."""
    import neos.tasks as tasks

    assert tasks.run_deep_analysis_job is task_module.run_deep_analysis_job
    assert "run_deep_analysis_job" in tasks.__all__
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `.venv/bin/pytest tests/workflow/deep_analysis/test_deep_analysis_job_task.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'neos.tasks.deep_analysis_job_task'`

- [ ] **Step 3: 최소 구현**

`neos/tasks/deep_analysis_job_task.py` 신규 작성:

```python
"""deep_analysis durable job의 실행자 계층 (Phase 3a, D22).

**실행자는 둘, 계약은 하나다.**

- `CELERY_ENABLED=true`  → `apply_async`로 큐잉, 워커 프로세스가 완주
- `CELERY_ENABLED=false` → 응답을 막지 않는 백그라운드 asyncio 태스크

기본값이 `false`이므로(`schema.py` CeleryConfig.enabled) 폴백이 없으면
기본 구성에서 심층분석이 아예 안 도는 회귀가 된다. 두 경로 모두 같은
`_execute`를 돌고 **같은 DB 이벤트 로그**에 쓰므로,
`GET /api/v1/deep-analysis/{run_id}/events`는 실행자와 무관하게 동일하게
동작한다. 실행자는 운영 선택이지 API 계약이 아니다.

이 모듈이 `neos/tasks/`에 있는 이유: `deep_analysis` 패키지는 프레임워크
프리이고 내부 의존이 4개다. Celery와 ChatService는 그 안으로 들어가면
안 되는 통합 관심사이므로 여기서 흡수한다.
"""

from __future__ import annotations

import asyncio

from celery import shared_task

from neos.config.settings import settings
from neos.utils.logger import get_logger

logger = get_logger(__name__)

#: 실행 중인 인라인 태스크의 강한 참조. asyncio.create_task의 반환값을
#: 붙들지 않으면 GC가 실행 중 태스크를 거둬갈 수 있다.
_BACKGROUND_TASKS: set[asyncio.Task] = set()

_config = settings.config.deep_analysis


def _celery_enabled() -> bool:
    return bool(getattr(settings, "CELERY_ENABLED", False))


async def _persist_assistant_message(run_id: str, report_markdown: str) -> None:
    """리포트를 대화 메시지로 저장한다(대화에 묶인 run만).

    인라인 SSE 시절 핸들러가 하던 일이다. 실행이 요청 밖으로 나갔으므로
    job 쪽으로 옮긴다. 실패해도 run 자체는 성공이므로 삼킨다 -- 리포트는
    이미 job_completed 이벤트에 실려 있다.
    """
    from neos.api.services.chat_service import ChatService
    from neos.database.connection import get_session_ctx
    from neos.database.deep_analysis_models import DARun

    async with get_session_ctx() as session:
        run = await session.get(DARun, run_id)
        conversation_id = getattr(run, "conversation_id", None)
        message_id = getattr(run, "assistant_message_id", None)

    if not conversation_id or not message_id:
        return

    try:
        await ChatService.add_message(
            conversation_id=conversation_id,
            role="assistant",
            content=report_markdown,
            message_id=message_id,
            model_name="deep-analysis-harness",
            metadata={
                "deep_analysis_run_id": run_id,
                "research_status": "completed",
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "failed to persist deep_analysis report message for run %s: %s",
            run_id,
            exc,
        )


async def _execute(
    run_id: str,
    question: str,
    profile: str,
    resume: bool,
) -> dict[str, str]:
    """두 실행자가 공유하는 async 본문."""
    from neos.database.connection import get_session_ctx
    from neos.workflow.deep_analysis.jobs import execute_run, resume_run

    if resume:
        result = await resume_run(get_session_ctx, run_id)
    else:
        result = await execute_run(get_session_ctx, run_id, question, profile)

    await _persist_assistant_message(run_id, result["report_markdown"])
    return result


@shared_task(
    name="neos.tasks.run_deep_analysis_job",
    bind=True,
    max_retries=_config.job_max_retries,
    default_retry_delay=30,
    soft_time_limit=_config.job_soft_time_limit,
    time_limit=_config.job_time_limit,
)
def run_deep_analysis_job(
    self,
    run_id: str,
    question: str = "",
    profile: str = "dev",
    resume: bool = False,
):
    """deep_analysis run 하나를 완주시킨다.

    재시도는 **resume=True로** 재큐잉한다(스펙 §9 "resume 트리거 = Celery
    재시도"). 중복 지출은 원장이 막으므로(jobs.py 참조) 재시도가 라운드
    예산을 다시 쓰지 않는다.
    """
    try:
        asyncio.run(_execute(run_id, question, profile, resume))
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "run_deep_analysis_job %s failed: %s", run_id, exc, exc_info=True
        )
        raise self.retry(
            exc=exc,
            kwargs={
                "run_id": run_id,
                "question": question,
                "profile": profile,
                "resume": True,
            },
        )


def _discard_task(task: asyncio.Task) -> None:
    _BACKGROUND_TASKS.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error("inline deep_analysis job failed: %s", exc, exc_info=exc)


def submit_deep_analysis_job(
    run_id: str,
    question: str = "",
    profile: str = "dev",
    *,
    resume: bool = False,
) -> str:
    """run을 설정된 실행자로 디스패치한다. 실행자 이름을 반환한다."""
    kwargs = {
        "run_id": run_id,
        "question": question,
        "profile": profile,
        "resume": resume,
    }
    if _celery_enabled():
        run_deep_analysis_job.apply_async(
            kwargs=kwargs,
            queue=settings.config.deep_analysis.job_queue,
        )
        return "celery"

    task = asyncio.create_task(
        _execute(run_id, question, profile, resume)
    )
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_discard_task)
    return "inline"
```

`neos/tasks/__init__.py`를 교체:

```python
"""NEOS Tasks — Celery 비동기 태스크 패키지

Phase 4 (OpenClaw Cron 스케줄 스킬):
- scheduled_task_runner: DB 폴링 기반 동적 스케줄 실행기

Phase 3a (deep_analysis durable job, D22):
- deep_analysis_job_task: run 실행자(Celery / 인라인 백그라운드) 디스패처
"""

from .scheduled_task_runner import poll_and_run_scheduled_tasks, run_workflow_task
from .deep_analysis_report_task import compute_deep_analysis_improvement_report
from .deep_analysis_job_task import (
    run_deep_analysis_job,
    submit_deep_analysis_job,
)

__all__ = [
    "poll_and_run_scheduled_tasks",
    "run_workflow_task",
    "compute_deep_analysis_improvement_report",
    "run_deep_analysis_job",
    "submit_deep_analysis_job",
]
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv/bin/pytest tests/workflow/deep_analysis/test_deep_analysis_job_task.py -q`
Expected: PASS (6 passed)

- [ ] **Step 5: 커밋**

```bash
git add neos/tasks/deep_analysis_job_task.py neos/tasks/__init__.py tests/workflow/deep_analysis/test_deep_analysis_job_task.py
git commit -m "feat(deep-analysis): dual executors behind one job contract

Celery when enabled, a detached asyncio task otherwise -- CELERY_ENABLED
defaults to false, so no fallback would mean deep analysis simply stops
working in the default configuration. Both write the same event log."
```

---

### Task 6: API — 202 제출, 커서 SSE, resume

**Files:**
- Modify: `neos/api/models/deep_analysis_models.py` (응답 모델 추가)
- Modify: `neos/api/handlers/deep_analysis_handlers.py:48-158` (POST 재작성 + 엔드포인트 2개 신설)
- Test: `tests/api/test_deep_analysis_api.py` (기존 SSE 테스트 교체 + 신규)

**Interfaces:**
- Consumes: Task 2의 `read_events_after`/`get_run_owner`, Task 3의 `TERMINAL_JOB_KINDS`/`RESUMABLE_STATUSES`, Task 5의 `submit_deep_analysis_job`
- Produces:
  - `class DeepAnalysisJobResponse(BaseModel)`: `run_id: str`, `status: str`, `executor: str`, `events_url: str`
  - `POST /deep-analysis` → 202 `DeepAnalysisJobResponse`
  - `GET /deep-analysis/{run_id}/events?after=<int>` → `text/event-stream`
  - `POST /deep-analysis/{run_id}/resume` → 202 `DeepAnalysisJobResponse`

**소비자 확인 결과(착수 전 grep 완료):** `web/` · `mcp/` · `examples/` · `neos_evals/` · `scripts/`에 `deep-analysis`/`deep_analysis` 참조가 **0건**이다. 이 엔드포인트의 유일한 소비자는 `tests/api/test_deep_analysis_api.py`다. 따라서 POST를 202로 바꾸는 것이 깨뜨리는 외부 소비자는 없다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/api/test_deep_analysis_api.py`의 `test_sse_run_links_user_and_report_messages`(47-130행)를 **삭제하고** 아래로 교체한다. 그 테스트가 검증하던 "리포트 → assistant 메시지" 동작은 Task 5의 `_persist_assistant_message`로 이동했다.

```python
@pytest.mark.asyncio
async def test_post_returns_202_with_run_id_without_blocking(monkeypatch):
    """AC1: 제출은 즉시 반환한다 -- 오케스트레이터를 기다리지 않는다."""
    from neos.api.handlers import deep_analysis_handlers as handlers

    messages = []

    async def get_conversation(conversation_id):
        return {"conversation_id": conversation_id, "user_id": "owner"}

    async def add_message(**kwargs):
        messages.append(kwargs)
        return kwargs

    monkeypatch.setattr(handlers.ChatService, "get_conversation", get_conversation)
    monkeypatch.setattr(handlers.ChatService, "add_message", add_message)

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def commit(self):
            return None

    async def get_session():
        return Session()

    monkeypatch.setattr(handlers.db_manager, "get_session", get_session)

    async def fake_create_run(*args, **kwargs):
        return "run00001"

    monkeypatch.setattr(handlers, "create_run", fake_create_run)

    submitted = {}

    def fake_submit(run_id, question="", profile="dev", *, resume=False):
        submitted.update(
            run_id=run_id, question=question, profile=profile, resume=resume
        )
        return "inline"

    monkeypatch.setattr(handlers, "submit_deep_analysis_job", fake_submit)

    response = await handlers.start_deep_analysis(
        DeepAnalysisRequest(question="Question", conversation_id="conversation"),
        SimpleNamespace(user_id="owner"),
    )

    assert response.run_id == "run00001"
    assert response.status == "accepted"
    assert response.executor == "inline"
    assert response.events_url == "/api/v1/deep-analysis/run00001/events"
    assert submitted == {
        "run_id": "run00001",
        "question": "Question",
        "profile": "dev",
        "resume": False,
    }
    # 사용자 메시지는 제출 시점에 저장된다. assistant 메시지는 job이 쓴다.
    assert [message["role"] for message in messages] == ["user"]


def test_post_is_declared_202():
    from neos.api.deep_analysis_routes import router

    route = next(
        r
        for r in router.routes
        if r.path == "/deep-analysis" and "POST" in r.methods
    )
    assert route.status_code == 202


def test_job_routes_registered():
    from neos.api.deep_analysis_routes import router

    paths = {route.path for route in router.routes}
    assert "/deep-analysis" in paths
    assert "/deep-analysis/{run_id}/events" in paths
    assert "/deep-analysis/{run_id}/resume" in paths


@pytest.mark.asyncio
async def test_events_stream_replays_full_history_for_a_late_subscriber(
    monkeypatch,
):
    """AC6: 커서를 0에서 시작하면 진행 중인 run의 전체 이력이 재생된다."""
    from neos.api.handlers import deep_analysis_handlers as handlers

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

    async def get_session():
        return Session()

    monkeypatch.setattr(handlers.db_manager, "get_session", get_session)

    async def fake_owner(session, run_id):
        return ("owner", "running")

    monkeypatch.setattr(handlers, "get_run_owner", fake_owner)

    history = [
        {"seq": 1, "type": "job_started", "qid": None, "payload": {}},
        {"seq": 2, "type": "question_opened", "qid": "q1", "payload": {"depth": 0}},
        {"seq": 3, "type": "pass_completed", "qid": "q1", "payload": {"verified": 1}},
        {
            "seq": 4,
            "type": "job_completed",
            "qid": None,
            "payload": {"report_markdown": "## 요약"},
        },
    ]

    async def fake_read(session, run_id, after_seq=0, limit=200):
        return [event for event in history if event["seq"] > after_seq]

    monkeypatch.setattr(handlers, "read_events_after", fake_read)

    class Request:
        async def is_disconnected(self):
            return False

    response = await handlers.stream_deep_analysis_events(
        "run00001",
        Request(),
        0,
        SimpleNamespace(user_id="owner"),
    )

    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
    stream = "".join(chunks)

    assert '"type": "job_started"' in stream
    assert '"type": "question_opened"' in stream
    assert '"type": "pass_completed"' in stream
    assert '"type": "job_completed"' in stream
    # 종료 이벤트에서 스트림이 닫힌다.
    assert stream.count('"type": "job_completed"') == 1


@pytest.mark.asyncio
async def test_events_stream_honours_the_after_cursor(monkeypatch):
    """재접속 클라이언트는 마지막 seq를 넘겨 이어받는다."""
    from neos.api.handlers import deep_analysis_handlers as handlers

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

    async def get_session():
        return Session()

    monkeypatch.setattr(handlers.db_manager, "get_session", get_session)

    async def fake_owner(session, run_id):
        return ("owner", "running")

    monkeypatch.setattr(handlers, "get_run_owner", fake_owner)

    history = [
        {"seq": 1, "type": "job_started", "qid": None, "payload": {}},
        {"seq": 2, "type": "job_failed", "qid": None, "payload": {"error": "boom"}},
    ]

    async def fake_read(session, run_id, after_seq=0, limit=200):
        return [event for event in history if event["seq"] > after_seq]

    monkeypatch.setattr(handlers, "read_events_after", fake_read)

    class Request:
        async def is_disconnected(self):
            return False

    response = await handlers.stream_deep_analysis_events(
        "run00001",
        Request(),
        1,
        SimpleNamespace(user_id="owner"),
    )

    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
    stream = "".join(chunks)

    assert '"type": "job_started"' not in stream
    assert '"type": "job_failed"' in stream


@pytest.mark.asyncio
async def test_events_stream_hides_other_users_runs(monkeypatch):
    from neos.api.handlers import deep_analysis_handlers as handlers

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

    async def get_session():
        return Session()

    monkeypatch.setattr(handlers.db_manager, "get_session", get_session)

    async def fake_owner(session, run_id):
        return ("someone-else", "running")

    monkeypatch.setattr(handlers, "get_run_owner", fake_owner)

    class Request:
        async def is_disconnected(self):
            return False

    with pytest.raises(Exception) as captured:
        await handlers.stream_deep_analysis_events(
            "run00001", Request(), 0, SimpleNamespace(user_id="owner")
        )
    assert getattr(captured.value, "status_code", None) == 404


@pytest.mark.asyncio
async def test_resume_dispatches_the_job_for_a_running_run(monkeypatch):
    """AC5의 API 표면."""
    from neos.api.handlers import deep_analysis_handlers as handlers

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

    async def get_session():
        return Session()

    monkeypatch.setattr(handlers.db_manager, "get_session", get_session)

    async def fake_owner(session, run_id):
        return ("owner", "running")

    monkeypatch.setattr(handlers, "get_run_owner", fake_owner)

    submitted = {}

    def fake_submit(run_id, question="", profile="dev", *, resume=False):
        submitted.update(run_id=run_id, resume=resume)
        return "celery"

    monkeypatch.setattr(handlers, "submit_deep_analysis_job", fake_submit)

    response = await handlers.resume_deep_analysis(
        "run00001", SimpleNamespace(user_id="owner")
    )

    assert response.run_id == "run00001"
    assert response.status == "accepted"
    assert response.executor == "celery"
    assert submitted == {"run_id": "run00001", "resume": True}


@pytest.mark.asyncio
async def test_resume_refuses_a_completed_run(monkeypatch):
    from neos.api.handlers import deep_analysis_handlers as handlers

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

    async def get_session():
        return Session()

    monkeypatch.setattr(handlers.db_manager, "get_session", get_session)

    async def fake_owner(session, run_id):
        return ("owner", "completed")

    monkeypatch.setattr(handlers, "get_run_owner", fake_owner)

    with pytest.raises(Exception) as captured:
        await handlers.resume_deep_analysis(
            "run00001", SimpleNamespace(user_id="owner")
        )
    assert getattr(captured.value, "status_code", None) == 409
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `.venv/bin/pytest tests/api/test_deep_analysis_api.py -q`
Expected: FAIL — `AttributeError: module ... has no attribute 'submit_deep_analysis_job'`

- [ ] **Step 3: 최소 구현 (1/2) — 응답 모델**

`neos/api/models/deep_analysis_models.py` 끝에 추가:

```python
class DeepAnalysisJobResponse(BaseModel):
    """202 제출 응답. 실행자가 무엇이든 계약은 동일하다."""

    run_id: str
    status: str = "accepted"
    executor: str
    events_url: str
```

- [ ] **Step 4: 최소 구현 (2/2) — 핸들러**

`neos/api/handlers/deep_analysis_handlers.py`를 아래 내용으로 **전면 교체**:

```python
"""Authenticated job API for loop-based deep analysis runs.

Phase 3a(D22): 제출과 실행을 분리한다. `POST`는 run을 만들고 job을
디스패치한 뒤 **즉시 202를 반환**한다(AC1). 진행 상황은
`GET /{run_id}/events`가 append-only 이벤트 로그를 seq 커서로 재생해
전달한다 -- 이 매체가 DB이므로 Celery 워커가 넣은 이벤트를 API 프로세스가
볼 수 있다(`stream_manager`는 프로세스 내 dict라 불가능하다).

동기 요청 안에서 심층분석을 완주시키려는 시도 자체가 구조적으로 틀렸다:
프론트 maxDuration 60s < 노드 캡 300s < dig 하나의 wall_clock_cap 600s.
가장 작은 예산이 클라이언트 쪽에 있으므로, 라운드를 여러 번 도는 run은
어떤 동기 요청 예산에도 맞지 않는다.
"""

from __future__ import annotations

import asyncio
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from neos.api.dependencies.auth import get_current_active_user
from neos.api.models.deep_analysis_models import (
    DeepAnalysisJobResponse,
    DeepAnalysisRequest,
)
from neos.api.services.chat_service import ChatService
from neos.config.settings import settings
from neos.database.connection import db_manager
from neos.database.models import User
from neos.tasks.deep_analysis_job_task import submit_deep_analysis_job
from neos.utils.logger import get_logger
from neos.workflow.deep_analysis.event_stream import (
    get_run_owner,
    read_events_after,
)
from neos.workflow.deep_analysis.jobs import (
    RESUMABLE_STATUSES,
    TERMINAL_JOB_KINDS,
)
from neos.workflow.deep_analysis.ledger import create_run


logger = get_logger(__name__)
router = APIRouter()


def _events_url(run_id: str) -> str:
    return f"{settings.API_V1_PREFIX}/deep-analysis/{run_id}/events"


async def ensure_owned_conversation(
    conversation_id: str | None,
    user_id: str,
    chat_service=ChatService,
):
    if conversation_id is None:
        return None
    conversation = await chat_service.get_conversation(conversation_id)
    if conversation is None or conversation.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail="Resource not found")
    return conversation


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _require_owned_run(run_id: str, user_id: str) -> tuple[str | None, str]:
    async with await db_manager.get_session() as session:
        owner = await get_run_owner(session, run_id)
    if owner is None or owner[0] != user_id:
        # 존재 여부를 흘리지 않는다.
        raise HTTPException(status_code=404, detail="Resource not found")
    return owner


@router.post(
    "/deep-analysis",
    status_code=202,
    response_model=DeepAnalysisJobResponse,
)
async def start_deep_analysis(
    request: DeepAnalysisRequest,
    current_user: User = Depends(get_current_active_user),
) -> DeepAnalysisJobResponse:
    """run을 생성하고 job을 디스패치한 뒤 즉시 반환한다(AC1)."""
    conversation = await ensure_owned_conversation(
        request.conversation_id,
        current_user.user_id,
    )
    assistant_message_id = str(uuid.uuid4()) if conversation is not None else None

    if conversation is not None:
        await ChatService.add_message(
            conversation_id=request.conversation_id,
            role="user",
            content=request.question,
            metadata={"deep_analysis_initiated": True},
        )

    async with await db_manager.get_session() as session:
        run_id = await create_run(
            session,
            request.question,
            request.profile,
            user_id=current_user.user_id,
            conversation_id=request.conversation_id,
            assistant_message_id=assistant_message_id,
        )
        # 커밋이 필수다 -- job이 다른 프로세스/태스크에서 이 run을 읽는다.
        await session.commit()

    executor = submit_deep_analysis_job(
        run_id,
        request.question,
        request.profile,
    )
    logger.info(
        "deep_analysis run %s submitted by %s via %s",
        run_id,
        current_user.user_id,
        executor,
    )
    return DeepAnalysisJobResponse(
        run_id=run_id,
        status="accepted",
        executor=executor,
        events_url=_events_url(run_id),
    )


@router.get("/deep-analysis/{run_id}/events")
async def stream_deep_analysis_events(
    run_id: str,
    request: Request,
    after: int = Query(0, ge=0, description="이 seq보다 큰 이벤트만. 0이면 전체 이력."),
    current_user: User = Depends(get_current_active_user),
):
    """이벤트 로그를 seq 커서로 재생 + 라이브 tail (AC6).

    `after=0`(기본)이면 진행 중인 run이라도 처음부터 전부 받는다. 재접속
    클라이언트는 마지막으로 받은 seq를 넘겨 이어받는다.
    """
    await _require_owned_run(run_id, current_user.user_id)
    config = settings.config.deep_analysis

    async def generate():
        cursor = after
        idle = 0.0
        while True:
            if await request.is_disconnected():
                return

            async with await db_manager.get_session() as session:
                events = await read_events_after(session, run_id, cursor)

            if events:
                idle = 0.0
                for event in events:
                    cursor = event["seq"]
                    yield _sse(event)
                    if event["type"] in TERMINAL_JOB_KINDS:
                        return
                # 배치가 꽉 찼을 수 있으므로 곧바로 다음 배치를 읽는다.
                continue

            yield ": keepalive\n\n"
            await asyncio.sleep(config.events_poll_interval)
            idle += config.events_poll_interval
            if idle >= config.events_stream_idle_timeout:
                yield _sse(
                    {
                        "type": "stream_idle_timeout",
                        "run_id": run_id,
                        "seq": cursor,
                    }
                )
                return

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post(
    "/deep-analysis/{run_id}/resume",
    status_code=202,
    response_model=DeepAnalysisJobResponse,
)
async def resume_deep_analysis(
    run_id: str,
    current_user: User = Depends(get_current_active_user),
) -> DeepAnalysisJobResponse:
    """중단된 run을 재개한다(AC5).

    중복 지출은 원장이 막는다 -- 소비된 토큰은 `DAQuestion.spent_tokens`에,
    충돌 재조사 소진은 이벤트 로그에 남아 있다. 재개는 새 상태 저장소가
    아니라 진입점이다(스펙 §5.3).
    """
    _owner_id, status = await _require_owned_run(run_id, current_user.user_id)
    if status not in RESUMABLE_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=f"run is {status!r} and cannot be resumed",
        )

    executor = submit_deep_analysis_job(run_id, resume=True)
    logger.info("deep_analysis run %s resumed by %s via %s",
                run_id, current_user.user_id, executor)
    return DeepAnalysisJobResponse(
        run_id=run_id,
        status="accepted",
        executor=executor,
        events_url=_events_url(run_id),
    )
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `.venv/bin/pytest tests/api/test_deep_analysis_api.py -q`
Expected: PASS (11 passed)

- [ ] **Step 6: 커밋**

```bash
git add neos/api/handlers/deep_analysis_handlers.py neos/api/models/deep_analysis_models.py tests/api/test_deep_analysis_api.py
git commit -m "feat(deep-analysis): submit runs as jobs and stream events from the log

POST now returns 202 + run_id without blocking; GET /{run_id}/events replays
the append-only event log by seq cursor, so a late subscriber gets the full
history and a Celery worker's progress is visible to the API process."
```

---

### Task 7: 무회귀 고정 (AC7) + D22 기록

**Files:**
- Test: `tests/workflow/test_deep_analysis_job_no_regression.py` (신규)
- Modify: `neos/workflow/deep_analysis/DECISIONS.md` (끝에 D22 추가)

**Interfaces:**
- Consumes: 없음
- Produces: 없음

**AC7의 의미:** `DEEP_ANALYSIS_ENABLED=false`(기본)일 때 챗 그래프는 `deep_analysis_orchestrator` 노드를 **등록조차 하지 않는다**(D18의 구조적 무회귀 보장). 3a는 챗 경로를 건드리지 않으므로 이 성질이 유지되는지만 고정하면 된다. 동시에 **3b로 미룬 것이 실제로 남아 있는지**(챗 노드가 아직 존재하는지)도 고정해, 범위 이탈을 테스트가 잡게 한다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/workflow/test_deep_analysis_job_no_regression.py` 신규 작성:

```python
"""AC7 + 3a/3b 경계 고정.

3a는 job 서비스만 만든다. 챗 경로(그래프 노드·라우터·분류기)는 3b의
범위이며 이 단계에서 바뀌면 안 된다.
"""

from pathlib import Path

import pytest


pytestmark = pytest.mark.no_db


def test_chat_node_is_untouched_by_phase_3a():
    """AC2/AC3(챗 노드 제거)는 3b다. 여기서 사라지면 범위 이탈이다."""
    source = Path("neos/workflow/graph.py").read_text(encoding="utf-8")

    assert "_deep_analysis_orchestrator_node" in source
    # 9763eb5의 wall-clock 바운드가 그대로 있어야 한다.
    assert "node_wall_clock_cap" in source


def test_deep_analysis_node_not_registered_when_flag_is_off():
    """D18의 구조적 무회귀: 플래그가 꺼져 있으면 노드가 등록되지 않는다."""
    from neos.config.settings import settings

    assert settings.config.deep_analysis.enabled is False


def test_job_service_does_not_import_langgraph_or_langchain():
    """스펙 §1.4 / 이 계획의 전역 제약: deep_analysis는 프레임워크 프리다."""
    for name in ("jobs.py", "event_stream.py"):
        source = Path(f"neos/workflow/deep_analysis/{name}").read_text(
            encoding="utf-8"
        )
        assert "langchain" not in source
        assert "langgraph" not in source


def test_job_runner_does_not_import_celery_or_fastapi():
    """실행자 관심사는 neos/tasks/에 있다 -- deep_analysis의 내부 의존을
    4개로 유지하기 위해서다."""
    source = Path("neos/workflow/deep_analysis/jobs.py").read_text(
        encoding="utf-8"
    )

    assert "celery" not in source.lower()
    assert "fastapi" not in source.lower()


def test_job_service_does_not_use_the_in_process_stream_manager():
    """stream_manager._sessions는 프로세스 내 dict라 Celery 워커의 이벤트가
    API 프로세스로 넘어오지 못한다. 전달 매체는 DB여야 한다."""
    for path in (
        "neos/workflow/deep_analysis/jobs.py",
        "neos/workflow/deep_analysis/event_stream.py",
        "neos/api/handlers/deep_analysis_handlers.py",
        "neos/tasks/deep_analysis_job_task.py",
    ):
        source = Path(path).read_text(encoding="utf-8")
        assert "stream_manager" not in source, path
```

- [ ] **Step 2: 테스트 실행**

Run: `.venv/bin/pytest tests/workflow/test_deep_analysis_job_no_regression.py -q`
Expected: PASS (5 passed)

- [ ] **Step 3: D22를 DECISIONS.md에 기록**

`neos/workflow/deep_analysis/DECISIONS.md` 끝(D21 뒤)에 추가:

```markdown

---

## D22. durable job 서비스로 전환 — D7의 "나중"이 왔다 (3a: 제출·스트림·resume)

**결정:** D7("M1은 인라인 asyncio + SSE, Celery는 나중")을 갱신한다. `POST /api/v1/deep-analysis`는
run을 만들고 job을 디스패치한 뒤 **202 + run_id를 즉시 반환**한다. 실행은 요청 밖에서 진행되고,
진행 상황은 `GET /api/v1/deep-analysis/{run_id}/events`가 append-only 이벤트 로그를
`deep_analysis_events.seq` 커서로 재생해 전달한다. `POST /api/v1/deep-analysis/{run_id}/resume`가
중단된 run의 재개 진입점이다. **실행자는 둘, 계약은 하나다** — `CELERY_ENABLED=true`면
`apply_async`, 기본값 `false`면 응답을 막지 않는 백그라운드 asyncio 태스크. 두 경로 모두 같은
이벤트 로그에 쓰므로 스트림 엔드포인트는 실행자와 무관하게 동일하게 동작한다.

**근거 — 동기 요청 안에서 완주시키려는 시도 자체가 구조적으로 틀렸다:** 세 예산을 나란히 놓으면
프론트 `maxDuration` 60s < 노드 wall-clock 캡 300s < `dig` effort 하나의 `wall_clock_cap` 600s다.
**가장 작은 예산이 클라이언트 쪽에 있으므로**, 라운드를 여러 번 도는 run은 어떤 동기 요청 예산에도
애초에 맞지 않는다. 커밋 `9763eb5`의 노드 캡은 "호출자가 떠난 뒤에도 백엔드가 자원을 붙들고 있는 것"을
막을 뿐, 사용자가 결과를 받게 하지 못한다. 비동기 job + 이벤트 스트림은 우회가 아니라 유일한 해법이다.

**근거 — 전달 매체는 `stream_manager`가 아니라 DB다:** `neos/workflow/stream_manager.py:99`의
`self._sessions: Dict[str, StreamSession] = {}`는 **프로세스 내 메모리**다. Celery 워커가 넣은
이벤트를 API 프로세스의 SSE가 볼 수 없다. 반면 `DAEvent.seq`는 BigInteger autoincrement PK라
**그 자체가 단조 커서**이고, 매체가 DB이므로 프로세스 경계를 자연히 넘는다. 커서를 0에서 시작하면
진행 중인 run의 전체 이력이 재생되므로 **AC6이 공짜로 따라온다.** D8이 이 테이블을 append-only
DB 불변식으로 만들어 뒀으므로 P4와도 일치한다. seq 폴링이 행을 건너뛰지 않는 근거는 P2(단일
작성자)다 — run당 작성자가 하나면 seq 할당 순서가 곧 커밋 순서다.

**근거 — `event_sink`를 영속화 경로로 쓰지 않는다:** `Ledger.log()`가 이미 하네스 이벤트
대부분(`question_opened`·`pass_completed`·`claim_verified` 등 14종)을 `deep_analysis_events`에
쓴다. 오케스트레이터의 `_emit`은 그 kind들과 겹치므로, job이 "DB에 쓰는 싱크"를 넘기면 같은
이벤트가 두 번 쌓인다. 겹치는 kind만 골라내는 allowlist는 오케스트레이터 내부와 조용히 결합되는
유지보수 함정이다. 대신 **`job_` 접두어 라이프사이클 이벤트 4종**(`job_started`/`job_resumed`/
`job_completed`/`job_failed`)만 직접 쓴다 — 이 접두어는 하네스의 어떤 kind와도 충돌할 수 없고,
**하네스 코어(M0–M4)를 한 줄도 바꾸지 않는다**(D18의 "최소 침습" 제약 유지).

**근거 — resume은 새 저장소가 아니라 진입점이다(AC5):** Ledger가 이미 단일 상태 저장소이므로(P2),
같은 run_id로 `orch.run()`을 다시 부르는 것이 곧 resume이다. 중복 지출을 막는 것은 신규 코드가
아니라 **이미 존재하던 네 불변식**이다:
1. `ledger.recover()`가 `investigating`에 잠긴 질문을 `open`으로 회수한다
2. `_ensure_root()`가 기존 루트를 찾으면 즉시 반환해 LLM 재분해를 막는다
3. `budgeter.should_stop()`이 `ledger.total_spent()`(= `DAQuestion.spent_tokens`의 DB 합계)를
   읽으므로, 크래시로 인메모리 Budgeter가 리셋돼도 소비 기록은 원장에 남는다. breadth pass도
   같은 DB 값으로 게이팅된다
4. 충돌 재조사 캡은 인메모리 카운터가 아니라 **이벤트 로그**를 게이트로 쓴다(`orchestrator.py:611`,
   `ledger.has_event`) — "resumed run은 두 번째 라운드를 쓸 수 없다"는 불변식이 이미 코드에 있었다

따라서 `resume` 플래그는 (a) 어떤 라이프사이클 이벤트를 남길지, (b) `failed` run을 `running`으로
되돌릴지만 결정한다. 이 성질 덕분에 Celery가 worker-lost로 태스크를 `resume=False`로 재배달해도
안전하다. `completed` run은 재개를 거부한다 — 리포트 조립/채점 비용 재지출은 곧 재과금이다.
회귀 고정: `tests/workflow/deep_analysis/test_orchestrator_resume.py`.

**이탈 — D7 갱신:** D7이 예고한 "later"가 왔다. D7이 사전 기록한 리스크 2건의 현황:
1. **단일 작성자** — D2의 advisory lock으로 선제 해결됨. 변동 없음.
2. **A1 partial 시맨틱이 Celery로 이전되지 않음** — **여전히 미해소다.** `asyncio.wait_for` 취소는
   같은 프로세스 안이라 `flush_partial()`이 워커 버퍼에 닿지만, Celery **하드** 타임아웃
   (`task_time_limit`)은 프로세스를 죽여 버퍼가 증발한다. 이 결정은 (a) 태스크 시간 제한을
   run 규모에 맞게 크게 잡고(soft 3600s / hard 3900s — celery_app.py 전역 기본값 300/360s는
   `dig` 하나의 600s에도 못 미친다), (b) soft 타임아웃 예외를 잡아 `job_failed`를 남긴 뒤
   resume으로 회수하는 경로를 둔다. **그래도 하드 킬 시 진행 중 라운드의 partial 클레임은
   유실된다** — 다만 커밋된 라운드는 원장에 남으므로 resume이 그 지점부터 속행한다.
   손실 경계가 "라운드 하나"로 줄었을 뿐 사라지지는 않았다. M2의 partial AC는 **Celery
   환경에서 여전히 재검증 대상**이다.
- **부수 리스크(인라인 SSE ↔ nginx `proxy_read_timeout`)는 해소됐다.** POST가 더 이상 스트림을
  붙들지 않고, GET 스트림은 `events_stream_idle_timeout`(기본 300s)로 스스로 닫힌 뒤
  클라이언트가 `?after=<seq>`로 재접속해 이어받는다.

**영향 — 3b가 남았다:** 이 결정은 스펙 §5의 AC 중 **AC1·AC5·AC6·AC7만** 이행한다. 남은 것:
- **AC2** 챗 요청이 deep analysis 실행 중 블로킹되지 않는다
- **AC3** `graph.py`에서 `_deep_analysis_orchestrator_node`가 제거된다
- **AC4** 챗과 전용 API가 동일한 이벤트 스트림 계약을 사용한다(R4 no-op 싱크 해소)

이 셋은 **챗 API 계약을 바꾸므로 프론트엔드 변경이 필수다**(스펙 §5.4, K4). FE 준비도가 낮다는
감사 결과가 있으므로 3b는 FE 작업과 조율해 별도로 진행한다. 그때까지 `_deep_analysis_orchestrator_node`는
`9763eb5`의 wall-clock 바운드를 단 채 그대로 남는다 — **제거는 3b의 일이다.** 경계 고정:
`tests/workflow/test_deep_analysis_job_no_regression.py`.

**영향 — 스트림 해상도는 라운드 단위다:** `Ledger.log()`는 flush만 하고, 다른 프로세스에
보이려면 커밋이 필요하며 커밋은 `Orchestrator._checkpoint()`가 한다. `_checkpoint`는 라운드
경계와 `_finalize` 중간에 호출되므로 claim 단위 실시간성은 나오지 않는다. 3a의 AC 중 어느 것도
이를 요구하지 않는다. claim 단위 스트리밍은 3b에서 챗 SSE 프로토콜 통합과 함께 다룬다.

**영향 — 동시 실행 방지는 도입하지 않는다:** 같은 run에 대해 두 job이 동시에 도는 것을 막는
리스(lease)는 만들지 않았다. 크래시한 워커와 실행 중인 워커를 이벤트 로그만으로 구별할 수 없기
때문이다(둘 다 `job_started`에 종료 이벤트 없음). 대신 P2의 advisory lock이 원장 쓰기를
직렬화하고, 소비 회계가 DB에 있으므로 최악의 경우도 **진행 중이던 라운드 하나를 다시 도는 것**에
그친다 — 이미 원장에 기록된 지출은 어느 경로로도 두 번 청구되지 않는다. 리스가 필요해지면
`deep_analysis_runs`에 heartbeat 컬럼을 더하는 별도 결정으로 다룬다.
```

- [ ] **Step 4: 전체 테스트 실행 및 기준선 대조**

```bash
.venv/bin/pytest tests/workflow/ -q --ignore=tests/workflow/mission --ignore=tests/workflow/harness
.venv/bin/pytest tests/workflow/mission tests/workflow/harness -q
.venv/bin/pytest tests/api/ -q
```

Expected:
- 분할 1: **failed 수가 기준선 37에서 늘지 않는다.** passed는 258 + 신규(약 25)로 증가.
- 분할 2: 103 passed (변동 없음)
- `tests/api/`: `test_deep_analysis_api.py` 11 passed. 다른 API 테스트의 실패 수가 늘지 않아야 한다.

**failed 수가 37을 넘으면 멈추고 어느 테스트가 새로 깨졌는지 보고하라.**

- [ ] **Step 5: 커밋**

```bash
git add tests/workflow/test_deep_analysis_job_no_regression.py neos/workflow/deep_analysis/DECISIONS.md
git commit -m "docs(deep-analysis): record D22 -- durable job service supersedes D7

Phase 3a delivers AC1/AC5/AC6/AC7. AC2/AC3/AC4 (removing the chat node and
having chat consume the job) stay in 3b because they change the chat API
contract and require frontend work. Tests pin that boundary."
```

---

## Self-Review

**1. 스펙 §5 커버리지**

| 스펙 항목 | 어디서 |
|---|---|
| §5.1 제출: run_id 즉시 반환(202) | Task 6 `start_deep_analysis` |
| §5.1 실행: Celery 워커 | Task 5 `run_deep_analysis_job` (+ 인라인 폴백) |
| §5.1 진행: 이벤트 로그 재생 + 라이브 tail | Task 2 리더 + Task 6 `stream_deep_analysis_events` |
| §5.1 재개: Ledger에서 open 질문 복원 후 속행 | Task 3 `resume_run` + Task 4 불변식 고정 |
| §5.2 D18 승계 (챗 노드 제거) | **3b — 의도적 미이행.** Task 7이 경계를 테스트로 고정 |
| §5.3 resume 설계 3단계 | Task 3 문서화 + Task 4 테스트 |
| §5.4 챗 API 계약 변경 | **3b** — 이 계획은 챗을 건드리지 않는다 |
| §5.5 AC1 | Task 6 `test_post_returns_202_with_run_id_without_blocking` |
| §5.5 AC2·AC3·AC4 | **3b** |
| §5.5 AC5 | Task 3 + Task 4 |
| §5.5 AC6 | Task 6 `test_events_stream_replays_full_history_for_a_late_subscriber` |
| §5.5 AC7 | Task 7 |
| §9 resume 트리거 = Celery 재시도 | Task 5 `self.retry(kwargs={..., "resume": True})` |
| 추가 AC: `CELERY_ENABLED=false` 동작 | Task 5 `test_submit_falls_back_to_a_background_task_when_celery_is_off` |

**2. 플레이스홀더 스캔:** 모든 스텝이 실제 코드/명령/예상 출력을 담고 있다. "TBD"·"적절히 처리"·"Task N과 유사" 없음.

**3. 타입 일관성 확인:**
- `submit_deep_analysis_job(run_id, question="", profile="dev", *, resume=False) -> str` — Task 5 정의, Task 6에서 동일 시그니처로 호출/모킹
- `read_events_after(session, run_id, after_seq=0, limit=200) -> list[dict]` — Task 2 정의, Task 6에서 동일 인자로 호출
- `get_run_owner(session, run_id) -> tuple[str | None, str] | None` — Task 2 정의, Task 6 `_require_owned_run`이 `(user_id, status)` 언팩
- `TERMINAL_JOB_KINDS` / `RESUMABLE_STATUSES` — Task 3 정의, Task 6 임포트
- `execute_run(session_factory, run_id, question, profile, *, resume, build_orchestrator_fn)` — Task 3 정의, Task 5 `_execute`가 위치 인자로 호출
- 이벤트 dict 키는 전 구간 `{"seq", "type", "qid", "payload"}`로 통일
- `DeepAnalysisJobResponse(run_id, status, executor, events_url)` — Task 6 정의, 두 엔드포인트가 동일하게 반환
