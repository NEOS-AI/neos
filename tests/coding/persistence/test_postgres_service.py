from contextlib import asynccontextmanager

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


async def test_event_is_published_only_after_transaction_exits() -> None:
    timeline: list[str] = []

    class TrackingTransaction(FakeTransaction):
        async def __aexit__(self, *_):
            timeline.append("committed")
            return False

    class TrackingSession(FakeSession):
        def begin(self):
            return TrackingTransaction()

    class Broker:
        async def publish(self, event):
            timeline.append(f"published:{event.seq}")

    async def session_factory():
        return TrackingSession()

    service = PostgresCodingService(session_factory, broker=Broker())
    await service.append(
        task_id="ct_fixed", event_type="text.delta", payload={"delta": "hi"}
    )

    assert timeline == ["committed", "published:1"]


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
