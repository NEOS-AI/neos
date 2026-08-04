# 마무리 단계 예산 확보 구현 플랜 (G5)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 마무리 3단계(`node_reduction` · `report_assembly` · `report_grading`)가 항상 0이 아닌 토큰 예약을 받게 해, LLM이 쓴 리포트가 실제로 생성되게 한다.

**Architecture:** `TokenBudget`에 floor를 두고 `reserve()`가 stage에 따라 다른 천장을 쓴다 — 조사 stage는 floor 위에서만, 마무리 stage는 floor 아래까지. `Budgeter.should_stop`도 같은 선을 보고 조사를 끝내 거절 루프를 막는다. floor는 `service.py`에서 프로파일 해석과 함께 계산해 주입하며, 기본값 0이면 현행 동작이 그대로 보존된다.

**Tech Stack:** Python 3.12, pytest + pytest-asyncio, Pydantic (`StrictConfigModel`), 기존 deep_analysis 예산/카세트 인프라.

**설계 문서:** `docs/superpowers/specs/2026-08-03-deep-analysis-finalization-budget-design.md`

## Global Constraints

- **매직넘버 금지** — 모든 상수는 `neos/config/schema.py`의 설정으로 들어간다.
- **테스트에서 실 LLM/네트워크 금지** — 카세트 재생 또는 fake 주입만.
- **`deep_analysis_events`는 append-only (D8 §11.3)** — 새 kind 추가만, 기존 payload 형태 변경 금지.
- **이벤트 페이로드에 응답 텍스트 금지** — 카운트와 식별자만.
- **P2 단일 작성자** — grader는 ledger에 쓰지 않는다. Synthesizer는 이미 `synth_pass`를 쓰므로 작성자 자격이 있다.
- **하위호환이 이 플랜의 핵심 제약이다.** `floor_tokens` 기본값 0에서 기존 동작이 **완전히** 같아야 한다. `test_golden_integration.py:300`이 `global_token_cap=1000`으로 오케스트레이터를 만들고, `test_budgeter.py:57`이 `TokenBudget(100, ...)`을 쓴다 — floor를 전역 설정에서 계산하면 이 둘이 깨진다. **floor는 반드시 주입받는다.**
- **테스트 명령:** `HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/python -m pytest <paths> -q` (bare `pytest`는 asyncio 마커 수집 실패)
- **커밋 메시지에 `Co-Authored-By` 트레일러 금지.**

## File Structure

| 파일 | 책임 | 변경 |
|---|---|---|
| `neos/workflow/deep_analysis/token_budget.py` | floor 보유, stage별 천장 결정 | 수정 |
| `neos/workflow/deep_analysis/budgeter.py` | floor에서 조사 종료 | 수정 |
| `neos/config/schema.py` | `finalization_reduction_allowance`, dev `synthesis_max_tokens` | 수정 |
| `neos/workflow/deep_analysis/orchestrator.py` | floor를 받아 TokenBudget에 전달 | 수정 |
| `neos/workflow/deep_analysis/service.py` | 프로파일 해석 + floor 계산 + 주입 | 수정 |
| `neos/workflow/deep_analysis/synthesizer.py` | 합성 상한 주입, degraded 기록 | 수정 |
| `neos/workflow/deep_analysis/graders/report.py` | `judge_budget_exhausted` 표시 | 수정 |
| `neos/config/loader.py` | floor 불균형 경고 (백스톱) | 수정 |
| `docs/TODO_260729.md` | G5 상태 갱신 | 수정 |

Task 1–2가 예산 메커니즘, Task 3–4가 배선, Task 5가 백스톱, Task 6이 침묵 제거, Task 7이 회귀·문서다.

---

## Task 1: `TokenBudget`이 floor를 지킨다

**Files:**
- Modify: `neos/workflow/deep_analysis/token_budget.py` (`__init__`, `reserve`, 새 프로퍼티, 새 상수)
- Test: `tests/workflow/deep_analysis/test_budgeter.py`

**Interfaces:**
- Consumes: 없음 (첫 태스크)
- Produces:
  - `FINALIZATION_STAGES: frozenset[str]` — `{"node_reduction", "report_assembly", "report_grading"}`
  - `TokenBudget(cap_tokens, *, consumed_tokens=0, outstanding=None, persist=None, floor_tokens=0)`
  - `TokenBudget.available_for_investigation -> int` — `max(0, remaining_tokens - floor_tokens)`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/workflow/deep_analysis/test_budgeter.py` 끝에 추가한다. 이 파일은 `TokenBudget`을 이미 import한다.

```python
@pytest.mark.asyncio
async def test_investigation_cannot_reserve_below_the_floor():
    """floor는 마무리 단계 몫이다 — 조사 stage는 넘볼 수 없다."""
    budget = TokenBudget(10_000, floor_tokens=4_000)

    with pytest.raises(TokenBudgetExhausted):
        await budget.reserve(
            {"model": "m"}, 9_000, stage="worker_analysis", model="m"
        )


@pytest.mark.asyncio
async def test_investigation_is_clamped_to_the_floor_not_refused():
    """floor 위에 여유가 있으면 조사는 그만큼만 받는다."""
    budget = TokenBudget(10_000, floor_tokens=4_000)

    reservation = await budget.reserve(
        {"model": "m"}, 9_000, stage="worker_analysis", model="m"
    )

    # 6000에서 input_bound를 뺀 만큼. 정확한 input_bound는 계약이 아니므로
    # 상한만 단언한다.
    assert 0 < reservation.max_output_tokens <= 6_000


@pytest.mark.asyncio
async def test_finalization_stages_may_draw_on_the_floor():
    """마무리 stage만 floor 아래로 내려간다 — 이것이 이 작업의 목적이다."""
    budget = TokenBudget(10_000, floor_tokens=4_000)
    # 조사로 floor 위를 전부 소진한다.
    spent = await budget.reserve(
        {"model": "m"}, 9_000, stage="worker_analysis", model="m"
    )
    await budget.settle(spent, spent.reserved_tokens)

    assert budget.available_for_investigation == 0
    for stage in ("node_reduction", "report_assembly", "report_grading"):
        reservation = await budget.reserve(
            {"model": "m"}, 500, stage=stage, model="m"
        )
        assert reservation.max_output_tokens > 0
        await budget.settle(reservation, reservation.reserved_tokens)


@pytest.mark.asyncio
async def test_floor_defaults_to_zero_and_preserves_current_behaviour():
    """기존 호출부는 floor를 모른다 — 기본값에서 동작이 바뀌면 안 된다."""
    budget = TokenBudget(10_000)

    assert budget.floor_tokens == 0
    assert budget.available_for_investigation == budget.remaining_tokens
    reservation = await budget.reserve(
        {"model": "m"}, 9_000, stage="worker_analysis", model="m"
    )
    assert reservation.max_output_tokens > 8_000
```

- [ ] **Step 2: 실패를 확인한다**

```bash
HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/python -m pytest \
  tests/workflow/deep_analysis/test_budgeter.py -k "floor or finalization" -q
```

Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'floor_tokens'`

- [ ] **Step 3: 상수와 생성자를 추가한다**

`token_budget.py`의 `PersistEvent` 선언 아래에 상수를 넣는다.

```python
# Stages that run after investigation is over: hierarchical reduction, report
# assembly, and the report judgement. They are the only callers allowed to
# draw on the reserved floor.
#
# The budget layer knowing stage names is a deliberate coupling. Threading an
# `is_finalization` flag from each call site through call_llm / call_json /
# call_messages / _budgeted_dispatch would touch every caller; one constant is
# explicit, testable, and lives in a single place.
FINALIZATION_STAGES = frozenset({
    "node_reduction",
    "report_assembly",
    "report_grading",
})
```

`TokenBudget.__init__`에 인자를 더한다 (`persist` 다음, 키워드 전용 유지):

```python
        floor_tokens: int = 0,
    ) -> None:
        if cap_tokens < 0 or consumed_tokens < 0:
            raise ValueError("token counts must be non-negative")
        if floor_tokens < 0:
            raise ValueError("floor_tokens must be non-negative")
```

그리고 본문에 저장한다:

```python
        self.floor_tokens = floor_tokens
```

- [ ] **Step 4: 프로퍼티를 추가한다**

`remaining_tokens` 프로퍼티 바로 아래에 넣는다.

```python
    @property
    def available_for_investigation(self) -> int:
        """Remaining tokens that non-finalization stages may reserve.

        The floor is what stops the investigation loop from consuming the
        whole cap and leaving report assembly and grading to fail open --
        which is what every recorded run did before this existed.
        """
        return max(0, self.remaining_tokens - self.floor_tokens)
```

- [ ] **Step 5: `reserve()`가 stage를 본다**

`reserve()`의 `async with self._lock:` 블록 안 `output_tokens` 계산을 바꾼다.

```python
        input_bound = conservative_input_bound(request)
        async with self._lock:
            ceiling = (
                self.remaining_tokens
                if stage in FINALIZATION_STAGES
                else self.available_for_investigation
            )
            output_tokens = min(max_output_tokens, ceiling - input_bound)
            if output_tokens < 1:
                raise TokenBudgetExhausted("deep-analysis token budget exhausted")
```

나머지(예약 생성, 이벤트 기록, `_outstanding` 갱신)는 손대지 않는다.

- [ ] **Step 6: 테스트 통과를 확인한다**

```bash
HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/python -m pytest \
  tests/workflow/deep_analysis/test_budgeter.py \
  tests/workflow/deep_analysis/test_llm.py -q
```

Expected: PASS 전량. `test_llm.py`가 중요하다 — floor 없는 예산 경로의 하위호환을 거기서 확인한다.

- [ ] **Step 7: 커밋한다**

```bash
git add neos/workflow/deep_analysis/token_budget.py tests/workflow/deep_analysis/test_budgeter.py
git commit -m "feat(deep-analysis): reserve a token floor for finalization stages

The investigation loop stops when the budget is empty, so every recorded run
reached report assembly and grading with nothing left and both failed open --
assembly to a template, grading to the deterministic verdict.

TokenBudget now carries a floor that only node_reduction, report_assembly and
report_grading may draw on. Investigation stages are clamped above it and
refused when nothing is left there.

The floor defaults to zero, so every existing caller and test behaves exactly
as before; it is supplied by the callers that know the profile."
```

---

## Task 2: `Budgeter`가 floor에서 조사를 끝낸다

hard floor만 있으면 워커가 계속 예약을 시도해 거절당하고 `investigate()`가 `flush_partial`로 받아내며 라운드를 헛돈다. 조기 정지가 그 낭비를 막는다.

**Files:**
- Modify: `neos/workflow/deep_analysis/budgeter.py:116-121` (`should_stop`)
- Test: `tests/workflow/deep_analysis/test_budgeter.py`

**Interfaces:**
- Consumes: `TokenBudget.available_for_investigation` (Task 1)
- Produces: 없음 (동작 변경만)

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/workflow/deep_analysis/test_budgeter.py` 끝에 추가한다.

```python
@pytest.mark.asyncio
async def test_should_stop_when_only_the_floor_remains():
    """floor만 남으면 조사는 끝이다.

    계속 돌면 워커가 거절만 반복하고 flush_partial로 받아내며 라운드를 태운다.
    """

    class Ledger:
        async def total_spent(self):
            return 0

        async def open_questions(self):
            raise AssertionError("floor stop must short-circuit question lookup")

    budget = TokenBudget(10_000, floor_tokens=10_000)
    budgeter = Budgeter(global_token_cap=10_000, token_budget=budget)

    assert await budgeter.should_stop(Ledger()) is True
```

- [ ] **Step 2: 실패를 확인한다**

```bash
HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/python -m pytest \
  tests/workflow/deep_analysis/test_budgeter.py -k only_the_floor -q
```

Expected: FAIL — `AssertionError: floor stop must short-circuit question lookup` (현재는 `exhausted`가 False라 질문 조회로 넘어간다)

- [ ] **Step 3: 구현한다**

`budgeter.py:116-121`을 바꾼다.

```python
    async def should_stop(self, ledger) -> bool:
        if self.token_budget is not None:
            # The floor belongs to finalization. Investigation is done once it
            # is all that remains -- continuing only produces refused
            # reservations and wasted rounds.
            if self.token_budget.available_for_investigation <= 0:
                return True
        spent = await ledger.total_spent()
        if spent >= self.global_token_cap:
            return True
```

`self.token_budget`이 `None`인 경로는 기존 `spent` 검사를 그대로 탄다. floor 산식이 두 곳에 흩어지지 않도록 Budgeter는 floor를 직접 계산하지 않는다.

⚠️ 기존 `test_budget_exhaustion_short_circuits_question_lookup`(`test_budgeter.py:57` 부근)은 `TokenBudget(100, outstanding={"orphan": 100})` → `remaining_tokens == 0` → floor 0에서 `available_for_investigation == 0`이므로 **그대로 통과한다.**

- [ ] **Step 4: 테스트 통과를 확인한다**

```bash
HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/python -m pytest \
  tests/workflow/deep_analysis/test_budgeter.py \
  tests/workflow/deep_analysis/test_budgeter_select.py -q
```

Expected: PASS 전량

- [ ] **Step 5: 커밋한다**

```bash
git add neos/workflow/deep_analysis/budgeter.py tests/workflow/deep_analysis/test_budgeter.py
git commit -m "feat(deep-analysis): end investigation when only the floor is left

The hard floor in reserve() stops investigation from spending the reserve,
but on its own it makes workers keep asking and getting refused, with
investigate() absorbing each refusal through flush_partial and the round
producing nothing.

should_stop now reads the same line, so the loop ends instead of grinding
against it. The floor guarantees; this avoids the waste."
```

---

## Task 3: floor를 계산해 주입한다

**Files:**
- Modify: `neos/config/schema.py` (`DeepAnalysisConfig`에 설정 1개)
- Modify: `neos/workflow/deep_analysis/orchestrator.py:67`, `:92-95`, `:122`, `:153-158`
- Modify: `neos/workflow/deep_analysis/service.py:104-132`
- Test: `tests/workflow/deep_analysis/test_config_defaults.py`, `tests/workflow/deep_analysis/test_budgeter.py`

**Interfaces:**
- Consumes: `TokenBudget(..., floor_tokens=...)` (Task 1)
- Produces:
  - `settings.config.deep_analysis.finalization_reduction_allowance: int` — 기본 `2`
  - `Orchestrator(..., finalization_floor_tokens: int = 0)` — TokenBudget으로 전달된다

⚠️ **floor를 오케스트레이터 안에서 전역 설정으로 계산하면 안 된다.** `test_golden_integration.py:300`이 `global_token_cap=1000`으로 오케스트레이터를 만든다. 기본 floor 12,800을 안에서 계산하면 그 run의 조사 예산이 0이 되어 골든 테스트가 깨진다. **주입받고 기본값 0이어야 한다.**

- [ ] **Step 1: 설정 테스트를 쓴다**

`tests/workflow/deep_analysis/test_config_defaults.py` 끝에 추가한다.

```python
def test_finalization_reduction_allowance_default():
    from neos.config.settings import settings

    assert settings.config.deep_analysis.finalization_reduction_allowance == 2
```

- [ ] **Step 2: 주입 테스트를 쓴다**

`tests/workflow/deep_analysis/test_budgeter.py` 끝에 추가한다. import에 `Orchestrator`를 더한다: `from neos.workflow.deep_analysis.orchestrator import Orchestrator`.

```python
def test_orchestrator_floor_defaults_to_zero():
    """골든/통합 테스트가 작은 cap으로 오케스트레이터를 만든다.

    floor를 안에서 전역 설정으로 계산하면 그런 run의 조사 예산이 0이 된다.
    주입받고 기본값은 0이어야 한다.
    """
    orch = Orchestrator(
        object(), "run0001", lambda: None, None, global_token_cap=1000
    )

    assert orch.token_budget.floor_tokens == 0
    assert orch.token_budget.available_for_investigation == 1000


def test_orchestrator_accepts_an_injected_floor():
    orch = Orchestrator(
        object(),
        "run0001",
        lambda: None,
        None,
        global_token_cap=20_000,
        finalization_floor_tokens=4_400,
    )

    assert orch.token_budget.floor_tokens == 4_400
    assert orch.token_budget.available_for_investigation == 15_600
```

- [ ] **Step 3: 실패를 확인한다**

```bash
HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/python -m pytest \
  tests/workflow/deep_analysis/test_budgeter.py \
  tests/workflow/deep_analysis/test_config_defaults.py \
  -k "floor_defaults or injected_floor or reduction_allowance" -q
```

Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'finalization_floor_tokens'`

- [ ] **Step 4: 설정값을 추가한다**

`neos/config/schema.py`의 `DeepAnalysisConfig`, `report_uncited_ratio_max` 다음 줄에 넣는다.

```python
    # How many node_reduction calls the finalization floor budgets for.
    #
    # Measured: node_reduction runs a median of 2 times per run (max 9). Runs
    # with deeper trees will see their last reductions clamped, but assembly
    # and the judge survive -- which is the point of the reserve. Budgeting
    # for the observed maximum of 9 would put the floor at 40,800, more than
    # twice the dev profile's entire cap.
    finalization_reduction_allowance: int = Field(default=2, ge=1)
```

- [ ] **Step 5: 오케스트레이터가 floor를 받는다**

`orchestrator.py`의 `__init__` 시그니처에서 `global_token_cap: int | None = None` 다음 줄에 더한다.

```python
        finalization_floor_tokens: int = 0,
```

`self.global_token_cap = ...` 블록 다음에 저장한다.

```python
        # Injected, never computed here: integration and golden tests build
        # this orchestrator with caps as small as 1000, and a floor derived
        # from global config would leave those runs no investigation budget
        # at all. service.py computes it from the resolved profile.
        self.finalization_floor_tokens = finalization_floor_tokens
```

`orchestrator.py:122`의 생성을 바꾼다.

```python
        self.token_budget = TokenBudget(
            self.global_token_cap,
            floor_tokens=self.finalization_floor_tokens,
        )
```

`_install_token_budget`(`:153-158`)의 재생성도 바꾼다 — resume 경로가 floor를 잃으면 안 된다.

```python
        self.token_budget = TokenBudget(
            self.global_token_cap,
            consumed_tokens=consumed,
            outstanding=outstanding,
            persist=self._persist_token_budget,
            floor_tokens=self.finalization_floor_tokens,
        )
```

- [ ] **Step 6: `service.py`가 계산해 넘긴다**

`service.py`의 `max_depth = (...)` 다음, `return Orchestrator(` 앞에 넣는다.

```python
    # The floor buys one reduction per allowance, one assembly, and one judge.
    finalization_floor_tokens = (
        (config.finalization_reduction_allowance + 1) * config.synthesis_max_tokens
        + config.report_judge_max_output_tokens
    )
```

그리고 `Orchestrator(...)` 호출에 인자를 더한다.

```python
        finalization_floor_tokens=finalization_floor_tokens,
```

⚠️ 여기서는 전역 `config.synthesis_max_tokens`를 쓴다. 프로파일별 상한은 Task 4가
`dev_profile.synthesis_max_tokens`를 추가하면서 이 계산에 분기를 넣는다 — 그 설정값이
아직 존재하지 않으므로 지금 참조하면 `AttributeError`가 난다.

- [ ] **Step 7: 테스트 통과를 확인한다**

```bash
HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/python -m pytest \
  tests/workflow/deep_analysis/ -q --disable-warnings
```

Expected: PASS 전량. 특히 `test_golden_integration.py`와 `test_golden_gate.py`가 통과해야 한다 — 주입 기본값 0이 지켜졌다는 증거다.

- [ ] **Step 8: 커밋한다**

```bash
git add neos/config/schema.py neos/workflow/deep_analysis/orchestrator.py \
  neos/workflow/deep_analysis/service.py \
  tests/workflow/deep_analysis/test_budgeter.py \
  tests/workflow/deep_analysis/test_config_defaults.py
git commit -m "feat(deep-analysis): compute the finalization floor from config

The floor is derived where the profile is resolved -- one reduction per
configured allowance, one assembly, one judge -- and injected into the
orchestrator rather than computed inside it.

That placement is load-bearing. Integration and golden tests construct the
orchestrator with caps as small as 1000, and a floor read from global config
would leave those runs with no investigation budget at all. Injected with a
default of zero, they are untouched.

The allowance is 2 because node_reduction runs a median of twice per run.
Deeper trees clamp their last reductions; assembly and the judge survive,
which is what the reserve exists for."
```

---

## Task 4: dev 프로파일이 자기 합성 상한을 갖는다

이것이 설계의 핵심 수정이다. dev는 예산을 15배 줄이면서(300,000 → 20,000) 합성 상한은 큰 프로파일용 4,000을 그대로 물려받았다. floor가 dev에 안 맞는 진짜 이유가 이것이다.

**Files:**
- Modify: `neos/config/schema.py` (`DeepAnalysisDevProfileConfig`)
- Modify: `neos/workflow/deep_analysis/synthesizer.py:12-27` (생성자), `:85`, `:145`, `:230`
- Modify: `neos/workflow/deep_analysis/service.py`
- Test: `tests/workflow/deep_analysis/test_config_defaults.py`, `tests/workflow/deep_analysis/test_synthesizer.py`

**Interfaces:**
- Consumes: Task 3의 `finalization_floor_tokens` 계산
- Produces:
  - `settings.config.deep_analysis.dev_profile.synthesis_max_tokens: int` — 기본 `1200`
  - `Synthesizer(ledger, *, ..., synthesis_max_tokens: int | None = None)` — `None`이면 전역 설정값

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/workflow/deep_analysis/test_config_defaults.py`의 `test_deep_analysis_dev_profile_present`에 단언을 더한다(그 테스트는 이미 `dev.global_token_cap == 20000`을 확인한다).

```python
    assert dev.synthesis_max_tokens == 1200
```

그리고 `tests/workflow/deep_analysis/test_synthesizer.py` 끝에 추가한다. 이 파일에는 이미 `FakeLedger`(이벤트를 `self.events`에 모으고 `async def log(kind, qid, payload)`를 가진다)와 `LLMResponse` import가 있다.

```python
@pytest.mark.asyncio
async def test_synthesizer_uses_the_injected_ceiling():
    """dev는 cap을 15배 줄이면서 합성 상한은 물려받았다.

    상한을 주입받지 못하면 20000 예산에 4000짜리 호출을 세 번 넣게 된다.
    """
    seen = []

    async def recording_llm_call(model, prompt, **kw):
        seen.append(kw["max_tokens"])
        return LLMResponse(
            text="보고서", input_tokens=1, output_tokens=1, model=model
        )

    synth = Synthesizer(
        FakeLedger(),
        llm_call=recording_llm_call,
        synthesis_max_tokens=1200,
    )

    await synth.assemble(None, [], [])

    assert seen == [1200]


@pytest.mark.asyncio
async def test_synthesizer_falls_back_to_the_global_ceiling():
    seen = []

    async def recording_llm_call(model, prompt, **kw):
        seen.append(kw["max_tokens"])
        return LLMResponse(
            text="보고서", input_tokens=1, output_tokens=1, model=model
        )

    synth = Synthesizer(FakeLedger(), llm_call=recording_llm_call)

    await synth.assemble(None, [], [])

    assert seen == [settings.config.deep_analysis.synthesis_max_tokens]
```

`settings`는 이 파일이 이미 import한다.

- [ ] **Step 2: 실패를 확인한다**

```bash
HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/python -m pytest \
  tests/workflow/deep_analysis/test_synthesizer.py \
  tests/workflow/deep_analysis/test_config_defaults.py -q
```

Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'synthesis_max_tokens'`

- [ ] **Step 3: dev 프로파일 설정을 추가한다**

`neos/config/schema.py`의 `DeepAnalysisDevProfileConfig`(`max_depth` 다음 줄)에 넣는다.

```python
    # dev shrinks the budget 15x (300000 -> 20000) but inherited a synthesis
    # ceiling sized for the full profile, which is why the finalization floor
    # did not fit: three 4000-token calls against a 20000 cap.
    #
    # 1200 is measured, not chosen for roundness -- node_reduction's actual
    # consumption ran a median of 1109 tokens INCLUDING input, at granted
    # ceilings whose median was 748.
    synthesis_max_tokens: int = 1200
```

- [ ] **Step 4: `Synthesizer`가 상한을 주입받는다**

생성자에 인자를 더한다(`cassette` 다음, 키워드 전용 유지).

```python
        synthesis_max_tokens: int | None = None,
    ) -> None:
        self.ledger = ledger
        self.llm_call = llm_call
        self.json_call = json_call
        self.llm_client = llm_client
        self.cassette = cassette
        # None means "use the global default" so every existing construction
        # site keeps working; service.py passes the profile-resolved value.
        self._synthesis_max_tokens = synthesis_max_tokens
```

그리고 프로퍼티를 더한다:

```python
    @property
    def synthesis_max_tokens(self) -> int:
        if self._synthesis_max_tokens is not None:
            return self._synthesis_max_tokens
        return settings.config.deep_analysis.synthesis_max_tokens
```

`synthesizer.py`의 세 호출부(`:85`, `:145`, `:230`)에서 `max_tokens=config.synthesis_max_tokens`를 `max_tokens=self.synthesis_max_tokens`로 바꾼다. 세 곳 전부다 — 하나라도 남으면 dev가 여전히 4000을 쓴다.

- [ ] **Step 5: `service.py`가 프로파일 값을 넘긴다**

Task 3에서 넣은 floor 계산을 프로파일 분기로 바꾼다.

```python
    synthesis_max_tokens = (
        config.dev_profile.synthesis_max_tokens
        if profile == "dev"
        else config.synthesis_max_tokens
    )
    finalization_floor_tokens = (
        (config.finalization_reduction_allowance + 1) * synthesis_max_tokens
        + config.report_judge_max_output_tokens
    )
```

⚠️ **`Synthesizer`는 `service.py`가 아니라 `orchestrator.py:79`가 만든다.** 그래서 상한은 오케스트레이터를 통과해야 한다.

`orchestrator.py`의 `__init__` 시그니처에 `synthesis_max_tokens: int | None = None`을 더하고, `:79`의 기본 생성에 넘긴다.

```python
        self.synthesizer = synthesizer or Synthesizer(
            self.ledger,
            llm_client=llm_client,
            cassette=cassette,
            synthesis_max_tokens=synthesis_max_tokens,
        )
```

`synthesizer`가 주입된 경우(테스트 대부분)는 그 객체를 그대로 쓰므로 영향이 없다.

그리고 `service.py`의 `Orchestrator(...)` 호출에 더한다.

```python
        synthesis_max_tokens=synthesis_max_tokens,
```

- [ ] **Step 6: 테스트 통과를 확인한다**

```bash
HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/python -m pytest \
  tests/workflow/deep_analysis/ -q --disable-warnings
```

Expected: PASS 전량

- [ ] **Step 7: 커밋한다**

```bash
git add neos/config/schema.py neos/workflow/deep_analysis/synthesizer.py \
  neos/workflow/deep_analysis/service.py \
  tests/workflow/deep_analysis/test_synthesizer.py \
  tests/workflow/deep_analysis/test_config_defaults.py
git commit -m "feat(deep-analysis): give the dev profile its own synthesis ceiling

dev overrides the budget cap, worker count and depth, but not
synthesis_max_tokens -- so it shrank its budget fifteenfold while keeping a
ceiling sized for the full profile. Three 4000-token calls against a 20000
cap is why the finalization floor appeared not to fit.

At 1200 the floor costs dev 4400 instead of 12800, leaving 78% of its budget
for investigation while it runs the finalization chain for the first time.
The number is measured: node_reduction consumed a median of 1109 tokens
including input, at granted ceilings whose median was 748.

This is also why dev never surfaced the bug -- the profile meant to exercise
the pipeline cheaply has been skipping its last third."
```

---

## Task 5: 불균형한 floor를 경고한다 (백스톱)

기본 설정에서는 **발생하지 않는다**. 잘못 튜닝된 프로파일을 잡기 위한 백스톱이다.

**Files:**
- Modify: `neos/config/loader.py` (`warn_yaml_only_feature_flag_env` 인근)
- Test: `tests/workflow/deep_analysis/test_config_defaults.py`

**Interfaces:**
- Consumes: Task 3·4의 설정값
- Produces: `warn_finalization_floor_ratio(config) -> None` — `UserWarning` 발생

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
def test_default_config_does_not_warn_about_the_floor():
    """기본값에서 보일 경고가 아니다 — 보인다면 산식이나 기본값이 틀린 것이다."""
    import warnings

    from neos.config.loader import warn_finalization_floor_ratio
    from neos.config.settings import settings

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        warn_finalization_floor_ratio(settings.config.deep_analysis)

    assert [w for w in caught if issubclass(w.category, UserWarning)] == []


def test_a_disproportionate_floor_warns():
    import warnings

    from neos.config.loader import warn_finalization_floor_ratio
    from neos.config.settings import settings

    config = settings.config.deep_analysis.model_copy(deep=True)
    config.dev_profile.global_token_cap = 4000  # floor 4400 > 2000

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        warn_finalization_floor_ratio(config)

    messages = [str(w.message) for w in caught]
    assert any("4400" in m and "4000" in m for m in messages)
```

- [ ] **Step 2: 실패를 확인한다**

```bash
HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/python -m pytest \
  tests/workflow/deep_analysis/test_config_defaults.py -k floor -q
```

Expected: FAIL — `ImportError: cannot import name 'warn_finalization_floor_ratio'`

- [ ] **Step 3: 구현한다**

`neos/config/loader.py`의 `warn_yaml_only_feature_flag_env` 아래에 넣는다.

```python
_FINALIZATION_FLOOR_WARN_RATIO = 0.5


def warn_finalization_floor_ratio(deep_analysis) -> None:
    """Warn when the finalization reserve crowds out investigation.

    Not expected to fire on the shipped defaults -- it is a backstop for a
    profile tuned into a corner, where the reserve would leave too little
    budget to investigate anything worth reporting on.
    """

    def _floor(synthesis: int) -> int:
        return (
            (deep_analysis.finalization_reduction_allowance + 1) * synthesis
            + deep_analysis.report_judge_max_output_tokens
        )

    profiles = (
        ("default", deep_analysis.global_token_cap,
         _floor(deep_analysis.synthesis_max_tokens)),
        ("dev", deep_analysis.dev_profile.global_token_cap,
         _floor(deep_analysis.dev_profile.synthesis_max_tokens)),
    )
    for name, cap, floor in profiles:
        if cap > 0 and floor >= cap * _FINALIZATION_FLOOR_WARN_RATIO:
            warnings.warn(
                f"deep_analysis {name} profile: finalization floor {floor} is "
                f"{floor / cap:.0%} of global_token_cap {cap}; raise the cap or "
                f"lower finalization_reduction_allowance / synthesis_max_tokens.",
                UserWarning,
                stacklevel=2,
            )
```

호출 지점은 설정 로드 경로에서 `warn_yaml_only_feature_flag_env`가 불리는 곳 옆이다. **`grep -n "warn_yaml_only_feature_flag_env" neos/config/loader.py`로 호출부를 확인하고 같은 자리에 더할 것.**

- [ ] **Step 4: 테스트 통과를 확인한다**

```bash
HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/python -m pytest \
  tests/workflow/deep_analysis/test_config_defaults.py -q
```

Expected: PASS

- [ ] **Step 5: 커밋한다**

```bash
git add neos/config/loader.py tests/workflow/deep_analysis/test_config_defaults.py
git commit -m "feat(config): warn when the finalization floor crowds out investigation

A backstop, not a signal for normal operation: on the shipped defaults the
floor is 4.3% of the default profile's cap and 22% of dev's, so this never
fires. It catches a profile tuned into a corner, where the reserve would
leave too little budget to investigate anything worth reporting on.

A warning rather than a hard failure precisely because nobody should see it
-- making an unreachable condition fatal buys nothing, and the repo already
warns this way for yaml-only feature flags."
```

---

## Task 6: 조용한 fallback이 흔적을 남긴다

floor가 있어도 clamp는 일어날 수 있고, floor가 깨지면 예전 침묵이 그대로 돌아온다. `synth_pass = 0`을 알아채는 데 세션 하나가 걸렸다.

**Files:**
- Modify: `neos/workflow/deep_analysis/synthesizer.py:143-153` (`except TokenBudgetExhausted`)
- Modify: `neos/workflow/deep_analysis/graders/report.py` (`grade`의 `except TokenBudgetExhausted`)
- Test: `tests/workflow/deep_analysis/test_synthesizer.py`, `tests/workflow/deep_analysis/test_report_grader.py`

**Interfaces:**
- Consumes: 없음
- Produces:
  - ledger 이벤트 `report_assembly_degraded`, 페이로드 `{"reason": "token_budget_exhausted"}`
  - `Verdict(ok=True, detail="judge_budget_exhausted")` — 오케스트레이터의 `report_graded`가 이미 `verdict.diagnostics`를 싣는 경로로 흐른다

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/workflow/deep_analysis/test_synthesizer.py`에 추가한다.

```python
@pytest.mark.asyncio
async def test_template_fallback_is_recorded():
    """예산 고갈로 템플릿으로 떨어지는 것이 성공처럼 보이면 안 된다.

    이 침묵 때문에 synth_pass=0을 알아채는 데 세션 하나가 걸렸다.
    """

    async def exhausted_llm_call(model, prompt, **kw):
        raise TokenBudgetExhausted("cap")

    ledger = FakeLedger()
    synth = Synthesizer(ledger, llm_call=exhausted_llm_call)

    report = await synth.assemble(None, [], [])

    assert report  # 빈손 종료는 없다 (§6.8)
    kinds = [kind for (kind, _qid, _payload) in ledger.events]
    assert "report_assembly_degraded" in kinds
```

`FakeLedger`와 `TokenBudgetExhausted`는 이 파일이 이미 갖고 있다 — `FakeLedger.log`가
`(kind, qid, payload)` 튜플을 `self.events`에 넣는다.

`tests/workflow/deep_analysis/test_report_grader.py`에 추가한다.

```python
@pytest.mark.asyncio
async def test_budget_exhausted_judge_is_marked_not_silent():
    root = Question("root0001", "루트 질문")
    grader = _grader(
        FakeLedger(children=[CHILD1, CHILD2], root=root),
        json_call=_exhausted_json_call,
    )

    verdict = await grader.grade(_clean_report(), root.id)

    assert verdict.ok is True
    assert verdict.detail == "judge_budget_exhausted"
```

- [ ] **Step 2: 실패를 확인한다**

```bash
HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/python -m pytest \
  tests/workflow/deep_analysis/test_synthesizer.py \
  tests/workflow/deep_analysis/test_report_grader.py -k "degraded or budget_exhausted_judge" -q
```

Expected: FAIL — 이벤트 없음 / `detail`이 빈 문자열

- [ ] **Step 3: synthesizer가 기록한다**

`synthesizer.py`의 `except TokenBudgetExhausted:` 블록을 바꾼다.

```python
        except TokenBudgetExhausted:
            # Falling back to a template is correct -- no empty-handed exit
            # (§6.8) -- but it must not look like success. Every recorded run
            # took this path and nothing said so.
            qid = root_summary.question_id if root_summary is not None else ""
            await self.ledger.log(
                "report_assembly_degraded",
                qid,
                {"reason": "token_budget_exhausted"},
            )
            return self.deterministic_report(
                root_summary,
                child_summaries,
                caveats,
            )
```

- [ ] **Step 4: report grader가 표시한다**

`graders/report.py`의 `grade`에서 `except TokenBudgetExhausted: return deterministic`을 바꾼다.

```python
        except TokenBudgetExhausted:
            # Same fallback as before, but no longer indistinguishable from a
            # judge that ran and approved. P2 keeps this grader read-only, so
            # the marker rides the verdict to the orchestrator's event.
            return replace(deterministic, detail="judge_budget_exhausted")
```

파일 상단에 `from dataclasses import replace`를 추가한다. `deterministic`을 제자리에서 고치지 않는 이유는 그 객체가 호출부에 이미 반환됐을 수 있기 때문이다.

- [ ] **Step 5: 테스트 통과를 확인한다**

```bash
HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/python -m pytest \
  tests/workflow/deep_analysis/ -q --disable-warnings
```

Expected: PASS 전량

- [ ] **Step 6: 커밋한다**

```bash
git add neos/workflow/deep_analysis/synthesizer.py \
  neos/workflow/deep_analysis/graders/report.py \
  tests/workflow/deep_analysis/test_synthesizer.py \
  tests/workflow/deep_analysis/test_report_grader.py
git commit -m "feat(deep-analysis): record the two budget-exhaustion fallbacks

Falling back to a template report, and to the deterministic verdict, are
both correct responses to an exhausted budget -- neither exits empty-handed.
What was wrong is that both were indistinguishable from success.

That silence is why synth_pass sitting at zero across 165 report gradings
went unnoticed. Assembly now logs report_assembly_degraded, and the grader
marks its verdict judge_budget_exhausted, which rides to the orchestrator's
existing report_graded event since P2 keeps the grader read-only."
```

---

## Task 7: 전체 회귀와 문서 갱신

**Files:**
- Modify: `docs/TODO_260729.md`
- Test: 전량 + Ruff

**Interfaces:**
- Consumes: Task 1–6
- Produces: 없음 (종결)

- [ ] **Step 1: deep_analysis 전량**

```bash
HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/python -m pytest \
  tests/workflow/deep_analysis/ -q --disable-warnings
```

Expected: PASS. 직전 기준선은 460 passed이며 이 플랜이 추가한 만큼 늘어난다.

- [ ] **Step 2: 라우팅·노드 회귀**

```bash
HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/python -m pytest \
  tests/workflow/routing/test_deep_analysis_routing.py \
  tests/workflow/test_deep_analysis_node.py -q
```

Expected: PASS

- [ ] **Step 3: Ruff**

```bash
/Users/ywsung/Desktop/neos/.venv/bin/ruff check \
  neos/workflow/deep_analysis/ neos/config/ tests/workflow/deep_analysis/
```

Expected: 통과. 실패하면 고치고 Step 1을 다시 돌린다.

- [ ] **Step 4: `docs/TODO_260729.md`를 갱신한다**

G5 절 머리에 넣는다.

```markdown
**상태: 해소됨 (2026-08-03).** 마무리 3단계가 floor에서 0이 아닌 예약을 받는다.
dev는 자기 합성 상한(1200)을 갖게 되어 floor가 4,400으로 내려갔고 조사 예산의
78%를 유지한다. 두 fallback은 이제 흔적을 남긴다
(`report_assembly_degraded`, `judge_budget_exhausted`).

⚠️ **`synth_pass`가 실제로 기록되는지는 다음 실행 표본에서 확인해야 한다.**
이 작업은 예약을 보장할 뿐이고, 보장이 실제 산출로 이어졌다는 증거는 아직 없다.
```

「권장 순서」의 G5 항목을 해소 처리하고, G3에 다음을 덧붙인다.

```markdown
⚠️ **G5 이후 판단 근거가 달라졌다.** 게이트가 채점하던 대상이 템플릿에서 LLM
산출물로 바뀌므로, G3의 「빈 리포트가 통과한다」는 관측을 **새 표본에서 다시
확인한 뒤** 정책을 정해야 한다.
```

- [ ] **Step 5: 커밋한다**

```bash
git add docs/TODO_260729.md
git commit -m "docs: record the finalization budget floor

G5 is closed: the three finalization stages now receive a non-zero
reservation, dev carries its own synthesis ceiling, and both
budget-exhaustion fallbacks leave a record.

What is not yet evidence: whether synth_pass actually starts being written.
This work guarantees the reservation, not the output, and the distinction
matters after a session spent discovering how much silent degradation hid
behind reasonable-looking fallbacks.

G3 also needs re-deciding rather than resuming. The gate was scoring a
template; it will now score generated prose, so 'empty reports pass' has to
be re-observed on a fresh sample before any policy follows from it."
```

---

## 완료 기준

1. 마무리 3단계가 0이 아닌 예약을 받는다 (Task 1).
2. 조사 stage가 floor 아래로 예약할 수 없다 (Task 1).
3. `should_stop`이 floor에서 멈춘다 (Task 2).
4. `floor_tokens=0`에서 기존 동작이 완전히 보존된다 — 골든 테스트가 증거다 (Task 3).
5. dev가 조사 예산 78%를 유지하며 마무리 체인을 실행한다 (Task 4).
6. 기본 설정에서 경고가 발생하지 않는다 (Task 5).
7. 두 fallback이 흔적을 남긴다 (Task 6).
8. deep_analysis 테스트 전량과 Ruff가 통과한다 (Task 7).
