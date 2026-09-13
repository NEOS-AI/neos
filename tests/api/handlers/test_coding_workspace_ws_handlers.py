from dataclasses import dataclass
import base64

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

pytestmark = pytest.mark.no_db

from neos.api.handlers.coding_workspace_ws_handlers import (
    get_workspace_stream_service,
    get_workspace_ticket_store,
    router,
)
from neos.coding.sandbox.base import StreamEvent
from neos.coding.sandbox.events import (
    PtyOutput,
    WorkspaceChange,
    WorkspaceChangeBatch,
    WorkspaceChangeKind,
)
from neos.coding.transport.workspace_tickets import (
    InMemoryWorkspaceTicketStore,
    WorkspaceStreamKind,
)


class Watcher:
    def __init__(self):
        self._sent = False
        self.replay_called = False

    def _event(self):
        return StreamEvent(
            cursor=1,
            value=WorkspaceChangeBatch(
                changes=(
                    WorkspaceChange(
                        path="src/app.py",
                        kind=WorkspaceChangeKind.MODIFIED,
                    ),
                ),
                workspace_revision=7,
            ),
        )

    async def replay(self, *, after_cursor):
        self.replay_called = True
        assert after_cursor == 0
        return (self._event(),)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._sent:
            self._sent = True
            return self._event()
        raise StopAsyncIteration

    async def aclose(self):
        return None


@dataclass
class Streams:
    watcher: Watcher

    async def open_watcher(self, *, task_id, owner_id, after_cursor):
        assert (task_id, owner_id, after_cursor) == ("ct_1", "u1", 0)
        return self.watcher


class Terminal:
    pty_id = "pty_1"

    async def _events(self):
        yield StreamEvent(cursor=1, value=PtyOutput(data=b"ready\n"))
        import asyncio

        await asyncio.Event().wait()

    def subscribe(self, *, after_cursor):
        assert after_cursor == 0
        return self._events()


class PtyStreams(Streams):
    def __init__(self):
        super().__init__(Watcher())
        self.record = type(
            "Record",
            (),
            {"pty_id": "pty_1", "terminal": Terminal()},
        )()
        self.inputs = []
        self.sizes = []
        self.killed = []

    async def create_pty(self, *, task_id, owner_id, argv):
        assert (task_id, owner_id, argv) == ("ct_1", "u1", ("/bin/sh",))
        return self.record

    async def write_pty(self, record, data):
        self.inputs.append(data)

    async def resize_pty(self, record, *, rows, cols):
        self.sizes.append((rows, cols))

    async def kill_pty(self, *, task_id, owner_id, pty_id):
        self.killed.append((task_id, owner_id, pty_id))


def _app(tickets, streams) -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_workspace_ticket_store] = lambda: tickets
    app.dependency_overrides[get_workspace_stream_service] = lambda: streams
    return app


def test_watcher_ticket_replays_changes_and_is_single_use() -> None:
    tickets = InMemoryWorkspaceTicketStore()
    import asyncio

    token = asyncio.run(
        tickets.issue(
            owner_id="u1",
            task_id="ct_1",
            kind=WorkspaceStreamKind.WATCHER,
        )
    )
    watcher = Watcher()
    app = _app(tickets, Streams(watcher))

    with TestClient(app).websocket_connect(
        "/api/v1/coding/workspace/ws?task_id=ct_1",
        headers={"X-Neos-Ticket": token},
        subprotocols=["neos.coding.workspace.v1"],
    ) as socket:
        assert socket.receive_json() == {
            "v": 1,
            "type": "workspace.changed",
            "cursor": 1,
            "workspace_revision": 7,
            "changes": [
                {
                    "path": "src/app.py",
                    "kind": "modified",
                    "previous_path": None,
                }
            ],
        }
    assert watcher.replay_called is False

    with pytest.raises(Exception):
        with TestClient(app).websocket_connect(
            "/api/v1/coding/workspace/ws?task_id=ct_1",
            headers={"X-Neos-Ticket": token},
            subprotocols=["neos.coding.workspace.v1"],
        ):
            pass


def test_workspace_ws_rejects_querystring_ticket() -> None:
    tickets = InMemoryWorkspaceTicketStore()
    import asyncio

    token = asyncio.run(
        tickets.issue(
            owner_id="u1",
            task_id="ct_1",
            kind=WorkspaceStreamKind.WATCHER,
        )
    )
    app = _app(tickets, Streams(Watcher()))
    with pytest.raises(Exception):
        with TestClient(app).websocket_connect(
            f"/api/v1/coding/workspace/ws?task_id=ct_1&ticket={token}",
            subprotocols=["neos.coding.workspace.v1"],
        ):
            pass


def test_watcher_rejects_wrong_subprotocol_before_accept() -> None:
    app = _app(InMemoryWorkspaceTicketStore(), Streams(Watcher()))
    with pytest.raises(Exception):
        with TestClient(app).websocket_connect(
            "/api/v1/coding/workspace/ws?task_id=ct_1&ticket=bad",
            subprotocols=["neos.coding.pty.v1"],
        ):
            pass


def test_pty_create_output_input_resize_and_explicit_kill() -> None:
    import asyncio

    tickets = InMemoryWorkspaceTicketStore()
    token = asyncio.run(
        tickets.issue(
            owner_id="u1",
            task_id="ct_1",
            kind=WorkspaceStreamKind.PTY,
        )
    )
    streams = PtyStreams()
    app = _app(tickets, streams)

    with TestClient(app).websocket_connect(
        "/api/v1/coding/pty/ws?task_id=ct_1",
        headers={"X-Neos-Ticket": token},
        subprotocols=["neos.coding.pty.v1"],
    ) as socket:
        assert socket.receive_json()["type"] == "pty.ready"
        output = socket.receive_json()
        assert base64.b64decode(output["data"]) == b"ready\n"
        socket.send_json({"type": "pty.input", "data": base64.b64encode(b"ls\n").decode()})
        socket.send_json({"type": "pty.resize", "rows": 40, "cols": 120})
        socket.send_json({"type": "pty.kill"})

    assert streams.inputs == [b"ls\n"]
    assert streams.sizes == [(40, 120)]
    assert streams.killed == [("ct_1", "u1", "pty_1")]
