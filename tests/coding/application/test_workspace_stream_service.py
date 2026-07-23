from types import SimpleNamespace

import pytest

from neos.coding.application.workspace_stream_service import (
    CodingWorkspaceStreamService,
    WorkspaceStreamConflict,
)


class Tasks:
    async def get_owned(self, task_id, owner_id):
        if (task_id, owner_id) == ("ct_1", "u1"):
            return SimpleNamespace(task_id=task_id)
        return None


class Session:
    def __init__(self):
        self.terminals = {}
        self.killed = []

    async def create_pty(self, *, argv):
        terminal = SimpleNamespace(pty_id=f"pty_{len(self.terminals) + 1}")
        self.terminals[terminal.pty_id] = terminal
        return terminal

    async def kill_pty(self, pty_id):
        self.killed.append(pty_id)

    async def watch_files(self, *, after_cursor=0):
        return ("watcher", after_cursor)


class Bindings:
    def __init__(self, session):
        self.session = session
        self.opens = 0

    async def open_existing_admin(self, task_id):
        self.opens += 1
        return SimpleNamespace(session=self.session)


async def test_foreign_task_is_hidden_before_binding_access() -> None:
    bindings = Bindings(Session())
    service = CodingWorkspaceStreamService(
        tasks=Tasks(), bindings=bindings, pty_max_sessions=2
    )

    with pytest.raises(WorkspaceStreamConflict, match="workspace_not_found"):
        await service.open_watcher(
            task_id="ct_1", owner_id="foreign", after_cursor=0
        )

    assert bindings.opens == 0


async def test_pty_survives_disconnect_until_explicit_kill() -> None:
    session = Session()
    service = CodingWorkspaceStreamService(
        tasks=Tasks(), bindings=Bindings(session), pty_max_sessions=2
    )

    created = await service.create_pty(
        task_id="ct_1", owner_id="u1", argv=("/bin/sh",)
    )
    reconnected = await service.connect_pty(
        task_id="ct_1", owner_id="u1", pty_id=created.pty_id
    )
    assert reconnected.terminal is created.terminal

    await service.kill_pty(
        task_id="ct_1", owner_id="u1", pty_id=created.pty_id
    )
    assert session.killed == [created.pty_id]
    with pytest.raises(WorkspaceStreamConflict, match="pty_not_found"):
        await service.connect_pty(
            task_id="ct_1", owner_id="u1", pty_id=created.pty_id
        )


async def test_pty_session_limit_is_task_scoped() -> None:
    service = CodingWorkspaceStreamService(
        tasks=Tasks(), bindings=Bindings(Session()), pty_max_sessions=1
    )
    await service.create_pty(
        task_id="ct_1", owner_id="u1", argv=("/bin/sh",)
    )
    with pytest.raises(WorkspaceStreamConflict, match="pty_limit_reached"):
        await service.create_pty(
            task_id="ct_1", owner_id="u1", argv=("/bin/sh",)
        )
