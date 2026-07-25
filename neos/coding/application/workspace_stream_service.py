import asyncio
import logging
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Callable, Protocol

from neos.coding.domain.models import CodingTaskStatus
from neos.coding.sandbox.bindings import SandboxBindingService

logger = logging.getLogger(__name__)

_TERMINAL_TASK_STATUSES = frozenset(
    {
        CodingTaskStatus.COMPLETED,
        CodingTaskStatus.FAILED,
        CodingTaskStatus.CANCELLED,
        CodingTaskStatus.EXPIRED,
        CodingTaskStatus.ARCHIVED,
    }
)


class OwnedTaskRepository(Protocol):
    async def get(self, task_id: str): ...

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
        pty_idle_ttl_seconds: int = 1_800,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if pty_max_sessions < 1:
            raise ValueError("pty_max_sessions must be positive")
        if pty_idle_ttl_seconds < 1:
            raise ValueError("pty_idle_ttl_seconds must be positive")
        self._tasks = tasks
        self._bindings = bindings
        self._pty_max_sessions = pty_max_sessions
        self._pty_idle_ttl = timedelta(seconds=pty_idle_ttl_seconds)
        self._reap_interval = min(30.0, max(1.0, pty_idle_ttl_seconds / 2))
        self._clock = clock or (lambda: datetime.now(UTC))
        self._ptys: dict[tuple[str, str], WorkspacePty] = {}
        self._lock = asyncio.Lock()
        self._reaper_task: asyncio.Task[None] | None = None
        self._closed = False

    def start(self) -> None:
        if self._closed:
            raise RuntimeError("workspace stream service is closed")
        if self._reaper_task is None:
            self._reaper_task = asyncio.create_task(
                self._run_reaper(),
                name="coding-workspace-pty-reaper",
            )

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        reaper = self._reaper_task
        self._reaper_task = None
        if reaper is not None:
            reaper.cancel()
            with suppress(asyncio.CancelledError):
                await reaper
        await self._kill_records(await self._take_all())

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

    async def reap(self, *, now: datetime | None = None) -> int:
        now = now or self._clock()
        async with self._lock:
            task_ids = {record.task_id for record in self._ptys.values()}

        terminal_task_ids: set[str] = set()
        for task_id in task_ids:
            try:
                task = await self._tasks.get(task_id)
            except Exception:
                logger.exception("Failed to inspect coding task %s for PTY reap", task_id)
                continue
            if task is None or task.status in _TERMINAL_TASK_STATUSES:
                terminal_task_ids.add(task_id)

        async with self._lock:
            records = [
                record
                for record in self._ptys.values()
                if record.task_id in terminal_task_ids
                or now - record.last_activity_at > self._pty_idle_ttl
            ]
            for record in records:
                self._ptys.pop((record.task_id, record.pty_id), None)

        await self._kill_records(records)
        return len(records)

    async def _run_reaper(self) -> None:
        while True:
            await asyncio.sleep(self._reap_interval)
            try:
                await self.reap()
            except Exception:
                logger.exception("Unexpected coding workspace PTY reaper failure")

    async def _take_all(self) -> list[WorkspacePty]:
        async with self._lock:
            records = list(self._ptys.values())
            self._ptys.clear()
            return records

    @staticmethod
    async def _kill_records(records: list[WorkspacePty]) -> None:
        results = await asyncio.gather(
            *(record.session.kill_pty(record.pty_id) for record in records),
            return_exceptions=True,
        )
        for record, result in zip(records, results, strict=True):
            if isinstance(result, BaseException):
                logger.warning(
                    "Failed to kill coding workspace PTY %s: %r",
                    record.pty_id,
                    result,
                )

    async def _owned_session(self, task_id: str, owner_id: str):
        await self._require_owned(task_id, owner_id)
        return (await self._bindings.open_existing_admin(task_id)).session

    async def _require_owned(self, task_id: str, owner_id: str) -> None:
        if await self._tasks.get_owned(task_id, owner_id) is None:
            raise WorkspaceStreamConflict("workspace_not_found")
