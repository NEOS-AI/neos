# L5 개선 루프 (Sub-project B) 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** append-only `deep_analysis_events`(+ claims/feedback)를 개선 신호로 집계하는 AnalyticsService + on-demand API + 주기 Celery 리포트 + golden 회귀 게이트를 추가한다(auto-mutation 없음, 사람 검토용).

**Architecture:** 기존 `WebSearchAnalyticsService`(집계) + `poll-scheduled-tasks`(Celery beat) 패턴을 그대로 따른다. L5는 events에서 **읽기만** 하고 리포트는 별도 테이블에 쓴다.

**Tech Stack:** Python 3.12, async SQLAlchemy, FastAPI, Celery Beat, pytest + pytest-asyncio.

**Spec:** [docs/superpowers/specs/2026-07-11-deep-analysis-chatswap-and-l5-design.md](../specs/2026-07-11-deep-analysis-chatswap-and-l5-design.md).

## Global Constraints

- **events read-only(§11.3, D8):** L5는 `deep_analysis_events`를 UPDATE/DELETE하지 않는다. 리포트는 신규 `deep_analysis_reports` 테이블.
- **전역 집계:** run 스코프가 아니라 여러 run에 걸친 기간 집계. period 파라미터(day/week/month).
- **auto-mutation 없음(D19):** 신호만 산출. 프롬프트/설정 자동 변경 금지.
- **매직넘버 금지:** 상수는 settings.
- **테스트 실 LLM/네트워크 금지.** DB 집계 테스트는 실 세션 + 시드 이벤트 + rollback.
- **테스트 명령:** `.venv/bin/python -m pytest`.

---

## 파일 구조
- Create: `neos/workflow/deep_analysis/analytics.py` — `DeepAnalysisAnalyticsService`.
- Create: `db/migrations/037_add_deep_analysis_reports.sql` + `DAReport` ORM(`deep_analysis_models.py`).
- Create: `neos/api/deep_analysis_analytics_routes.py` + `neos/api/handlers/deep_analysis_analytics_handlers.py`.
- Create: `neos/tasks/deep_analysis_report_task.py` — Celery 태스크.
- Modify: `neos/main.py`(라우터 등록), `neos/workflow/celery_app.py`(beat), `neos/database/deep_analysis_models.py`(DAReport).
- Tests: `test_deep_analysis_analytics.py`, `test_deep_analysis_analytics_api.py`, `test_deep_analysis_report_task.py`, golden 게이트.

---

### Task 1: DeepAnalysisAnalyticsService (events → 개선 신호)

**Files:**
- Create: `neos/workflow/deep_analysis/analytics.py`
- Test: `tests/workflow/deep_analysis/test_deep_analysis_analytics.py`

**Interfaces:**
- Produces: `class DeepAnalysisAnalyticsService(session)`; `async signals(self, *, since: datetime | None = None) -> dict` 반환:
  - `reject_rate_by_code: dict[str,float]` — `claim_rejected` 이벤트 payload `code`별 카운트/총 클레임 이벤트.
  - `overclaim_rate: float` — (`E_OVERCLAIM`+`E_CONFIDENCE_INFLATED`) / 총 거절.
  - `dead_end_rate: float` — `dead_end` 이벤트 / `question_opened` 이벤트.
  - `unverified_rate: float` — `claim_unverified` / (`claim_verified`+`claim_rejected`+`claim_unverified`).
  - `reinvestigation_count: int` — `conflict_reinvestigation` 이벤트 수.
  - `avg_verified_per_pass: float` — `pass_completed` payload `verified` 평균.
  - `report_retry_rate: float` — `report_graded` ok=false / 총 report_graded.
  - `totals: dict` — 이벤트 kind별 카운트.
  - `async summary(self, *, since=None) -> dict` — 위 신호 + 기간 메타 롤업.
- events는 `deep_analysis_events`(seq, run_id, ts, kind, qid, payload TEXT JSON). payload는 `json.loads`. `since`로 ts 필터.

- [ ] **Step 1: 실패 테스트** (실 세션 + 시드 이벤트)

```python
# tests/workflow/deep_analysis/test_deep_analysis_analytics.py
import pytest
from sqlalchemy import text as sql
from neos.workflow.deep_analysis.analytics import DeepAnalysisAnalyticsService
from neos.workflow.deep_analysis.ledger import create_run
from neos.database.connection import db_manager
import neos.database.models  # register FK targets

async def _ev(s, run_id, kind, payload="{}"):
    await s.execute(sql("INSERT INTO deep_analysis_events (run_id, kind, qid, payload) "
        "VALUES (:r,:k,NULL,:p)"), {"r": run_id, "k": kind, "p": payload})

@pytest.mark.asyncio
async def test_signals_compute_from_events():
    async with await db_manager.get_session() as s:
        run_id = await create_run(s, "root", "dev")
        await _ev(s, run_id, "claim_verified", '{"claim_id":"a"}')
        await _ev(s, run_id, "claim_rejected", '{"code":"E_OVERCLAIM"}')
        await _ev(s, run_id, "claim_rejected", '{"code":"E_UNSUPPORTED"}')
        await _ev(s, run_id, "claim_unverified", '{"code":"E_UNSUPPORTED"}')
        await _ev(s, run_id, "pass_completed", '{"verified":2}')
        await _ev(s, run_id, "pass_completed", '{"verified":0}')
        await _ev(s, run_id, "report_graded", '{"ok":false,"code":"E_ORPHAN_CITE"}')
        await _ev(s, run_id, "report_graded", '{"ok":true}')
        svc = DeepAnalysisAnalyticsService(s)
        sig = await svc.signals()
        assert sig["reject_rate_by_code"]["E_OVERCLAIM"] > 0
        assert abs(sig["avg_verified_per_pass"] - 1.0) < 1e-6
        assert abs(sig["report_retry_rate"] - 0.5) < 1e-6
        assert sig["unverified_rate"] > 0
        await s.rollback()
```

- [ ] **Step 2~5:** 실패 확인 → 구현(집계 쿼리 + payload 파싱) → 통과 → 커밋.

```bash
git commit -m "feat(deep-analysis): add DeepAnalysisAnalyticsService mining events into improvement signals"
```

---

### Task 2: 리포트 테이블 마이그레이션 + DAReport ORM

**Files:**
- Create: `db/migrations/037_add_deep_analysis_reports.sql`
- Modify: `neos/database/deep_analysis_models.py`
- Test: `tests/workflow/deep_analysis/test_deep_analysis_report_model.py`

**Interfaces:**
- Produces: 테이블 `deep_analysis_reports(id BIGSERIAL PK, period_start TIMESTAMP, period_end TIMESTAMP, signals JSONB NOT NULL, created_at TIMESTAMP DEFAULT NOW())`. ORM `DAReport`.

- [ ] **Step 1: 실패 테스트** — 마이그레이션 적용 후 테이블/컬럼 존재 + ORM tablename.
- [ ] **Step 2~5:** 마이그레이션 SQL(migration 036 포맷 미러) + `DAReport` 모델(`neos/database/deep_analysis_models.py`, `Base`) + `__all__` 추가 → 통과 → 커밋.

```sql
-- db/migrations/037_add_deep_analysis_reports.sql
CREATE TABLE IF NOT EXISTS deep_analysis_reports (
    id           BIGSERIAL   PRIMARY KEY,
    period_start TIMESTAMP   NOT NULL,
    period_end   TIMESTAMP   NOT NULL,
    signals      JSONB       NOT NULL,
    created_at   TIMESTAMP   NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_da_reports_created ON deep_analysis_reports (created_at DESC);
```

```bash
git commit -m "feat(deep-analysis): add deep_analysis_reports table and DAReport model"
```

---

### Task 3: Analytics API 엔드포인트

**Files:**
- Create: `neos/api/handlers/deep_analysis_analytics_handlers.py`
- Create: `neos/api/deep_analysis_analytics_routes.py`
- Modify: `neos/main.py` (라우터 등록)
- Test: `tests/api/test_deep_analysis_analytics_api.py`

**Interfaces:**
- Produces: `GET /api/v1/deep-analysis/analytics?period=week` → `DeepAnalysisAnalyticsService.summary` JSON. `get_current_active_user` 인증. period → since 변환(day=1, week=7, month=30).

- [ ] **Step 1: 실패 스모크** — 라우트 등록 확인(`from neos.main import app; any "/deep-analysis/analytics" in routes`).
- [ ] **Step 2~5:** 핸들러(deep_research_handlers 패턴) + 라우터 위임 + main.py 등록(`_include_router_for_runtime(deep_analysis_analytics_router, prefix=settings.API_V1_PREFIX, tags=["Deep Analysis Analytics"])`) → 통과 → 커밋.

```bash
git commit -m "feat(deep-analysis): add /api/v1/deep-analysis/analytics endpoint"
```

---

### Task 4: Celery-Beat 주기 개선 리포트

**Files:**
- Create: `neos/tasks/deep_analysis_report_task.py`
- Modify: `neos/workflow/celery_app.py` (beat_schedule)
- Test: `tests/workflow/deep_analysis/test_deep_analysis_report_task.py`

**Interfaces:**
- Produces: Celery 태스크 `compute_deep_analysis_improvement_report()` — 롤링 윈도우(예: 최근 7일) `DeepAnalysisAnalyticsService.summary` 계산 → `deep_analysis_reports` INSERT + 로그. beat_schedule에 `compute-deep-analysis-report`(예: 매일 1회) 추가(`poll-scheduled-tasks` 패턴).

- [ ] **Step 1: 실패 테스트** — 시드 이벤트 → 태스크 실행(async 코어 함수 직접 호출) → `deep_analysis_reports` 행 1개 생성 + signals 포함.
- [ ] **Step 2~5:** 태스크(async 코어 `_compute_report(session)` + Celery 래퍼) + beat 항목 → 통과 → 커밋.

```bash
git commit -m "feat(deep-analysis): add daily Celery improvement-report task"
```

---

### Task 5: Golden 회귀 게이트 + 문서 + DECISIONS D19 + 회귀

**Files:**
- Modify/Create: `tests/workflow/deep_analysis/test_golden_gate.py` (기존 golden_integration 공식화)
- Modify: `neos/workflow/deep_analysis/DECISIONS.md` (D19)
- Create: `docs/deep_analysis_l5.md` (L5 운영 문서 — 신호 정의, 게이트 사용법)

**내용:**
- **Golden 게이트:** 기존 `test_golden_integration`(cassette 재생)을 프롬프트 변경 회귀 게이트로 공식화. 고정 golden 질문의 verified-claim 수 / citation 구조 스냅샷을 assert. 프롬프트 파일 `<!-- version -->` 변경 시 이 테스트가 회귀를 잡는다. (cassette가 없으면 기존 test_golden_integration을 참조해 스냅샷 assert 추가.)
- **D19:** L5는 관측/신호 + golden 게이트만. auto-mutation 없음. 근거: 자가 수정은 가드레일 필요, 범위 밖.
- **문서:** 각 신호의 정의/해석, 엔드포인트/리포트 사용법, golden 게이트 실행법.
- 전체 회귀: `.venv/bin/python -m pytest tests/workflow/deep_analysis/ -q` green.

- [ ] Steps: golden 스냅샷 assert → 통과 → 문서 + D19 → 회귀 → 커밋.

```bash
git commit -m "feat(deep-analysis): formalize golden regression gate; L5 docs + D19 (L5 complete)"
```

**완료 게이트:** Task 1–5 통과 = events에서 개선 신호 산출(API + 주기 리포트) + 프롬프트 변경 golden 회귀 게이트, auto-mutation 없음.

---

## 자체 리뷰 (스펙 대비)
- **B.1 AnalyticsService** → Task 1. **B.2 golden 게이트** → Task 5. **B.3 API** → Task 3. **B.4 마이그레이션+Celery** → Task 2+4. **B.5 테스트/문서** → 전반 + Task 5. **B.6 D19** → Task 5.
- **플레이스홀더:** 없음. golden 게이트는 기존 test_golden_integration/cassette 존재 여부에 따라 스냅샷 assert를 추가하라고 명시.
- **타입 일관성:** `DeepAnalysisAnalyticsService(session).signals()/summary()`, `DAReport`, `compute_deep_analysis_improvement_report()`, 엔드포인트 period→since — 일치.
- **불변식:** events read-only(리포트는 별도 테이블), auto-mutation 없음 — Global Constraints 명시.
