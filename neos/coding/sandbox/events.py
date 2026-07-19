from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import StrEnum
from typing import TypeAlias

from neos.coding.sandbox.base import StreamEvent
from neos.coding.sandbox.streams import BoundedReplayStream


@dataclass(frozen=True, slots=True)
class PtyOutput:
    data: bytes


@dataclass(frozen=True, slots=True)
class PtyClosed:
    reason: str
    exit_code: int | None


PtyEvent: TypeAlias = PtyOutput | PtyClosed


class WorkspaceChangeKind(StrEnum):
    CREATED = "created"
    MODIFIED = "modified"
    DELETED = "deleted"
    RENAMED = "renamed"
    WATCH_OVERFLOW = "watch_overflow"
    WORKSPACE_INVALIDATED = "workspace_invalidated"


@dataclass(frozen=True, slots=True)
class WorkspaceChange:
    path: str
    kind: WorkspaceChangeKind
    previous_path: str | None = None


@dataclass(frozen=True, slots=True)
class WorkspaceChangeBatch:
    changes: tuple[WorkspaceChange, ...]
    workspace_revision: int


class SandboxWatcher:
    def __init__(
        self,
        stream: BoundedReplayStream[WorkspaceChangeBatch],
        *,
        after_cursor: int,
    ) -> None:
        self._stream = stream
        self._subscription = stream.subscribe(after_cursor=after_cursor)

    def __aiter__(self) -> SandboxWatcher:
        return self

    async def __anext__(self) -> StreamEvent[WorkspaceChangeBatch]:
        return await anext(self._subscription)

    async def replay(
        self,
        *,
        after_cursor: int,
    ) -> tuple[StreamEvent[WorkspaceChangeBatch], ...]:
        return await self._stream.replay(after_cursor=after_cursor)

    async def aclose(self) -> None:
        await self._subscription.aclose()


class SandboxWatcherHub:
    def __init__(self, *, debounce_sec: float, replay_events: int) -> None:
        self._debounce_sec = debounce_sec
        self._stream = BoundedReplayStream[WorkspaceChangeBatch](
            max_events=replay_events,
            max_bytes=1024 * 1024,
            size_of=lambda batch: sum(
                len(change.path.encode()) + 32 for change in batch.changes
            ),
        )
        self._pending: dict[str, WorkspaceChange] = {}
        self._revision = 0
        self._flush_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    async def record(self, change: WorkspaceChange, *, revision: int) -> None:
        async with self._lock:
            previous = self._pending.get(change.path)
            if previous is not None and previous.kind is WorkspaceChangeKind.CREATED:
                change = previous
            self._pending[change.path] = change
            self._revision = revision
            if self._flush_task is None or self._flush_task.done():
                self._flush_task = asyncio.create_task(self._flush_after_delay())

    def open(self, *, after_cursor: int) -> SandboxWatcher:
        return SandboxWatcher(self._stream, after_cursor=after_cursor)

    async def close(self) -> None:
        task = self._flush_task
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        await self._flush()
        await self._stream.close()

    async def _flush_after_delay(self) -> None:
        await asyncio.sleep(self._debounce_sec)
        await self._flush()

    async def _flush(self) -> None:
        async with self._lock:
            if not self._pending:
                return
            batch = WorkspaceChangeBatch(
                changes=tuple(
                    self._pending[path] for path in sorted(self._pending)
                ),
                workspace_revision=self._revision,
            )
            self._pending.clear()
        await self._stream.publish(batch)
