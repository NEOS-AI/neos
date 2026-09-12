from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import text

from neos.learn.lessons import (
    Lesson,
    LessonStatus,
    SessionFactory,
    force_stage_on_write,
)

_LESSON_COLUMNS = """
    lesson_id, namespace, title, body, status,
    pinned, kind, created_at, updated_at,
    last_injected_at, inject_count
"""


def _row_to_lesson(row: dict[str, object]) -> Lesson:
    created = row["created_at"]
    if not isinstance(created, datetime):
        raise TypeError("learned_lessons.created_at must be a datetime")
    last_injected = row.get("last_injected_at")
    if last_injected is not None and not isinstance(last_injected, datetime):
        raise TypeError("learned_lessons.last_injected_at must be a datetime")
    raw_count = row.get("inject_count")
    return Lesson(
        lesson_id=str(row["lesson_id"]),
        namespace=str(row["namespace"]),
        title=str(row["title"]),
        body=str(row["body"]),
        status=LessonStatus(str(row["status"])),
        created_at=created,
        pinned=bool(row["pinned"]),
        kind=str(row["kind"]),
        last_injected_at=last_injected,
        inject_count=0 if raw_count is None else int(raw_count),
    )


class PostgresLessonStore:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def add(self, lesson: Lesson) -> Lesson:
        stored = force_stage_on_write(lesson)
        now = datetime.now(UTC)
        async with await self._session_factory() as session:
            async with session.begin():
                await session.execute(
                    text(
                        """
                        INSERT INTO learned_lessons (
                            lesson_id, namespace, title, body, status,
                            pinned, kind, created_at, updated_at,
                            last_injected_at, inject_count
                        ) VALUES (
                            :lesson_id, :namespace, :title, :body, :status,
                            :pinned, :kind, :created_at, :updated_at,
                            :last_injected_at, :inject_count
                        )
                        """
                    ),
                    {
                        "lesson_id": stored.lesson_id,
                        "namespace": stored.namespace,
                        "title": stored.title,
                        "body": stored.body,
                        "status": stored.status.value,
                        "pinned": stored.pinned,
                        "kind": stored.kind,
                        "created_at": stored.created_at,
                        "updated_at": now,
                        "last_injected_at": stored.last_injected_at,
                        "inject_count": stored.inject_count,
                    },
                )
        return stored

    async def get(self, lesson_id: str) -> Lesson | None:
        async with await self._session_factory() as session:
            result = await session.execute(
                text(
                    """
                    SELECT lesson_id, namespace, title, body, status,
                           pinned, kind, created_at, updated_at,
                           last_injected_at, inject_count
                    FROM learned_lessons
                    WHERE lesson_id = :lesson_id
                    """
                ),
                {"lesson_id": lesson_id},
            )
            row = result.mappings().first()
        if row is None:
            return None
        return _row_to_lesson(dict(row))

    async def list(self, namespace: str | None = None) -> tuple[Lesson, ...]:
        if namespace is None:
            query = f"""
                SELECT {_LESSON_COLUMNS}
                FROM learned_lessons
            """
            params: dict[str, object] = {}
        else:
            query = f"""
                SELECT {_LESSON_COLUMNS}
                FROM learned_lessons
                WHERE namespace = :namespace
            """
            params = {"namespace": namespace}
        async with await self._session_factory() as session:
            result = await session.execute(text(query), params)
            rows = result.mappings().all()
        return tuple(_row_to_lesson(dict(row)) for row in rows)

    async def update(self, lesson: Lesson) -> None:
        now = datetime.now(UTC)
        async with await self._session_factory() as session:
            async with session.begin():
                await session.execute(
                    text(
                        """
                        UPDATE learned_lessons
                        SET namespace = :namespace,
                            title = :title,
                            body = :body,
                            status = :status,
                            pinned = :pinned,
                            kind = :kind,
                            last_injected_at = :last_injected_at,
                            inject_count = :inject_count,
                            updated_at = :updated_at
                        WHERE lesson_id = :lesson_id
                        """
                    ),
                    {
                        "lesson_id": lesson.lesson_id,
                        "namespace": lesson.namespace,
                        "title": lesson.title,
                        "body": lesson.body,
                        "status": lesson.status.value,
                        "pinned": lesson.pinned,
                        "kind": lesson.kind,
                        "last_injected_at": lesson.last_injected_at,
                        "inject_count": lesson.inject_count,
                        "updated_at": now,
                    },
                )

    async def record_inject(
        self, lesson_ids: Sequence[str], *, now: datetime | None = None
    ) -> None:
        if not lesson_ids:
            return
        injected_at = now or datetime.now(UTC)
        async with await self._session_factory() as session:
            async with session.begin():
                for lesson_id in lesson_ids:
                    await session.execute(
                        text(
                            """
                            UPDATE learned_lessons
                            SET last_injected_at = :now,
                                inject_count = COALESCE(inject_count, 0) + 1,
                                updated_at = :now
                            WHERE lesson_id = :lesson_id
                              AND status = :status
                            """
                        ),
                        {
                            "now": injected_at,
                            "lesson_id": lesson_id,
                            "status": LessonStatus.APPROVED.value,
                        },
                    )

    async def approved_texts(self, namespace: str) -> tuple[str, ...]:
        async with await self._session_factory() as session:
            result = await session.execute(
                text(
                    """
                    SELECT body
                    FROM learned_lessons
                    WHERE namespace = :namespace AND status = :status
                    """
                ),
                {
                    "namespace": namespace,
                    "status": LessonStatus.APPROVED.value,
                },
            )
            rows = result.mappings().all()
        return tuple(str(row["body"]) for row in rows)
