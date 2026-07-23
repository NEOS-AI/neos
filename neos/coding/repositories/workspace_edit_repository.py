import json
from datetime import datetime
from uuid import uuid4

from sqlalchemy import text

from neos.coding.domain.events import CodingEvent
from neos.coding.domain.workspace_edits import (
    CodingWorkspaceEdit,
    WorkspaceEditCommit,
    WorkspaceEditConflict,
    WorkspaceEditStatus,
)
from neos.coding.persistence.postgres import SessionFactory


_COLUMNS = """
edit_id, task_id, run_id, path, base_revision, resulting_revision, status,
content_digest, content_bytes, created_at, committed_at, applied_checkpoint_id
"""


class PostgresWorkspaceEditRepository:
    def __init__(self, session_factory: SessionFactory, wake_outbox=None) -> None:
        self._session_factory = session_factory
        self._wake_outbox = wake_outbox

    async def prepare_edit(
        self,
        *,
        task_id: str,
        run_id: str,
        edit_id: str,
        path: str,
        base_revision: str,
        digest: str,
        content_bytes: int,
        now: datetime,
    ) -> WorkspaceEditCommit:
        async with await self._session_factory() as session:
            async with session.begin():
                canonical = await session.execute(
                    text(
                        """
                        SELECT run.run_id
                        FROM coding_runs AS run
                        JOIN coding_tasks AS task ON task.task_id = run.task_id
                        WHERE run.run_id = :run_id
                          AND run.task_id = :task_id
                          AND run.status = 'running'
                          AND task.status = 'running'
                          AND task.deleted_at IS NULL
                          AND run.attempt = (
                              SELECT MAX(candidate.attempt)
                              FROM coding_runs AS candidate
                              WHERE candidate.task_id = :task_id
                          )
                        FOR UPDATE OF run
                        """
                    ),
                    {"task_id": task_id, "run_id": run_id},
                )
                if canonical.first() is None:
                    raise WorkspaceEditConflict("workspace_run_changed")
                inserted = await session.execute(
                    text(
                        f"""
                        INSERT INTO coding_workspace_edits
                            (edit_id, task_id, run_id, path, base_revision,
                             resulting_revision, status, content_digest,
                             content_bytes, created_at, committed_at,
                             applied_checkpoint_id)
                        VALUES
                            (:edit_id, :task_id, :run_id, :path, :base_revision,
                             NULL, 'prepared', :content_digest, :content_bytes,
                             :created_at, NULL, NULL)
                        ON CONFLICT (edit_id) DO NOTHING
                        RETURNING {_COLUMNS}
                        """
                    ),
                    {
                        "edit_id": edit_id,
                        "task_id": task_id,
                        "run_id": run_id,
                        "path": path,
                        "base_revision": base_revision,
                        "content_digest": digest,
                        "content_bytes": content_bytes,
                        "created_at": now,
                    },
                )
                row = inserted.first()
                created = row is not None
                if row is None:
                    existing = await session.execute(
                        text(
                            f"""
                            SELECT {_COLUMNS}
                            FROM coding_workspace_edits
                            WHERE edit_id = :edit_id
                            FOR UPDATE
                            """
                        ),
                        {"edit_id": edit_id},
                    )
                    row = existing.first()
                edit = self._require_row(row, edit_id)
                if (
                    edit.task_id,
                    edit.run_id,
                    edit.path,
                    edit.base_revision,
                    edit.content_digest,
                    edit.content_bytes,
                ) != (
                    task_id,
                    run_id,
                    path,
                    base_revision,
                    digest,
                    content_bytes,
                ):
                    raise WorkspaceEditConflict("workspace_edit_exists")
        return WorkspaceEditCommit(edit=edit, event=None, created=created)

    async def commit_edit(
        self, *, edit_id: str, resulting_revision: str, now: datetime
    ) -> WorkspaceEditCommit:
        event: CodingEvent | None = None
        async with await self._session_factory() as session:
            async with session.begin():
                selected = await session.execute(
                    text(
                        f"""
                        SELECT {_COLUMNS}
                        FROM coding_workspace_edits
                        WHERE edit_id = :edit_id
                        FOR UPDATE
                        """
                    ),
                    {"edit_id": edit_id},
                )
                edit = self._require_row(selected.first(), edit_id)
                if edit.status is WorkspaceEditStatus.COMMITTED:
                    if edit.resulting_revision != resulting_revision:
                        raise WorkspaceEditConflict("workspace_edit_exists")
                    return WorkspaceEditCommit(edit, None, False)
                if edit.status not in {
                    WorkspaceEditStatus.PREPARED,
                    WorkspaceEditStatus.RECONCILE_REQUIRED,
                }:
                    raise WorkspaceEditConflict("workspace_edit_not_committable")
                sequence = await session.execute(
                    text(
                        """
                        UPDATE coding_tasks
                        SET last_seq = last_seq + 1,
                            updated_at = :now,
                            last_activity_at = :now
                        WHERE task_id = :task_id
                        RETURNING last_seq
                        """
                    ),
                    {"task_id": edit.task_id, "now": now},
                )
                sequence_row = sequence.first()
                if sequence_row is None:
                    raise WorkspaceEditConflict("workspace_not_found")
                updated = await session.execute(
                    text(
                        f"""
                        UPDATE coding_workspace_edits
                        SET status = 'committed',
                            resulting_revision = :resulting_revision,
                            committed_at = :now
                        WHERE edit_id = :edit_id
                        RETURNING {_COLUMNS}
                        """
                    ),
                    {
                        "edit_id": edit_id,
                        "resulting_revision": resulting_revision,
                        "now": now,
                    },
                )
                committed = self._require_row(updated.first(), edit_id)
                event = CodingEvent(
                    version=1,
                    task_id=committed.task_id,
                    seq=int(sequence_row[0]),
                    event_id=f"ce_{uuid4().hex}",
                    type="workspace.user_edit.applied",
                    payload={
                        "edit_id": committed.edit_id,
                        "path": committed.path,
                        "base_revision": committed.base_revision,
                        "resulting_revision": committed.resulting_revision,
                        "status": "pending_agent_sync",
                    },
                    created_at=now,
                    run_id=committed.run_id,
                )
                await self._insert_event(session, event)
        if event is not None and self._wake_outbox is not None:
            self._wake_outbox()
        return WorkspaceEditCommit(committed, event, True)

    async def mark_reconcile_required(
        self, *, edit_id: str, now: datetime
    ) -> CodingWorkspaceEdit:
        async with await self._session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    text(
                        f"""
                        UPDATE coding_workspace_edits
                        SET status = 'reconcile_required'
                        WHERE edit_id = :edit_id
                          AND status IN ('prepared', 'reconcile_required')
                        RETURNING {_COLUMNS}
                        """
                    ),
                    {"edit_id": edit_id, "now": now},
                )
        return self._require_row(result.first(), edit_id)

    async def list_reconcile_required(
        self, *, limit: int
    ) -> tuple[CodingWorkspaceEdit, ...]:
        async with await self._session_factory() as session:
            result = await session.execute(
                text(
                    f"""
                    SELECT {_COLUMNS}
                    FROM coding_workspace_edits
                    WHERE status = 'reconcile_required'
                    ORDER BY created_at, edit_id
                    LIMIT :limit
                    """
                ),
                {"limit": limit},
            )
        return tuple(self._from_row(row) for row in result.fetchall())

    @staticmethod
    async def _insert_event(session, event: CodingEvent) -> None:
        await session.execute(
            text(
                """
                INSERT INTO coding_events
                    (event_id, task_id, seq, version, event_type, payload,
                     created_at, run_id)
                VALUES
                    (:event_id, :task_id, :seq, 1, :event_type,
                     CAST(:payload AS JSONB), :created_at, :run_id)
                """
            ),
            {
                "event_id": event.event_id,
                "task_id": event.task_id,
                "seq": event.seq,
                "event_type": event.type,
                "payload": json.dumps(dict(event.payload)),
                "created_at": event.created_at,
                "run_id": event.run_id,
            },
        )
        await session.execute(
            text(
                """
                INSERT INTO coding_event_outbox
                    (outbox_id, event_id, task_id, seq,
                     next_attempt_at, created_at)
                VALUES
                    (:outbox_id, :event_id, :task_id, :seq, :now, :now)
                ON CONFLICT (event_id) DO NOTHING
                """
            ),
            {
                "outbox_id": f"co_{uuid4().hex}",
                "event_id": event.event_id,
                "task_id": event.task_id,
                "seq": event.seq,
                "now": event.created_at,
            },
        )

    @classmethod
    def _require_row(cls, row, edit_id: str) -> CodingWorkspaceEdit:
        if row is None:
            raise WorkspaceEditConflict(f"workspace_edit_not_found:{edit_id}")
        return cls._from_row(row)

    @staticmethod
    def _from_row(row) -> CodingWorkspaceEdit:
        return CodingWorkspaceEdit(
            edit_id=row[0],
            task_id=row[1],
            run_id=row[2],
            path=row[3],
            base_revision=row[4],
            resulting_revision=row[5],
            status=WorkspaceEditStatus(row[6]),
            content_digest=row[7],
            content_bytes=int(row[8]),
            created_at=row[9],
            committed_at=row[10],
            applied_checkpoint_id=row[11],
        )
