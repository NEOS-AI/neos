# 마무리 예산 floor 분할 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `report_assembly` 단계가 `node_reduction` 호출 수와 무관하게 유효한 토큰 예약을 받아, 574 run 동안 한 번도 실행된 적 없는 LLM 리포트 조립이 실제로 실행되게 한다.

**Architecture:** 단일 floor를 중첩 계단으로 쪼갠다 — `report_assembly`·`report_grading`만 접근 가능한 안쪽 tier(`report_floor_tokens`)를 두어 리덕션이 조립 몫에 물리적으로 닿지 못하게 한다. 두 tier 모두 `TokenBudget.reserve`가 실제로 차감하는 통화(입력 바운드 + 출력)로 사이징하고, 마무리 프롬프트는 **예산이 쓰는 것과 동일한 함수**로 측정해 허용량 안으로 강제 축소한다.

**Tech Stack:** Python 3.12, Pydantic v2 (`StrictConfigModel`), pytest + pytest-asyncio

**설계 정본:** [../specs/2026-08-04-deep-analysis-finalization-floor-split-design.md](../specs/2026-08-04-deep-analysis-finalization-floor-split-design.md)

## Global Constraints

- **테스트 실행은 `.venv` 경로로.** bare `pytest`는 asyncio 마커 수집에 실패한다.
  전체: `.venv/bin/python -m pytest` · 대상 스위트: `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/deep_analysis -q`
- **전체 스위트 기준선은 2,234 passed / 0 failed.** 실패가 하나라도 보이면 실제 회귀로 취급한다.
  회귀 비교 시 `grep '^FAILED tests/'`로 거른다 — `'^FAILED'`만 쓰면 진행 표시(`FAILED  [ 7%]`)까지 걸린다.
- **커밋 메시지에 `Co-Authored-By` 트레일러를 넣지 않는다.**
- **매직넘버 금지.** 모든 수치는 `neos/config/schema.py`의 설정으로. 프롬프트는 전부 `prompts/*.md` 파일.
- **append-only 이벤트 로그** (D8). 이벤트 페이로드에는 개수와 식별자만 싣는다 — 응답 텍스트·리포트 본문 금지.
- **`conservative_input_bound`를 완화하지 않는다.** `settle()`이 `actual > reserved`에서 `TokenBudgetContractError`를 내므로 bound는 입력 토큰의 참인 상한이어야 한다.
- **라이브 표본을 실행하지 않는다.** 검증은 결정론 테스트까지다.
- 한국어 주석/문서, 영문 docstring — 각 파일의 기존 관행을 따른다.

---

## File Structure

| 파일 | 책임 |
|---|---|
| `neos/workflow/deep_analysis/token_budget.py` | 계단형 ceiling. `REPORT_STAGES` 신설, `report_floor_tokens` 파라미터·불변식·`available_for_reduction` |
| `neos/config/schema.py` | 입력 비율 3종, `report_floor_tokens()` 신설, `finalization_floor_tokens()` 산식 교체, dev cap 상향 |
| `neos/workflow/deep_analysis/llm.py` | `prompt_input_bound()` — 예산과 같은 자 |
| `neos/workflow/deep_analysis/prompt_clamp.py` | **신규.** 축소 정책 + 렌더·측정·축소 루프. 순수 함수라 LLM·DB 없이 테스트된다 |
| `neos/workflow/deep_analysis/synthesizer.py` | `assemble`·`reduce_node`에 클램프 배선, 이벤트 2종 기록 |
| `neos/workflow/deep_analysis/orchestrator.py` | `report_floor_tokens`를 `TokenBudget` 두 생성 지점에 전달 |
| `neos/workflow/deep_analysis/service.py` | 두 floor를 config에서 계산해 주입 |

**스펙 대비 조정 2건** (구현 중 더 나은 경계가 드러난 부분):

1. 클램프 로직을 `synthesizer.py`가 아니라 신규 `prompt_clamp.py`에 둔다. 순수 함수로 분리하면 T5가 LLM·ledger 없이 성립한다.
2. 입력 허용량을 `service.py`에서 주입하지 않고 `Synthesizer`의 프로퍼티로 계산한다. `synthesis_max_tokens`가 이미 프로파일 해석된 값으로 들어와 있고 비율은 전역이므로, 생성자 파라미터 2개를 늘리는 것보다 단일 원천에 가깝다.

---

## Task 1: `TokenBudget`에 report tier 추가

**Files:**
- Modify: `neos/workflow/deep_analysis/token_budget.py:17-29` (상수), `:66-117` (`__init__`/프로퍼티), `:131-137` (ceiling)
- Test: `tests/workflow/deep_analysis/test_budgeter.py`

**Interfaces:**
- Consumes: 없음 (첫 태스크)
- Produces:
  - `REPORT_STAGES: frozenset[str]` — `{"report_assembly", "report_grading"}`
  - `TokenBudget(..., report_floor_tokens: int = 0)`
  - `TokenBudget.report_floor_tokens: int`
  - `TokenBudget.available_for_reduction -> int`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/workflow/deep_analysis/test_budgeter.py` 끝에 추가한다. 파일 상단 import에 `conservative_input_bound`가 이미 있다(현재 173행에서 사용 중).

```python
@pytest.mark.asyncio
async def test_node_reduction_cannot_reach_the_report_tier():
    """G7: 리덕션이 몇 번 돌든 조립 몫에 닿지 못한다.

    `reduce_tree`는 노드마다 `reduce_node`를 부르고 상한이 없다 --
    `finalization_reduction_allowance`는 floor의 크기만 정했지 호출 수를
    제한한 적이 없다. 실측 6 run 평균 3.7회 vs allowance 2. 안쪽 tier가
    호출 카운터 없이 이 초과를 무해하게 만든다.
    """
    budget = TokenBudget(
        10_000, floor_tokens=6_000, report_floor_tokens=4_000
    )

    # 조사와 리덕션이 접근 가능한 것을 전부 태운다.
    spent = await budget.reserve(
        {"model": "m"}, 10_000, stage="node_reduction", model="m"
    )
    await budget.settle(spent, spent.reserved_tokens)

    assert budget.available_for_reduction == 0
    with pytest.raises(TokenBudgetExhausted):
        await budget.reserve(
            {"model": "m"}, 500, stage="node_reduction", model="m"
        )

    # 조립은 여전히 자기 몫을 받는다 -- 이것이 이 작업 전체의 목적이다.
    reservation = await budget.reserve(
        {"model": "m"}, 500, stage="report_assembly", model="m"
    )
    assert reservation.max_output_tokens > 0


def test_report_tier_may_not_exceed_the_total_floor():
    """안쪽 tier가 바깥 tier보다 크면 계단이 아니라 모순이다."""
    with pytest.raises(ValueError):
        TokenBudget(10_000, floor_tokens=1_000, report_floor_tokens=2_000)

    with pytest.raises(ValueError):
        TokenBudget(10_000, floor_tokens=1_000, report_floor_tokens=-1)


@pytest.mark.asyncio
async def test_report_tier_defaults_to_zero_and_preserves_current_behaviour():
    """기존 호출부는 안쪽 tier를 모른다 -- 기본값에서 동작이 바뀌면 안 된다."""
    budget = TokenBudget(10_000, floor_tokens=4_000)

    assert budget.report_floor_tokens == 0
    assert budget.available_for_reduction == budget.remaining_tokens
```

- [ ] **Step 2: 실패를 확인한다**

Run: `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/deep_analysis/test_budgeter.py -q -k "report_tier or reach_the_report"`
Expected: FAIL — `TypeError: TokenBudget.__init__() got an unexpected keyword argument 'report_floor_tokens'`

- [ ] **Step 3: 상수를 쪼갠다**

`token_budget.py`의 `FINALIZATION_STAGES` 블록(17-29행)을 통째로 아래로 바꾼다.

```python
# The report is the run's only user-visible product. `node_reduction`
# improving a summary that will never be assembled is worthless, yet it
# drew first from the shared floor and starved assembly in every recorded
# run -- `reduce_tree` calls `reduce_node` once per node and nothing caps
# that count. `REPORT_STAGES` is the inner tier reduction cannot reach.
REPORT_STAGES = frozenset({
    "report_assembly",
    "report_grading",
})

# Stages that run after investigation is over: hierarchical reduction plus
# everything in REPORT_STAGES. They are the only callers allowed to draw on
# the reserved floor.
#
# The budget layer knowing stage names is a deliberate coupling. Threading an
# `is_finalization` flag from each call site through call_llm / call_json /
# call_messages / _budgeted_dispatch would touch every caller; one constant is
# explicit, testable, and lives in a single place.
FINALIZATION_STAGES = frozenset({
    "node_reduction",
    *REPORT_STAGES,
})
```

- [ ] **Step 4: `__init__`에 파라미터와 불변식을 넣는다**

`__init__` 시그니처의 `floor_tokens: int = 0,` 바로 아래에 추가한다.

```python
        report_floor_tokens: int = 0,
```

검증 블록에서 `if floor_tokens < 0:` 뒤에 이어 붙인다.

```python
        if report_floor_tokens < 0:
            raise ValueError("report_floor_tokens must be non-negative")
        if report_floor_tokens > floor_tokens:
            raise ValueError(
                "report_floor_tokens must not exceed floor_tokens"
            )
```

`self.floor_tokens = floor_tokens` 바로 아래에 추가한다.

```python
        self.report_floor_tokens = report_floor_tokens
```

- [ ] **Step 5: `available_for_reduction` 프로퍼티를 추가한다**

`available_for_investigation` 프로퍼티 바로 아래에 넣는다.

```python
    @property
    def available_for_reduction(self) -> int:
        """Remaining tokens `node_reduction` may reserve.

        Isolating the report's tier enforces the reduction allowance
        without a call counter. `finalization_reduction_allowance` sizes
        the floor but never limited how many times `reduce_node` runs;
        reductions past the allowance now degrade through the path they
        already have (synthesizer.py) instead of eating the assembly's
        reservation.
        """
        return max(0, self.remaining_tokens - self.report_floor_tokens)
```

- [ ] **Step 6: ceiling을 계단으로 바꾼다**

`reserve` 안의 기존 3줄

```python
            ceiling = (
                self.remaining_tokens
                if stage in FINALIZATION_STAGES
                else self.available_for_investigation
            )
```

를 아래로 바꾼다.

```python
            if stage in REPORT_STAGES:
                ceiling = self.remaining_tokens
            elif stage in FINALIZATION_STAGES:
                ceiling = self.available_for_reduction
            else:
                ceiling = self.available_for_investigation
```

- [ ] **Step 7: 테스트 통과를 확인한다**

Run: `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/deep_analysis/test_budgeter.py -q`
Expected: PASS — 신규 3건 포함 전부. 기존 `test_finalization_stages_may_draw_on_the_floor`는 `report_floor_tokens` 기본값 0 덕분에 그대로 통과한다.

- [ ] **Step 8: 커밋**

```bash
git add neos/workflow/deep_analysis/token_budget.py tests/workflow/deep_analysis/test_budgeter.py
git commit -m "feat(deep-analysis): give the report its own budget tier

node_reduction drew from the same floor as report_assembly and, having no
cap on how many times reduce_tree calls it, took the assembly's share in
every recorded run. An inner tier it cannot reach enforces the split
without a call counter."
```

---

## Task 2: 입력 통화로 floor를 다시 계산한다

**Files:**
- Modify: `neos/config/schema.py:633-644` (dev 프로파일), `:800-807` (allowance 주석), `:894-909` (산식)
- Test: `tests/workflow/deep_analysis/test_config_defaults.py:41-46`, `:127-141`

**Interfaces:**
- Consumes: 없음
- Produces:
  - `DeepAnalysisConfig.reduction_input_ratio: float` (1.6)
  - `DeepAnalysisConfig.assembly_input_ratio: float` (3.0)
  - `DeepAnalysisConfig.grading_input_ratio: float` (5.0)
  - `DeepAnalysisConfig.report_floor_tokens(synthesis_max_tokens: int) -> int`
  - `DeepAnalysisConfig.finalization_floor_tokens(synthesis_max_tokens: int) -> int` (기존 시그니처 유지, 값 변경)
  - `DeepAnalysisDevProfileConfig.global_token_cap == 100000`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/workflow/deep_analysis/test_config_defaults.py` 끝에 추가한다.

```python
def test_the_floor_counts_input_not_only_output():
    """G6: floor는 출력만 셌고 reserve()는 입력+출력을 뺐다.

    node_reduction 한 번의 input_bound 실측 최대는 6,480 -- 기존 dev floor
    4,400 전체보다 크다. 두 tier 모두 reserve()가 실제로 차감하는 통화로
    사이징돼야 한다.
    """
    from neos.config.schema import DeepAnalysisConfig

    config = DeepAnalysisConfig()

    # default 프로파일: assembly (3.0+1)*4000=16,000 / grading 5.0*4000+800=20,800
    # -> attempt 36,800 * (report_retry_cap 2 + 1) = 110,400
    assert config.report_floor_tokens(4_000) == 110_400
    # reduction (1.6+1)*4000=10,400 * allowance 2 = 20,800
    assert config.finalization_floor_tokens(4_000) == 110_400 + 20_800

    # dev 프로파일 (synthesis_max_tokens=1200)
    assert config.report_floor_tokens(1_200) == 34_800
    assert config.finalization_floor_tokens(1_200) == 41_040


def test_the_report_tier_never_exceeds_the_total_floor():
    """TokenBudget의 불변식이 config 산식에서 이미 성립해야 한다."""
    from neos.config.schema import DeepAnalysisConfig

    config = DeepAnalysisConfig()
    for synth in (1, 100, 1_200, 4_000, 40_000):
        assert config.report_floor_tokens(synth) <= (
            config.finalization_floor_tokens(synth)
        )


def test_dev_profile_can_hold_a_worker_call():
    """실측 worker_analysis input_bound는 5,542~17,723이다.

    dev의 기존 20,000 캡은 floor를 빼기 전에도 워커 호출 하나를 확실히
    담지 못했다 -- dev run이 병리적이었던 이유다.
    """
    from neos.config.schema import DeepAnalysisConfig

    config = DeepAnalysisConfig()
    cap = config.dev_profile.global_token_cap
    floor = config.finalization_floor_tokens(
        config.dev_profile.synthesis_max_tokens
    )

    assert cap - floor > 17_723 * 2
```

- [ ] **Step 2: 실패를 확인한다**

Run: `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/deep_analysis/test_config_defaults.py -q -k "input_not_only_output or report_tier_never or hold_a_worker"`
Expected: FAIL — `AttributeError: 'DeepAnalysisConfig' object has no attribute 'report_floor_tokens'`

- [ ] **Step 3: 입력 비율 3종을 추가한다**

`schema.py`의 `min_viable_output_tokens` 필드 정의 바로 아래(831행 다음)에 넣는다.

```python
    # Input allowances for the finalization stages, expressed as multiples of
    # `synthesis_max_tokens` so a profile that shrinks its synthesis ceiling
    # shrinks its floor with it instead of needing three more per-profile
    # knobs.
    #
    # These exist because the floor and `TokenBudget.reserve` used different
    # currencies: the floor counted output tokens only, while `reserve`
    # charges `conservative_input_bound(request) + output`. Measured
    # 2026-08-04: one node_reduction took 6,480 on input alone -- larger than
    # the entire 4,400-token dev floor of the time.
    #
    # Measured: node_reduction input_bound ran 1,225 / 1,369 / 6,480
    # (min/median/max) against synthesis_max_tokens=4000 -> 6480/4000 = 1.62.
    reduction_input_ratio: float = Field(default=1.6, gt=0.0)
    # Never measured -- report_assembly has never received a reservation in
    # 574 runs. This is not an estimate but a CLAMP: `prompt_clamp` shrinks
    # the assembly prompt until `prompt_input_bound` reports a value under
    # this allowance, so the bound holds by construction.
    assembly_input_ratio: float = Field(default=3.0, gt=0.0)
    # Derived, not clamped. The judge is handed the whole report and giving it
    # a truncated one changes what is being judged, so there is nothing to
    # clamp. The report body is already bounded by the assembly's own output
    # ceiling (synthesis_max_tokens); only the token -> UTF-8 byte conversion
    # that `conservative_input_bound` performs remains. Korean runs ~3 bytes
    # per syllable at roughly one token per syllable; 4.5 bytes/token covers
    # rarer 4-byte characters and JSON escaping, plus ~600 bytes of the
    # report_judge.md template.
    grading_input_ratio: float = Field(default=5.0, gt=0.0)
```

- [ ] **Step 4: 산식을 교체한다**

`finalization_floor_tokens` 메서드(894-909행) 전체를 아래 **두 메서드**로 바꾼다.

```python
    def report_floor_tokens(self, synthesis_max_tokens: int) -> int:
        """The INNER floor tier: `report_retry_cap + 1` rounds of one
        assembly plus one judge, counted in the input+output currency
        `TokenBudget.reserve` actually charges.

        `node_reduction` cannot draw on this (token_budget.REPORT_STAGES).
        Sizing it for the whole retry loop is deliberate: `_finalize`
        re-assembles up to `report_retry_cap` times and grades every draft,
        so a tier covering one round leaves the later rounds to fail open --
        the failure this split exists to end.
        """
        assembly = int(
            (self.assembly_input_ratio + 1) * synthesis_max_tokens
        )
        grading = int(
            self.grading_input_ratio * synthesis_max_tokens
            + self.report_judge_max_output_tokens
        )
        return (self.report_retry_cap + 1) * (assembly + grading)

    def finalization_floor_tokens(self, synthesis_max_tokens: int) -> int:
        """The TOTAL floor: the report tier plus
        `finalization_reduction_allowance` node_reduction calls.

        Shared by `neos/config/loader.py`'s `warn_finalization_floor_ratio`
        (checks this against `global_token_cap` at config-load time) and
        `neos/workflow/deep_analysis/service.py`'s `build_orchestrator` (the
        floor actually enforced by `TokenBudget`). Kept as one method, not two
        independent expressions, so a future change to the formula cannot
        silently leave the warning describing a floor that is no longer in
        force.
        """
        reduction = int(
            (self.reduction_input_ratio + 1) * synthesis_max_tokens
        )
        return (
            self.report_floor_tokens(synthesis_max_tokens)
            + self.finalization_reduction_allowance * reduction
        )
```

- [ ] **Step 5: allowance 주석의 낡은 수치를 고친다**

`finalization_reduction_allowance` 위 주석(800-806행)에서 `40,800` 문장을 아래로 바꾼다. 산식이 바뀌어 그 숫자가 더는 성립하지 않는다.

```python
    # How many node_reduction calls the finalization floor budgets for.
    #
    # Measured: node_reduction runs a median of 2 times per run (max 9). Runs
    # with deeper trees will see their last reductions degrade to joining
    # child answers, but assembly and the judge survive -- which is the point
    # of the reserve, and why the report tier is isolated from this one.
    # Budgeting for the observed maximum of 9 would put the reduction tier at
    # 93,600 on the default profile, more than four times the whole dev cap.
    finalization_reduction_allowance: int = Field(default=2, ge=1)
```

- [ ] **Step 6: dev 캡을 올린다**

`DeepAnalysisDevProfileConfig.global_token_cap`(634행)을 아래로 바꾼다.

```python
    # 20000 could not hold ONE worker_analysis call: measured input_bound for
    # that stage ran 5,542 / 10,893 / 17,723 (min/median/max), and that is
    # before the finalization floor is subtracted. The profile was sized
    # before `reserve` charged for input at all, which is why dev runs were
    # pathological rather than merely small. 100,000 leaves 58,960 for
    # investigation against a 41,040 floor (41%), matching the default
    # profile's 43.7%.
    global_token_cap: int = 100000
```

- [ ] **Step 7: 낡아진 기존 테스트 단언을 고친다**

`tests/workflow/deep_analysis/test_config_defaults.py:44`

```python
    assert dev.global_token_cap == 100000
```

같은 파일 `test_a_disproportionate_floor_warns`의 134·141행 — dev floor가 4,400에서 41,040으로 바뀌었다.

```python
    config.dev_profile.global_token_cap = 4000  # floor 41040 > 2000
```

```python
    assert any("41040" in m and "4000" in m for m in messages)
```

- [ ] **Step 8: 테스트 통과를 확인한다**

Run: `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/deep_analysis/test_config_defaults.py -q`
Expected: PASS — 신규 3건 + 갱신 2건 포함 전부. 특히 `test_default_config_does_not_warn_about_the_floor`가 통과해야 한다(default 43.7% · dev 41.0%, 둘 다 `warn_ratio` 0.5 미만).

- [ ] **Step 9: 커밋**

```bash
git add neos/config/schema.py tests/workflow/deep_analysis/test_config_defaults.py
git commit -m "feat(config): size the finalization floor in the currency reserve charges

The floor counted output tokens; reserve() charges input_bound + output.
One node_reduction was measured at 6,480 input alone, larger than the whole
dev floor. Both tiers now include an input allowance derived from
synthesis_max_tokens, and dev's cap goes to 100,000 -- 20,000 could not hold
a single worker call."
```

---

## Task 3: 프롬프트를 예산과 같은 자로 재고 줄인다

**Files:**
- Modify: `neos/workflow/deep_analysis/llm.py` (`_budgeted_dispatch` 바로 위)
- Create: `neos/workflow/deep_analysis/prompt_clamp.py`
- Test: `tests/workflow/deep_analysis/test_prompt_clamp.py` (신규)

**Interfaces:**
- Consumes: 없음
- Produces:
  - `neos.workflow.deep_analysis.llm.prompt_input_bound(model: str, prompt: str) -> int`
  - `neos.workflow.deep_analysis.prompt_clamp.ClampResult` — 필드 `prompt: str`, `bound_before: int`, `bound_after: int`, `dropped_primary: int`, `dropped_secondary: int`, `exhausted: bool`; 프로퍼티 `clamped: bool`
  - `neos.workflow.deep_analysis.prompt_clamp.shrink_once(primary: list[str], secondary: list[str]) -> tuple[list[str], list[str]] | None`
  - `neos.workflow.deep_analysis.prompt_clamp.clamp_prompt(*, model: str, allowance: int, render_prompt: Callable[[list[str], list[str]], str], primary: list[str], secondary: list[str]) -> ClampResult`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/workflow/deep_analysis/test_prompt_clamp.py`를 새로 만든다.

```python
"""클램프는 추정하지 않는다 -- 예산과 같은 함수로 재고 줄인다."""

import pytest

from neos.workflow.deep_analysis.llm import prompt_input_bound
from neos.workflow.deep_analysis.prompt_clamp import (
    clamp_prompt,
    shrink_once,
)
from neos.workflow.deep_analysis.token_budget import conservative_input_bound


def _render(primary: list[str], secondary: list[str]) -> str:
    return "머리말\n" + "\n".join(primary) + "\n" + "\n".join(secondary)


def test_prompt_input_bound_matches_what_reserve_would_charge():
    """자가 두 벌이면 클램프의 유일한 보장이 깨진다.

    call_llm 은 request={"model": m, "messages": [...], "tools": None} 로
    reserve() 를 부른다(llm.py:328). 헬퍼는 반드시 같은 모양이어야 한다.
    """
    prompt = "한국어 프롬프트 본문"
    expected = conservative_input_bound(
        {
            "model": "m",
            "messages": [{"role": "user", "content": prompt}],
            "tools": None,
        }
    )

    assert prompt_input_bound("m", prompt) == expected


def test_a_prompt_within_the_allowance_is_untouched():
    result = clamp_prompt(
        model="m",
        allowance=100_000,
        render_prompt=_render,
        primary=["자식 A", "자식 B"],
        secondary=["미확인: 1"],
    )

    assert result.clamped is False
    assert result.exhausted is False
    assert result.dropped_primary == 0
    assert result.dropped_secondary == 0
    assert result.prompt == _render(["자식 A", "자식 B"], ["미확인: 1"])


def test_an_oversized_prompt_is_forced_under_the_allowance():
    """조립이 574 run 동안 예약을 못 받은 이유가 입력 크기다."""
    primary = [f"- [q{i:04d}] {'가' * 400}" for i in range(12)]
    secondary = [f"미확인: {'나' * 200}" for _ in range(8)]
    allowance = 4_000

    assert prompt_input_bound("m", _render(primary, secondary)) > allowance

    result = clamp_prompt(
        model="m",
        allowance=allowance,
        render_prompt=_render,
        primary=primary,
        secondary=secondary,
    )

    assert prompt_input_bound("m", result.prompt) <= allowance
    assert result.clamped is True
    assert result.bound_after < result.bound_before


def test_secondary_is_spent_before_primary():
    """D-6: caveats -> 자식 꼬리 -> 자식 수. 본문 커버리지를 먼저 지킨다."""
    primary = ["- [q0001] 짧은 자식"]
    secondary = [f"미확인: {'나' * 300}" for _ in range(6)]

    result = clamp_prompt(
        model="m",
        allowance=prompt_input_bound("m", _render(primary, [])) + 32,
        render_prompt=_render,
        primary=primary,
        secondary=secondary,
    )

    assert result.dropped_secondary > 0
    assert result.dropped_primary == 0


def test_an_unshrinkable_prompt_reports_exhaustion_instead_of_looping():
    """가변 조각을 다 비워도 템플릿이 크면 더 줄일 것이 없다.

    포기하고 reserve() 에 판단을 넘긴다. 무한 루프를 만들지 않는다.
    """

    def huge_template(primary: list[str], secondary: list[str]) -> str:
        return "머" * 5_000 + "\n".join(primary) + "\n".join(secondary)

    result = clamp_prompt(
        model="m",
        allowance=100,
        render_prompt=huge_template,
        primary=["자식"],
        secondary=["미확인"],
    )

    assert result.exhausted is True
    assert prompt_input_bound("m", result.prompt) > 100


def test_shrink_once_returns_none_when_nothing_is_left():
    assert shrink_once([], []) is None


def test_clamp_terminates_even_if_the_policy_stops_making_progress(
    monkeypatch,
):
    """정책 함수가 손대지 않은 리스트를 돌려줘도 루프는 끝나야 한다.

    종료를 정책의 정확성에 걸지 않는다 -- 정책은 사람이 고치는 부분이다.
    """
    from neos.workflow.deep_analysis import prompt_clamp

    monkeypatch.setattr(
        prompt_clamp,
        "shrink_once",
        lambda primary, secondary: (primary, secondary),
    )

    result = prompt_clamp.clamp_prompt(
        model="m",
        allowance=1,
        render_prompt=_render,
        primary=["자식"],
        secondary=["미확인"],
    )

    assert result.exhausted is True
```

- [ ] **Step 2: 실패를 확인한다**

Run: `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/deep_analysis/test_prompt_clamp.py -q`
Expected: FAIL — `ImportError: cannot import name 'prompt_input_bound'`

- [ ] **Step 3: `prompt_input_bound`를 추가한다**

`llm.py`의 `async def _budgeted_dispatch(` 정의 **바로 위**에 넣는다. `_budgeted_dispatch`가 `reserve()`에 넘기는 request와 같은 모양이어야 하므로 그 코드 옆을 떠나면 안 된다.

파일 상단 import에 `conservative_input_bound`를 추가한다 (기존 `from .token_budget import ...` 줄에 합친다).

```python
def prompt_input_bound(model: str, prompt: str) -> int:
    """The input bound `reserve()` would charge for this single-prompt call.

    Deliberately mirrors the `request` dict `call_llm` passes to
    `_budgeted_dispatch` below. Two rulers -- one for measuring, one for
    charging -- would let a clamp certify a prompt the budget then refuses,
    which is the whole failure this measurement exists to prevent. If the
    request shape below changes, this changes with it.
    """
    return conservative_input_bound(
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "tools": None,
        }
    )
```

- [ ] **Step 4: `prompt_clamp.py`의 뼈대를 만든다 (정책 함수는 비워 둔다)**

```python
"""Force a finalization prompt under its input allowance.

The floor can only be honoured if the input side is bounded. `reserve()`
charges `conservative_input_bound(request) + output`, so a prompt that grows
with the question tree consumes a stage's whole reserve before one output
token is granted -- which is how `report_assembly` went 574 runs without a
single reservation.

Nothing here estimates. The prompt is measured with `prompt_input_bound`,
the same function the budget charges with, and shrunk until it fits.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .llm import prompt_input_bound


@dataclass(frozen=True, slots=True)
class ClampResult:
    prompt: str
    bound_before: int
    bound_after: int
    dropped_primary: int
    dropped_secondary: int
    exhausted: bool

    @property
    def clamped(self) -> bool:
        return self.bound_after < self.bound_before


def shrink_once(
    primary: list[str],
    secondary: list[str],
) -> tuple[list[str], list[str]] | None:
    """Drop the least valuable remaining input, once.

    Returns the reduced ``(primary, secondary)``, or ``None`` when there is
    nothing left to drop.

    Callers map their own material onto the two slots:

    ==================  ==========================  ====================
    call site           primary                     secondary
    ==================  ==========================  ====================
    Synthesizer         child summary blocks        caveats
      .assemble
    Synthesizer         verified claim lines        child summary lines
      .reduce_node
    ==================  ==========================  ====================

    Neither the root answer (assemble) nor the question text (reduce_node)
    is passed here -- those are never dropped.

    POLICY (design D-6): secondary first, then primary tails, then primary
    count. Implemented in the body below.
    """
    raise NotImplementedError


def clamp_prompt(
    *,
    model: str,
    allowance: int,
    render_prompt: Callable[[list[str], list[str]], str],
    primary: list[str],
    secondary: list[str],
) -> ClampResult:
    """Render, measure, shrink, repeat until the prompt fits ``allowance``.

    Termination does not depend on ``shrink_once`` being correct: a step
    that returns the same lists it was given ends the loop as surely as one
    that returns ``None``. The policy is the part a human tunes, so the loop
    refuses to trust it.
    """
    original_primary = len(primary)
    original_secondary = len(secondary)
    prompt = render_prompt(primary, secondary)
    bound_before = prompt_input_bound(model, prompt)

    while prompt_input_bound(model, prompt) > allowance:
        shrunk = shrink_once(primary, secondary)
        if shrunk is None or shrunk == (primary, secondary):
            return ClampResult(
                prompt=prompt,
                bound_before=bound_before,
                bound_after=prompt_input_bound(model, prompt),
                dropped_primary=original_primary - len(primary),
                dropped_secondary=original_secondary - len(secondary),
                exhausted=True,
            )
        primary, secondary = shrunk
        prompt = render_prompt(primary, secondary)

    return ClampResult(
        prompt=prompt,
        bound_before=bound_before,
        bound_after=prompt_input_bound(model, prompt),
        dropped_primary=original_primary - len(primary),
        dropped_secondary=original_secondary - len(secondary),
        exhausted=False,
    )
```

- [ ] **Step 5: 축소 정책을 구현한다 — 사람이 쓰는 부분**

> 이 함수는 리포트에서 **무엇이 살아남는지**를 결정한다. 예산이나 종료는
> 이미 위 루프가 보장하므로, 여기서 정할 것은 순수하게 품질 정책이다.
> 설계 D-6이 정한 순서는 **secondary 전부 → primary 꼬리 → primary 개수**이며,
> 얼마나 공격적으로 자를지(꼬리를 몇 자씩 자를지, 절반씩 줄일지)는
> 구현자의 판단이다. 한 스텝이 반드시 뭔가를 줄여야 한다 —
> 그러지 않으면 루프가 `exhausted`로 끝난다.

`shrink_once`의 `raise NotImplementedError`를 정책 구현으로 바꾼다. 참고 구현:

```python
    if secondary:
        return primary, secondary[:-1]
    if not primary:
        return None
    longest = max(range(len(primary)), key=lambda i: len(primary[i]))
    if len(primary[longest]) > 1:
        trimmed = list(primary)
        trimmed[longest] = trimmed[longest][: len(trimmed[longest]) // 2]
        return trimmed, secondary
    return primary[:-1], secondary
```

- [ ] **Step 6: 테스트 통과를 확인한다**

Run: `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/deep_analysis/test_prompt_clamp.py -q`
Expected: PASS — 7건 전부

- [ ] **Step 7: 커밋**

```bash
git add neos/workflow/deep_analysis/llm.py neos/workflow/deep_analysis/prompt_clamp.py tests/workflow/deep_analysis/test_prompt_clamp.py
git commit -m "feat(deep-analysis): measure finalization prompts with the budget's own ruler

A floor sized in tokens can only be honoured if the input side is bounded.
Rather than estimate the input, render the prompt and measure it with the
same function reserve() charges with, then shrink until it fits."
```

---

## Task 4: `Synthesizer`를 클램프에 배선하고 강등을 원장에 남긴다

**Files:**
- Modify: `neos/workflow/deep_analysis/synthesizer.py:34-38` (프로퍼티), `:111-185` (`assemble`), `:212-283` (`reduce_node`)
- Test: `tests/workflow/deep_analysis/test_prompt_clamp.py` (같은 파일에 이어 붙인다)

**Interfaces:**
- Consumes: Task 3의 `clamp_prompt`, `ClampResult`
- Produces:
  - `Synthesizer.assembly_input_allowance -> int`
  - `Synthesizer.reduction_input_allowance -> int`
  - 원장 이벤트 `finalization_prompt_clamped` — 페이로드 `stage`, `bound_before`, `bound_after`, `allowance`, `dropped_primary`, `dropped_secondary`, `exhausted`
  - 원장 이벤트 `node_reduction_degraded` — 페이로드 `question_id`, `child_count`, `reason`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/workflow/deep_analysis/test_prompt_clamp.py` 끝에 이어 붙인다.

```python
from neos.workflow.deep_analysis.models import NodeSummary
from neos.workflow.deep_analysis.synthesizer import Synthesizer
from neos.workflow.deep_analysis.token_budget import TokenBudgetExhausted


class _Ledger:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict]] = []

    async def log(self, kind, qid, payload):
        self.events.append((kind, qid, payload))

    async def verified_claims(self, qid):
        return []

    def kinds(self) -> list[str]:
        return [kind for kind, _qid, _payload in self.events]

    def payload(self, kind: str) -> dict:
        return next(p for k, _q, p in self.events if k == kind)


class _Response:
    text = "## 요약\n본문"
    input_tokens = 10
    output_tokens = 20


@pytest.mark.asyncio
async def test_assemble_clamps_an_oversized_prompt_and_records_it():
    ledger = _Ledger()
    seen: dict[str, str] = {}

    async def llm_call(model, prompt, **kwargs):
        seen["model"] = model
        seen["prompt"] = prompt
        return _Response()

    synth = Synthesizer(
        ledger, llm_call=llm_call, synthesis_max_tokens=1_200
    )
    # 루트 요약은 절대 잘리지 않는다(D-6). 이 테스트는 자식·caveats 축소만
    # 보려는 것이므로 루트를 짧게 두어 허용량 대부분을 가변 조각에 남긴다.
    root = NodeSummary(
        question_id="q0000000",
        answer="루트 요약",
        key_claim_ids=[],
        confidence=0.8,
        caveats=[],
    )
    children = [
        NodeSummary(
            question_id=f"q{i:07d}",
            answer="가" * 900,
            key_claim_ids=[],
            confidence=0.5,
            caveats=[],
        )
        for i in range(10)
    ]

    await synth.assemble(root, children, ["미확인: " + "나" * 400])

    # 예약이 쓸 자와 같은 자로, 실제로 넘어간 모델명으로 잰다.
    assert (
        prompt_input_bound(seen["model"], seen["prompt"])
        <= synth.assembly_input_allowance
    )
    assert "finalization_prompt_clamped" in ledger.kinds()
    clamped = ledger.payload("finalization_prompt_clamped")
    assert clamped["stage"] == "report_assembly"
    assert clamped["bound_after"] < clamped["bound_before"]
    assert clamped["exhausted"] is False
    assert "synth_pass" in ledger.kinds()


@pytest.mark.asyncio
async def test_assemble_does_not_log_a_clamp_when_nothing_was_cut():
    """클램프 이벤트는 실제로 잘랐을 때만 나온다 -- 원장을 노이즈로 채우지 않는다."""
    ledger = _Ledger()

    async def llm_call(model, prompt, **kwargs):
        return _Response()

    synth = Synthesizer(
        ledger, llm_call=llm_call, synthesis_max_tokens=1_200
    )
    root = NodeSummary(
        question_id="q0000001",
        answer="짧은 답",
        key_claim_ids=[],
        confidence=0.9,
        caveats=[],
    )

    await synth.assemble(root, [], [])

    assert "finalization_prompt_clamped" not in ledger.kinds()
    assert "synth_pass" in ledger.kinds()


@pytest.mark.asyncio
async def test_a_degraded_reduction_leaves_a_trace():
    """W1 검증에 필수다.

    강등이 원장에 안 남으면 "리덕션은 강등됐지만 조립은 살았다"(설계 의도)와
    "리덕션이 전부 성공했다"를 구분할 수 없다.
    """
    ledger = _Ledger()

    async def json_call(model, prompt, **kwargs):
        raise TokenBudgetExhausted("budget")

    synth = Synthesizer(
        ledger, json_call=json_call, synthesis_max_tokens=1_200
    )

    class _Question:
        id = "q0000001"
        text = "질문"

    child = NodeSummary(
        question_id="q0000002",
        answer="자식 답",
        key_claim_ids=[],
        confidence=0.4,
        caveats=[],
    )

    summary = await synth.reduce_node(_Question(), [child])

    assert summary.caveats == ["token_budget_exhausted"]
    assert "node_reduction_degraded" in ledger.kinds()
    degraded = ledger.payload("node_reduction_degraded")
    assert degraded == {
        "question_id": "q0000001",
        "child_count": 1,
        "reason": "token_budget_exhausted",
    }
```

- [ ] **Step 2: 실패를 확인한다**

Run: `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/deep_analysis/test_prompt_clamp.py -q -k "assemble or degraded"`
Expected: FAIL — `AttributeError: 'Synthesizer' object has no attribute 'assembly_input_allowance'`

- [ ] **Step 3: 허용량 프로퍼티를 추가한다**

`synthesizer.py`의 `synthesis_max_tokens` 프로퍼티 바로 아래에 넣는다. 파일 상단 import에 `from .prompt_clamp import clamp_prompt`를 추가한다.

```python
    @property
    def assembly_input_allowance(self) -> int:
        """Input bytes report_assembly's prompt may occupy.

        Derived here rather than injected: `synthesis_max_tokens` above is
        already the profile-resolved value, and the ratio is global policy.
        Threading two more constructor arguments through service.py would
        give the same number two sources.
        """
        ratio = settings.config.deep_analysis.assembly_input_ratio
        return int(ratio * self.synthesis_max_tokens)

    @property
    def reduction_input_allowance(self) -> int:
        ratio = settings.config.deep_analysis.reduction_input_ratio
        return int(ratio * self.synthesis_max_tokens)
```

- [ ] **Step 4: 클램프 기록 헬퍼를 추가한다**

`Synthesizer` 안, 위 프로퍼티들 아래에 넣는다.

```python
    async def _log_clamp(self, stage: str, qid: str, result, allowance: int) -> None:
        """Record a clamp only when it actually cut something.

        Logging every call would bury the signal: the interesting event is
        a finalization prompt that did not fit, not one that did.
        """
        if not (result.clamped or result.exhausted):
            return
        await self.ledger.log(
            "finalization_prompt_clamped",
            qid,
            {
                "stage": stage,
                "bound_before": result.bound_before,
                "bound_after": result.bound_after,
                "allowance": allowance,
                "dropped_primary": result.dropped_primary,
                "dropped_secondary": result.dropped_secondary,
                "exhausted": result.exhausted,
            },
        )
```

- [ ] **Step 5: `assemble`을 클램프 경유로 바꾼다**

`assemble` 본문에서 `root_answer = ...`부터 `response = await self.llm_call(...)` 호출 직전까지를 아래로 바꾼다. `except TokenBudgetExhausted:` 이하 강등 경로와 마지막 `synth_pass` 기록은 **그대로 둔다.**

```python
        root_answer = root_summary.answer if root_summary is not None else ""
        child_blocks = [
            f"- [{child.question_id}] {child.answer}"
            for child in child_summaries
        ]
        has_content = bool(root_answer.strip()) or bool(child_blocks)
        config = settings.config.deep_analysis
        synth_model = resolve_model(
            config=settings.config.model_routing,
            provider="anthropic",
            role="powerful",
            feature_override=config.models.synth,
        ).model
        qid = root_summary.question_id if root_summary is not None else ""

        def render_assembly(blocks: list[str], notes: list[str]) -> str:
            if notes:
                caveats_text = "\n".join(notes)
            elif has_content:
                caveats_text = "(없음)"
            else:
                caveats_text = "검증된 클레임을 확보하지 못함"
            return render(
                "final_compose",
                root_summary=root_answer or "(요약 없음)",
                child_summaries="\n".join(blocks) or "(검증된 발견 없음)",
                caveats=caveats_text,
            )

        clamp = clamp_prompt(
            model=synth_model,
            allowance=self.assembly_input_allowance,
            render_prompt=render_assembly,
            primary=child_blocks,
            secondary=list(caveats),
        )
        await self._log_clamp(
            "report_assembly", qid, clamp, self.assembly_input_allowance
        )
        try:
            response = await self.llm_call(
                synth_model,
                clamp.prompt,
                max_tokens=self.synthesis_max_tokens,
                client=self.llm_client,
                cassette=self.cassette,
                stage="report_assembly",
            )
```

이어지는 `except TokenBudgetExhausted:` 블록에서 지역변수 `qid`를 다시 만드는 줄

```python
            qid = root_summary.question_id if root_summary is not None else ""
```

과, `synth_pass` 기록 직전의 같은 줄(175행)을 **삭제한다** — 위에서 이미 계산했다.

- [ ] **Step 6: `reduce_node`를 클램프 경유로 바꾸고 강등을 기록한다**

`reduce_node`에서 `prompt = render(...)`부터 `except Exception:` 블록 끝까지를 아래로 바꾼다.

```python
        synth_model = resolve_model(
            config=settings.config.model_routing,
            provider="anthropic",
            role="powerful",
            feature_override=settings.config.deep_analysis.models.synth,
        ).model

        def render_node(claims: list[str], children: list[str]) -> str:
            return render(
                "node_summary",
                question_id=question.id,
                question_text=question.text,
                verified_claims="\n".join(claims) or "(없음)",
                child_summaries="\n".join(children) or "(없음)",
            )

        clamp = clamp_prompt(
            model=synth_model,
            allowance=self.reduction_input_allowance,
            render_prompt=render_node,
            primary=claim_lines,
            secondary=child_lines,
        )
        await self._log_clamp(
            "node_reduction",
            question.id,
            clamp,
            self.reduction_input_allowance,
        )
        prompt = clamp.prompt
        try:
            data, resp = await self.json_call(
                synth_model,
                prompt,
                max_tokens=self.synthesis_max_tokens,
                client=self.llm_client,
                cassette=self.cassette,
                stage="node_reduction",
            )
        except TokenBudgetExhausted:
            return await self._degraded_summary(
                question, child_summaries, "token_budget_exhausted"
            )
        except Exception:
            return await self._degraded_summary(
                question, child_summaries, "node_summary_unparseable"
            )
```

`reduce_node` 아래에 강등 헬퍼를 추가한다.

```python
    async def _degraded_summary(
        self, question, child_summaries: list[NodeSummary], reason: str
    ) -> NodeSummary:
        """Fall back to joining the children's answers, and say so.

        This degradation predates the ledger entry and left no trace, so a
        run whose reductions all degraded was byte-identical to one where
        they all succeeded. That distinction is exactly what tells whether
        isolating the report tier worked: reductions are allowed to degrade,
        the assembly is not.
        """
        await self.ledger.log(
            "node_reduction_degraded",
            question.id,
            {
                "question_id": question.id,
                "child_count": len(child_summaries),
                "reason": reason,
            },
        )
        return NodeSummary(
            question_id=question.id,
            answer=" ".join(c.answer for c in child_summaries) or "",
            key_claim_ids=[],
            confidence=0.0,
            caveats=[reason],
            conflicts=[],
        )
```

기존 `reduce_node` 본문에 남아 있던 `config = settings.config.deep_analysis` 줄과 그 아래 중복 `synth_model = resolve_model(...)` 블록은 삭제한다 — 위에서 대체했다.

- [ ] **Step 7: 테스트 통과를 확인한다**

Run: `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/deep_analysis/test_prompt_clamp.py tests/workflow/deep_analysis/test_synthesizer.py -q`
Expected: PASS — 신규 3건 + 기존 synthesizer 스위트 전부

- [ ] **Step 8: 커밋**

```bash
git add neos/workflow/deep_analysis/synthesizer.py tests/workflow/deep_analysis/test_prompt_clamp.py
git commit -m "feat(deep-analysis): clamp finalization prompts and record degraded reductions

assemble and reduce_node now render through the clamp, so neither can
present reserve() with a prompt larger than its input allowance. reduce_node
degrading to joined child answers left no ledger trace, which made a run
whose reductions all degraded indistinguishable from one where none did."
```

---

## Task 5: floor 두 개를 배선하고 G7 재발을 가둔다

**Files:**
- Modify: `neos/workflow/deep_analysis/orchestrator.py:67-69` · `:105` · `:137-141` · `:172-179`
- Modify: `neos/workflow/deep_analysis/service.py:122-148`
- Test: `tests/workflow/deep_analysis/test_budgeter.py`

**Interfaces:**
- Consumes: Task 1의 `TokenBudget(report_floor_tokens=...)`, Task 2의 `DeepAnalysisConfig.report_floor_tokens()`
- Produces: `Orchestrator(..., report_floor_tokens: int = 0)`, `Orchestrator.report_floor_tokens: int`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/workflow/deep_analysis/test_budgeter.py` 끝에 추가한다.

```python
def test_orchestrator_report_tier_defaults_to_zero():
    """골든/통합 테스트가 1,000토큰 캡으로 오케스트레이터를 만든다.

    안쪽 tier를 안에서 전역 설정으로 계산하면 그런 run의 리덕션 예산이
    0이 된다. floor와 같은 이유로 주입받고 기본값은 0이다.
    """
    orch = Orchestrator(
        object(), "run0001", lambda: None, None, global_token_cap=1000
    )

    assert orch.token_budget.report_floor_tokens == 0
    assert orch.token_budget.available_for_reduction == 1000


def test_orchestrator_passes_both_tiers_to_the_budget():
    orch = Orchestrator(
        object(),
        "run0001",
        lambda: None,
        None,
        global_token_cap=100_000,
        finalization_floor_tokens=41_040,
        report_floor_tokens=34_800,
    )

    assert orch.token_budget.floor_tokens == 41_040
    assert orch.token_budget.report_floor_tokens == 34_800
    assert orch.token_budget.available_for_investigation == 58_960


def test_service_wiring_keeps_the_tiers_ordered():
    """service.py가 계산해 넣는 두 값이 TokenBudget의 불변식을 만족해야 한다.

    build_orchestrator 를 세션 없이 부를 수는 없으므로 산식만 검증한다.
    """
    from neos.config.settings import settings

    config = settings.config.deep_analysis
    for synth in (
        config.synthesis_max_tokens,
        config.dev_profile.synthesis_max_tokens,
    ):
        assert (
            config.report_floor_tokens(synth)
            <= config.finalization_floor_tokens(synth)
        )
```

- [ ] **Step 2: 실패를 확인한다**

Run: `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/deep_analysis/test_budgeter.py -q -k "report_tier_defaults or both_tiers or service_wiring"`
Expected: FAIL — `TypeError: Orchestrator.__init__() got an unexpected keyword argument 'report_floor_tokens'`

- [ ] **Step 3: `Orchestrator`에 파라미터를 통과시킨다**

시그니처의 `finalization_floor_tokens: int = 0,` 바로 아래에 추가한다.

```python
        report_floor_tokens: int = 0,
```

`self.finalization_floor_tokens = finalization_floor_tokens` 바로 아래에 추가한다.

```python
        # The inner tier, injected for the same reason as the floor above.
        # Golden tests build this with caps as small as 1,000; a tier derived
        # from global config would leave them no reduction budget at all.
        self.report_floor_tokens = report_floor_tokens
```

`TokenBudget(...)` **두 생성 지점**(`__init__`의 137행 부근, `_install_token_budget`의 172행 부근) 모두에서 `floor_tokens=self.finalization_floor_tokens,` 바로 아래에 추가한다.

```python
            report_floor_tokens=self.report_floor_tokens,
```

> ⚠️ 두 곳 다 고쳐야 한다. `_install_token_budget`은 `run()` 시작 때 예산을 재생성하므로, 여기를 빠뜨리면 **실제 run에서만** tier가 사라진다 — 테스트는 통과하고 프로덕션만 깨지는 형태다.

- [ ] **Step 4: `service.py`가 두 tier를 계산해 넣는다**

`build_orchestrator`의 `finalization_floor_tokens = config.finalization_floor_tokens(...)` 블록을 아래로 바꾼다.

```python
    # Two nested tiers, not one pool. The outer floor keeps investigation out
    # of the finalization chain; the inner one keeps node_reduction out of the
    # report. `reduce_tree` calls `reduce_node` once per node and nothing caps
    # that count -- 6 measured runs averaged 3.7 calls against an allowance of
    # 2 -- so without the inner tier the assembly's reservation is taken by
    # whichever reduction happens to run last. Both come from
    # `DeepAnalysisConfig` so `neos/config/loader.py`'s
    # `warn_finalization_floor_ratio` can never describe a floor that is not
    # the one enforced here.
    finalization_floor_tokens = config.finalization_floor_tokens(
        synthesis_max_tokens
    )
    report_floor_tokens = config.report_floor_tokens(synthesis_max_tokens)
```

`Orchestrator(...)` 호출의 `finalization_floor_tokens=finalization_floor_tokens,` 바로 아래에 추가한다.

```python
        report_floor_tokens=report_floor_tokens,
```

- [ ] **Step 5: 테스트 통과를 확인한다**

Run: `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/deep_analysis -q`
Expected: PASS — deep_analysis 스위트 전부

- [ ] **Step 6: 전체 회귀를 확인한다**

```bash
.venv/bin/python -m pytest 2>&1 | tail -20
.venv/bin/python -m pytest 2>&1 | grep '^FAILED tests/' || echo "no failures"
```

Expected: `no failures`, 총계 2,234 이상 passed / 0 failed.
실패가 보이면 **실제 회귀로 취급한다** — 이 스위트는 `c219531d` 이후 결정론적이다.

- [ ] **Step 7: Ruff를 통과시킨다**

```bash
.venv/bin/ruff check neos/ tests/workflow/deep_analysis/
```

Expected: `All checks passed!`

- [ ] **Step 8: 커밋**

```bash
git add neos/workflow/deep_analysis/orchestrator.py neos/workflow/deep_analysis/service.py tests/workflow/deep_analysis/test_budgeter.py
git commit -m "feat(deep-analysis): wire both floor tiers through to the budget

service.py computes the report tier alongside the total floor and the
orchestrator passes both to TokenBudget at each of its two construction
sites -- missing the one in _install_token_budget would drop the tier in
real runs only, where every test still passed."
```

---

## Task 6: 로드맵과 결정 원장을 갱신한다

**Files:**
- Modify: `docs/DEEP_ANALYSIS_HARNESS_ROADMAP.md` (§1 표, §7 인벤토리, §8 W1, §9 D-1·D-4)
- Modify: `neos/workflow/deep_analysis/DECISIONS.md` (D24 추가)

**Interfaces:**
- Consumes: Task 1–5의 완료 상태
- Produces: 없음 (문서)

- [ ] **Step 1: `DECISIONS.md`에 D24를 추가한다**

파일 끝에 기존 D 항목과 같은 형식으로 추가한다. 내용은 아래를 담는다.

- **D24 — 마무리 floor를 중첩 계단으로 분할한다.**
- 맥락: floor가 단일 풀이었고 출력 토큰만 계상했다. `reserve()`는 입력+출력을 뺀다. 574 run · `synth_pass` 0건.
- 결정: `REPORT_STAGES`(assembly·grading) 전용 안쪽 tier를 두고, 두 tier 모두 입력 허용량을 포함해 사이징한다. 마무리 프롬프트는 `prompt_input_bound`로 측정해 허용량 안으로 강제한다.
- 기각한 대안: `reduce_node` 호출 수 하드 캡 — 풀 격리가 같은 일을 하며 "예산은 남았는데 못 부른다"는 새 실패 모드를 만든다.
- 기각한 대안: `conservative_input_bound` 완화 — `settle()`의 계약이 참인 상한에 의존한다.
- 부수 결정: dev `global_token_cap` 20,000 → 100,000. 기존 캡은 워커 호출 하나(input_bound 5,542~17,723)도 담지 못했다.

- [ ] **Step 2: 로드맵 §7 인벤토리에서 G6·G7을 해소로 옮긴다**

`| 🔴 | **G6** | ... |`와 `| 🔴 | **G7** | ... |` 두 행을 제거하고, §3.5 「최근 해소된 것」 표에 두 행을 추가한다.

커밋 해시는 아래로 얻는다 (Task 1이 G7, Task 2가 G6를 해소한 커밋이다).

```bash
git log --oneline -6 --format='%h %s'
```

```markdown
| G6 | floor를 입력 통화로 재사이징 — 비율 3종을 `synthesis_max_tokens`에서 유도 | `<Task 2 커밋 해시>` |
| G7 | `REPORT_STAGES` 전용 안쪽 tier — 리덕션이 조립 몫에 닿지 못한다 | `<Task 1 커밋 해시>` |
```

- [ ] **Step 3: 로드맵 §8 W1에 판정 상태를 적는다**

W1 절 끝에 추가한다.

```markdown
**2026-08-04 상태:** 코드·결정론 테스트 완료(D-1 = 2안 풀 분할, D-4 = dev cap 100,000,
D-5 = 재시도 3회분 보장, D-6 = caveats → 자식 꼬리 → 자식 수).
**완료 기준은 아직 미판정이다** — `synth_pass ≥ 1`은 라이브 표본 5+1이 필요하고,
§10.2의 "정확히 1회" 원칙상 코드가 확정된 지금 한 번만 실행해야 한다.
따라서 §2.2의 S1은 ❌로 유지한다.
```

- [ ] **Step 4: 로드맵 §9에서 해소된 결정을 표시한다**

D-1과 D-4 행의 「영향」칸 앞에 `✅ 결정됨:` 을 붙이고 채택안을 적는다. D-2(G3)·D-3(E3)은 그대로 둔다 — W3·W4 소관이다.

- [ ] **Step 5: 커밋**

```bash
git add docs/DEEP_ANALYSIS_HARNESS_ROADMAP.md neos/workflow/deep_analysis/DECISIONS.md
git commit -m "docs(deep-analysis): record the finalization floor split as D24

G6 and G7 move to the resolved list; W1 stays unjudged until a live sample
runs, since synth_pass >= 1 cannot be observed from deterministic tests."
```

---

## 완료 기준

- Task 1–6의 모든 스텝 체크
- `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/deep_analysis -q` 통과
- `.venv/bin/python -m pytest` — 2,234 이상 passed / **0 failed**
- `.venv/bin/ruff check neos/ tests/` 통과

**미판정으로 남는 것:** 로드맵 W1의 `synth_pass ≥ 1`(S1). 라이브 표본 5+1은 코드가
확정된 뒤 사용자가 1회 실행한다(§10.2 "정확히 1회", 재실행 금지). 그 실행 전까지
W1은 완료가 아니다.
