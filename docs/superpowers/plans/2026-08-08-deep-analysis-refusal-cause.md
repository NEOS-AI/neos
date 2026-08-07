# 거절에는 사유가 있다 (G10) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `TokenBudget.reserve()`가 거절한 사유를 예외에 실어, 지금 침묵하거나 거짓말하는 소비자 셋이 참을 적게 만든다.

**Architecture:** 사유를 아는 자리는 `reserve()` 하나뿐이므로 예외가 운반체가 된다. `TokenBudgetExhausted`가 `cause`(`"tier_floor"` | `"input_bound"`)와 거절 순간의 수치를 싣고, `_mark_stop_reason`은 기존 상태 분기 **뒤에** 셋째 분기를 얻어 새 이벤트 `investigation_stopped_at_input_bound`를 남기며, synthesizer의 하드코딩된 `reason` 두 곳은 사유를 따라간다. 프론트는 라벨 하나만 얻고 강등 어휘는 건드리지 않는다.

**Tech Stack:** Python 3.12 (asyncio, pytest) · TypeScript (`tsx --test`)

## Global Constraints

- **설계 정본:** `docs/superpowers/specs/2026-08-08-deep-analysis-refusal-cause-design.md`. 충돌하면 스펙이 이긴다.
- **`reserve()`의 거절 *동작*을 바꾸지 않는다.** 무엇을 거절할지는 한 글자도 안 바뀐다. 바뀌는 것은 사유의 기록뿐이다 (로드맵 §10.2 "측정 대상 변경 금지").
- **`TokenBudgetExhausted`의 모든 필드는 기본값을 갖는다.** 테스트 9곳이 `TokenBudgetExhausted("cap")`으로 생성하며 계속 유효해야 한다. `cause` 기본값은 `"tier_floor"`.
- **`_mark_stop_reason`의 상태 분기 둘이 먼저다.** 새 분기는 셋째이며 `exc`가 있을 때만 진입한다. G9의 판정은 한 글자도 안 바뀐다.
- **`tier_floor`의 강등 `reason` 문자열은 `"token_budget_exhausted"` 그대로.** 새 문자열 `"input_bound"`는 새로 구별된 경우에만.
- **강등 어휘를 건드리지 않는다.** `ledger.py`의 `_DEGRADATION_KINDS`와 `progress.ts`의 `degradationKind()`는 수정 대상이 아니다 (로드맵 §7 FE6).
- **이벤트 페이로드는 수치와 식별자만.** 프롬프트·응답·리포트 텍스트를 절대 싣지 않는다.
- **커밋 메시지에 `Co-Authored-By` 트레일러를 넣지 않는다.**
- **베이스라인 (2026-08-08 실측):** `tests/workflow/deep_analysis` **528 passed**, `pnpm --dir web test:source` **174 passed**. 이 숫자가 줄면 회귀다.

---

## File Structure

| 파일 | 책임 | 태스크 |
|---|---|---|
| `neos/workflow/deep_analysis/token_budget.py` | 거절 사유를 계산하고 예외에 싣는다 | 1 |
| `tests/workflow/deep_analysis/test_token_budget.py` | 사유 판별과 경계를 고정 | 1 |
| `neos/workflow/deep_analysis/orchestrator.py` | 사유를 정지 이벤트로 옮긴다 | 2 |
| `tests/workflow/deep_analysis/test_orchestrator_token_budget.py` | 세 정지 클래스의 배타성을 고정 | 2 |
| `neos/workflow/deep_analysis/synthesizer.py` | 강등 `reason`을 사유에서 유도 | 3 |
| `tests/workflow/deep_analysis/test_synthesizer.py` | 두 강등 경로의 `reason` 고정 | 3 |
| `web/lib/deep-analysis/progress.ts` | 새 kind에 라벨 | 4 |
| `web/tests/source/deep-analysis-progress.test.ts` | 라벨 존재 | 4 |
| `web/tests/source/deep-analysis-degradation.test.ts` | 정본 fixture — 비강등 고정 | 4 |
| `tests/workflow/deep_analysis/test_ledger_degradations.py` | 정본 fixture — 비강등 고정 (TS와 동일 내용) | 4 |

---

## Task 1: 거절이 사유를 싣는다

**Files:**
- Modify: `neos/workflow/deep_analysis/token_budget.py:41-42` (예외 클래스), `:181-183` (거절 지점)
- Test: `tests/workflow/deep_analysis/test_token_budget.py`

**Interfaces:**
- Consumes: 없음 (첫 태스크)
- Produces: `TokenBudgetExhausted(message: str = ..., *, cause: str = "tier_floor", stage: str = "", model: str = "", input_bound: int = 0, ceiling: int = 0, requested: int = 0, granted: int = 0)`. 인스턴스 속성 이름은 키워드 이름과 같다. `cause` 값은 `"tier_floor"` 또는 `"input_bound"` 둘뿐이다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/workflow/deep_analysis/test_token_budget.py` 상단 import 블록에 `conservative_input_bound`를 추가한다:

```python
from neos.workflow.deep_analysis.token_budget import (
    TokenBudget,
    TokenBudgetContractError,
    TokenBudgetExhausted,
    TokenReservation,
    active_token_budget,
    conservative_input_bound,
    token_budget_scope,
)
```

그리고 파일 끝에 다음 넷을 추가한다:

```python
def test_a_bare_exception_still_reads_as_a_spent_tier():
    """테스트 9곳이 메시지만으로 생성한다 -- 기본값이 옛 해석을 지켜야 한다."""
    exc = TokenBudgetExhausted("cap")

    assert exc.cause == "tier_floor"
    assert str(exc) == "cap"


@pytest.mark.asyncio
async def test_an_empty_tier_refuses_with_tier_floor():
    budget = TokenBudget(10, min_viable_output_tokens=4)
    budget._consumed_tokens = 10

    with pytest.raises(TokenBudgetExhausted) as excinfo:
        await budget.reserve({}, 100, stage="worker_analysis", model="m")

    assert excinfo.value.cause == "tier_floor"
    assert excinfo.value.ceiling == 0


@pytest.mark.asyncio
async def test_a_prompt_larger_than_the_headroom_refuses_with_input_bound():
    """G10 이 가리키는 클래스 -- tier 에 여유가 있는데도 나는 거절이다."""
    budget = TokenBudget(5_000, min_viable_output_tokens=2_048)
    request = {"prompt": "가" * 2_000}

    with pytest.raises(TokenBudgetExhausted) as excinfo:
        await budget.reserve(
            request, 4_000, stage="worker_analysis", model="claude-sonnet-5"
        )

    exc = excinfo.value
    assert exc.cause == "input_bound"
    assert exc.stage == "worker_analysis"
    assert exc.model == "claude-sonnet-5"
    assert exc.ceiling == 5_000
    assert exc.input_bound == conservative_input_bound(request)
    assert exc.requested == 4_000
    # 프롬프트가 tier 보다 크면 음수다 -- 0 으로 깎지 않는다.
    assert exc.granted == exc.ceiling - exc.input_bound
    assert exc.granted < 0


@pytest.mark.asyncio
async def test_the_boundary_between_the_last_grant_and_the_first_refusal():
    """`ceiling - input_bound == viability` 가 마지막 승인이다."""
    request = {"prompt": "x" * 1_000}
    input_bound = conservative_input_bound(request)

    granting = TokenBudget(input_bound + 2_048, min_viable_output_tokens=2_048)
    reservation = await granting.reserve(
        request, 2_048, stage="worker_analysis", model="m"
    )
    assert reservation.max_output_tokens == 2_048

    refusing = TokenBudget(input_bound + 2_047, min_viable_output_tokens=2_048)
    with pytest.raises(TokenBudgetExhausted) as excinfo:
        await refusing.reserve(
            request, 2_048, stage="worker_analysis", model="m"
        )
    assert excinfo.value.cause == "input_bound"
```

- [ ] **Step 2: 실패를 확인한다**

Run: `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/deep_analysis/test_token_budget.py -q`
Expected: FAIL — `ImportError` 또는 `AttributeError: 'TokenBudgetExhausted' object has no attribute 'cause'`

- [ ] **Step 3: 예외에 사유를 붙인다**

`token_budget.py:41-42`의 클래스를 통째로 교체한다:

```python
class TokenBudgetExhausted(RuntimeError):
    """Raised when no output token can be reserved within the hard cap.

    Carries *why*. `reserve` refuses for two different reasons and used to
    throw the same bare exception for both, so every consumer had to guess:
    `_mark_stop_reason` guessed "neither" and logged nothing at all (G10),
    and the synthesizer guessed "token_budget_exhausted" and wrote it into
    the ledger even when the budget had headroom left. The refusal site is
    the only place that knows which of the two happened -- the budget's own
    state afterwards looks identical for the second case. This is how it
    says so.

    Every field defaults, so `TokenBudgetExhausted("cap")` stays valid; the
    default `cause` is the reading the bare exception always carried.
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
        super().__init__(message)
        self.cause = cause
        self.stage = stage
        self.model = model
        self.input_bound = input_bound
        self.ceiling = ceiling
        self.requested = requested
        self.granted = granted
```

- [ ] **Step 4: 거절 지점이 사유를 계산해 던지게 한다**

`token_budget.py:182-183`의 두 줄을 교체한다. **위쪽 주석 블록(169-180)은 그대로 둔다** — 거절 *동작*의 근거이고 이번 작업은 동작을 바꾸지 않는다.

```python
            if output_tokens < viability:
                # `ceiling > 0` separates the two refusals: the tier is
                # empty, or the tier has room and this prompt does not fit
                # in it. Nothing downstream can recover the distinction --
                # both raise from here, and for the second case the budget
                # still reads as having headroom, which is exactly why that
                # stop went unrecorded (G10).
                raise TokenBudgetExhausted(
                    "deep-analysis token budget exhausted",
                    cause="input_bound" if ceiling > 0 else "tier_floor",
                    stage=stage,
                    model=model,
                    input_bound=input_bound,
                    ceiling=ceiling,
                    requested=max_output_tokens,
                    granted=output_tokens,
                )
```

- [ ] **Step 5: 통과를 확인한다**

Run: `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/deep_analysis/test_token_budget.py -q`
Expected: PASS

- [ ] **Step 6: 전체 회귀를 확인한다**

Run: `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/deep_analysis -q`
Expected: **528 passed** (베이스라인 유지 — 기존 9곳의 맨손 생성이 안 깨졌다는 증거)

- [ ] **Step 7: 커밋**

```bash
git add neos/workflow/deep_analysis/token_budget.py tests/workflow/deep_analysis/test_token_budget.py
git commit -m "feat(deep-analysis): make a refusal say which kind it was"
```

---

## Task 2: 정지 사유가 셋째 이름을 얻는다

**Files:**
- Modify: `neos/workflow/deep_analysis/orchestrator.py:141` (플래그), `:239-282` (`_mark_stop_reason`), `:1021-1022` (호출부)
- Test: `tests/workflow/deep_analysis/test_orchestrator_token_budget.py`

**Interfaces:**
- Consumes: Task 1의 `TokenBudgetExhausted.cause` / `.stage` / `.model` / `.input_bound` / `.ceiling`
- Produces: 원장 이벤트 kind `"investigation_stopped_at_input_bound"`. 페이로드 키는 정확히 `cap_tokens`·`consumed_tokens`·`reserved_tokens`·`stage`·`model`·`input_bound`·`ceiling` 일곱 개. 메서드 `_mark_stop_reason(exc: TokenBudgetExhausted | None = None)`.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/workflow/deep_analysis/test_orchestrator_token_budget.py` 파일 끝에 셋을 추가한다. `FloorLedger`·`Grader`·`Synthesizer`·`CitationRenderer`·`Orchestrator`·`TokenBudgetExhausted`는 이미 이 파일에 import 돼 있다.

```python
@pytest.mark.asyncio
async def test_a_refusal_with_headroom_left_records_its_own_stop():
    """G10: `reserve` 는 tier 에 여유가 있어도 프롬프트가 안 들어가면 거절한다.

    두 상태 분기 모두 그 정지를 잡지 못해 원장에 아무것도 남지 않았다.
    W1 의 라이브 표본은 "정확히 1회"라 그 침묵이 영구 기록이 된다.
    """
    ledger = FloorLedger()
    emitted = []

    async def event_sink(kind, payload):
        emitted.append((kind, payload))

    orchestrator = Orchestrator(
        object(),
        "run",
        worker_factory=lambda: None,
        grader=Grader(),
        ledger=ledger,
        synthesizer=Synthesizer(),
        citation_renderer=CitationRenderer(),
        event_sink=event_sink,
        global_token_cap=100_000,
    )
    await orchestrator._install_token_budget()
    # 두 상태 분기가 모두 거짓인 조건 -- 여기가 지금 침묵하는 자리다.
    assert orchestrator.token_budget.exhausted is False
    assert (
        orchestrator.token_budget.available_for_investigation
        >= orchestrator.token_budget.min_viable_output_tokens
    )

    await orchestrator._mark_stop_reason(
        TokenBudgetExhausted(
            cause="input_bound",
            stage="worker_analysis",
            model="claude-sonnet-5",
            input_bound=17_723,
            ceiling=12_000,
        )
    )

    kinds = [event[0] for event in ledger.events]
    stops = [
        e for e in ledger.events
        if e[0] == "investigation_stopped_at_input_bound"
    ]
    assert len(stops) == 1
    assert stops[0][2] == {
        "cap_tokens": 100_000,
        "consumed_tokens": 0,
        "reserved_tokens": 0,
        "stage": "worker_analysis",
        "model": "claude-sonnet-5",
        "input_bound": 17_723,
        "ceiling": 12_000,
    }
    assert "token_budget_exhausted" not in kinds
    assert "investigation_stopped_at_floor" not in kinds
    assert (
        [kind for kind, _payload in emitted].count(
            "investigation_stopped_at_input_bound"
        )
        == 1
    )


@pytest.mark.asyncio
async def test_the_budget_state_outranks_the_refusal_cause():
    """상태 분기를 먼저 두는 것이 설계다.

    예산이 실제로 없으면, 마지막 거절이 우연히 큰 프롬프트였다는 사실은
    정지 사유가 아니다. G9 의 판정이 그대로 이겨야 한다.
    """
    ledger = FloorLedger()
    orchestrator = Orchestrator(
        object(),
        "run",
        worker_factory=lambda: None,
        grader=Grader(),
        ledger=ledger,
        synthesizer=Synthesizer(),
        citation_renderer=CitationRenderer(),
        global_token_cap=100,
    )
    await orchestrator._install_token_budget()
    orchestrator.token_budget._consumed_tokens = 100

    await orchestrator._mark_stop_reason(
        TokenBudgetExhausted(cause="input_bound", stage="report_assembly")
    )

    kinds = [event[0] for event in ledger.events]
    assert "token_budget_exhausted" in kinds
    assert "investigation_stopped_at_input_bound" not in kinds


@pytest.mark.asyncio
async def test_recording_an_input_bound_stop_twice_records_it_once():
    """예외 경로가 부르고 무조건 호출이 뒤따른다 -- 중복 적재는 안 된다."""
    ledger = FloorLedger()
    orchestrator = Orchestrator(
        object(),
        "run",
        worker_factory=lambda: None,
        grader=Grader(),
        ledger=ledger,
        synthesizer=Synthesizer(),
        citation_renderer=CitationRenderer(),
        global_token_cap=100_000,
    )
    await orchestrator._install_token_budget()
    exc = TokenBudgetExhausted(cause="input_bound", stage="worker_analysis")

    await orchestrator._mark_stop_reason(exc)
    await orchestrator._mark_stop_reason(exc)
    await orchestrator._mark_stop_reason()

    stops = [
        e for e in ledger.events
        if e[0] == "investigation_stopped_at_input_bound"
    ]
    assert len(stops) == 1
```

- [ ] **Step 2: 실패를 확인한다**

Run: `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/deep_analysis/test_orchestrator_token_budget.py -q`
Expected: FAIL — `_mark_stop_reason()`이 인자를 받지 않아 `TypeError`

- [ ] **Step 3: 플래그를 추가한다**

`orchestrator.py:141` 다음 줄에 넣는다:

```python
        self._investigation_stopped_at_floor_logged = False
        self._investigation_stopped_at_input_bound_logged = False
```

- [ ] **Step 4: 새 헬퍼를 추가한다**

`_mark_investigation_stopped_at_floor()` 정의가 끝나는 `orchestrator.py:237` 바로 뒤, `_mark_stop_reason` 앞에 넣는다:

```python
    async def _mark_investigation_stopped_at_input_bound(
        self, exc: TokenBudgetExhausted
    ) -> None:
        """Record that investigation stopped because a prompt would not fit
        the headroom left -- not because there was no headroom.

        `TokenBudget.reserve` refuses when `ceiling - input_bound` falls
        under viability even with `ceiling > 0`. Afterwards the budget looks
        like a run that simply had questions left, so neither state branch in
        `_mark_stop_reason` catches it and the stop went unrecorded (G10).
        Only the refusal carries the fact; this payload is what it carried.

        `floor_tokens` is deliberately absent. This stop did not reach the
        floor, and quoting floor numbers would read as if it had -- the same
        mistake, one label covering two facts, that G9 removed. `stage`,
        `input_bound` and `ceiling` say what failed to fit into what.

        Payload carries counts and identifiers only, mirroring the other two
        stop events -- never prompt or report text.
        """
        if self._investigation_stopped_at_input_bound_logged:
            return
        has_event = getattr(self.ledger, "has_event", None)
        if has_event is not None and await has_event(
            "investigation_stopped_at_input_bound"
        ):
            self._investigation_stopped_at_input_bound_logged = True
            return
        payload = {
            "cap_tokens": self.token_budget.cap_tokens,
            "consumed_tokens": self.token_budget.consumed_tokens,
            "reserved_tokens": self.token_budget.reserved_tokens,
            "stage": exc.stage,
            "model": exc.model,
            "input_bound": exc.input_bound,
            "ceiling": exc.ceiling,
        }
        await self.ledger.log(
            "investigation_stopped_at_input_bound", None, payload
        )
        await self._checkpoint()
        await self._emit("investigation_stopped_at_input_bound", payload)
        self._investigation_stopped_at_input_bound_logged = True
```

- [ ] **Step 5: `_mark_stop_reason`에 셋째 분기를 단다**

시그니처를 바꾸고, docstring에서 **G10을 "tracked, not fixed here"로 적은 문단(`:262-270`)을 해소 서술로 교체**하며, `elif`를 하나 더 단다:

```python
    async def _mark_stop_reason(
        self, exc: TokenBudgetExhausted | None = None
    ) -> None:
        """Record why investigation stopped, from the budget's state.

        The exception path used to assert "exhausted" on its own, and the
        normal path made a different decision from the same facts a few
        lines later -- two judgements of one question, disagreeing. Measured
        2026-08-04: 4 of 6 recorded stops were labelled `token_budget_
        exhausted` when the run had actually stopped at the floor with
        headroom left in the cap.

        `TokenBudget.reserve` raises the same `TokenBudgetExhausted` for
        every cause, so the exception *type* carries no information about
        which one happened. The budget's state answers two of the three;
        for the third only the exception's `cause` does, which is why it is
        now carried (token_budget.py).

        The floor branch below tests `<` against `min_viable_output_tokens`
        rather than `<= 0`, mirroring `Budgeter.should_stop`'s own viability
        threshold -- `<= 0` would leave the ordinary floor stop unrecorded,
        since the loop already halts once headroom drops below viability,
        not once it reaches zero.

        Order matters. The two state branches come first so G9's judgement
        is untouched: when the budget really is spent, the last refusal
        happening to carry a large prompt is not the reason the run stopped.
        The third branch only fills the silence -- a refusal raised while
        `available_for_investigation` still cleared viability, which used to
        satisfy no branch at all (G10).

        There is still deliberately no branch for a run that stopped because
        no open question cleared `score_floor`: it has no budget event to
        record, and inventing one would put the ledger back to guessing.

        All three `_mark_*` helpers are idempotent (in-memory flag plus a
        `has_event` lookup), so calling this from both paths cannot
        double-log.
        """
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

- [ ] **Step 6: 호출부가 예외를 넘기게 한다**

`orchestrator.py:1021-1022`:

```python
                except TokenBudgetExhausted as exc:
                    await self._mark_stop_reason(exc)
```

`:1028`의 무조건 호출은 **그대로 둔다** (인자 없음).

- [ ] **Step 7: 통과를 확인한다**

Run: `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/deep_analysis/test_orchestrator_token_budget.py -q`
Expected: PASS (기존 `test_the_exception_path_does_not_call_the_stop_a_cap_exhaustion`·`test_a_normal_stop_records_no_budget_event` 포함 전부)

- [ ] **Step 8: 커밋**

```bash
git add neos/workflow/deep_analysis/orchestrator.py tests/workflow/deep_analysis/test_orchestrator_token_budget.py
git commit -m "feat(deep-analysis): give the silent stop a name in the ledger"
```

---

## Task 3: 강등이 예외 타입 대신 사유를 적는다

**Files:**
- Modify: `neos/workflow/deep_analysis/synthesizer.py:218-226` (assembly), `:326-328` (reduction), 모듈 최상단에 헬퍼 추가
- Test: `tests/workflow/deep_analysis/test_synthesizer.py`

**Interfaces:**
- Consumes: Task 1의 `TokenBudgetExhausted.cause`
- Produces: 모듈 함수 `_degradation_reason(exc: TokenBudgetExhausted) -> str`. 반환값은 `"input_bound"` 또는 `"token_budget_exhausted"` 둘뿐. 이 문자열이 `report_assembly_degraded`·`node_reduction_degraded` 페이로드의 `reason` 이자 `NodeSummary.caveats`의 원소가 된다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/workflow/deep_analysis/test_synthesizer.py`의 기존 `_exhausted` 헬퍼(파일 내 `async def _exhausted`) 바로 뒤에 새 헬퍼와 테스트 셋을 추가한다:

```python
async def _refused_for_input_bound(*args, **kwargs):
    raise TokenBudgetExhausted(cause="input_bound", stage="node_reduction")


@pytest.mark.asyncio
async def test_a_degraded_summary_names_the_refusal_it_actually_hit():
    ledger = FakeLedger()
    synth = Synthesizer(ledger, json_call=_refused_for_input_bound)
    child = NodeSummary("child001", "verified child answer", [], 0.8, [])

    summary = await synth.reduce_node(ledger.root, [child])

    assert summary.caveats == ["input_bound"]
    degraded = [e for e in ledger.events if e[0] == "node_reduction_degraded"]
    assert len(degraded) == 1
    assert degraded[0][2]["reason"] == "input_bound"


@pytest.mark.asyncio
async def test_a_degraded_assembly_names_the_refusal_it_actually_hit():
    ledger = FakeLedger()
    synth = Synthesizer(ledger, llm_call=_refused_for_input_bound)
    root = NodeSummary("root0001", "verified root answer", [], 0.8, [])

    await synth.assemble(root, [], [])

    degraded = [
        e for e in ledger.events if e[0] == "report_assembly_degraded"
    ]
    assert len(degraded) == 1
    assert degraded[0][2] == {"reason": "input_bound"}


@pytest.mark.asyncio
async def test_a_spent_tier_keeps_the_word_the_ledger_already_uses():
    """의도적 결정: `tier_floor` 는 옛 문자열을 그대로 낸다.

    이미 쌓인 강등 이벤트가 그 어휘를 쓰고 있어 경계 전후 집계가 이어져야
    한다. 새 어휘는 새로 구별된 경우에만 붙는다.
    """
    ledger = FakeLedger()
    synth = Synthesizer(ledger, llm_call=_exhausted)
    root = NodeSummary("root0001", "verified root answer", [], 0.8, [])

    await synth.assemble(root, [], [])

    degraded = [
        e for e in ledger.events if e[0] == "report_assembly_degraded"
    ]
    assert degraded[0][2] == {"reason": "token_budget_exhausted"}
```

- [ ] **Step 2: 실패를 확인한다**

Run: `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/deep_analysis/test_synthesizer.py -q`
Expected: FAIL — `assert 'token_budget_exhausted' == 'input_bound'` (하드코딩된 문자열이 사유를 무시한다)

- [ ] **Step 3: 헬퍼를 추가한다**

`synthesizer.py`의 `from .token_budget import TokenBudgetExhausted` 다음, `class Synthesizer` 앞에 넣는다:

```python
def _degradation_reason(exc: TokenBudgetExhausted) -> str:
    """강등 이벤트의 `reason` -- 예외 타입이 아니라 거절 사유에서 온다.

    이 두 자리는 `"token_budget_exhausted"` 를 하드코딩하고 있었다.
    `reserve` 가 캡 소진과 `input_bound` 거절에 같은 예외를 던지므로, 여유가
    남은 채 거절된 run 도 "예산 소진"으로 기록됐다 -- G9 가 정지 사유에서
    없앤 것과 같은 종류의 거짓이다.

    `tier_floor` 는 옛 문자열을 그대로 낸다. 이미 원장에 쌓인 강등 이벤트가
    그 어휘를 쓰고 있어 경계 전후 집계가 이어져야 하기 때문이다. 새 문자열은
    지금까지 존재하지 않던 구별에만 붙는다.
    """
    if exc.cause == "input_bound":
        return "input_bound"
    return "token_budget_exhausted"
```

- [ ] **Step 4: assembly 경로를 고친다**

`synthesizer.py:218-226`:

```python
        except TokenBudgetExhausted as exc:
            # Falling back to a template is correct -- no empty-handed exit
            # (§6.8) -- but it must not look like success. Every recorded run
            # took this path and nothing said so.
            await self.ledger.log(
                "report_assembly_degraded",
                qid,
                {"reason": _degradation_reason(exc)},
            )
```

- [ ] **Step 5: reduction 경로를 고친다**

`synthesizer.py:326-328`:

```python
        except TokenBudgetExhausted as exc:
            return await self._degraded_summary(
                question, child_summaries, _degradation_reason(exc)
            )
```

- [ ] **Step 6: 통과를 확인한다**

Run: `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/deep_analysis/test_synthesizer.py tests/workflow/deep_analysis/test_prompt_clamp.py -q`
Expected: PASS. `test_prompt_clamp.py:356,362`와 `test_synthesizer.py:164`의 기존 `"token_budget_exhausted"` 단언이 **수정 없이** 통과해야 한다 — 그것이 어휘 보존의 증거다.

- [ ] **Step 7: 백엔드 전체 회귀**

Run: `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/deep_analysis -q`
Expected: **528 + 신규 10 = 538 passed** (Task 1의 4건, Task 2의 3건, Task 3의 3건)

- [ ] **Step 8: 커밋**

```bash
git add neos/workflow/deep_analysis/synthesizer.py tests/workflow/deep_analysis/test_synthesizer.py
git commit -m "fix(deep-analysis): stop degradations naming a cause they did not check"
```

---

## Task 4: 새 정지가 화면에 뜨되 강등으로는 세지 않는다

**Files:**
- Modify: `web/lib/deep-analysis/progress.ts:182-184` 뒤 (라벨 추가)
- Modify: `web/tests/source/deep-analysis-progress.test.ts:266-281` (kind 목록)
- Modify: `web/tests/source/deep-analysis-degradation.test.ts:24-43` (`CANONICAL_FIXTURE`)
- Modify: `tests/workflow/deep_analysis/test_ledger_degradations.py:19-38` (`CANONICAL_FIXTURE`)

**Interfaces:**
- Consumes: Task 2가 만든 kind `"investigation_stopped_at_input_bound"`
- Produces: `activityLabel()`이 그 kind에 문자열을 낸다. `degradationKind()`는 **변경하지 않으므로** 그 kind에 `null`을 낸다.

> ⚠️ 두 `CANONICAL_FIXTURE`는 **같은 내용이어야 한다.** 한쪽만 고치면 로드맵 §7 FE6이 경고한 이중 구현이 갈라진다. 두 파일을 같은 커밋에 넣는다.

- [ ] **Step 1: 실패하는 테스트를 쓴다 — 프론트**

`web/tests/source/deep-analysis-progress.test.ts`의 `"새 실패 이벤트 전부가 라벨을 가진다"` 테스트 안 `kinds` 배열에 한 줄을 추가한다:

```ts
    "investigation_stopped_at_floor",
    "investigation_stopped_at_input_bound",
    "llm_truncated",
```

`web/tests/source/deep-analysis-degradation.test.ts`의 `CANONICAL_FIXTURE`에서 floor 항목 바로 뒤에 추가한다:

```ts
  ["investigation_stopped_at_floor", { floor_tokens: 41040 }, null],
  ["investigation_stopped_at_input_bound",
    { stage: "worker_analysis", input_bound: 17723, ceiling: 12000 }, null],
  ["claim_discarded", {}, null],
```

- [ ] **Step 2: 실패하는 테스트를 쓴다 — 백엔드 정본 fixture**

`tests/workflow/deep_analysis/test_ledger_degradations.py`의 `CANONICAL_FIXTURE`에 같은 항목을 같은 자리에 넣는다:

```python
    ("investigation_stopped_at_floor", {"floor_tokens": 41040}, None),
    ("investigation_stopped_at_input_bound",
     {"stage": "worker_analysis", "input_bound": 17723, "ceiling": 12000}, None),
    ("claim_discarded", {}, None),
```

- [ ] **Step 3: 실패를 확인한다**

Run: `pnpm --dir web test:source 2>&1 | grep -E "^# (pass|fail)"`
Expected: FAIL 1건 — `investigation_stopped_at_input_bound 에 라벨이 없다`

(백엔드 fixture 쪽은 `degradationKind`가 이미 `None`을 내므로 통과한다. 그것이 의도다 — 이 단계는 "안 세기로 한 결정"을 고정하는 것이지 동작을 바꾸는 것이 아니다.)

- [ ] **Step 4: 라벨을 추가한다**

`web/lib/deep-analysis/progress.ts:182-184`의 floor 분기 바로 뒤에 넣는다:

```ts
  if (kind === "investigation_stopped_at_input_bound") {
    // floor 정지와 다른 사실이다 — 예산은 남았는데 프롬프트가 그 안에
    // 안 들어갔다. 하나로 묶으면 백엔드가 방금 없앤 구별이 화면에서
    // 다시 사라진다 (로드맵 §7 G10).
    return "조사 중단 — 남은 예산에 프롬프트가 들어가지 않음";
  }
```

`degradationKind()`는 **건드리지 않는다.** 조사 범위를 깎은 것이지 리포트를 깎은 것이 아니라는 `progress.ts:221-225`의 논리가 그대로 적용된다.

- [ ] **Step 5: 통과를 확인한다**

Run: `pnpm --dir web test:source 2>&1 | grep -E "^# (tests|pass|fail)"`
Expected: `# fail 0`, `# pass 174` (기존 테스트에 케이스를 더한 것이라 총 테스트 수는 그대로)

- [ ] **Step 6: 타입 검사와 백엔드 fixture 확인**

Run: `pnpm --dir web exec tsc --noEmit`
Expected: 출력 없음 (clean)

Run: `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/deep_analysis/test_ledger_degradations.py -q`
Expected: PASS

- [ ] **Step 7: 커밋**

```bash
git add web/lib/deep-analysis/progress.ts web/tests/source/deep-analysis-progress.test.ts web/tests/source/deep-analysis-degradation.test.ts tests/workflow/deep_analysis/test_ledger_degradations.py
git commit -m "feat(web): show the stop that used to leave no trace"
```

---

## Task 5: 로드맵과 결정 원장을 갱신한다

**Files:**
- Modify: `docs/DEEP_ANALYSIS_HARNESS_ROADMAP.md` (§7 G10 행, §2.2 S4 행, §3.5 표)
- Modify: `neos/workflow/deep_analysis/DECISIONS.md` (D28 추가 — D27은 FE4가 이미 썼다)

**Interfaces:**
- Consumes: Task 1–4의 커밋 해시
- Produces: 없음 (문서)

- [ ] **Step 1: 커밋 해시를 모은다**

```bash
git log --oneline -5
```

- [ ] **Step 2: `DECISIONS.md`에 D28을 추가한다**

파일 끝(D27 뒤)에 그대로 덧붙인다:

```markdown
## D28. 거절은 사유를 안다. 그 사유는 예외가 운반한다.

**맥락:** D26 이 정지 사유 판정을 `_mark_stop_reason()` 하나로 접으면서 구멍을 하나
남겼고 코드가 스스로 그렇게 적었다(`orchestrator.py`, "tracked, not fixed here").
`TokenBudget.reserve` 는 `available_for_investigation - input_bound < min_viable` 일
때도 거절하는데, 그때는 헤드룸이 **남아 있어서** 두 상태 분기 모두 거짓이다. 그 정지는
원장에 아무것도 남기지 않았다. 로드맵 §7 G10.

**결정:** (1) `TokenBudgetExhausted` 가 `cause`(`tier_floor` | `input_bound`)와 거절
순간의 수치(`stage`·`model`·`input_bound`·`ceiling`·`requested`·`granted`)를 싣는다.
모든 필드가 기본값을 가져 맨손 생성이 계속 유효하다. (2) `_mark_stop_reason(exc=None)`
에 셋째 분기를 달되 **상태 분기 둘 뒤에** 둔다. (3) 새 kind
`investigation_stopped_at_input_bound` 를 쓴다 — `floor_tokens` 는 싣지 않는다.
(4) synthesizer 의 하드코딩된 강등 `reason` 두 곳이 `cause` 를 따른다.

**근거 — 왜 예외인가:** 사유를 아는 코드는 `reserve()` 하나뿐이다. 캡 소진과
`input_bound` 거절은 같은 예외 타입이고, 거절 **후**의 예산 상태는 두 번째 경우에
"헤드룸이 남은 정상 run" 과 구별되지 않는다. 사후 상태로는 복원할 수 없는 사실이므로
거절 지점에서 실어 보내는 것 외에 방법이 없다.

**근거 — 왜 상태 분기가 먼저인가:** D26 이 세운 판정("경로가 아니라 예산 상태에서")을
보존하기 위해서다. 예산이 실제로 없으면, 마지막 거절이 우연히 큰 프롬프트였다는 사실은
정지 사유가 아니다. 새 분기는 **지금 침묵이 나는 자리만** 채운다.

**근거 — 왜 별도 kind 인가:** floor 정지는 "남은 것이 마무리 몫뿐", input_bound 정지는
"여유는 있는데 이 프롬프트가 안 들어감"이다. 하나로 접으면 D26 이 없앤 실수 — 한 라벨이
두 사유를 덮는 것 — 를 그대로 반복한다. 이미 쌓인 floor 이벤트에는 분별 키가 없어 경계
전후 비교도 애매해진다.

**의도적 보존:** `tier_floor` 의 강등 `reason` 은 옛 문자열 `"token_budget_exhausted"`
그대로다. 이미 원장에 쌓인 강등 이벤트가 그 어휘를 쓰고 있어 집계가 이어져야 한다.
새 문자열 `"input_bound"` 는 지금까지 존재하지 않던 구별에만 붙는다.

**범위 밖:** 거절 **전부**를 기록하는 `token_budget_refused`. 워커와 판정자가 삼키는
거절은 정지가 아니라 부분 실패이므로 stop 이벤트로 세면 S4 집계가 오염된다.

**영향:** `_mark_stop_reason` 의 어느 분기에도 안 걸리는 정지는 이제 `score_floor`
케이스 하나뿐이며, 그것은 예산 사건이 아니라 의도적 무이벤트다. **코드상 해소 —
재측정은 라이브 표본에서**, D25·D26 과 같은 규율이다. 로드맵 §2.2 S4 는 ⚠️(코드상
해소, 라이브 미측정)로 남는다.
```

- [ ] **Step 3: 로드맵 §7의 G10 행을 해소로 옮긴다**

§7 인벤토리에서 G10 행을 제거하고 §3.5 "최근 해소된 것" 표 맨 위에 추가한다:

```markdown
| G10 | `_mark_stop_reason`이 놓치던 `input_bound` 거절 클래스가 이름을 얻었다 — `TokenBudgetExhausted`가 `cause`를 싣고, 상태 분기 **뒤에** 셋째 분기가 붙는다(G9 판정 보존). 부수로 synthesizer의 하드코딩된 강등 `reason` 두 곳이 예외 타입 대신 실제 사유를 적는다. **코드상 해소 — 재측정은 라이브 표본에서** | `<Task 2 해시>` |
```

- [ ] **Step 4: §2.2의 S4 행을 갱신한다**

현재 `⚠️ 부분 (2026-08-07, W2 — G9 해소, `input_bound` 거절 클래스는 미해소)`를 다음으로 바꾼다:

```markdown
| S4 | 정지 사유가 원장에서 정확히 구분된다 | ⚠️ 코드상 해소, 라이브 미측정 (2026-08-08, G10) | `token_budget_exhausted` vs `investigation_stopped_at_floor` vs `investigation_stopped_at_input_bound` — 세 kind 밖의 무이벤트 정지는 `score_floor` 케이스뿐이어야 한다 |
```

> ⚠️ **"라이브 미측정"을 지우지 말 것.** W2가 G9에 대해 세운 규율과 같다 — 코드상 해소와 실측은 다른 주장이다. §8 W2의 "G9의 '6건 중 4건 → 0건'에 대한 정확한 서술" 문단이 그 이유를 적어뒀다.

- [ ] **Step 5: 커밋**

```bash
git add docs/DEEP_ANALYSIS_HARNESS_ROADMAP.md neos/workflow/deep_analysis/DECISIONS.md
git commit -m "docs(deep-analysis): record G10 and what it leaves to the live sample"
```

---

## 최종 검증

- [ ] **백엔드 deep_analysis**

Run: `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/deep_analysis -q`
Expected: **538 passed / 0 failed**

- [ ] **백엔드 전체**

Run: `.venv/bin/python -m pytest -q 2>&1 | tail -5`
Expected: 실패 0. 회귀 비교 시 `grep '^FAILED tests/'`로 거른다 (`'^FAILED'`만 쓰면 진행 표시 `FAILED  [ 7%]`까지 걸린다).

- [ ] **프론트**

Run: `pnpm --dir web test:source && pnpm --dir web exec tsc --noEmit`
Expected: `# fail 0`, tsc 출력 없음

- [ ] **잔여 침묵이 `score_floor` 하나뿐인지 코드로 확인**

Run: `rg -n 'G10' neos/ docs/DEEP_ANALYSIS_HARNESS_ROADMAP.md`
Expected: `orchestrator.py`의 "tracked, not fixed here" 문단이 **사라졌고**, 로드맵의 G10은 §3.5(해소)에만 남는다.
