# 거절에는 사유가 있다 — 설계

**작성일:** 2026-08-08
**대상:** `docs/DEEP_ANALYSIS_HARNESS_ROADMAP.md` §7 **G10** (S4의 마지막 조각)
**브랜치:** `dev`
**선행:** W2 — [2026-08-07-deep-analysis-ledger-truth-design.md](2026-08-07-deep-analysis-ledger-truth-design.md)
(커밋 `7318a840..a9dbcfe3`)

---

## 1. 배경

W2의 G9는 정지 사유 판정을 `_mark_stop_reason()` 하나로 접어, 정상 경로와 예외
경로가 같은 판정을 내게 했다. 그때 **의도적으로 남긴 구멍이 하나** 있고, 코드가
스스로 그 사실을 적어뒀다 (`orchestrator.py:262-270`):

> `TokenBudget.reserve` also refuses a reservation when
> `available_for_investigation - input_bound < min_viable_output_tokens`,
> i.e. with headroom left in `available_for_investigation` itself; that
> refusal raises the same `TokenBudgetExhausted` but satisfies neither
> branch here, so it reaches this method and still logs nothing (see G10).

로드맵 §2.2가 S4의 측정법에 이것을 명시적으로 걸어뒀다:

> `token_budget_exhausted` vs `investigation_stopped_at_floor` **그리고**
> `_mark_stop_reason`의 두 분기 모두를 벗어나는 무이벤트 정지 건수(G10, 목표 0)

**이 작업을 W1(라이브 표본 5+1)보다 먼저 하는 이유.** §10.2가 표본에 "정확히 1회"
규칙을 걸어 두었으므로, 이 구멍을 남긴 채 표본을 쓰면 그 정지 클래스는 **영구히
침묵으로 기록된다.** 표본을 쓰기 전에 세는 눈을 고쳐야 한다.

---

## 2. 문제 — 사유를 아는 곳은 하나, 추측하는 곳은 넷

`TokenBudget.reserve()`는 서로 다른 두 사실에 같은 맨손 예외를 던진다
(`token_budget.py:168-183`, 저장소 전체에서 **유일한 raise 지점**):

```python
output_tokens = min(max_output_tokens, ceiling - input_bound)
viability = min(max_output_tokens, self.min_viable_output_tokens)
if output_tokens < viability:
    raise TokenBudgetExhausted("deep-analysis token budget exhausted")
```

| 사실 | 판별식 | 뜻 |
|---|---|---|
| tier가 비었다 | `ceiling <= 0` | 그 tier에 남은 것이 없다 |
| 프롬프트가 안 들어간다 | `ceiling > 0` 이고 `ceiling - input_bound < viability` | **여유는 있는데** 이 프롬프트가 그 안에 안 들어간다 |

`ceiling`은 stage에 따라 셋 중 하나다 (`token_budget.py:162-167`): `REPORT_STAGES`는
`remaining_tokens`, `FINALIZATION_STAGES`는 `available_for_reduction`, 나머지는
`available_for_investigation`. 즉 "tier가 비었다"는 캡 소진일 수도 floor 도달일
수도 있다 — 그 구별은 이미 `_mark_stop_reason`의 상태 분기가 정확히 하고 있다.

예외는 이 정보를 하나도 싣지 않는다. 그래서 소비자 넷이 전부 밖에서 추측한다:

| 소비자 | 현재 코드 | 결과 |
|---|---|---|
| `orchestrator.py:276-282` `_mark_stop_reason` | 예산 *상태* 두 분기 | 둘째 사실은 **어느 분기에도 안 걸려 침묵** — 이것이 G10 |
| `synthesizer.py:222` `report_assembly_degraded` | `{"reason": "token_budget_exhausted"}` 하드코딩 | 여유가 남았는데 "소진"이라 **거짓 기록** |
| `synthesizer.py:327` `_degraded_summary(..., "token_budget_exhausted")` | 같은 문자열 하드코딩 | 같은 거짓이 `NodeSummary.caveats`를 거쳐 **리포트 본문까지** 도달 |
| `worker.py:159,375` / `orchestrator.py:327` `_grade` | 사유를 안 쓴다 (부분 결과 반환·`agentic="exhausted"`) | 변경 없음 |

**이것은 G9와 같은 결함의 다른 층이다.** G9는 "어느 경로로 왔는가"로 사유를
단정했고, 여기 남은 셋은 "어떤 예외 타입인가"로 사유를 단정한다. 둘 다 사유를
아는 자리에서 판정하지 않는다.

---

## 3. 설계

### 3.1 사유를 예외에 싣는다

사유를 아는 유일한 자리가 `reserve()` 안이므로 예외가 운반체가 된다. 추정이
아니라 그 자리의 계산값을 그대로 싣는다.

```python
class TokenBudgetExhausted(RuntimeError):
    """Raised when no output token can be reserved within the hard cap.

    Carries why. `reserve` refuses for two different reasons and used to
    throw the same bare exception for both, so every consumer had to guess
    -- `_mark_stop_reason` guessed "neither" and logged nothing (G10), and
    the synthesizer guessed "token_budget_exhausted" and wrote it down even
    when the budget had headroom left. The refusal site is the only place
    that knows; this is how it says so.
    """

    def __init__(
        self,
        message: str = "deep-analysis token budget exhausted",
        *,
        cause: str = "tier_floor",
        stage: str = "",
        model: str = "",
        input_bound: int = 0,
        ceiling: int = 0,
        requested: int = 0,
        granted: int = 0,
    ) -> None:
        ...
```

**모든 필드가 기본값을 갖는다.** 테스트 9곳이 `TokenBudgetExhausted("cap")`처럼
메시지만으로 생성하며, 그것이 계속 유효해야 한다. `cause` 기본값 `"tier_floor"`는
기존 해석("예산이 없다")과 같다.

`cause` 값은 둘뿐이다:

- `"tier_floor"` — `ceiling <= 0`
- `"input_bound"` — `ceiling > 0`인데 프롬프트가 안 들어간다

나머지 필드는 거절 순간의 계산값을 그대로 옮긴다:

| 필드 | 값 | 비고 |
|---|---|---|
| `stage`·`model` | `reserve()`의 키워드 인자 | 어느 호출이 거절됐는지 |
| `input_bound` | `conservative_input_bound(request)` | 프롬프트가 요구한 입력 몫 |
| `ceiling` | stage가 고른 세 tier 중 하나의 값 | 그 순간 그 tier에 남은 양 |
| `requested` | 호출자의 `max_output_tokens` | 원한 출력 몫 |
| `granted` | `min(max_output_tokens, ceiling - input_bound)` | **음수일 수 있다** — 프롬프트가 tier보다 크면 그렇다. 0으로 깎지 않는다: 얼마나 모자랐는지가 곧 진단이다 |

### 3.2 `_mark_stop_reason` — 상태 분기를 먼저, 새 분기는 fallback

```python
async def _mark_stop_reason(
    self, exc: TokenBudgetExhausted | None = None
) -> None:
    if self.token_budget.exhausted:
        await self._mark_token_budget_exhausted()
    elif (
        self.token_budget.available_for_investigation
        < self.token_budget.min_viable_output_tokens
    ):
        await self._mark_investigation_stopped_at_floor()
    elif exc is not None and exc.cause == "input_bound":
        await self._mark_investigation_stopped_at_input_bound(exc)
```

**순서가 설계의 핵심이다.** 상태 분기 둘을 앞에 두면 G9의 판정이 한 글자도 바뀌지
않는다. 새 분기는 **지금 침묵이 나는 자리만** 채운다. `exc`가 `input_bound`인데
예산 상태가 이미 소진/floor라면 상태 쪽이 이기는데, 그것이 옳다 — 그 run은 실제로
예산이 없어서 멈춘 것이고, 마지막 거절이 우연히 큰 프롬프트였을 뿐이다.

`exc is None`이고 어느 분기도 안 걸리는 경우는 **여전히 의도적 무이벤트다**:
열린 질문이 `score_floor`를 못 넘어 멈춘 run에는 기록할 예산 사건이 없다
(기존 주석이 이미 이 이유를 적어뒀고, 그대로 둔다).

**호출부** (`orchestrator.py:1021-1028`):

```python
except TokenBudgetExhausted as exc:
    await self._mark_stop_reason(exc)
    ...
await self._mark_stop_reason()          # 무조건 호출은 그대로
```

무조건 호출이 뒤따르지만 이중 기록은 나지 않는다. 새 헬퍼도 기존 둘과 같은
멱등 패턴(인메모리 플래그 + `ledger.has_event` 조회)을 쓰고, 새 분기는 `exc`가
없으면 애초에 진입하지 않는다.

### 3.3 새 이벤트 `investigation_stopped_at_input_bound`

기존 두 stop 이벤트와 같은 규약을 따른다 — **수치와 식별자만, 본문 텍스트 없음.**

```python
payload = {
    "cap_tokens": ...,
    "consumed_tokens": ...,
    "reserved_tokens": ...,
    "stage": exc.stage,
    "model": exc.model,
    "input_bound": exc.input_bound,
    "ceiling": exc.ceiling,
}
```

`floor_tokens`/`report_floor_tokens`는 싣지 않는다. 이 정지는 floor에 닿아서 난 것이
아니므로 floor 수치를 실으면 읽는 사람을 `investigation_stopped_at_floor` 쪽으로
오도한다. 대신 `stage`·`input_bound`·`ceiling`이 "무엇이 얼마나 안 들어갔는가"를
말한다.

**별도 kind인 이유.** `investigation_stopped_at_floor`에 `cause` 페이로드를 다는
안도 있었으나 기각했다. 두 사실이 다르고(floor = "남은 것이 마무리 몫뿐",
input_bound = "여유는 있는데 이 프롬프트가 안 들어감"), 하나로 접으면 G9가 고친
실수 — 한 라벨이 두 사유를 덮는 것 — 를 그대로 반복한다. 게다가 이미 쌓인
`investigation_stopped_at_floor` 이벤트에는 그 키가 없어 경계 전후 비교가
애매해진다.

### 3.4 synthesizer 두 곳 — 사유를 유도하되 옛 어휘는 보존

```python
except TokenBudgetExhausted as exc:
    await self.ledger.log(
        "report_assembly_degraded", qid, {"reason": _degradation_reason(exc)}
    )
```

```python
def _degradation_reason(exc: TokenBudgetExhausted) -> str:
    """`tier_floor` 는 기존 문자열을 그대로 낸다 -- 새 어휘는 새로 구별된
    경우에만 나온다. 이미 쌓인 이벤트와의 비교 가능성이 그만큼의 값어치가 있다."""
    return "input_bound" if exc.cause == "input_bound" else "token_budget_exhausted"
```

`tier_floor`가 기존 문자열 `"token_budget_exhausted"`를 그대로 내는 것은 의도적
결정이다. 이미 원장에 쌓인 강등 이벤트와 새 이벤트가 같은 어휘를 쓰므로 경계
전후 집계가 이어진다. 새 문자열 `"input_bound"`는 **지금까지 존재하지 않던 구별**에만
붙는다.

부수 효과로 기존 단언 셋이 그대로 통과한다:
`test_synthesizer.py:164`·`test_prompt_clamp.py:356,362`의
`caveats == ["token_budget_exhausted"]`.

### 3.5 프론트엔드

`web/lib/deep-analysis/progress.ts`의 `activityLabel()`에 항목 하나:

```ts
if (kind === "investigation_stopped_at_input_bound") {
  return "조사 중단 — 남은 예산에 프롬프트가 들어가지 않음";
}
```

**강등으로 세지 않는다.** `progress.ts:221-225`와 `ledger.py:92-94`가
`investigation_stopped_at_floor`에 대해 세운 논리와 같다 — 조사 범위나 검증
강도를 깎은 것이지 리포트 자체를 깎은 것이 아니며, 리포트는 주어진 재료로 낼 수
있는 최선이다(D26). 따라서 `_DEGRADATION_KINDS`(`ledger.py:57`)와
`degradationKind()`(`progress.ts:232`)는 **건드리지 않는다** — 로드맵 §7 FE6이
경고한 이중 구현에 손대지 않는다는 뜻이기도 하다.

그 "안 세기로 한 결정"을 사고와 구별하기 위해, 양쪽 정본 fixture에 새 kind를
**`null`(비강등)로 못박는다**:
`tests/workflow/deep_analysis/test_ledger_degradations.py`의 `CANONICAL_FIXTURE`와
`web/tests/source/deep-analysis-degradation.test.ts`의 `CANONICAL_FIXTURE`.

---

## 4. 변경 대상

| 파일 | 변경 |
|---|---|
| `neos/workflow/deep_analysis/token_budget.py` | `TokenBudgetExhausted`에 사유 필드 · `reserve()`가 `cause`를 계산해 던진다 |
| `neos/workflow/deep_analysis/orchestrator.py` | `_mark_stop_reason(exc=None)` 셋째 분기 · `_mark_investigation_stopped_at_input_bound()` 신설 · 플래그 1개 · 호출부 1곳 |
| `neos/workflow/deep_analysis/synthesizer.py` | `_degradation_reason()` 신설 · 하드코딩 문자열 2곳 교체 |
| `web/lib/deep-analysis/progress.ts` | `activityLabel()` 항목 1개 |
| `tests/workflow/deep_analysis/test_token_budget.py` | `cause` 판별 (경계 포함) |
| `tests/workflow/deep_analysis/test_orchestrator_token_budget.py` | 새 stop 이벤트 · 상태 분기 우선순위 회귀 |
| `tests/workflow/deep_analysis/test_synthesizer.py` | 강등 `reason`이 사유를 따라간다 |
| `tests/workflow/deep_analysis/test_ledger_degradations.py` | `CANONICAL_FIXTURE`에 새 kind → `None` |
| `web/tests/source/deep-analysis-progress.test.ts` | 라벨 |
| `web/tests/source/deep-analysis-degradation.test.ts` | `CANONICAL_FIXTURE`에 새 kind → `null` |

---

## 5. 테스트

**`reserve()`의 사유 판별**

- `ceiling <= 0` → `cause == "tier_floor"`
- `ceiling > 0`인데 `ceiling - input_bound < viability` → `cause == "input_bound"`
- 경계: `ceiling - input_bound == viability - 1`은 `input_bound`,
  `== viability`는 거절 자체가 없다
- `stage`·`model`·`input_bound`·`ceiling`·`requested`·`granted`가 실제 값을 싣는다
- `TokenBudgetExhausted("cap")` 맨손 생성이 여전히 유효하고 `cause == "tier_floor"`

**정지 사유 기록 (S4)**

- `input_bound` 거절이 오케스트레이터 루프에 도달하면
  `investigation_stopped_at_input_bound` **정확히 1건** — 무이벤트 0건
- 같은 run에서 무조건 호출이 뒤따라도 **중복 기록 없음**
- 회귀: 캡 소진은 여전히 `token_budget_exhausted`만, floor 정지는 여전히
  `investigation_stopped_at_floor`만 (`exc.cause`가 `input_bound`여도 상태가 이긴다)
- 회귀: `score_floor` 정지는 여전히 **무이벤트**

**강등 사유**

- `input_bound` 원인의 `report_assembly_degraded`는 `reason == "input_bound"`
- `tier_floor` 원인은 `reason == "token_budget_exhausted"` (문자열 불변)
- `_degraded_summary` 경로도 동일

**프론트엔드**

- `activityLabel()`이 새 kind에 문자열을 낸다
- `degradationKind()`가 새 kind에 `null`을 낸다 (양쪽 `CANONICAL_FIXTURE`)

---

## 6. 범위 밖

- **거절 전부를 기록하는 `token_budget_refused`.** 워커(`worker.py:159,375`)와
  판정자(`orchestrator.py:327` `_grade`)가 삼키는 거절은 정지가 아니라 부분
  실패이므로 stop 이벤트로 세면 S4 집계가 오염된다. 별도 항목으로 남긴다.
- **`reserve()`의 거절 동작 변경.** 무엇을 거절할지는 한 글자도 바뀌지 않는다.
  바뀌는 것은 **사유의 기록뿐**이다 — §10.2가 금지한 "측정 대상 변경"에 해당하지
  않게 하려는 의도적 제약이다.
- **FE6 이중 구현 통합.** 강등 어휘를 건드리지 않으므로 이번 작업과 무관하다.
- **라이브 표본 실행(W1).** 이 작업은 그 표본을 **쓰기 전에** 세는 눈을 고치는 것이다.

---

## 7. 리스크

| 리스크 | 완화 |
|---|---|
| 예외 시그니처 변경이 기존 호출자를 깬다 | 모든 필드에 기본값. 유일한 프로덕션 raise 지점은 `token_budget.py:183` 하나이고, 테스트 9곳은 메시지만 넘긴다 |
| 새 분기가 기존 분기를 가로챈다 | 상태 분기를 **먼저** 둔다. 회귀 테스트가 세 정지 클래스를 각각 고정한다 |
| 강등 `reason` 어휘 변경이 기존 집계를 끊는다 | `tier_floor`는 기존 문자열 유지. 새 문자열은 새로 구별된 경우에만 |
| 새 kind가 FE에서 커서를 멈춘다 | 멈추지 않는다 — `progress.ts:148-153`이 모르는 kind도 커서를 전진시키고 라벨만 `null`을 낸다. 라벨 추가는 가시성을 위한 것이지 안전을 위한 것이 아니다 |

---

## 8. 완료 기준

- `input_bound` 거절로 조사가 멈춘 run이 원장에 **이름 있는 이벤트**를 남긴다
- `_mark_stop_reason`의 어느 분기에도 안 걸리는 정지가 **`score_floor` 케이스뿐**이다
  (로드맵 §2.2 S4의 "무이벤트 정지 건수 목표 0" — 의도적 무이벤트는 제외)
- 강등 이벤트의 `reason`이 예외 타입이 아니라 **거절 사유**를 적는다
- 새 이벤트가 UI에 라벨로 뜨고, 강등으로는 **세지 않는다**
- `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/deep_analysis -q` 통과
- `pnpm --dir web test:source` 통과 · `pnpm --dir web exec tsc --noEmit` clean

---

## 9. 참조

- 로드맵: `docs/DEEP_ANALYSIS_HARNESS_ROADMAP.md` §7 G10 · §2.2 S4 · §10.2
- 선행 설계: [2026-08-07-deep-analysis-ledger-truth-design.md](2026-08-07-deep-analysis-ledger-truth-design.md) (G9)
- 결정 원장: `neos/workflow/deep_analysis/DECISIONS.md` (D26이 W2를 기록)
- G10을 적어둔 코드 주석: `neos/workflow/deep_analysis/orchestrator.py:262-270`
