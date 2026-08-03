# 심층 분석 하네스 — 프로덕션 챗 경로 전환(A) + L5 개선 루프(B) 설계 스펙

**작성일:** 2026-07-11
**상태:** 사용자 승인 완료 (2026-07-11)
**전제:** M0–M4 하네스 완성(147 tests green). 원 설계 [docs/DEEP_ANALYSIS_HARNESS_DESIGN.md](../../DEEP_ANALYSIS_HARNESS_DESIGN.md), DECISIONS [neos/workflow/deep_analysis/DECISIONS.md](../../../neos/workflow/deep_analysis/DECISIONS.md).

두 개의 독립 서브프로젝트. A를 먼저(프로덕션 대면), 그 다음 B. 각자 별도 플랜 → subagent-driven 실행.

---

## 사용자 승인 결정
- **A 라우팅:** flag-gated + auto-route. `DEEP_ANALYSIS_ENABLED`(기본 false)로 게이팅, 활성 시 deep/analytical 쿼리를 하네스 노드로 auto-route. 활성 시 hyper_deep/recursive보다 **우선**(점진적 workflow 대체 경로).
- **A 실행 형태:** 하네스는 **단일 workflow 노드**로 완주(챗에는 노드 레벨 진행). 세밀한 per-claim 스트리밍은 기존 `/api/v1/deep-analysis` SSE 엔드포인트가 담당.
- **B 범위:** analytics + 개선 신호 + golden 회귀 게이트. **auto-mutation 없음**(신호는 사람 검토용).
- **B 전달:** analytics API 엔드포인트 + Celery-Beat 주기 리포트(+ 소형 리포트 테이블 1개).

---

## 서브프로젝트 A — 프로덕션 챗 경로 → 하네스

### A.1 설정 / enum / intent
- `settings.DEEP_ANALYSIS_ENABLED: bool = False`, `DEEP_ANALYSIS_COMPLEXITY_THRESHOLD: float`(기본 0.5 근방; RECURSIVE/HYPER_DEEP와 유사). `schema.py`의 `DeepAnalysisConfig`에 `enabled`(이미 있음) 활용 + threshold 추가, `settings.DEEP_ANALYSIS_ENABLED` 별칭 확인.
- `WorkflowNode.DEEP_ANALYSIS_ORCHESTRATOR` 추가(`enums.py`).
- (선택) `IntentType.DEEP_ANALYSIS` 추가 — 명시적 intent도 라우팅 대상. 없으면 DEEP_RESEARCH/COMPLEX_ANALYSIS + 복잡도로만.

### A.2 라우팅 (`OrchestratorRouter.route`)
`route()`에서 hyper_deep/recursive 분기 **앞에** deep_analysis 분기 삽입:
```
if settings.DEEP_ANALYSIS_ENABLED and policy.allows_recursive_research():
    if intent == IntentType.DEEP_ANALYSIS.value:  # (intent 추가 시)
        return "deep_analysis"
    da_intents = (DEEP_RESEARCH, COMPLEX_ANALYSIS)
    if complexity >= settings.DEEP_ANALYSIS_COMPLEXITY_THRESHOLD and intent in da_intents:
        return "deep_analysis"
```
활성 시 동일 intent에서 hyper_deep/recursive보다 우선. 비활성이면 기존 동작 그대로(무회귀).

### A.3 그래프 노드 (`graph.py`)
- `DEEP_ANALYSIS_ENABLED`일 때만 노드 등록(recursive 노드 조건부 등록 패턴 미러링).
- 라우팅 맵 `["deep_analysis"] = WorkflowNode.DEEP_ANALYSIS_ORCHESTRATOR.value`.
- 엣지 `DEEP_ANALYSIS_ORCHESTRATOR → RESULT_INTEGRATOR`(정상 파이프라인 합류).
- `_deep_analysis_orchestrator_node(state) -> Dict[str, Any]`:
  - `async with await db_manager.get_session() as s:`
  - `run_id = await create_run(s, query, profile)`; `await s.commit()`
  - `orch = await build_orchestrator(s, run_id, event_sink=<노드 진행 이벤트로 매핑>)`
  - `result = await orch.run(query)`; `await s.commit()`
  - return `{...: result["report_markdown"], "deep_analysis_run_id": run_id}` — recursive 오케스트레이터 `execute()`가 쓰는 state 필드와 동일 매핑(RESULT_INTEGRATOR가 그대로 소비). query는 `state.refined_query or original_query`, profile은 설정.
  - 초기화 미완/예외 시 recursive 노드처럼 `{"final_response": <오류>}` graceful.
- `graph.py` 초기화에 `deep_analysis` 활성 여부 저장(노드 조건부 등록용).

### A.4 DECISIONS (신규 D18)
하네스가 단일 workflow 노드로 완주(챗 노드 레벨 진행). per-claim SSE는 전용 엔드포인트. 근거: 기존 챗 스트리밍/대화 플럼빙 재사용 + 최소 침습. workflow 대체는 점진적.

### A.5 테스트
- 라우팅 단위: DEEP_ANALYSIS_ENABLED on/off × intent/complexity → "deep_analysis" vs 기존. off면 무회귀.
- 노드 계약: FakeWorker+fake 하네스로 `_deep_analysis_orchestrator_node`가 report를 올바른 state 필드에 매핑(실 LLM 없음, 하네스 주입).
- 스모크: DEEP_ANALYSIS_ENABLED로 그래프 빌드 시 노드/엣지 등록 확인.

---

## 서브프로젝트 B — L5 개선 루프

### B.1 AnalyticsService
`neos/workflow/deep_analysis/analytics.py`(또는 `neos/database/`): `DeepAnalysisAnalyticsService(session)` — `deep_analysis_events`(+ claims/feedback) 집계. 신호(현행 이벤트에서 파생 가능):
- **reject rate by code:** `claim_rejected` 이벤트/feedback code별 비율.
- **overclaim frequency:** `E_OVERCLAIM` + `E_CONFIDENCE_INFLATED` 비율.
- **dead-end rate:** `dead_end` 이벤트 / 질문 수.
- **conflict / reinvestigation rate:** `conflict_found`(있으면) + `conflict_reinvestigation` / `question_reopened` 이벤트.
- **retry-cap-exhaustion (unverified) rate:** `claim_unverified` / 총 클레임.
- **verified-per-pass gain:** `pass_completed` payload의 `verified` 평균.
- **report-assembly-retry rate:** `report_graded` ok=false attempt 분포.
- `get_summary(period)` 롤업(WebSearchAnalyticsService.get_analytics_summary 패턴).
- period 파라미터(일/주/월), run 스코프 아닌 **전역 집계**(여러 run).

### B.2 Golden 회귀 게이트
기존 `test_golden_integration`(cassette)을 §10 프롬프트 변경 게이트로 공식화: 고정 golden 질문의 verified-claim/citation 구조 스냅샷. 프롬프트 파일 `<!-- version -->` 변경 시 이 테스트 통과 필수. 스냅샷 불일치 = 회귀 신호. (§6.4 overclaim 신호는 B.1 지표로 포착.)

### B.3 API 엔드포인트
`neos/api/deep_analysis_analytics_routes.py` → `handlers/deep_analysis_analytics_handlers.py`. `GET /api/v1/deep-analysis/analytics?period=week` → 신호 JSON. `main.py` 등록. 인증은 기존 패턴(`get_current_active_user`).

### B.4 Celery-Beat 주기 리포트 + 리포트 테이블
- 마이그레이션 `db/migrations/037_add_deep_analysis_reports.sql`: `deep_analysis_reports(id, period_start, period_end, signals JSONB, created_at)`.
- ORM 모델 `DAReport`.
- Celery 태스크 `compute_deep_analysis_improvement_report`(neos/tasks/ 또는 celery_tasks): 롤링 윈도우 신호 계산 → `deep_analysis_reports` INSERT + 로그.
- `celery_app.py` beat_schedule에 항목 추가(예: 매일; `poll-scheduled-tasks` 패턴).

### B.5 테스트 + 문서
- AnalyticsService 단위: 이벤트 시드 → 각 신호 정확 계산(no_db 아님, 실 세션 + rollback).
- 엔드포인트 스모크: 라우트 등록 + 인증.
- Celery 태스크: 시드 이벤트 → 리포트 행 생성.
- golden 스냅샷 게이트 동작.

### B.6 DECISIONS (신규 D19)
L5는 관측/신호 + golden 게이트만. auto-mutation 없음(사람 검토). 근거: 자가 수정은 가드레일 필요, 범위 밖.

---

## 불변식 (양 서브프로젝트)
- 하네스 코어(M0–M4) 동작/불변식 유지(P2 단일 작성자, run 스코프, judge≠worker). A/B는 그 위의 통합/관측 계층.
- DEEP_ANALYSIS_ENABLED=false에서 기존 챗 동작 **무회귀**(A).
- L5는 events append-only(§11.3, D8)에서 **읽기만**(B). 이벤트에 쓰지 않음(리포트는 별도 테이블).
- 매직넘버 금지(전부 settings). 테스트 실 LLM/네트워크 금지(fake 주입).

## 마일스톤/실행
- A: 4 태스크(설정/enum/intent → 라우터 분기 → 그래프 노드 → 테스트). subagent-driven.
- B: 5 태스크(analytics → golden 게이트 → API → 마이그레이션+Celery → 테스트/문서). subagent-driven.
- 각 태스크 TDD, `.venv/bin/python -m pytest`, 전체 회귀 green 유지.
