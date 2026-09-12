import asyncio
import base64

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect

from neos.api.handlers.coding_ws_handlers import ticket_from_websocket

from neos.coding.application.workspace_stream_service import (
    CodingWorkspaceStreamService,
    WorkspaceStreamConflict,
)
from neos.coding.runtime import (
    coding_workspace_stream_service,
    get_workspace_ticket_store,
)
from neos.coding.sandbox.base import ReplayGap
from neos.coding.sandbox.events import PtyClosed, PtyOutput
from neos.coding.transport.workspace_tickets import (
    WorkspaceStreamKind,
    WorkspaceTicketStore,
)


router = APIRouter(prefix="/coding", tags=["Coding Workspace WebSocket"])


def get_workspace_stream_service() -> CodingWorkspaceStreamService:
    return coding_workspace_stream_service


def _has_protocol(websocket: WebSocket, expected: str) -> bool:
    offered = websocket.headers.get("sec-websocket-protocol", "")
    return expected in {value.strip() for value in offered.split(",")}


def _watcher_frame(event) -> dict:
    return {
        "v": 1,
        "type": "workspace.changed",
        "cursor": event.cursor,
        "workspace_revision": event.value.workspace_revision,
        "changes": [
            {
                "path": change.path,
                "kind": change.kind.value,
                "previous_path": change.previous_path,
            }
            for change in event.value.changes
        ],
    }


@router.websocket("/workspace/ws")
async def coding_workspace_watcher(
    websocket: WebSocket,
    task_id: str = Query(...),
    after_cursor: int = Query(0, ge=0),
    tickets: WorkspaceTicketStore = Depends(get_workspace_ticket_store),
    streams: CodingWorkspaceStreamService = Depends(get_workspace_stream_service),
) -> None:
    protocol = "neos.coding.workspace.v1"
    if not _has_protocol(websocket, protocol):
        await websocket.close(code=4406, reason="Unsupported protocol")
        return
    ticket = ticket_from_websocket(websocket)
    if not ticket:
        await websocket.close(code=4401, reason="Authentication required")
        return
    owner_id = await tickets.consume(
        ticket,
        task_id=task_id,
        kind=WorkspaceStreamKind.WATCHER,
    )
    if owner_id is None:
        await websocket.close(code=4401, reason="Authentication required")
        return
    try:
        watcher = await streams.open_watcher(
            task_id=task_id,
            owner_id=owner_id,
            after_cursor=after_cursor,
        )
    except WorkspaceStreamConflict:
        await websocket.close(code=4404, reason="Workspace not found")
        return
    try:
        await websocket.accept(subprotocol=protocol)
        async for event in watcher:
            await websocket.send_json(_watcher_frame(event))
    except ReplayGap:
        await websocket.send_json({"v": 1, "type": "workspace.resync_required"})
        await websocket.close(code=1012, reason="Workspace resync required")
    except WebSocketDisconnect:
        return
    finally:
        await watcher.aclose()


def _pty_frame(event) -> dict:
    value = event.value
    if isinstance(value, PtyOutput):
        return {
            "v": 1,
            "type": "pty.output",
            "cursor": event.cursor,
            "data": base64.b64encode(value.data).decode("ascii"),
        }
    assert isinstance(value, PtyClosed)
    return {
        "v": 1,
        "type": "pty.closed",
        "cursor": event.cursor,
        "reason": value.reason,
        "exit_code": value.exit_code,
    }


@router.websocket("/pty/ws")
async def coding_workspace_pty(
    websocket: WebSocket,
    task_id: str = Query(...),
    pty_id: str | None = Query(None),
    after_cursor: int = Query(0, ge=0),
    tickets: WorkspaceTicketStore = Depends(get_workspace_ticket_store),
    streams: CodingWorkspaceStreamService = Depends(get_workspace_stream_service),
) -> None:
    protocol = "neos.coding.pty.v1"
    if not _has_protocol(websocket, protocol):
        await websocket.close(code=4406, reason="Unsupported protocol")
        return
    ticket = ticket_from_websocket(websocket)
    if not ticket:
        await websocket.close(code=4401, reason="Authentication required")
        return
    owner_id = await tickets.consume(
        ticket,
        task_id=task_id,
        kind=WorkspaceStreamKind.PTY,
    )
    if owner_id is None:
        await websocket.close(code=4401, reason="Authentication required")
        return
    try:
        if pty_id is None:
            record = await streams.create_pty(
                task_id=task_id,
                owner_id=owner_id,
                argv=("/bin/sh",),
            )
        else:
            record = await streams.connect_pty(
                task_id=task_id,
                owner_id=owner_id,
                pty_id=pty_id,
            )
    except WorkspaceStreamConflict:
        await websocket.close(code=4404, reason="PTY not found")
        return
    try:
        await websocket.accept(subprotocol=protocol)
        await websocket.send_json(
            {"v": 1, "type": "pty.ready", "pty_id": record.pty_id}
        )
        output = record.terminal.subscribe(after_cursor=after_cursor)
        incoming = asyncio.create_task(websocket.receive_json())
        outgoing = asyncio.create_task(anext(output))
        while True:
            done, _ = await asyncio.wait(
                {incoming, outgoing},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if outgoing in done:
                await websocket.send_json(_pty_frame(outgoing.result()))
                outgoing = asyncio.create_task(anext(output))
            if incoming in done:
                message = incoming.result()
                kind = message.get("type")
                if kind == "ping":
                    await websocket.send_json({"v": 1, "type": "pong"})
                elif kind == "pty.input":
                    await streams.write_pty(
                        record,
                        base64.b64decode(message.get("data", ""), validate=True),
                    )
                elif kind == "pty.resize":
                    await streams.resize_pty(
                        record,
                        rows=int(message["rows"]),
                        cols=int(message["cols"]),
                    )
                elif kind == "pty.kill":
                    await streams.kill_pty(
                        task_id=task_id,
                        owner_id=owner_id,
                        pty_id=record.pty_id,
                    )
                    return
                incoming = asyncio.create_task(websocket.receive_json())
    except ReplayGap:
        await websocket.send_json({"v": 1, "type": "pty.resync_required"})
        await websocket.close(code=1012, reason="PTY resync required")
    except (ValueError, TypeError, KeyError):
        await websocket.close(code=4400, reason="Invalid PTY message")
    except (WebSocketDisconnect, StopAsyncIteration):
        return
    finally:
        for task_name in ("incoming", "outgoing"):
            task = locals().get(task_name)
            if isinstance(task, asyncio.Task) and not task.done():
                task.cancel()
