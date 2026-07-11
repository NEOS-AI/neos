# 심층 분석 하네스 — L5 개선 루프 운영 문서

L5는 하네스의 append-only 이벤트 로그(`deep_analysis_events`)를 **개선 신호**로 집계해
사람이 프롬프트·설정을 개선하도록 돕는 관측 계층이다. **자동 수정(auto-mutation)은 하지
않는다**([DECISIONS D19](../neos/workflow/deep_analysis/DECISIONS.md)).

관련 원 설계: P4(모든 것은 이벤트 로그를 통과), §6.4(과장 습관은 L5 신호), §10(golden 통합이
L5 최소 게이트).

## 1. 개선 신호 (DeepAnalysisAnalyticsService)

`neos/workflow/deep_analysis/analytics.py` — 이벤트 로그를 **전역(모든 run)** 집계. 읽기 전용.

| 신호 | 정의 | 해석 |
|---|---|---|
| `reject_rate_by_code` | 코드별 `claim_rejected` 비율 | 어떤 실패 모드가 지배적인가 (E_QUOTE_MISMATCH↑ → fetch/발췌 문제 등) |
| `overclaim_rate` | (E_OVERCLAIM + E_CONFIDENCE_INFLATED) / 전체 거절 | 워커가 근거보다 강하게 주장하는 습관(§6.4) — worker_brief 조정 신호 |
| `dead_end_rate` | `dead_end` / `question_opened` | 조사가 막다른 길에 자주 빠지면 분해/검색 품질 신호 |
| `unverified_rate` | `claim_unverified` / (verified+rejected+unverified) | 재시도 캡 소진 비율 — 수리 처방/재조사 효율 신호 |
| `reinvestigation_count` | `conflict_reinvestigation` 이벤트 수 | 충돌 재조사 발동 빈도 |
| `avg_verified_per_pass` | `pass_completed.verified` 평균 | 패스당 산출 효율(예산 사다리 gain과 연동) |
| `report_retry_rate` | 실패한 `report_graded` / 전체 | 조립/인용 품질 — final_compose·citation 신호 |
| `totals` | kind별 이벤트 카운트 | 볼륨/분포 스냅샷 |

- 잘못된 JSON payload는 kind별 `totals`(분모)에는 계수되나 수치 집계(평균/코드 비율)를 오염시키지 않는다.
- 분모 0이면 0.0.

## 2. On-demand API

```
GET /api/v1/deep-analysis/analytics?period=week   # period: day | week | month | all
```
인증 필요(`get_current_active_user`). 반환: `{"period", "signals": {...}, "since", "generated_at"}`.
`period`는 `since = now - N일`로 변환(all이면 전체).

## 3. 주기 리포트 (Celery-Beat)

- 태스크: `neos.tasks.compute_deep_analysis_report`(`compute_deep_analysis_improvement_report`).
- 스케줄: 매일 1회(`celery_app.py` beat_schedule `compute-deep-analysis-report`, 86400s).
- 최근 7일(`DEFAULT_WINDOW_DAYS`) 롤링 윈도우 신호를 계산해 `deep_analysis_reports`
  (마이그레이션 037)에 스냅샷 INSERT + 로그. 이벤트 로그에는 쓰지 않는다.
- 테스트 가능 코어: `_compute_report(session, *, window_days=7) -> DAReport`.

## 4. Golden 회귀 게이트 (프롬프트 변경 통제)

두 축:
1. **런타임 결정성:** `test_golden_integration`의 record→replay 테스트 —
   같은 입력이 동일 보고서로 재생(고아 인용 없음).
2. **변경 통제:** `test_golden_gate`의 프롬프트 버전 매니페스트 —
   각 프롬프트 `<!-- version: N -->`(§7.1)가 `EXPECTED_PROMPT_VERSIONS`와 일치해야 한다.
   프롬프트 내용을 바꿔 버전을 올리면 이 테스트가 깨진다 → **의도적 체크포인트**:
   매니페스트 갱신 + golden 재녹화 + 개선 신호 검토를 강제한다.

프롬프트를 바꿀 때:
1. 프롬프트 내용 수정 + `<!-- version -->` 증가(§7.1).
2. `EXPECTED_PROMPT_VERSIONS` 갱신.
3. golden replay 재녹화(`test_golden_integration`).
4. `/analytics` 신호로 회귀(overclaim_rate 급증 등) 확인 후 머지.

## 5. 무엇을 하지 않는가 (D19)
- 신호로부터 프롬프트/설정을 자동 조정하지 않는다.
- 이벤트 로그를 수정하지 않는다(read-only, §11.3/D8).
- 자가 수정 루프는 별도 가드레일 설계가 필요한 후속 과제.
