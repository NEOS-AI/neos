import pytest
from types import SimpleNamespace
from neos.workflow.deep_analysis.budgeter import Budgeter
from neos.workflow.deep_analysis.models import Effort
from neos.workflow.deep_analysis.orchestrator import Orchestrator
from neos.workflow.deep_analysis.token_budget import (
    TokenBudget,
    TokenBudgetExhausted,
    conservative_input_bound,
)

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


@pytest.mark.asyncio
async def test_reserve_succeeds_at_the_one_token_margin_above_the_floor():
    """§7 경계: 조사 stage가 floor 위로 1토큰 여유가 있으면 예약이 성공한다.

    `test_investigation_is_clamped_to_the_floor_not_refused`는 넉넉한 여유에서
    `0 < n <= 6000`만 단언했다 -- 정확히 성공/실패가 갈리는 지점(여유 1 vs 0)은
    검증된 적이 없다.
    """
    request = {"model": "m"}
    input_bound = conservative_input_bound(request)
    floor = 100
    # available_for_investigation == input_bound + 1 -> ceiling - input_bound == 1
    cap = floor + input_bound + 1
    budget = TokenBudget(cap, floor_tokens=floor)
    assert budget.available_for_investigation == input_bound + 1

    reservation = await budget.reserve(
        request, 10, stage="worker_analysis", model="m"
    )

    assert reservation.max_output_tokens == 1


@pytest.mark.asyncio
async def test_reserve_raises_with_zero_margin_above_the_floor():
    """§7 경계: 여유가 정확히 0이면(available_for_investigation == input_bound)
    조사 stage의 예약은 TokenBudgetExhausted를 던진다."""
    request = {"model": "m"}
    input_bound = conservative_input_bound(request)
    floor = 100
    cap = floor + input_bound
    budget = TokenBudget(cap, floor_tokens=floor)
    assert budget.available_for_investigation == input_bound

    with pytest.raises(TokenBudgetExhausted):
        await budget.reserve(request, 10, stage="worker_analysis", model="m")


@pytest.mark.asyncio
async def test_should_stop_falls_through_to_ledger_when_one_token_remains():
    """§7 경계: available_for_investigation == 1이면 floor 검사만으로 멈추면
    안 된다 -- 1은 0이 아니므로 ledger의 나머지 조건까지 내려가야 한다.

    `test_should_stop_when_only_the_floor_remains`는 ==0(short-circuit)만
    다뤘다. 여기서는 반대쪽 경계를 증명한다: ledger.open_questions가 실제로
    호출되고, 그 결과가 계속할 이유를 주면 should_stop은 False다.
    """

    class Ledger:
        async def total_spent(self):
            return 0

        async def open_questions(self):
            return [
                SimpleNamespace(
                    id="q1", value_est=1.0, confidence=0.0, spent_tokens=0,
                    cap_tokens=2000, fail_streak=0, depth=1, status="open",
                )
            ]

        async def gain_history(self, question_id, last_n=3):
            return []

    budget = TokenBudget(10_000, floor_tokens=9_999)
    budgeter = Budgeter(global_token_cap=10_000, token_budget=budget)

    assert budget.available_for_investigation == 1
    assert await budgeter.should_stop(Ledger()) is False


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
