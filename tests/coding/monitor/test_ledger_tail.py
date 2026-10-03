"""Q5b MP6: the monitor reads the ledger with a cursor, not from seq 0 every turn.

The Q5 shadow read a task's whole ledger at every model turn, judged or not.
Before the monitor may pause anything, the read is a cursor: per task, the last
seq seen and the most recent `max_events` events.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from neos.coding.domain.events import make_event
from neos.coding.monitor.ledger import LedgerTail

pytestmark = pytest.mark.no_db

NOW = datetime(2026, 10, 2, tzinfo=UTC)


class Ledger:
    def __init__(self) -> None:
        self.events: dict[str, list] = {}
        self.reads: list[tuple[str, int]] = []
        self.fail_after: int | None = None

    def add(self, task_id: str, count: int) -> None:
        rows = self.events.setdefault(task_id, [])
        for _ in range(count):
            seq = len(rows) + 1
            rows.append(
                make_event(task_id=task_id, seq=seq, event_type="tool.completed", payload={}, now=NOW)
            )

    async def __call__(self, task_id, *, after_seq=0, limit=500):
        self.reads.append((task_id, after_seq))
        if self.fail_after is not None and after_seq >= self.fail_after:
            raise RuntimeError("db blip")
        return [e for e in self.events.get(task_id, []) if e.seq > after_seq][:limit]


@pytest.mark.asyncio
async def test_the_second_read_starts_after_the_last_seq_seen() -> None:
    ledger, tail = Ledger(), LedgerTail(max_events=100)
    ledger.add("ct_1", 3)
    assert [e.seq for e in await tail.read(ledger, "ct_1")] == [1, 2, 3]

    ledger.reads.clear()
    ledger.add("ct_1", 2)
    events = await tail.read(ledger, "ct_1")

    assert [e.seq for e in events] == [1, 2, 3, 4, 5]
    assert ledger.reads == [("ct_1", 3)]  # never from 0 again


@pytest.mark.asyncio
async def test_a_turn_with_nothing_new_reads_one_empty_page() -> None:
    ledger, tail = Ledger(), LedgerTail(max_events=100)
    ledger.add("ct_1", 1200)
    await tail.read(ledger, "ct_1")
    ledger.reads.clear()

    events = await tail.read(ledger, "ct_1")

    assert len(events) == 100
    assert ledger.reads == [("ct_1", 1200)]


@pytest.mark.asyncio
async def test_it_keeps_only_the_most_recent_max_events() -> None:
    ledger, tail = Ledger(), LedgerTail(max_events=100)
    ledger.add("ct_1", 1200)

    events = await tail.read(ledger, "ct_1")

    assert [e.seq for e in events] == list(range(1101, 1201))


@pytest.mark.asyncio
async def test_tasks_do_not_share_a_cursor() -> None:
    ledger, tail = Ledger(), LedgerTail(max_events=100)
    ledger.add("ct_1", 3)
    ledger.add("ct_2", 1)
    await tail.read(ledger, "ct_1")

    assert [e.seq for e in await tail.read(ledger, "ct_2")] == [1]
    assert ("ct_2", 0) in ledger.reads


@pytest.mark.asyncio
async def test_a_forgotten_task_is_read_from_the_start_again() -> None:
    ledger, tail = Ledger(), LedgerTail(max_events=100, max_tasks=1)
    ledger.add("ct_1", 3)
    ledger.add("ct_2", 1)
    await tail.read(ledger, "ct_1")
    await tail.read(ledger, "ct_2")  # evicts ct_1
    ledger.reads.clear()

    assert [e.seq for e in await tail.read(ledger, "ct_1")] == [1, 2, 3]
    assert ledger.reads[0] == ("ct_1", 0)


@pytest.mark.asyncio
async def test_overlapping_pages_do_not_duplicate_events() -> None:
    """A reader that hands back an event already seen does not add it twice."""
    ledger, tail = Ledger(), LedgerTail(max_events=100)
    ledger.add("ct_1", 3)
    await tail.read(ledger, "ct_1")

    async def stale(task_id, *, after_seq=0, limit=500):
        return ledger.events[task_id][1:]  # seq 2..3 again

    events = await tail.read(stale, "ct_1")

    assert [e.seq for e in events] == [1, 2, 3]


@pytest.mark.asyncio
async def test_a_failed_read_keeps_what_was_already_read() -> None:
    ledger, tail = Ledger(), LedgerTail(max_events=2000)
    ledger.add("ct_1", 700)
    ledger.fail_after = 500  # the second page fails

    with pytest.raises(RuntimeError):
        await tail.read(ledger, "ct_1")

    ledger.fail_after = None
    ledger.reads.clear()
    events = await tail.read(ledger, "ct_1")
    assert [e.seq for e in events] == list(range(1, 701))
    assert ledger.reads == [("ct_1", 500)]


def test_bounds_are_positive() -> None:
    with pytest.raises(ValueError):
        LedgerTail(max_events=0)
    with pytest.raises(ValueError):
        LedgerTail(max_events=1, max_tasks=0)


def test_the_configured_max_events_reaches_the_monitor() -> None:
    """Q5 read `getattr(monitor, "max_events", 2000)` but the monitor had no such
    attribute -- the setting never reached the read. Now it does."""
    from neos.config.schema import JevConfig
    from neos.jev.assembly import build_trajectory_monitor

    config = JevConfig(
        enabled=True,
        model="jev-1.13.0",
        monitor={"shadow_enabled": True, "pause_at_or_above": 0.7, "max_events": 300},
    )

    assert build_trajectory_monitor(config, api_key="k", client=object()).max_events == 300
