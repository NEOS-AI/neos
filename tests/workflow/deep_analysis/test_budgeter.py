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


# --- G8: 예산에 굶주린 예약은 내주지 않고 거절한다 (2026-08-04 실측) ---
#
# 2026-08-04 라이브 샘플에서 dev run 5건이 전부 죽었다. reserve()가 1토큰만
# 남아도 예약을 내주는 바람에 25·38·851·1123 토큰짜리 JSON 호출이 발급됐고,
# 확실히 잘린 응답이 TruncatedResponseError로 run 전체를 실패시켰다.


@pytest.mark.asyncio
async def test_reserve_refuses_a_grant_below_the_viability_threshold():
    """예산이 상한 아래로 깎아버린 예약은 내주지 않고 거절한다.

    실패한 run의 재현: 3200을 요청했는데 예산이 25만 내줄 수 있는 상황.
    """
    request = {"model": "m"}
    input_bound = conservative_input_bound(request)
    # ceiling - input_bound == 25 인 cap을 만든다.
    budget = TokenBudget(
        input_bound + 25, min_viable_output_tokens=2_048
    )

    with pytest.raises(TokenBudgetExhausted):
        await budget.reserve(
            request, 3_200, stage="split_decompose", model="m"
        )


@pytest.mark.asyncio
async def test_reserve_allows_a_small_request_the_caller_actually_asked_for():
    """임계값은 caller의 요청량으로 clamp된다 — 일부러 적게 요청한 stage는
    영향을 받지 않는다.

    리포트 판정자는 800만 요청한다. 임계값 2048을 그대로 적용하면 예산이
    충분한데도 판정자가 영구히 거절당한다.
    """
    request = {"model": "m"}
    budget = TokenBudget(100_000, min_viable_output_tokens=2_048)

    reservation = await budget.reserve(
        request, 800, stage="report_grading", model="m"
    )

    assert reservation.max_output_tokens == 800


@pytest.mark.asyncio
async def test_viability_threshold_defaults_to_preserving_old_behaviour():
    """기본값 1은 2026-08-04 이전 동작 그대로다 — 1토큰이면 예약이 나간다.

    골든 카세트 테스트가 1,000토큰짜리 cap으로 orchestrator를 만든다.
    출하 기본값 2048을 여기에 적용하면 그 run들은 아무 예약도 받지 못한다.
    """
    request = {"model": "m"}
    input_bound = conservative_input_bound(request)
    budget = TokenBudget(input_bound + 1)

    assert budget.min_viable_output_tokens == 1
    reservation = await budget.reserve(
        request, 3_200, stage="split_decompose", model="m"
    )

    assert reservation.max_output_tokens == 1


@pytest.mark.asyncio
async def test_should_stop_at_the_viability_threshold_not_at_zero():
    """floor 위에 남은 몫이 임계값 미만이면 조사를 끝낸다.

    워커는 TokenBudgetExhausted를 flush_partial로 삼켜버린다. 임계값을
    무시하고 0까지 계속하면 아무 진전 없는 라운드만 stall cap까지 반복된다.
    """

    class Ledger:
        async def total_spent(self):
            return 0

        async def open_questions(self):
            raise AssertionError("viability stop must short-circuit")

    budget = TokenBudget(
        10_000, floor_tokens=9_000, min_viable_output_tokens=2_048
    )
    budgeter = Budgeter(global_token_cap=10_000, token_budget=budget)

    assert budget.available_for_investigation == 1_000
    assert await budgeter.should_stop(Ledger()) is True


def test_orchestrator_defaults_the_threshold_to_one_and_accepts_injection():
    """floor와 같은 이유로 주입식이다 — 작은 cap으로 만드는 테스트를 깨지 않는다."""
    default = Orchestrator(
        object(), "run0001", lambda: None, None, global_token_cap=1_000
    )
    assert default.token_budget.min_viable_output_tokens == 1

    injected = Orchestrator(
        object(),
        "run0002",
        lambda: None,
        None,
        global_token_cap=20_000,
        finalization_floor_tokens=4_400,
        min_viable_output_tokens=2_048,
    )
    assert injected.token_budget.min_viable_output_tokens == 2_048


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


class _StubLedger:
    """Mirrors the ledger stubs in test_orchestrator_token_budget.py --
    only `token_budget_state` is exercised by `_install_token_budget`."""

    async def token_budget_state(self):
        return 0, {}


@pytest.mark.asyncio
async def test_install_token_budget_carries_both_tiers_into_the_rebuilt_budget():
    """`_install_token_budget` rebuilds `token_budget` at the start of every
    `run()`, to restore consumed/outstanding tokens after a crash. Every
    other tier assertion in this module reads `orchestrator.token_budget`
    as set by `__init__` -- so a regression that drops `floor_tokens` or
    `report_floor_tokens` from the `TokenBudget(...)` call inside
    `_install_token_budget` (as opposed to `__init__`) would leave the
    whole suite green while every real run silently lost the tier. This
    test rebuilds the budget the same way `run()` does and asserts on the
    result, so that specific regression fails here instead of only in
    production.
    """
    orch = Orchestrator(
        object(),
        "run0001",
        lambda: None,
        None,
        ledger=_StubLedger(),
        global_token_cap=100_000,
        finalization_floor_tokens=41_040,
        report_floor_tokens=34_800,
    )

    await orch._install_token_budget()

    assert orch.token_budget.floor_tokens == 41_040
    assert orch.token_budget.report_floor_tokens == 34_800
