from datetime import datetime
from typing import Protocol

from neos.coding.domain.models import CodingTask, CodingTaskMode, CodingTaskStatus


class Database(Protocol):
    async def fetch_one(self, query: str, *params): ...
    async def fetch_all(self, query: str, *params): ...
    async def execute(self, query: str, *params): ...


class CodingTaskRepository:
    def __init__(self, database: Database):
        self._database = database

    async def get(self, task_id: str) -> CodingTask | None:
        row = await self._database.fetch_one(
            """
            SELECT task_id, owner_id, prompt, status, version, last_seq,
                   created_at, updated_at, mode
            FROM coding_tasks
            WHERE task_id = $1 AND deleted_at IS NULL
            """,
            task_id,
        )
        return _task_from_row(row)

    async def get_owned(self, task_id: str, owner_id: str) -> CodingTask | None:
        row = await self._database.fetch_one(
            """
            SELECT task_id, owner_id, prompt, status, version, last_seq,
                   created_at, updated_at, mode
            FROM coding_tasks
            WHERE task_id = $1 AND owner_id = $2 AND deleted_at IS NULL
            """,
            task_id,
            owner_id,
        )
        return _task_from_row(row)

    async def list_owned(self, owner_id: str, *, limit: int) -> list[CodingTask]:
        rows = await self._database.fetch_all(
            """
            SELECT task_id, owner_id, prompt, status, version, last_seq,
                   created_at, updated_at, mode
            FROM coding_tasks
            WHERE owner_id = $1 AND deleted_at IS NULL
            ORDER BY last_activity_at DESC, task_id DESC
            LIMIT $2
            """,
            owner_id,
            max(1, min(int(limit), 50)),
        )
        return [
            task
            for row in rows or ()
            if (task := _task_from_row(row)) is not None
        ]

    async def archive(self, task_id: str, owner_id: str) -> bool:
        result = await self._database.execute(
            """
            UPDATE coding_tasks
               SET status = 'archived',
                   deleted_at = NOW(),
                   updated_at = NOW(),
                   version = version + 1
             WHERE task_id = $1 AND owner_id = $2 AND deleted_at IS NULL
               AND status IN ('failed', 'completed', 'cancelled', 'expired')
            RETURNING task_id
            """,
            task_id,
            owner_id,
        )
        row = result.fetchone() if hasattr(result, "fetchone") else None
        if row is None:
            first = getattr(result, "first", None)
            row = first() if callable(first) else None
        if row is not None:
            return True
        return bool(getattr(result, "rowcount", 0))


def _task_from_row(row) -> CodingTask | None:
    if row is None:
        return None
    return CodingTask(
        task_id=row[0],
        owner_id=row[1],
        prompt=row[2],
        status=CodingTaskStatus(row[3]),
        version=row[4],
        last_seq=row[5],
        created_at=_as_datetime(row[6]),
        updated_at=_as_datetime(row[7]),
        mode=CodingTaskMode(row[8]),
    )


def _as_datetime(value: datetime | str) -> datetime:
    return value if isinstance(value, datetime) else datetime.fromisoformat(value)
