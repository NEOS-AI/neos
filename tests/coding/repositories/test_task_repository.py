from neos.coding.repositories.task_repository import CodingTaskRepository


class FakeDB:
    def __init__(self, row=None):
        self.row = row
        self.calls = []

    async def fetch_one(self, query, *params):
        self.calls.append((query, params))
        return self.row


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
        )
    )

    task = await CodingTaskRepository(db).get_owned("ct_1", "user_1")

    assert task is not None
    assert task.task_id == "ct_1"
    assert task.last_seq == 3
    assert task.status.value == "queued"

