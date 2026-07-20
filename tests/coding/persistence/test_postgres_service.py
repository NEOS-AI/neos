import pytest

from neos.coding.persistence.postgres import PostgresCodingService


class FakeResult:
    def __init__(self, row=None):
        self._row = row

    def first(self):
        return self._row

    def all(self):
        return []

    def scalar_one(self):
        return self._row[0]


class FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False


class FakeSession:
    def __init__(self):
        self.statements = []

    def begin(self):
        return FakeTransaction()

    async def execute(self, statement, params=None):
        sql = str(statement)
        self.statements.append((sql, params or {}))
        if "RETURNING last_seq" in sql:
            return FakeResult((1,))
        return FakeResult()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False


async def test_create_task_and_first_event_share_one_transaction() -> None:
    session = FakeSession()

    async def session_factory():
        return session

    service = PostgresCodingService(session_factory)

    task = await service.create_task(
        owner_id="u1", prompt="Fix it", task_id="ct_fixed"
    )

    sql = "\n".join(statement for statement, _ in session.statements)
    assert "INSERT INTO coding_tasks" in sql
    assert "UPDATE coding_tasks" in sql
    assert "INSERT INTO coding_events" in sql
    assert task.last_seq == 1


async def test_event_append_locks_task_sequence_before_insert() -> None:
    session = FakeSession()

    async def session_factory():
        return session

    service = PostgresCodingService(session_factory)
    await service.append(
        task_id="ct_fixed", event_type="text.delta", payload={"delta": "hi"}
    )

    sql = "\n".join(statement for statement, _ in session.statements)
    assert "FOR UPDATE" in sql
    assert sql.index("FOR UPDATE") < sql.index("INSERT INTO coding_events")


async def test_event_append_wakes_outbox_only_after_transaction_exits() -> None:
    timeline: list[str] = []

    class TrackingTransaction(FakeTransaction):
        async def __aexit__(self, *_):
            timeline.append("committed")
            return False

    class TrackingSession(FakeSession):
        def begin(self):
            return TrackingTransaction()

    async def session_factory():
        return TrackingSession()

    service = PostgresCodingService(
        session_factory, wake_outbox=lambda: timeline.append("woken")
    )
    await service.append(
        task_id="ct_fixed", event_type="text.delta", payload={"delta": "hi"}
    )

    assert timeline == ["committed", "woken"]


async def test_event_and_outbox_are_inserted_in_same_transaction() -> None:
    session = FakeSession()

    async def session_factory():
        return session

    service = PostgresCodingService(session_factory)
    await service.append(
        task_id="ct_fixed", event_type="text.delta", payload={"delta": "hi"}
    )

    sql = "\n".join(statement for statement, _ in session.statements)
    assert "INSERT INTO coding_events" in sql
    assert "INSERT INTO coding_event_outbox" in sql
    assert sql.index("INSERT INTO coding_events") < sql.index(
        "INSERT INTO coding_event_outbox"
    )


async def test_non_checkpoint_event_metadata_is_persisted_for_durable_replay() -> None:
    session = FakeSession()

    async def session_factory():
        return session

    service = PostgresCodingService(session_factory)
    event = await service.append(
        task_id="ct_fixed",
        event_type="checkpoint.created",
        payload={},
        run_id="cr_1",
        turn_id="turn_1",
        tool_call_id="tool_1",
    )

    event_insert = next(
        (sql, params)
        for sql, params in session.statements
        if "INSERT INTO coding_events" in sql
    )
    sql, params = event_insert
    assert "checkpoint_id" in sql
    assert params["checkpoint_id"] is None
    assert event.checkpoint_id is None


async def test_generic_append_rejects_checkpoint_identity() -> None:
    service = PostgresCodingService(lambda: None)

    with pytest.raises(ValueError, match="atomic checkpoint command"):
        await service.append(
            task_id="ct_1",
            event_type="phase.completed",
            payload={},
            checkpoint_id="cc_1",
        )


async def test_task_notifier_runs_after_transaction_and_outbox_wake() -> None:
    timeline: list[str] = []

    class TrackingTransaction(FakeTransaction):
        async def __aexit__(self, *_):
            timeline.append("transaction.exit")
            return False

    class TrackingSession(FakeSession):
        def begin(self):
            return TrackingTransaction()

    async def session_factory():
        return TrackingSession()

    service = PostgresCodingService(
        session_factory, wake_outbox=lambda: timeline.append("outbox.wake")
    )
    service.set_task_created_notifier(
        lambda task_id: timeline.append("task.notify")
    )

    await service.create_task(owner_id="u1", prompt="Fix it")

    assert timeline == ["transaction.exit", "outbox.wake", "task.notify"]


async def test_postgres_notifier_failure_does_not_rollback_task() -> None:
    session = FakeSession()

    async def session_factory():
        return session

    service = PostgresCodingService(session_factory)

    def fail_notification(task_id: str) -> None:
        raise RuntimeError("wake failed")

    service.set_task_created_notifier(fail_notification)

    task = await service.create_task(owner_id="u1", prompt="Fix it")

    assert task.task_id
    assert any("INSERT INTO coding_tasks" in sql for sql, _ in session.statements)
