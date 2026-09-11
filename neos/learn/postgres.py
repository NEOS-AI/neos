from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import text

from neos.learn.lessons import (
    Lesson,
    LessonStatus,
    SessionFactory,
    force_stage_on_write,
)


def _row_to_lesson(row: dict[str, object]) -> Lesson:
    created = row["created_at"]
    if not isinstance(created, datetime):
        raise TypeError("learned_lessons.created_at must be a datetime")
    return Lesson(
        lesson_id=str(row["lesson_id"]),
        namespace=str(row["namespace"]),
        title=str(row["title"]),
        body=str(row["body"]),
        status=LessonStatus(str(row["status"])),
        created_at=created,
        pinned=bool(row["pinned"]),
        kind=str(row["kind"]),
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
                            pinned, kind, created_at, updated_at
                        ) VALUES (
                            :lesson_id, :namespace, :title, :body, :status,
                            :pinned, :kind, :created_at, :updated_at
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
                    },
                )
        return stored

    async def get(self, lesson_id: str) -> Lesson | None:
        async with await self._session_factory() as session:
            result = await session.execute(
                text(
                    """
                    SELECT lesson_id, namespace, title, body, status,
                           pinned, kind, created_at, updated_at
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
            query = """
                SELECT lesson_id, namespace, title, body, status,
                       pinned, kind, created_at, updated_at
                FROM learned_lessons
            """
            params: dict[str, object] = {}
        else:
            query = """
                SELECT lesson_id, namespace, title, body, status,
                       pinned, kind, created_at, updated_at
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
                        "updated_at": now,
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
