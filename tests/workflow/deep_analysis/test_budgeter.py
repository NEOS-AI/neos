import pytest
from types import SimpleNamespace
from neos.workflow.deep_analysis.budgeter import Budgeter
from neos.workflow.deep_analysis.models import Effort
from neos.workflow.deep_analysis.token_budget import TokenBudget, TokenBudgetExhausted

pytestmark = pytest.mark.no_db


def _q(**kw):
    base = dict(id="q1", confidence=0.0, value_est=1.0, spent_tokens=0,
                cap_tokens=2000, fail_streak=0, depth=1, status="open")
    base.update(kw)
    return SimpleNamespace(**base)

def test_gain_decay_buckets():
    b = Budgeter()
    assert b.gain_decay([2, 3]) == 1.0
    assert b.gain_decay([1, 1]) == 0.6
    assert b.gain_decay([0, 0]) == 0.3
    assert b.gain_decay([]) == 1.0

def test_ladder_fail_streak_forces_split():
    b = Budgeter()
    assert b.ladder(_q(fail_streak=2)) == Effort.SPLIT

def test_ladder_cap_exhausted_forces_split():
    b = Budgeter()
    assert b.ladder(_q(spent_tokens=2000, cap_tokens=2000)) == Effort.SPLIT

def test_ladder_low_confidence_after_scout_digs():
    b = Budgeter()
    assert b.ladder(_q(confidence=0.2, spent_tokens=500)) == Effort.DIG

def test_ladder_default_scout():
    b = Budgeter()
    assert b.ladder(_q()) == Effort.SCOUT

def test_aging_increases_with_rounds():
    b = Budgeter(aging_per_round=0.05)
    b._round = 4
    assert abs(b.aging("never_selected") - 0.20) < 1e-9
    b._last_selected["q1"] = 2
    assert abs(b.aging("q1") - 0.10) < 1e-9


@pytest.mark.asyncio
async def test_shared_token_budget_exhaustion_stops_below_ledger_cap():
    class Ledger:
        async def total_spent(self):
            return 0

        async def open_questions(self):
            raise AssertionError("exhaustion must short-circuit question lookup")

    token_budget = TokenBudget(100, outstanding={"orphan": 100})
    budgeter = Budgeter(global_token_cap=100, token_budget=token_budget)

    assert await budgeter.should_stop(Ledger()) is True


@pytest.mark.asyncio
async def test_investigation_cannot_reserve_below_the_floor():
    """floor는 마무리 단계 몫이다 — 조사 stage는 넘볼 수 없다."""
    budget = TokenBudget(10_000, floor_tokens=4_000)
    # Use up all available_for_investigation
    spent = await budget.reserve(
        {"model": "m"}, 10_000, stage="worker_analysis", model="m"
    )
    await budget.settle(spent, spent.reserved_tokens)

    # Now try to reserve more - should fail because investigation cannot breach the floor
    with pytest.raises(TokenBudgetExhausted):
        await budget.reserve(
            {"model": "m"}, 100, stage="worker_analysis", model="m"
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
