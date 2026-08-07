import asyncio

import pytest

from neos.workflow.deep_analysis.token_budget import (
    TokenBudget,
    TokenBudgetContractError,
    TokenBudgetExhausted,
    TokenReservation,
    active_token_budget,
    conservative_input_bound,
    token_budget_scope,
)


pytestmark = pytest.mark.no_db


@pytest.mark.asyncio
async def test_concurrent_reservations_never_exceed_cap():
    budget = TokenBudget(100)

    results = await asyncio.gather(
        *(
            budget.reserve("x" * 10, 30, stage="worker", model="m")
            for _ in range(4)
        ),
        return_exceptions=True,
    )

    accepted = [r for r in results if isinstance(r, TokenReservation)]
    assert sum(r.reserved_tokens for r in accepted) <= 100
    assert any(isinstance(r, TokenBudgetExhausted) for r in results)


@pytest.mark.asyncio
async def test_settle_refunds_unused_capacity():
    budget = TokenBudget(100)
    reservation = await budget.reserve("x", 50, stage="worker", model="m")
    before = budget.remaining_tokens

    await budget.settle(reservation, 10)

    assert budget.consumed_tokens == 10
    assert budget.reserved_tokens == 0
    assert budget.remaining_tokens > before


@pytest.mark.asyncio
async def test_contract_error_when_actual_exceeds_reservation():
    budget = TokenBudget(100)
    reservation = await budget.reserve("x", 10, stage="worker", model="m")

    with pytest.raises(TokenBudgetContractError):
        await budget.settle(reservation, reservation.reserved_tokens + 1)

    assert budget.reserved_tokens == reservation.reserved_tokens


@pytest.mark.asyncio
async def test_persistence_precedes_reusable_capacity_changes():
    observed = []
    budget = None

    async def persist(kind, payload):
        observed.append((kind, payload, budget.remaining_tokens))

    budget = TokenBudget(120, persist=persist)
    reservation = await budget.reserve("x", 20, stage="worker", model="m")
    remaining_while_reserved = budget.remaining_tokens
    await budget.release(reservation)

    assert [event[0] for event in observed] == [
        "token_budget_reserved",
        "token_budget_released",
    ]
    assert observed[0][2] == 120
    assert observed[1][2] == remaining_while_reserved
    assert budget.remaining_tokens == 120


@pytest.mark.asyncio
async def test_abandon_keeps_ambiguous_dispatch_fully_reserved():
    budget = TokenBudget(100)
    reservation = await budget.reserve("x", 20, stage="worker", model="m")

    await budget.abandon(reservation)

    assert budget.reserved_tokens == reservation.reserved_tokens
    assert budget.remaining_tokens == 100 - reservation.reserved_tokens


@pytest.mark.asyncio
async def test_recovered_outstanding_reservations_reduce_remaining_budget():
    budget = TokenBudget(100, consumed_tokens=15, outstanding={"old": 25})

    assert budget.consumed_tokens == 15
    assert budget.reserved_tokens == 25
    assert budget.remaining_tokens == 60


def test_recovered_usage_above_reconfigured_cap_fails_closed():
    budget = TokenBudget(20, consumed_tokens=15, outstanding={"old": 10})

    assert budget.remaining_tokens == -5
    assert budget.exhausted is True


@pytest.mark.asyncio
async def test_context_scopes_are_isolated_across_tasks():
    first = TokenBudget(100)
    second = TokenBudget(200)

    async def observe(budget):
        with token_budget_scope(budget):
            await asyncio.sleep(0)
            return active_token_budget()

    observed = await asyncio.gather(observe(first), observe(second))

    assert observed == [first, second]
    assert active_token_budget() is None


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
