# Deep Analysis 작업 재개 문서

**작성일:** 2026-07-25 (갱신: 2026-07-26)
**작업 위치:** `dev` 브랜치. entailment 평가 worktree는 병합 후 제거됨 (§6 절차 준수)
**근거:** `docs/superpowers/plans/*deep-analysis*`, `docs/superpowers/specs/*deep-analysis*`,
`neos/workflow/deep_analysis/DECISIONS.md` (D1–D23), git 커밋 이력, `.superpowers/sdd/` 원장

> ⚠️ **플랜 문서의 체크박스는 신뢰하지 말 것.** 43개 플랜 전부 `- [x]`가 0개다.
> 실제 진행 상황은 (1) git 커밋 메시지, (2) `.superpowers/sdd/<plan>/progress.md` 원장,
> (3) `DECISIONS.md`의 D 번호에만 기록되어 있다.

---

## 1. 한눈에 보는 현재 상태

deep_analysis 하네스는 **M0–M4 코어 → 챗 편입 → durable job 서비스 → 신뢰도 개선 루프**
순서로 진화했고, entailment 실측 평가까지 종료했다. 현재 프론티어는
**entailment discard의 claim recall 손실 측정**이다 (§5).

> 갱신: 2026-07-26.

| 단계 | 상태 | 비고 |
|---|---|---|
| M0–M4 하네스 코어 | ✅ 완료 | Ledger / Budgeter / Grader / Cassette / Synthesizer |
| A. 프로덕션 챗 경로 편입 | ✅ 완료 → ⚠️ **대체됨** | D18 → **D23으로 대체** (아래 §3 필독) |
| B. L5 개선 루프 | ✅ 완료 | analytics + API + Celery beat + golden gate (D19) |
| durable job 서비스 | ✅ 완료 | D22 (제출·스트림·resume), D23 (챗=job 제출자) |
| 엔진 라우팅 재배치 | ✅ 완료 | D21 — 복잡도 임계값 → **질의 유형**으로 전환 |
| 운영 안정화 7종 | ✅ 완료 | 토큰 캡 / 브로커 / PDF / 영속화 / NUL / CI / 플래그 |
| verified claim funnel 진단 | ✅ 완료 | 퍼널 아티팩트 + 프로덕션 샘플링 |
| claim grounding (prompt v3) | ✅ 완료 | 2026-07-23 |
| claim entailment | ✅ 완료 (dev 병합) | `7c561d99` 머지 |
| entailment 실측 평가 | ✅ 완료 | `bc4e0656` — Task 1·2 + 최종 리뷰 종료 (§4) |
| claim recall 손실 측정 | 🟡 측정됨, 미결 | 2026-07-29 run: entailment 19회 호출, discard 0건 → `inconclusive` (§5) |

**기본 플래그:** `deep_analysis.enabled = False` (프로덕션 기본값에서 비활성).
`neos/config/schema.py:616`.

---

## 2. 완료된 작업 계보

### 2.1 하네스 코어 (M0–M4) — 2026-07-09 ~ 07-10

| 플랜 | 결과 |
|---|---|
| `2026-07-09-deep-analysis-harness-m0-m1.md` | Ledger, run 스코프, 단일 작성자(P2) |
| `2026-07-09-deep-analysis-harness-m2.md` | Budgeter, 라운드 루프 |
| `2026-07-10-deep-analysis-harness-m3.md` | 계층 리듀스 (D17: 순차 후위 순회) |
| `2026-07-10-deep-analysis-harness-m4.md` | 충돌 재조사, 인용, 통합 AC |

스펙: `docs/superpowers/specs/2026-07-09-deep-analysis-harness-design.md`.
설계 원본: `docs/DEEP_ANALYSIS_HARNESS_DESIGN.md`.
완료 시점 147 tests green (스펙 전제 기준).

핵심 불변식 (이후 모든 작업이 지켜야 함):
- P2 단일 작성자 + run 스코프
- judge ≠ worker (동일 모델 금지)
- `deep_analysis_events`는 **append-only** (D8, §11.3)
- 매직넘버 금지 — 전부 settings
- 테스트에서 실 LLM/네트워크 금지 (cassette 재생 또는 fake 주입)

### 2.2 Sub-project A — 프로덕션 챗 경로 전환

**플랜:** `docs/superpowers/plans/2026-07-11-deep-analysis-chatswap.md` (4 tasks)
**스펙:** `docs/superpowers/specs/2026-07-11-deep-analysis-chatswap-and-l5-design.md`

계획대로 완료되었으나 **이후 설계가 두 번 바뀌었다.** 아래 §3에서 상세히 다룬다.

| 플랜이 명세한 것 | 현재 코드 |
|---|---|
| `WorkflowNode.DEEP_ANALYSIS_ORCHESTRATOR` | ❌ 없음 → `DEEP_ANALYSIS_DISPATCH` (`enums.py:37`) |
| `_deep_analysis_orchestrator_node` (노드가 직접 완주) | ❌ → `_deep_analysis_dispatch_node` (`graph.py:1051`) — job 제출만 |
| `DEEP_ANALYSIS_ORCHESTRATOR → RESULT_INTEGRATOR` 엣지 | ❌ → `DEEP_ANALYSIS_DISPATCH → END` (`graph.py:442`) |
| 복잡도 임계값 기반 라우팅 | ❌ → 질의 유형 기반 (D21, `orchestrator_router.py:97~108`) |
| `IntentType.DEEP_ANALYSIS` | ✅ 유지 (`enums.py:86`) |
| `DEEP_ANALYSIS_ENABLED` 플래그 게이팅 | ✅ 유지 |
| 무회귀 테스트 | ✅ `tests/workflow/routing/test_deep_analysis_routing.py`, `tests/workflow/test_deep_analysis_node.py` |

### 2.3 Sub-project B — L5 개선 루프 ✅ 전량 완료

**플랜:** `docs/superpowers/plans/2026-07-11-deep-analysis-l5.md` (5 tasks)

5개 태스크 산출물이 전부 존재한다:

| Task | 산출물 | 확인 |
|---|---|---|
| 1. AnalyticsService | `neos/workflow/deep_analysis/analytics.py` | ✅ |
| 2. 리포트 테이블 + ORM | `db/migrations/037_add_deep_analysis_reports.sql`, `deep_analysis_models.py:214` | ✅ |
| 3. Analytics API | `neos/api/deep_analysis_analytics_routes.py`, `handlers/deep_analysis_analytics_handlers.py` | ✅ |
| 4. Celery-Beat 리포트 | `neos/tasks/deep_analysis_report_task.py`, `celery_app.py:194` (`compute-deep-analysis-report`, 매일 1회) | ✅ |
| 5. Golden 게이트 + 문서 + D19 | `tests/workflow/deep_analysis/test_golden_gate.py`, `docs/deep_analysis_l5.md`, `DECISIONS.md:393` | ✅ |

**D19 결정 유지:** L5는 관측/신호 + golden 게이트만. **auto-mutation 없음** (신호는 사람 검토용).

후속 수정: `fix: isolate deep analysis analytics by run` (2026-07-19) — 전역 집계가 run 스코프를
침범하던 문제. 단, `docs/TODO_260729.md` §11에 "analytics 테스트가 run 스코프 없이 전역 집계를
검증한다"가 **미해결 CI 선결 과제**로 남아 있다.

### 2.4 durable job 서비스 전환 (D22 / D23) — 2026-07-18 ~ 07-19

| 플랜 | 내용 |
|---|---|
| `2026-07-18-deep-analysis-job-service.md` | D22 — 제출·스트림·resume. D7의 "나중"이 도래 |
| `2026-07-18-engine-reassignment.md` | D21 — deep 엔진 라우팅을 복잡도 → 질의 유형으로 |
| `2026-07-19-deep-analysis-chat-job-integration.md` | D23 — **챗은 job의 제출자다. D18을 대체** |
| `2026-07-17-deep-analysis-skill-discovery.md` | 스킬 발견 통합 (phase 1) — `test_discovery.py`, `test_worker_discovery.py` |

### 2.5 운영 안정화 7종 — 2026-07-19 ~ 07-21

| 플랜 | 해결한 문제 |
|---|---|
| `2026-07-19-deep-analysis-failure-bounds.md` | 토큰을 쓰지 않는 워커 실패의 무한 루프 (TODO P0 #1) |
| `2026-07-19-deep-analysis-hard-token-cap.md` | run 간 토큰 캡 초과 — 원자적 예산 코어 + LLM 경계 예약 |
| `2026-07-19-deep-analysis-broker-dispatch-failure.md` | Celery 브로커 장애 시 명시적 실패 + 기록 |
| `2026-07-19-deep-analysis-pdf-and-test-stability.md` | `fetch.py` HTML 전용 → PDF 텍스트 추출 |
| `2026-07-19-deep-analysis-persistence-boundary.md` | 리포트 영속화 실패 경계 |
| `2026-07-19-yaml-only-feature-flag-warnings.md` | 환경변수로 못 켜는 플래그 조용한 무시 (TODO P0 #2) |
| `2026-07-19-backend-ci-isolation.md` | CI 부재 (TODO P0 #3) — 격리 백엔드 워크플로 추가 |
| `2026-07-21-deep-analysis-nul-normalization.md` | fetch 증거의 NUL 바이트 제거 |

### 2.6 verified claim 비율 개선 루프 — 2026-07-19 ~ 07-25

`docs/TODO_260729.md` §7 "verified 클레임 비율이 낮다"를 해결하기 위한 연속 작업.
**측정 → 원인 분해 → 프롬프트/로직 수정 → 재측정**의 반복 구조다.

```
verified-claim-funnel (07-19)          퍼널 진단 계측 (결정론 / 에이전틱 / 등급 분할)
        ↓
production-claim-funnel-sample (07-19~21)  mixed-v1 5+1 실측 러너 + 아티팩트
        ↓
claim-scope-confidence-calibration (07-21) 클레임 confidence 클램프 + 프롬프트 보정
funnel-clamp-aggregation (07-21)           클램프 버킷 집계 보존
        ↓
claim-grounding (07-23)                프롬프트 v3 — 단일 기관 스코프 + 연속 축자 발췌
        ↓  [베이스라인: dev verified 19/38, rejected 19/38, overclaim 16, quote mismatch 1]
claim-entailment (07-25)               배치 함의/자가수정 호출 — 채택·축소·폐기
        ↓
entailment-evaluation (07-25~26)       ✅ 완료 — `bc4e0656`
        ↓
claim recall 손실 측정                  ← ⬜ 다음 (§5)
```

**최신 완료:** `2026-07-25-deep-analysis-claim-entailment.md` (4 tasks) — `7c561d99`로 dev 병합.
- Task 1: 순수 원자 함의 결과 적용
- Task 2: 버전 프롬프트 + 워커 통합
- Task 3: golden 프롬프트 변경 통제 + 리플레이
- Task 4: 전체 회귀 + 평가 인계

---

## 3. ⚠️ 재개 전 필독 — chatswap 플랜은 이미 낡았다

`docs/superpowers/plans/2026-07-11-deep-analysis-chatswap.md`와
`docs/superpowers/plans/2026-07-11-deep-analysis-l5.md`는 **untracked 상태로 남아 있는
2026-07-11 시점 문서**다. L5는 그대로 유효하지만, **chatswap은 D21/D22/D23이 그 위를
세 번 덮어썼다.**

```
D18 (07-11)  하네스가 단일 workflow 노드로 완주, RESULT_INTEGRATOR로 합류
   ↓
D21 (07-18)  라우팅을 복잡도 임계값이 아니라 질의 유형으로 가른다 (D18 선결 조건 #3 해소)
   ↓
D22 (07-18)  durable job 서비스로 전환 — 제출·스트림·resume
   ↓
D23 (07-19)  챗은 job의 "제출자"다 — 노드 제거·핸들 이벤트·리포트 영속화. **D18을 대체한다**
```

즉 현재 챗 노드는 하네스를 **직접 실행하지 않는다.** `_deep_analysis_dispatch_node`가
`create_run()`으로 run_id를 만들고 `submit_deep_analysis_job()`으로 Celery에 넘긴 뒤
`END`로 빠진다 (`graph.py:1051–1122`). 실행자 계층은
`neos/tasks/deep_analysis_job_task.py`이고, 진행 상황은 `on_deep_analysis_started`
핸들 이벤트로 전달된다.

**행동 지침:** chatswap 플랜을 재실행하지 말 것. 참조가 필요하면 `DECISIONS.md`의
D18 → D21 → D22 → D23 순으로 읽는 편이 정확하다.

---

## 4. ✅ 완료된 작업 — entailment 실측 평가 (2026-07-26 종료)

**병합:** `ad19cf26` (merge) ← `bc4e0656`. worktree·브랜치 모두 제거 완료.
**플랜:** `docs/superpowers/plans/2026-07-25-deep-analysis-entailment-evaluation.md` (2 tasks, 커밋됨)
**증거 보존:** 아티팩트와 SDD 원장은 main 체크아웃으로 복사 (체크섬 검증, §6)

### 목표

claim entailment 도입 후 `mixed-v1` 5+1 프로덕션 유사 샘플을 **정확히 한 번** 실행하고,
prompt-v3 베이스라인과 비교한 뒤 **인과적 과대해석 없이** 결과를 문서화한다.

### 진행 상황

| Task | 상태 |
|---|---|
| Task 1: 한정 `mixed-v1` 5+1 샘플 실행·검증 | ✅ 완료 (증거 한계 명시) |
| Task 2: 퍼널 비교 + 평가 경계 문서화 | ✅ 완료 — `docs/TODO_260729.md` 갱신 |
| 최종 리뷰 | ✅ 완료 — "With fixes", Critical 0건, 지적 10건 전량 반영 |

**커밋:** `bc4e0656` (브랜치 `codex/deep-analysis-entailment-eval`, dev 미병합).
문서 2개만 변경 — `docs/TODO_260729.md`와 플랜 파일. 아티팩트·정책 코드 무변경.
`.superpowers/sdd/.../progress.md` 원장도 동기화 완료.

**샘플 재실행 없음.** Task 1 리뷰의 "Needs fixes"는 전부 *기록* 수정으로 해소했다
(스키마 스니펫 정정, 증거 한계 명문화). 아티팩트는 재생성하지 않았다.

### 실측 결과 (아티팩트 `artifacts/deep-analysis-funnel/20260725T081707Z`)

6개 run 전부 `completed`, 프로파일 순서 `dev×5 + default×1`:

| # | case_id | profile | run_id | tokens | elapsed(s) |
|---:|---|---|---|---:|---:|
| 1 | fact-eu-ai-act | dev | 4ee86228 | 11,264 | 186.65 |
| 2 | fact-aspartame | dev | 706c3402 | 8,565 | 239.99 |
| 3 | tech-hybrid-search | dev | 66dd80ca | 6,788 | 170.53 |
| 4 | tech-free-threading | dev | d32d61d7 | 7,687 | 261.78 |
| 5 | policy-london-ulez | dev | be539372 | 13,188 | 264.49 |
| 6 | policy-london-ulez | default | ddf7dfdf | 240,242 | 792.99 |

- dev 토큰 합 47,492 / default 240,242 / 총 287,734
- 총 경과 1,916.43초
- 구조·매핑·회계 검증 전부 통과, `credential_present=false`
- dev 클램프 버킷 합 7 = `confidence_clamped_count`, default 2 = 2

**비교 대상 베이스라인** (`docs/TODO_260729.md` 및 아티팩트
`artifacts/deep-analysis-funnel/20260723T124006Z`): dev verified `19/38`, rejected `19/38`,
overclaim `16`, quote mismatch `1`.

### 측정 결과 요약 (2026-07-26 확정)

| 지표 | prompt v3 | entailment | 판정 |
|---|---:|---:|---|
| verified 비율 | 19/38 (50.0%) | 14/22 (63.6%) | ⚠️ Fisher p≈0.42 — **노이즈와 구별 불가** |
| graded (분모) | 38 | 22 | **-42.1%** |
| verified 절대수 | 19 | 14 | **-26.3%** |
| overclaim | 16 (거부의 84.2%) | 7 (거부의 87.5%) | p=1.00 — 점유율 변화 없음 |
| confidence clamp | 2/38 (5.3%) | 7/22 (31.8%) | ✅ p≈0.009 — **유일한 유의 변화** |
| dev tokens | 51,134 | 47,492 | -7.1% |

**핵심:** 비율은 올랐지만 claim pool이 더 크게 줄었다. 두 비율은 서로 다른 모집단에서
계산된 값이고, 5+1 단일 관측이라 인과 확정 불가다. 지배 손실 단계 라벨 변화
(`final_unresolved`→`agentic_loss`)는 **동수(8 vs 8) tie-break 산물**이므로 파이프라인
이동으로 읽으면 안 된다.

> **다음 작업은 §5**(entailment discard의 claim recall 손실 측정)로 이어진다.

### 📌 참고 — Task 1 리뷰 지적사항 (전량 해소됨)

리뷰 판정: **"Needs fixes (evidence/specification); artifact usable with stated limits"**
(Critical 없음. **아티팩트 자체는 유효하며 재실행으로 "고치면 안 된다."**)

1. **스키마 불일치** — 아티팩트는 현행 스키마(`confidence_clamped_by_source_count` +
   `confidence_clamped_count`)를 쓰는데, 브리프는 레거시 필드
   (`safe_confidence_clamp.buckets/total`)를 요구한다. 퍼널 레벨 `tokens_spent` 집계도 없다.
   → 의미적 등가물로 검증했으므로 **브리프의 리터럴 필드 assert는 적용 불가**로 기록.
2. **실행 증거 소실** — 원 실행 세션(PID 86909)의 exit code를 복구할 수 없어 `unavailable`.
   초기 에이전트가 하네스의 60초 yield를 프로세스 완료로 오인했으나, 러너는 계속 돌아
   아티팩트를 산출했다. **완료된 내부 정합 아티팩트가 성공 증거**다.
3. **비차단 심층방어 관찰** — 직렬화는 구조적 allowlist로 보호되지만 `secrets` 인자는 버려지고
   allowlist 통과 자유형 문자열은 실 크리덴셜과 독립 검증되지 않는다. 이번 아티팩트에서는
   누출 없음이 확인되었다(`secret-debug-report.md` 참조). Task 1 결과와는 별개 사안.

> 참고: 초기 크리덴셜 양성 반응은 **빈 needle 오탐**이었다. config 로더가 dotenv 값을
> `os.environ`에 넣지 않고 effective settings로만 공급하기 때문에, 부재한 프로세스 변수가
> `""`로 기본값 처리되어 모든 문자열에 매칭된 것. 실제 누출 아님.

### 재개 절차

```bash
cd /Users/ywsung/Desktop/neos/.worktrees/deep-analysis-entailment-eval

# 1) 결정론 베이스라인 (실 LLM 없음)
HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/pytest \
  tests/workflow/deep_analysis/test_funnel_sample.py \
  tests/workflow/deep_analysis/test_funnel_sample_runner.py \
  tests/workflow/deep_analysis/test_funnel_sample_runner_integration.py \
  -q -o log_cli=false --disable-warnings
```

**이 절차는 2026-07-26에 완료되었다.** 위 명령은 회귀 확인용으로만 남긴다
(29 passed / 전체 deep_analysis 344 passed, Ruff 통과).

⚠️ **reject code는 아티팩트에 없다.** `_safe_funnel`이 숫자 필드 allowlist만
직렬화하므로 `funnel.json`에 `rejection_reasons`류 필드가 존재하지 않는다.
append-only `deep_analysis_events`의 `kind='claim_rejected'` 행을 run ID로
조회해야 한다 (`payload.code` 집계). 이 방법은 v3 기준선 수치를 정확히 재현해
검증했다.

### 절대 하지 말 것 (플랜 Global Constraints)

- ❌ 라이브 샘플 **재실행** (정확히 1회 원칙, 실패해도 자동 재시도 금지)
- ❌ grader 임계값 / 샘플링 / discovery 폭 / 프롬프트 / 모델 / 토큰 한도 / 워커·깊이·
  벽시계 한도 / repair·entailment 동작 **변경**
- ❌ 아티팩트 커밋 (`artifacts/deep-analysis-funnel/` 는 gitignore 대상)
- ❌ 크리덴셜 값 출력·영속화 (boolean 유무만 확인)
- ❌ 5+1 단일 관측으로 **인과 주장**하기 — provider/검색결과/시각/질의선택 변동성 명시 필수

---

## 5. 🟡 측정 완료, 결론 미결 — entailment discard의 claim recall 손실

**상태:** 계측 구현 완료(`4e81d92f..901cf913`), 측정 run 1회 완료
(`20260729T131543Z`, 6/6 completed). **판정 `inconclusive`** — entailment가
19회 호출됐으나 discard가 0건이라 측정할 대상이 없었다. 계측은 정상
동작했다(fail-open 경고 0건). 상세는 `docs/TODO_260729.md` 참고.

⚠️ 이 표본은 dev claim이 4건뿐(v3 38건, entailment 22건)이고 dead_end가
90건이라 이전 표본과 비교 불가다. **다음은 claim 생산량이 정상인 표본에서
재측정**이며, dead_end 90건의 원인 규명이 선결 과제일 수 있다.

플랜: `docs/superpowers/plans/2026-07-28-deep-analysis-discard-recall-measurement.md`

### 왜 이것이 1순위인가

entailment 평가에서 verified 비율은 50.0%→63.6%로 올랐지만 **Fisher p≈0.42로
표본오차와 구별되지 않는다.** 반면 claim pool 축소(graded -42.1%, verified 절대수
-26.3%)는 크고 명확하다. discard된 claim 중 **evidence가 실제로 지지하던 비율**을
모르면, 비율 개선이 recall을 팔아서 산 것인지 판별할 수 없다. 이걸 모르는 상태에서
threshold·prompt·model을 건드리면 잘못된 방향으로 최적화된다.

### 측정 설계 스케치

1. **계측 추가** — worker의 batch entailment 호출에서 claim 단위 결정
   (`keep` / `narrow` / `discard`)과 그 근거를 이벤트로 남긴다.
   기존 이벤트는 append-only이므로 새 kind를 추가하는 방향
   (`neos/workflow/deep_analysis/DECISIONS.md` D8 §11.3 준수).
2. **discard 표본 추출** — 기존 `mixed-v1` 질의로 discard된 claim을 덤프한다.
   ⚠️ 이 목적으로 `20260725T081707Z` 표본을 **재실행하지 말 것**. 새 run을 별도
   실행하거나 cassette 재생을 쓴다.
3. **사람 판정** — discard된 claim 각각에 대해 "evidence가 실제로 지지했는가"를
   수동 라벨링한다. 이것이 recall 손실의 분모다.
4. **판정 기준** — false-discard 비율이 유의하게 높으면 entailment는 recall을
   희생해 정밀도를 올린 것이므로 narrow 쪽으로 완화한다. 낮으면 verified 비율
   개선이 실질적이라는 근거가 된다.

### 2순위 — 잔존 overclaim 원인 분해

overclaim은 두 표본 모두에서 거부 코드의 대부분이다(v3 16/19, entailment 7/8).
점유율 84.2%→87.5% 변화는 **p=1.00으로 신호가 아니므로 근거로 쓰지 말 것.**
근거는 절대적 지배력이다.

### 3순위 — 계측 부채 (이번 평가에서 도출)

live 표본 실행 시 `manifest.json`에 함께 남길 것:

- **실행 영수증:** PID, UTC start/end, exit status, 명령 동일성,
  test/Ruff/preflight 통과 boolean
- **구성 지문:** model ID, grader threshold, token/worker/depth/wall-clock cap

근거: `20260725T081707Z`는 exit code와 wall time이 복구 불가였고(→ `unavailable`),
구성 불변을 사후 증명할 지문이 없어 "저장소 상태로만 뒷받침됨"으로 기록해야 했다.

---

## 6. ⚠️ 운영 주의 — worktree 정리는 gitignore 증거를 파괴한다

**2026-07-26에 실제로 겪은 위험.** `git worktree remove`는 gitignore 대상 파일을
경고 없이 함께 삭제한다. deep-analysis 작업에서 이는 치명적이다:

| 위험 대상 | 이유 |
|---|---|
| `artifacts/deep-analysis-funnel/<ts>/` | **재생성 불가** — 플랜의 "정확히 1회" 원칙 |
| `.superpowers/sdd/<plan>/` | task brief·report·review·progress 원장 전체 |

`docs/TODO_260729.md`에 기록된 수치의 **유일한 근거가 아티팩트**인데, 아티팩트는
worktree 안에만 있고 gitignore 대상이라 커밋되지 않는다. worktree를 지우면 커밋된
문서가 존재하지 않는 경로를 인용하게 된다.

**정리 전 필수 절차:**

```bash
WT=.worktrees/<name>
# 1) main 체크아웃에 없는 gitignore 증거 확인
diff <(ls "$WT/artifacts/deep-analysis-funnel" 2>/dev/null) \
     <(ls artifacts/deep-analysis-funnel 2>/dev/null)
ls "$WT/.superpowers/sdd"

# 2) 고유한 것만 복사 후 체크섬 검증
cp -R "$WT/artifacts/deep-analysis-funnel/<ts>" artifacts/deep-analysis-funnel/
(cd "$WT/artifacts/deep-analysis-funnel/<ts>" && shasum -a 256 *) > /tmp/src.sha
(cd artifacts/deep-analysis-funnel/<ts> && shasum -a 256 -c /tmp/src.sha)

# 3) 미커밋 변경·미병합 커밋 확인
git -C "$WT" status --short
git -C "$WT" log --oneline dev..HEAD

# 4) 위 전부 통과해야 제거
git worktree remove "$WT" && git worktree prune
```

`20260725T081707Z` 아티팩트와 `2026-07-25-deep-analysis-entailment-evaluation`
SDD 원장은 이 절차로 main 체크아웃에 보존했다(체크섬 일치 확인 완료).

---

## 7. 미해결 백로그 (`docs/TODO_260729.md`)

| 우선순위 | 항목 |
|---|---|
| 🧪 CI 선결 #9 | `pytest tests/workflow/` 단일 실행이 수집 단계에서 실패 |
| 🧪 CI 선결 #10 | `tests/api/`에 순서 의존 오염 |
| 🧪 CI 선결 #11 | analytics 테스트가 run 스코프 없이 전역 집계 검증 |
| 🟡 P1 #7 | verified 클레임 비율 — **entailment 평가 완료**, recall 측정으로 이어짐 (§5) |
| 🟡 P1 #8 | `_persist_assistant_message`가 예외를 삼킴 |

---

## 8. 참조

- 평가 증거: `artifacts/deep-analysis-funnel/20260725T081707Z` (gitignore, 재생성 불가),
  `.superpowers/sdd/2026-07-25-deep-analysis-entailment-evaluation/` (task 원장)
- 결정 원장: `neos/workflow/deep_analysis/DECISIONS.md` (D1–D23)
- L5 운영 문서: `docs/deep_analysis_l5.md`
- 백로그: `docs/TODO_260729.md`
- 로드맵: `docs/ROADMAP.md`
- 관련 문서: [role_based_model_routing_task_resume.md](role_based_model_routing_task_resume.md),
  [coding_agent_task_resume.md](coding_agent_task_resume.md)

**테스트 명령:** `.venv/bin/python -m pytest` (bare `pytest`는 asyncio 마커 수집 실패)
