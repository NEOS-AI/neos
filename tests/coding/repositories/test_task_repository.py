import pytest

from neos.coding.repositories.task_repository import CodingTaskRepository

pytestmark = pytest.mark.no_db


class FakeResult:
    def __init__(self, row=None):
        self._row = row
        self.rowcount = 0 if row is None else 1

    def fetchone(self):
        return self._row

    def first(self):
        return self._row


class FakeDB:
    def __init__(self, row=None, rows=None):
        self.row = row
        self.rows = rows or []
        self.calls = []
        self.methods: list[str] = []

    async def fetch_one(self, query, *params):
        self.methods.append("fetch_one")
        self.calls.append((query, params))
        return self.row

    async def fetch_all(self, query, *params):
        self.methods.append("fetch_all")
        self.calls.append((query, params))
        return self.rows

    async def execute(self, query, *params):
        self.methods.append("execute")
        self.calls.append((query, params))
        return FakeResult(self.row)


async def test_get_owned_scopes_query_to_task_and_owner() -> None:
    db = FakeDB()

    task = await CodingTaskRepository(db).get_owned("ct_1", "user_1")

    assert task is None
    query, params = db.calls[0]
    assert "task_id = $1" in query
    assert "owner_id = $2" in query
    assert params == ("ct_1", "user_1")


async def test_get_owned_maps_task_row() -> None:
    db = FakeDB(
        (
            "ct_1",
            "user_1",
            "Fix it",
            "queued",
            1,
            3,
            "2026-07-18T10:00:00+00:00",
            "2026-07-18T10:01:00+00:00",
            "autonomous",
        )
    )

    task = await CodingTaskRepository(db).get_owned("ct_1", "user_1")

    assert task is not None
    assert task.task_id == "ct_1"
    assert task.last_seq == 3
    assert task.status.value == "queued"
    # K9: the run service reads the task through this repository, and the loop
    # judges unattended from it. Mutation: drop `mode` from the select or the
    # mapping -> an autonomous task resumes as interactive.
    assert task.mode.value == "autonomous"
    assert "mode" in db.calls[0][0]


async def test_list_owned_scopes_query_to_owner_and_orders_by_activity() -> None:
    db = FakeDB()

    tasks = await CodingTaskRepository(db).list_owned("user_1", limit=20)

    assert tasks == []
    query, params = db.calls[0]
    assert "owner_id = $1" in query
    assert "deleted_at IS NULL" in query
    assert "ORDER BY last_activity_at DESC, task_id DESC" in query
    assert params == ("user_1", 20)


async def test_archive_returns_false_when_update_matches_nothing() -> None:
    db = FakeDB(row=None)

    ok = await CodingTaskRepository(db).archive("ct_1", "user_1")

    assert ok is False
    assert db.methods == ["execute"]
    query, params = db.calls[0]
    assert "UPDATE coding_tasks" in query
    assert "RETURNING task_id" in query
    assert "status IN ('failed', 'completed', 'cancelled', 'expired')" in query
    assert params == ("ct_1", "user_1")


async def test_archive_returns_true_when_returning_row() -> None:
    db = FakeDB(row=("ct_1",))

    ok = await CodingTaskRepository(db).archive("ct_1", "user_1")

    assert ok is True
    assert db.methods == ["execute"]

