import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable, Protocol

from neos.coding.sandbox.bindings import SandboxBindingService


class OwnedTaskRepository(Protocol):
    async def get_owned(self, task_id: str, owner_id: str): ...


class WorkspaceStreamConflict(RuntimeError):
    pass


@dataclass(slots=True)
class WorkspacePty:
    task_id: str
    owner_id: str
    pty_id: str
    session: Any
    terminal: Any
    last_activity_at: datetime


class CodingWorkspaceStreamService:
    def __init__(
        self,
        *,
        tasks: OwnedTaskRepository,
        bindings: SandboxBindingService,
        pty_max_sessions: int,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if pty_max_sessions < 1:
            raise ValueError("pty_max_sessions must be positive")
        self._tasks = tasks
        self._bindings = bindings
        self._pty_max_sessions = pty_max_sessions
        self._clock = clock or (lambda: datetime.now(UTC))
        self._ptys: dict[tuple[str, str], WorkspacePty] = {}
        self._lock = asyncio.Lock()

    async def open_watcher(
        self,
        *,
        task_id: str,
        owner_id: str,
        after_cursor: int,
    ):
        session = await self._owned_session(task_id, owner_id)
        return await session.watch_files(after_cursor=after_cursor)

    async def create_pty(
        self,
        *,
        task_id: str,
        owner_id: str,
        argv: tuple[str, ...],
    ) -> WorkspacePty:
        session = await self._owned_session(task_id, owner_id)
        async with self._lock:
            count = sum(key[0] == task_id for key in self._ptys)
            if count >= self._pty_max_sessions:
                raise WorkspaceStreamConflict("pty_limit_reached")
            terminal = await session.create_pty(argv=argv)
            record = WorkspacePty(
                task_id=task_id,
                owner_id=owner_id,
                pty_id=terminal.pty_id,
                session=session,
                terminal=terminal,
                last_activity_at=self._clock(),
            )
            self._ptys[(task_id, record.pty_id)] = record
            return record

    async def connect_pty(
        self,
        *,
        task_id: str,
        owner_id: str,
        pty_id: str,
    ) -> WorkspacePty:
        await self._require_owned(task_id, owner_id)
        async with self._lock:
            record = self._ptys.get((task_id, pty_id))
            if record is None or record.owner_id != owner_id:
                raise WorkspaceStreamConflict("pty_not_found")
            record.last_activity_at = self._clock()
            return record

    async def write_pty(self, record: WorkspacePty, data: bytes) -> None:
        await record.session.write_pty(record.pty_id, data)
        record.last_activity_at = self._clock()

    async def resize_pty(
        self,
        record: WorkspacePty,
        *,
        rows: int,
        cols: int,
    ) -> None:
        await record.session.resize_pty(record.pty_id, rows=rows, cols=cols)
        record.last_activity_at = self._clock()

    async def kill_pty(
        self,
        *,
        task_id: str,
        owner_id: str,
        pty_id: str,
    ) -> None:
        record = await self.connect_pty(
            task_id=task_id,
            owner_id=owner_id,
            pty_id=pty_id,
        )
        await record.session.kill_pty(pty_id)
        async with self._lock:
            self._ptys.pop((task_id, pty_id), None)

    async def _owned_session(self, task_id: str, owner_id: str):
        await self._require_owned(task_id, owner_id)
        return (await self._bindings.open_existing_admin(task_id)).session

    async def _require_owned(self, task_id: str, owner_id: str) -> None:
        if await self._tasks.get_owned(task_id, owner_id) is None:
            raise WorkspaceStreamConflict("workspace_not_found")
