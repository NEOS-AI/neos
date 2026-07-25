from datetime import UTC, datetime, timedelta

from neos.coding.transport.workspace_tickets import (
    InMemoryWorkspaceTicketStore,
    WorkspaceStreamKind,
)


async def test_ticket_is_one_time_and_kind_bound() -> None:
    tickets = InMemoryWorkspaceTicketStore()
    token = await tickets.issue(
        owner_id="u1",
        task_id="ct_1",
        kind=WorkspaceStreamKind.PTY,
    )

    assert (
        await tickets.consume(
            token,
            task_id="ct_1",
            kind=WorkspaceStreamKind.WATCHER,
        )
        is None
    )
    assert (
        await tickets.consume(
            token,
            task_id="ct_1",
            kind=WorkspaceStreamKind.PTY,
        )
        == "u1"
    )
    assert (
        await tickets.consume(
            token,
            task_id="ct_1",
            kind=WorkspaceStreamKind.PTY,
        )
        is None
    )


async def test_wrong_task_does_not_burn_ticket_and_expired_ticket_is_removed() -> None:
    now = datetime(2026, 7, 23, tzinfo=UTC)
    tickets = InMemoryWorkspaceTicketStore(
        clock=lambda: now,
        ttl=timedelta(seconds=1),
    )
    token = await tickets.issue(
        owner_id="u1",
        task_id="ct_1",
        kind=WorkspaceStreamKind.WATCHER,
    )

    assert (
        await tickets.consume(
            token,
            task_id="ct_other",
            kind=WorkspaceStreamKind.WATCHER,
        )
        is None
    )
    assert (
        await tickets.consume(
            token,
            task_id="ct_1",
            kind=WorkspaceStreamKind.WATCHER,
        )
        == "u1"
    )

    expired = await tickets.issue(
        owner_id="u1",
        task_id="ct_1",
        kind=WorkspaceStreamKind.WATCHER,
    )
    now += timedelta(seconds=2)
    assert (
        await tickets.consume(
            expired,
            task_id="ct_1",
            kind=WorkspaceStreamKind.WATCHER,
        )
        is None
    )
