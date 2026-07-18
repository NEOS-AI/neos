from datetime import UTC, datetime, timedelta

from neos.coding.auth.ws_tickets import InMemoryWsTicketStore


async def test_ticket_is_bound_to_task_and_consumed_once() -> None:
    store = InMemoryWsTicketStore(clock=lambda: datetime(2026, 7, 18, tzinfo=UTC))
    ticket = await store.issue(owner_id="u1", task_id="ct_1")

    assert await store.consume(ticket, task_id="ct_2") is None
    assert await store.consume(ticket, task_id="ct_1") == "u1"
    assert await store.consume(ticket, task_id="ct_1") is None


async def test_expired_ticket_cannot_be_consumed() -> None:
    now = datetime(2026, 7, 18, tzinfo=UTC)
    current = [now]
    store = InMemoryWsTicketStore(clock=lambda: current[0], ttl=timedelta(seconds=30))
    ticket = await store.issue(owner_id="u1", task_id="ct_1")
    current[0] = now + timedelta(seconds=31)

    assert await store.consume(ticket, task_id="ct_1") is None
