# 원장이 진실을 말한다 — 설계

**작성일:** 2026-08-07
**대상:** `docs/DEEP_ANALYSIS_HARNESS_ROADMAP.md` §8 **W2** (이슈 G9 · G4 · FE1)
**브랜치:** `dev`
**선행:** W1 — [2026-08-04-deep-analysis-finalization-floor-split-design.md](2026-08-04-deep-analysis-finalization-floor-split-design.md)
(커밋 `c9a05d19..d9a08c17`)

---

## 1. 배경

W1은 마무리 단계가 예산을 받을 수 있게 만들었다. W2는 그 결과가 **원장에 정확히
적히고 사용자에게 도달하게** 만든다. 로드맵 §3.2가 이 구간의 주제로 적은
문장이 기준이다:

> 이 시스템의 모든 실패가 성공처럼 보였다. (…) 이 구간의 작업은 대부분
> **고치기 전에 보이게 만드는** 일이었다.

세 대상은 그 가시성이 끊기는 **서로 다른 세 층**이다.

| 층 | 이슈 | 끊기는 지점 |
|---|---|---|
| 원장이 사유를 틀리게 적는다 | G9 | 예외 경로가 사유를 판정하지 않는다 |
| 원장에 적힌 것을 꺼낼 수 없다 | G4 | 본문은 있으나 조회 경로가 없다 |
| 정확히 적힌 것이 화면에 안 뜬다 | FE1 | `activityLabel()`이 8종을 모른다 |

---

## 2. G9 — 정지 사유를 한 곳에서 판정한다

### 2.1 문제

로드맵은 "예외 핸들러가 if/elif보다 먼저 실행"이라고 적었다. 실제 구조는 조금 더
나쁘다: **정지 사유를 판정하는 코드가 두 벌이고, 둘이 다르다.**

| 경로 | 위치 | 판정 |
|---|---|---|
| 정상 종료 | `orchestrator.py:983-996` | `exhausted` → 소진 / `available_for_investigation < min_viable` → floor |
| 예외 종료 | `orchestrator.py:976-977` | **무조건 소진** |

`TokenBudget.reserve`는 두 사유 모두에 같은 `TokenBudgetExhausted`를 던진다
(`token_budget.py:152`). 예외 타입만으로는 구분할 수 없고, 예외 경로는 구분을
시도조차 하지 않는다. 로드맵 실측: **6건 중 4건 오분류.**

### 2.2 설계

판정을 `_mark_stop_reason()` 하나로 접고 양쪽에서 부른다. 예외 핸들러는 사유를
정하지 않고 "정지했다"만 알린다.

```python
async def _mark_stop_reason(self) -> None:
    """예산의 상태가 사유를 정한다 — 어느 경로로 멈췄는지가 아니라.

    `reserve` 는 캡 소진과 floor 정지 양쪽에 같은 `TokenBudgetExhausted` 를
    던지므로(token_budget.py) 예외 타입은 사유를 말해주지 않는다. 예외
    핸들러가 독자적으로 "소진"이라고 단정하던 것이 실측 6건 중 4건의
    오분류를 만들었다.
    """
    if self.token_budget.exhausted:
        await self._mark_token_budget_exhausted()
    elif (
        self.token_budget.available_for_investigation
        < self.token_budget.min_viable_output_tokens
    ):
        await self._mark_investigation_stopped_at_floor()
```

**세 번째 분기를 의도적으로 두지 않는다.** 둘 다 아니면 열린 질문이 없거나
`score_floor` 미달로 멈춘 것이고, 그건 정상 종료다 — 예산 이벤트를 남길 이유가 없다.
현재 동작과 같다.

**멱등성은 이미 보장돼 있다.** `_mark_token_budget_exhausted`와
`_mark_investigation_stopped_at_floor` 둘 다 인메모리 `_logged` 플래그와
`has_event()` 조회로 이중 방어한다(`orchestrator.py:189-204`, `:206-236`). 따라서
예외 경로와 정상 경로에서 연달아 불려도 중복 적재가 없다.

호출부는 두 곳이다:

- `except TokenBudgetExhausted:` 블록 — `_mark_token_budget_exhausted()` 대신
  `_mark_stop_reason()`
- 그 아래 `if self.token_budget.exhausted: ... elif ...` 블록 전체를
  `_mark_stop_reason()` 한 줄로

### 2.3 완료 기준

- floor에서 멈춘 run이 `token_budget_exhausted`를 남기지 않는다 (**S4 충족**)
- 두 경로가 같은 예산 상태에서 같은 이벤트를 낸다 — 테스트로 고정

---

## 3. G4 — 전제를 정정하고 조회 경로를 만든다

### 3.1 로드맵의 전제가 틀렸다

로드맵 §7은 G4를 "`report_path`가 574 run 전부 NULL — **리포트 본문이 보존된 적
없다**"로 적고, §2.2 S3도 같은 근거를 쓴다. **본문 유실은 사실이 아니다.**

`neos/workflow/deep_analysis/jobs.py:173-178`:

```python
# AC6: 늦게 접속한 구독자가 이벤트 재생만으로 리포트를 받도록
# 완료 이벤트가 리포트 본문을 싣는다.
await _log_lifecycle(session, run_id, JOB_COMPLETED,
                     {"report_markdown": result["report_markdown"]})
```

리포트 본문은 `job_completed` 이벤트 페이로드에 통째로 들어간다. 의도적 설계이며
`tests/workflow/deep_analysis/test_jobs.py:135`가 이를 고정한다.

그리고 **모든 실행이 이 경로를 지난다.** `neos/` 전체에서 `orchestrator.run()`의
호출자는 `jobs.py:154` 하나뿐이고, funnel 표본 러너도 `execute_run`을 임포트한다
(`funnel_sample_runner.py:29`).

즉 NULL인 것은 *열별 포인터*이지 *본문*이 아니다. 로드맵은 컬럼이 비어 있다는
사실을 본문 유실로 잘못 읽었다.

### 3.2 그러면 무엇이 없는가 — 조회 경로

G3(게이트 재보정)가 필요로 하는 것은 "표본 run들의 리포트 본문을 모아 uncited
비율을 다시 재는 것"이다. 본문은 있지만 그때마다 이벤트 페이로드를 파싱하는
질의를 손으로 짜야 한다. 그것을 이름 있는 조회로 만든다.

`Ledger`에 단건 조회:

```python
async def report_markdown(self) -> str | None:
    """이 run의 최종 리포트 본문.

    `job_completed` 페이로드에서 읽는다 — `report_path` 컬럼이 아니라
    여기가 정본이다(jobs.py, AC6). run이 실패했거나 아직 끝나지 않았으면
    None.
    """
```

`DeepAnalysisAnalyticsService`에 배치 조회:

```python
async def report_bodies(self, run_ids: Sequence[str]) -> dict[str, str]:
    """run_id -> 리포트 본문. 본문이 없는 run은 키가 없다."""
```

배치를 따로 두는 이유는 G3가 수백 run을 훑기 때문이다 — 단건 조회를 루프로 돌리면
run 수만큼 왕복한다.

### 3.3 `report_path` 컬럼은 건드리지 않는다

은퇴시키려면 마이그레이션이 필요하고, 그것은 스키마 결정이지 W2의 목표가 아니다.
`complete_run(report_path=...)` 시그니처도 그대로 둔다 — 호출부가 인자를 넘기지
않을 뿐, 계약 자체는 유효하다.

대신 **로드맵을 정정한다**: §2.2 S3의 측정법을 `report_path` NULL 비율에서
**`job_completed`에 `report_markdown`이 실린 비율**로 바꾸고, §7의 G4 서술을
"본문 유실"에서 "조회 경로 부재"로 고친다.

### 3.4 완료 기준

- `Ledger.report_markdown()`이 완료된 run의 본문을 돌려준다
- 실패한 run / 진행 중인 run에서 `None`을 돌려준다
- 배치 조회가 N개 run을 한 번의 질의로 읽는다
- 로드맵 §2.2 S3과 §7 G4의 서술이 관측과 일치한다 (**S3 충족**)

---

## 4. FE1 — 라벨과 지속되는 강등 상태

### 4.1 현재

`web/lib/deep-analysis/progress.ts`의 `activityLabel()`은 15종에 라벨을 붙이고,
결과는 `lastActivity` 문자열 하나로 접힌다(`progress.ts:175`). 실패 이벤트는 하나도
포함돼 있지 않다.

**라벨만 추가하면 부족하다.** `lastActivity`는 다음 이벤트가 오면 덮어써지므로,
강등은 스쳐 지나가고 run이 끝나면 흔적이 없다. 로드맵 §5.2가 지적한 문제 —
"사용자는 여전히 리포트가 템플릿으로 강등된 것을 알 수 없다" — 는 그대로 남는다.
강등은 **run이 끝난 뒤에도 남아야 하는 상태**다.

### 4.2 라벨 대상 8종

로드맵 §5.2는 6종을 적었고 W1이 2종을 더했다.

| 이벤트 | 추가 시점 | 강등? |
|---|---|---|
| `report_assembly_degraded` | 08-03 (G5) | 🔴 |
| `finalization_prompt_clamped` | 08-05 (W1) | 🔴 단, `exhausted === true`일 때만 |
| `node_reduction_degraded` | 08-05 (W1) | 🔴 |
| `investigation_stopped_at_floor` | 08-03/04 (G5·G8) | 🟡 |
| `report_graded` + `diagnostics.judge` | 08-03 (G5) | 🟡 — 아래 |
| `llm_truncated` | 08-02 (A2) | 🟡 |
| `truncation_handled` | 08-02 (A2) | 🟡 |
| `entailment_filter_skipped` | 08-02 (A2) | 🟡 |
| `claim_discarded` | 07-27 | 🟡 |

> ⚠️ **`judge_budget_exhausted`는 독립 kind가 아니다.** 확인 결과
> (`graders/report.py:215-232`) 그것은 `Verdict.detail` 문자열이고, 원장에
> 도달하는 것은 `report_graded` 페이로드의 `diagnostics.judge` 값이다 —
> `"budget_exhausted"` / `"truncated"` / `"unparseable"` 세 가지.
> 오케스트레이터의 `report_graded` 싱크는 `detail`을 읽지 않는다.
>
> 따라서 FE는 **새 kind를 기다리는 것이 아니라 이미 라벨이 있는
> `report_graded` 분기를 확장**해야 한다. 현재 그 분기는
> `payload.ok === true`만 보므로(`progress.ts:136-138`), 판정자가 굶어서
> 통과한 리포트와 판정자가 실제로 승인한 리포트가 **같은 문구**를 낸다.
> 이것이 이 항목의 실제 결함이다: 라벨 누락이 아니라 **라벨이 거짓말을 한다.**

### 4.3 강등 판정 기준

**"리포트가 사용자가 받았어야 할 것보다 못한가."** 이 질문에 예인 것만
`degradations`에 들어간다.

- 🔴 3종 — 최종 리포트의 내용을 직접 깎는다. 누적 상태에 남긴다.
- 🟡 6종 — 조사 범위나 검증 강도를 깎지만 리포트 자체는 최선이다. 라벨만 붙인다.

`llm_truncated`가 🟡인 이유가 이 기준을 잘 보여준다: 확장 재시도가 성공하면
(`truncation_handled.action === "retried_ok"`) 최종 산출물에 영향이 없다. 재시도가
실패한 경우만 강등이지만, 그걸 가르려면 두 이벤트를 상관시켜야 하고 그 상태 기계는
이번 범위를 넘는다. **과소 보고를 택한다** — 잘못된 경고보다 낫다.

### 4.4 상태 모양

`DeepAnalysisProgress`에 누적 필드를 더한다.

```ts
/** 리포트 품질을 깎은 사건들. lastActivity 와 달리 덮어써지지 않는다. */
degradations: DegradationEntry[];

type DegradationEntry = {
  kind: string;   // 원장의 kind 그대로 — UI 문구와 분리한다
  count: number;  // 같은 kind 반복 집계
};
```

**결정: 배열 + 카운트이지 `Set`이 아니다.** `node_reduction_degraded`는 run당
여러 번 날 수 있고, 3회와 1회는 다른 이야기다. 최초 발생 순서를 보존하도록 배열을
쓴다.

**`kind`를 그대로 싣고 문구는 싣지 않는다.** 상태는 원장의 어휘를 유지하고,
사람이 읽는 문구는 렌더 시점에 만든다 — 문구를 상태에 넣으면 재생된 옛 이벤트가
옛 문구를 고착시킨다.

### 4.5 유지할 규약

`progress.ts:148-153`의 명시적 설계 — **모르는 kind도 커서를 전진시킨다** — 를
유지한다. 새 라벨은 그 위에 얹을 뿐이며, 라벨 없는 kind가 커서를 멈추게 하는
회귀를 테스트로 막는다.

### 4.6 범위 밖

`components/deep-analysis-status.tsx`의 렌더링은 이번에 하지 않는다. 상태가 먼저
있어야 컴포넌트가 그릴 것이 생기고, 시각 디자인은 별도 판단이다. `degradations`가
상태에 실리는 것까지가 W2다.

### 4.7 완료 기준

- 신규 7종 전부 `activityLabel()`이 문자열을 돌려주고, `report_graded`가
  굶은 판정자를 승인한 판정자와 구별해 말한다
- 🔴 3종이 `degradations`에 누적되고 🟡 6종은 누적되지 않는다
- `finalization_prompt_clamped`가 `exhausted === false`면 누적되지 않는다
- 모르는 kind가 여전히 커서를 전진시킨다 (회귀 가드)
- `pnpm --dir web test:source` 통과

---

## 5. 변경 대상

| 파일 | 변경 |
|---|---|
| `neos/workflow/deep_analysis/orchestrator.py` | `_mark_stop_reason()` 신설, 두 호출부 교체 |
| `neos/workflow/deep_analysis/ledger.py` | `report_markdown()` 조회 |
| `neos/workflow/deep_analysis/analytics.py` | `report_bodies()` 배치 조회 |
| `web/lib/deep-analysis/progress.ts` | 라벨 8종, `degradations` 필드와 누적 로직 |
| `web/lib/deep-analysis/types.ts`(해당 타입 정의처) | `DegradationEntry`, `DeepAnalysisProgress` 확장 |
| `docs/DEEP_ANALYSIS_HARNESS_ROADMAP.md` | §2.2 S3 측정법, §7 G4 서술, §5.2 표 갱신 |

---

## 6. 테스트

| # | 고정하는 것 |
|---|---|
| T1 | 예외 경로에서 floor 정지면 `investigation_stopped_at_floor`가 나오고 `token_budget_exhausted`는 안 나온다 |
| T2 | 예외 경로에서 캡 소진이면 `token_budget_exhausted`가 나온다 |
| T3 | 두 경로(정상/예외)가 같은 예산 상태에서 같은 이벤트를 낸다 |
| T4 | `_mark_stop_reason`을 두 번 불러도 이벤트가 한 번만 적재된다 |
| T5 | `Ledger.report_markdown()`이 완료 run의 본문을, 미완료/실패 run에서 `None`을 돌려준다 |
| T6 | `report_bodies()`가 N개 run을 한 번의 질의로 읽고, 본문 없는 run은 키가 없다 |
| T7 | 신규 7종 전부 라벨이 `null`이 아니고, `report_graded`가 `diagnostics.judge`가 실린 경우 판정자 승인과 **다른** 문구를 낸다 |
| T8 | 🔴 3종만 `degradations`에 쌓이고, 반복은 `count`로 집계된다 |
| T9 | `finalization_prompt_clamped{exhausted:false}`는 누적되지 않는다 |
| T10 | 모르는 kind가 커서를 전진시킨다 (기존 규약 회귀 가드) |

---

## 7. 결정 기록

| # | 결정 | 근거 |
|---|---|---|
| W2-1 | 정지 사유를 `_mark_stop_reason()` 한 곳에서 판정 | 판정 코드가 두 벌이라 갈렸다. 예외 타입은 사유를 말하지 않는다 |
| W2-2 | `report_path` 컬럼을 채우지도 은퇴시키지도 않는다 | 본문은 이미 이벤트에 있다. 스키마 변경은 별도 결정 |
| W2-3 | 강등 판정은 "리포트 내용을 깎았는가" | 🔴 3종만. 조사 범위·검증 강도 축소는 라벨만 |
| W2-4 | `llm_truncated`는 강등이 아니다 | 재시도 성공 시 산출물에 영향 없음. 가르려면 두 이벤트 상관 필요 — 과소 보고를 택한다 |
| W2-5 | `degradations`는 배열+카운트, `Set` 아님 | 3회와 1회는 다른 이야기. 발생 순서 보존 |
| W2-6 | UI 컴포넌트 렌더링은 범위 밖 | 상태가 먼저. 시각 디자인은 별도 판단 |
| W2-7 | 굶은 판정자는 `report_graded` 분기를 고쳐 드러낸다 | 독립 kind가 아니다. 현재 분기는 `ok`만 보아 굶은 판정자의 통과를 승인과 같은 문구로 낸다 — 누락이 아니라 거짓말이다 |

---

## 8. 리스크

| 리스크 | 완화 |
|---|---|
| ~~`judge_budget_exhausted`가 독립 kind가 아닐 수 있다~~ | **해소** — 확인 결과 독립 kind가 아니라 `report_graded.diagnostics.judge`다. §4.2 참조 |
| `degradations` 추가가 기존 progress 소비자를 깨뜨림 | 필드 추가만 하고 기존 필드는 건드리지 않는다. `pnpm test:source` 147건이 회귀 가드 |
| 🟡 6종을 강등에서 뺀 판단이 틀릴 수 있다 | 라벨은 붙으므로 진행 로그에는 보인다. 판단이 틀렸다면 kind를 🔴로 옮기는 한 줄 변경 |
| G4 정정이 로드맵의 다른 서술과 충돌 | §2.2·§7·§8 W2를 함께 고친다. 수치의 원본은 `TODO_260729.md`이므로 그것도 확인 |

---

## 9. 참조

- 로드맵: [DEEP_ANALYSIS_HARNESS_ROADMAP.md](../../DEEP_ANALYSIS_HARNESS_ROADMAP.md) §5.2 · §7 · §8 W2
- W1 설계: [2026-08-04-deep-analysis-finalization-floor-split-design.md](2026-08-04-deep-analysis-finalization-floor-split-design.md)
- 결정 원장: `neos/workflow/deep_analysis/DECISIONS.md` (D25가 W1)
- FE 감사: [FE_AUDIT_260717.md](../../FE_AUDIT_260717.md) — ⚠️ 2026-07-17 기준
