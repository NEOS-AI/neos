# truncation 신호 전파 설계 (A2)

**작성일:** 2026-08-02
**대상:** `neos/workflow/deep_analysis/`
**근거:** `docs/TODO_260729.md` 「남은 할 일 — 상세」 A2 (권장 1순위)
**선행 작업:** `1c08e395`(entailment 상한), `06bfd39e`(judge 상한), `63b6ca26`(worker 상한),
`34cd4b96`(`llm_truncated` 이벤트)

---

## 1. 문제

LLM 응답이 `max_tokens`에서 잘리면 JSON 파싱이 실패한다. `call_json`은 이때
`JSONParseError`만 올리고 **응답 객체를 버린다**(`llm.py:342-347`). 그래서 호출부는
두 가지를 구분할 수 없다:

- **잘렸다** — 판정이 미완성이다. fail-open 하면 **안 된다.**
- **쓰레기다** — 모델이 형식을 어겼다. D14 fail-open이 **맞다.**

실측된 피해가 있다. `20260802T052306Z` 표본에서 judge 응답 4건이 잘렸고, 그중 하나는
이미 `"label": "CONTRADICTS"`를 내뱉은 뒤 잘렸다. 파싱이 실패하자 `_judge_failed`가
D14 fail-open을 적용해 **거절이 승인으로 뒤집혔다.**

상한을 올리는 것으로는 닫히지 않는다. 이번 작업 이전에 4개 상한을 올렸고 그중 2개
(`worker_analysis` 4000, `judge` 800)는 올린 뒤에도 잘렸다. **상한 조정은 절벽을 옮길
뿐이다.** 반면 신호는 이미 존재한다 — `_budgeted_dispatch`가 `response.stop_reason`을
읽어 `llm_truncated` 이벤트를 쓰고 있다(`llm.py:214-220`). 그 신호를 호출부까지
잇는 것이 이 설계다.

### 1.1 왜 상한 재보정으로 대체할 수 없는가

상한을 소모하는 주범은 대부분 **adaptive thinking**이다. judge 모델은
`thinking: adaptive`이고 `llm.py:137`이 `thinking_enabled=True`를 하드코딩한다.
thinking 토큰은 `max_tokens`에 계산되지만 content에서 제거되므로 **카세트에서 보이지
않는데 과금은 된다.** 잘린 judge 응답 하나는 300 토큰 중 텍스트가 83자뿐이었다.

`schema.py:742-746`이 18회 호출 실측으로 확인한 바에 따르면 토큰 소비는 claim 개수에
비례하지 않는다(1개→97, 3개→{237,434,923,1200(잘림)}, 6개→{512-655}). **변수는
thinking 분산이지 배치 크기가 아니다.** 분산이 지배하는 값을 상한으로 막으려면 항상
과대 할당해야 하는데, dev 프로파일은 `global_token_cap = 20000`이라 그럴 여유가 없다.

---

## 2. 범위

### 2.1 포함

`call_json`을 거치는 7개 호출부 전체의 truncation 처리, 그중 fail-open 하는 3개 지점의
종단 동작 변경, 관측 이벤트 2종 추가.

### 2.2 제외 (명시적)

| 항목 | 사유 |
|---|---|
| A1 — `report.py:136`의 하드코딩 `max_tokens=400` | 별도 작업. 이 설계는 종단 *동작*만 바꾼다 |
| A3 — `worker_analysis` 4000 재보정 | thinking 몫 측정이 선행 |
| A4 — `worker_repair`의 effort 예산 결박 | 측정 표본의 변수를 하나로 유지 |
| A5 — `deep_analysis` 밖의 하드코딩 상한 | fail-open 여부 미검증 |
| B — 예산 clamp 자체 | 이 설계는 clamp를 *감지*할 뿐 고치지 않는다 |
| C1 — discard recall 재측정 | **이 변경 이후에** 수행 (§7 참조) |
| D, F | 별도 범위 |

---

## 3. 아키텍처

```
_call_provider ──[stop_reason]──▶ LLMResponse
                                      │
_budgeted_dispatch ──[reservation.max_output_tokens]──▶ 응답에 실제 허용 상한 부착
                                      │
                                      ▼
call_json ── 파싱 실패의 원인을 3분류 ──┬─ 상한에 걸림 → multiplier 배로 확장 재시도 1회
                                      ├─ 예산에 걸림 → 재시도 없이 종단
                                      └─ 그냥 쓰레기 → 기존 동일 상한 재시도 (현행 유지)
                                      │
                                      ▼
              TruncatedResponseError (JSONParseError 서브클래스)
```

### 3.1 핵심 판단 — 서브클래스로 만든다

`TruncatedResponseError`를 `JSONParseError`의 **서브클래스**로 정의한다.

`call_json` 호출부는 7곳인데 `JSONParseError`를 잡아 fail-open 하는 곳은 2곳뿐이다.
서브클래스로 두면 나머지 5곳은 **코드 변경 없이 확장 재시도 이득만 받는다**:

| 호출부 | 현행 예외 처리 | 이 설계 이후 |
|---|---|---|
| `worker.py:242` (analysis) | 전파 | 변경 없음 + 확장 재시도 이득 (A3 12건 완화) |
| `worker.py:459` (repair) | 전파 | 변경 없음 + 확장 재시도 이득 (A4 완화) |
| `synthesizer.py:227` | 전파 | 변경 없음 |
| `orchestrator.py:287` (decompose) | 전파 | 변경 없음 |
| `orchestrator.py:311` (decompose) | 전파 | 변경 없음 |
| `graders/agentic.py:93` | fail-open (D14) | **명시적 변경** (§5.1) |
| `graders/report.py:141` | fail-open (무조건) | **명시적 변경** (§5.2) |

여덟 번째 지점인 `worker.py:379`(entailment)는 `call_json`이 아니라 `call_llm` +
`parse_json`을 직접 쓴다. 이미 응답 객체를 손에 쥐고 있어 오늘도 `stop_reason`을 볼 수
있으나, 재시도 규칙이 두 곳에 생기는 것을 피하려 `call_json`으로 이전한다(§5.3).

### 3.2 예산 clamp를 반드시 구분해야 하는 이유

`TokenBudget.reserve`는 요청 상한을 **조용히 깎는다**:

```python
output_tokens = min(max_output_tokens, self.remaining_tokens - input_bound)
```
(`token_budget.py:100-103`)

이미 예산에 깎여서 잘린 호출은 더 큰 상한을 요청해도 같은 값으로 깎인다. 게다가 첫
호출이 `settle`되면서 `remaining`이 줄었으므로 **재시도는 오히려 더 적은 여유를 받는다.**
예산만 더 태우고 똑같이 잘린다.

`20260802T052306Z` 표본에서 상한이 106, 487, 539, 576, 983, 1629, 3995 같은 어중간한
값인 truncation이 7건+ 관측됐다. 전부 예산 clamp의 결과다. **확장 재시도를 무조건
적용하면 이 7건에서 예산을 두 배로 태우고 결과는 동일하다.**

구분은 가능하다. `reservation.max_output_tokens`가 clamp *이후* 값으로 기록되어 있다
(`TODO_260729.md` B1이 "처방이 다르므로 이 구분을 유지할 것"이라고 명시한 그 설계).

- 허용 상한 **>=** 요청 상한 → **상한에 걸림**. 확장 재시도가 의미 있다.
- 허용 상한 **<** 요청 상한 → **예산에 걸림**. 재시도 없이 종단.

---

## 4. 컴포넌트

### 4.1 `LLMResponse`에 필드 추가 — `llm.py:24-34`

```python
granted_max_output_tokens: int = 0   # 0 = 미상(레거시 카세트)
```

`stop_reason`이 이미 쓴 것과 같은 하위호환 방식이다. 기존 골든 카세트 레코드에는 이 키가
없고 재생 시 `LLMResponse(**recorded)`로 복원되므로 **기본값이 필수다**(D19 골든 게이트
유지). 해당 주석(`llm.py:30-32`)이 그 이유를 이미 설명한다.

`_budgeted_dispatch`가 `dataclasses.replace`로 **카세트 계층 이후에** 채운다. 허용 상한은
기록 시점이 아니라 *이번 run*의 예산 속성이기 때문이다. `produce()`가 `asdict(response)`를
기록할 때는 이 값이 0이며, 재생 시에도 dispatch가 덮어쓴다.

카세트 키는 요청 페이로드(`model`/`prompt`/`max_tokens`/`temperature`)에서 파생되므로
응답 필드 추가가 골든 키를 바꾸지 않는다.

예산이 없는 경로(`active_token_budget()` is None, `llm.py:191-192`)에서는
`granted_max_output_tokens = max_tokens`로 채운다 — 깎을 예산이 없으므로 항상 상한 걸림이다.

### 4.2 `call_json` 재시도 루프 — `llm.py:329-347`

기존 루프는 파싱 실패 시 **같은 상한으로** 재호출한다. 잘린 응답은 재시도해도 또 잘리므로
결정론적으로 실패할 호출에 예산을 두 번 낸다. 새 루프는 원인별로 갈린다.

| 상황 | 판정식 | 행동 |
|---|---|---|
| 잘리지 않음 | `stop_reason != "max_tokens"` | 현행 유지 — 같은 상한 1회 재시도 |
| 상한에 걸림 | `granted >= 요청 상한` | 상한 × `multiplier`로 1회 재시도 |
| 예산에 걸림 | `granted < 요청 상한` | 즉시 `TruncatedResponseError` |
| 확장 소진 | 확장 후에도 잘림 | `TruncatedResponseError` |

확장은 **호출당 최대 1회**다. 확장 재시도가 다시 잘리면 더 늘리지 않는다.

`retries` 인자의 기존 의미(비-truncation 재시도 횟수)는 유지한다. 확장 재시도는 그와
별개로 1회 허용되는 추가 시도이며, `retries=0`으로 호출해도 확장은 시도한다 —
`retries`는 "쓰레기 응답을 몇 번 봐줄 것인가"이고 확장은 "잘린 것을 복구할 것인가"로
서로 다른 축이다.

### 4.3 설정값

```python
truncation_retry_multiplier: float = 2.0
```

`neos/config/schema.py`의 deep_analysis 설정에 추가한다. 매직넘버 금지 불변식을 따른다.

기본값 2.0의 근거: judge는 300에서도 800에서도 잘렸으므로 2배가 항상 충분하다는 보장은
없다. 그 경우 fail-closed로 간다(§5). 반면 "가용 여유 전부"는 dev 프로파일
(`global_token_cap = 20000`, `parallel_workers = 2`)에서 한 워커가 예산을 독점해 동시
실행 중인 다른 워커에게 `TokenBudgetExhausted`를 유발할 위험이 있다. 2.0은 그 압박을
한정하면서 관측된 truncation 다수를 덮는 절충이다.

---

## 5. 종단 동작

전제: 세 지점 모두 **확장 재시도가 성공하면 정상 판정을 쓴다.** 아래는 재시도까지 실패한
경우다.

### 5.1 judge (`graders/agentic.py:93`) — D24 신규 결정

```
Verdict(ok=False, code="E_UNSUPPORTED", detail="judge_truncated")
```

**mandatory 여부와 무관하게** 반려한다. D14의 fail-open은 "judge가 쓰레기를 뱉었다"에
대한 결정이었고, "판정이 미완성이다"에는 적용되지 않는다. 실측 근거가 정확히
비-mandatory fail-open 경로에서 나왔다(§1의 CONTRADICTS 사례).

반려된 claim은 기존 경로대로 재조사되고, `claim_retry_cap` 소진 시 `unverified`로
보고서 「한계」 절에 남는다. 빈손 종료는 없다.

**이는 D14 정책 변경이므로 `DECISIONS.md`에 D24로 기록한다.** 개정 대상은 D14의 저가치
샘플 경로 원결정이며, `judge_unparseable`(쓰레기)의 fail-open은 그대로 유지된다.

⚠️ **이 변경은 claim funnel 수치를 이동시킨다.** 비-mandatory claim이 judge truncation
때문에 반려되므로 verified 절대수가 줄어들 수 있다. `E1`의 baseline 단절이 한 번 더
발생한다 — §7 참조.

### 5.2 report (`graders/report.py:141`)

```
return deterministic   # grade()가 이미 통과시킨 결정론적 판정
```

반려(재조립)로 보내지 **않는다.** `orchestrator.py:833-868`에서 report 반려는 초안
재조립을 유발하는데, judge가 잘린 것은 초안 품질과 무관하다. 재조립해도 같은 judge가
같은 상한에서 또 잘린다. synthesizer 호출 3회(`report_retry_cap` 2 + 1)를 결정론적으로
낭비하고 결국 `orchestrator.py:870-874`의 「미해결 사유」 부록으로 끝난다. **judge 실패를
report 실패로 취급하는 인과 오류다.**

`report.py:167-168`의 `except TokenBudgetExhausted: return deterministic`가 이미 같은
경로다 — "심사를 못 했다"를 재조립이 아니라 결정론적 판정으로 되돌린다.

결과는 현행 fail-open과 같지만 두 가지가 다르다: **확장 재시도를 거친다**는 것과
**사유가 `detail`에 기록된다**는 것.

### 5.3 entailment (`worker.py:379`)

현행 fail-open(원본 claim 그대로 통과)을 **유지**하되, 스킵 사실을 기록한다.

entailment는 게이트가 아니라 **필터**다. 통과한 claim은 어차피 `DeterministicGrader`와
`AgenticGrader`를 다시 거친다. 필터를 못 건 것은 judge를 못 거친 것과 안전성 등급이
다르다. 배치 전체를 버리거나 전부 반려하는 것은 recall을 파괴하고, C1이 측정하려는
recall 손실을 새로 만들어내 측정 대상을 오염시킨다.

배치 분할 재시도는 **채택하지 않는다.** `schema.py:742-746`의 18회 호출 실측이 토큰
소비가 claim 개수에 비례하지 않음을 보였다 — 잘린 것은 3-claim 배치였고 모든 6-claim
배치는 완주했다. 분할해도 잘릴 수 있다.

구현 변경: `call_llm` + `parse_json`을 `call_json`으로 이전한다. 이전 후에도 파싱 결과에
대한 `apply_entailment_results` 검증은 그대로 유지된다 — `call_json`은 JSON 객체까지만
보장하고 스키마 검증은 호출부 책임이다.

---

## 6. 관측

### 6.1 P2 제약

두 grader 모두 이벤트를 쓸 수 없다. `AgenticGrader`는 ledger를 갖고 있지 않고
(`agentic.py:19-27`), `ReportGrader`는 갖고 있으나 P2가 읽기 전용으로 묶어놨다
(`report.py:5-6`). **worker도 ledger가 없다.**

기존 우회로를 따른다: worker는 `_discarded_claims`를 결과 객체에 실어 보내고
**오케스트레이터가** `orchestrator.py:660`에서 읽어 이벤트를 쓴다. 새 배관을 만들지 않는다.

### 6.2 이벤트

| kind | 작성자 | 페이로드 | 답하는 질문 |
|---|---|---|---|
| `llm_truncated` (기존) | `TokenBudget` | stage, model, max_output_tokens, output_tokens | "잘렸는가" |
| `truncation_handled` (신규) | `TokenBudget` (`call_json`이 `active_token_budget()`으로 접근) | stage, model, requested, granted, action | "확장 재시도를 했는가, 왜 안 했는가" |
| `entailment_filter_skipped` (신규) | 오케스트레이터 (worker 결과 플래그를 읽어) | qid, claim 수, 사유 | "이 배치가 필터를 통째로 건너뛰었는가" |

`action` ∈ `retried_ok` | `retried_failed` | `budget_bound`.

`truncation_handled`는 **truncation이 실제로 발생했을 때만** 쓴다. 잘리지 않은 호출까지
기록하면 정상 경로 전체가 이벤트가 되어 로그를 압도한다. 따라서 `llm_truncated` 1건에
`truncation_handled` 1건이 대응한다.

⚠️ 두 이벤트 모두 `TokenBudget`이 작성자이므로 **활성 예산이 없으면 기록되지 않는다**
(`active_token_budget()` is None). 프로덕션 경로에는 항상 예산이 있으나, 예산을 주입하지
않은 테스트에서는 이벤트를 단언할 수 없다 — §8의 예산 clamp 항목이 활성 예산을 요구하는
이유와 같다.

두 kind 모두 **신규 추가**이며 기존 kind의 페이로드를 바꾸지 않는다 (D8 §11.3 append-only).
페이로드는 카운트와 식별자만 싣는다 — 응답 텍스트는 절대 싣지 않는다
(`record_truncation` 주석의 기존 규약).

judge·report의 종단은 별도 이벤트가 필요 없다. `Verdict.detail`(`judge_truncated`)을
오케스트레이터가 이미 기록하는 경로에 실어 보낸다.

### 6.3 `entailment_filter_skipped`가 C1을 푼다

C1(discard recall 측정)은 두 표본 연속 discard 0건으로 `inconclusive`였다. 현재 계측으로는
**"버릴 게 없었다"와 "필터가 안 돌았다"를 구분할 수 없다.** `20260802T052306Z`에서
entailment 18회 중 1회가 잘렸으므로 후자가 0의 일부를 설명할 수 있다는 가설이 있으나
미검증이다. 이 이벤트가 그 가설을 판정 가능하게 만든다.

### 6.4 남는 계측 부채

`ledger.py:144`의 `_persist_token_budget`이 `qid=None`을 하드코딩하므로 `truncation_handled`
역시 질문 귀속이 없다(기존 budget 이벤트 전체가 그렇다 — 회귀 아님). "어느 질문에서
잘렸나"는 여전히 물을 수 없다. C2로 남긴다.

---

## 7. C1과의 순서 의존

**C1 재측정은 이 변경이 병합된 이후에 수행해야 한다.** 이유는 두 가지다:

1. §5.1의 D24가 claim funnel을 이동시킨다. 두 효과가 같은 표본에 섞이면 분리 불가다.
2. §6.2의 `entailment_filter_skipped`가 없으면 n=0을 또 해석할 수 없다.

`docs/superpowers/plans/2026-07-28-deep-analysis-discard-recall-measurement.md`는 그대로
재사용 가능하다. 단 사전 등록된 판정 규칙(`safe` = distinct discard 35건 이상 + verified
0건)은 유지한다.

---

## 8. 테스트 전략

실 LLM/네트워크 금지 불변식을 지킨다 — 카세트 재생 또는 fake 주입만 쓴다.

| 층 | 검증 |
|---|---|
| `call_json` 단위 | §4.2 매트릭스 4행 전부 |
| 예산 clamp 경로 | **활성 `TokenBudget`이 필요하다.** `granted`가 `_budgeted_dispatch`에서만 채워지므로 예산 없는 테스트는 항상 "상한 걸림"으로 읽힌다 |
| judge 종단 | mandatory / 비-mandatory **둘 다** 반려되는지. 쓰레기 응답은 여전히 D14 fail-open인지 |
| report 종단 | 결정론적 판정이 반환되고 재조립 루프가 돌지 않는지 |
| entailment 종단 | 원본 claim 통과 + `entailment_filter_skipped` 이벤트 1건 |
| 서브클래스 회귀 | 미변경 4개 호출부가 여전히 예외를 전파하는지 |
| 레거시 카세트 | `stop_reason=""` 레코드에서 동작 완전 불변 |
| 골든 게이트 (D19) | `tests/workflow/deep_analysis/test_golden_gate.py` green 유지 |

**테스트 명령:**

```bash
HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/python -m pytest \
  tests/workflow/deep_analysis/ -q --disable-warnings
```

bare `pytest`는 asyncio 마커 수집에 실패한다. Ruff도 통과해야 한다.

---

## 9. 성공 기준

1. 세 fail-open 지점이 truncation과 쓰레기 응답을 구분해 다르게 처리한다.
2. 예산 clamp로 잘린 호출에서 확장 재시도가 **발생하지 않는다** (예산 낭비 없음).
3. `truncation_handled` 이벤트로 4가지 action이 사후 집계 가능하다.
4. `entailment_filter_skipped`로 C1의 n=0이 해석 가능해진다.
5. D19 골든 게이트와 기존 deep_analysis 테스트 전량이 green이다.
6. D24가 `DECISIONS.md`에 기록된다.

---

## 10. 참조

- 잔여 과제 정본: `docs/TODO_260729.md` 「남은 할 일 — 상세 (2026-08-02 갱신)」
- 결정 원장: `neos/workflow/deep_analysis/DECISIONS.md` (D8 append-only, D14 fail-open)
- 설계 원본: `docs/DEEP_ANALYSIS_HARNESS_DESIGN.md`
- 후속 측정 플랜: `docs/superpowers/plans/2026-07-28-deep-analysis-discard-recall-measurement.md`
