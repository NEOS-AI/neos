import asyncio

import pytest

from neos.workflow.deep_analysis.token_budget import (
    TokenBudget,
    TokenBudgetContractError,
    TokenBudgetExhausted,
    TokenReservation,
    active_token_budget,
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
