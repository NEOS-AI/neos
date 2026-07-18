import asyncio

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect

from neos.api.handlers.coding_handlers import event_response
from neos.api.handlers.coding_handlers import get_coding_service
from neos.api.handlers.coding_handlers import get_ws_ticket_store
from neos.coding.application.task_service import CodingTaskService
from neos.coding.runtime import get_coding_event_transport
from neos.coding.transport.base import CodingEventTransport, CodingTicketStore
from neos.utils.jwt import verify_token


router = APIRouter(prefix="/coding", tags=["Coding Agent WebSocket"])


def get_coding_event_broker() -> CodingEventTransport:
    return get_coding_event_transport()


async def replay_protocol_messages(
    service: CodingTaskService,
    task_id: str,
    owner_id: str,
    after_seq: int,
) -> list[dict] | None:
    snapshot = await service.snapshot(task_id, owner_id)
    if snapshot is None:
        return None
    replay = await service.events.list_after(task_id, after_seq=after_seq, limit=5000)
    return [
        {
            "v": 1,
            "type": "hello",
            "task_id": task_id,
            "head_seq": snapshot.head_seq,
            "heartbeat_ms": 30_000,
        },
        *[event_response(event) for event in replay],
        {
            "v": 1,
            "type": "caught_up",
            "task_id": task_id,
            "head_seq": snapshot.head_seq,
        },
    ]


@router.websocket("/ws")
async def coding_task_websocket(
    websocket: WebSocket,
    task_id: str = Query(...),
    after_seq: int = Query(0, ge=0),
    access_token: str | None = Query(None),
    ticket: str | None = Query(None),
    service: CodingTaskService = Depends(get_coding_service),
    broker: CodingEventTransport = Depends(get_coding_event_broker),
    tickets: CodingTicketStore = Depends(get_ws_ticket_store),
) -> None:
    requested_protocols = websocket.headers.get("sec-websocket-protocol", "")
    if "neos.coding.v1" not in {
        protocol.strip() for protocol in requested_protocols.split(",")
    }:
        await websocket.close(code=4406, reason="Unsupported protocol")
        return

    owner_id = None
    if ticket:
        owner_id = await tickets.consume(ticket, task_id=task_id)
    elif access_token:
        payload = verify_token(access_token, token_type="access")
        owner_id = payload.get("user_id") if payload else None
    if not isinstance(owner_id, str) or not owner_id:
        await websocket.close(code=4401, reason="Authentication required")
        return

    subscription = await broker.subscribe(task_id)
    try:
        messages = await replay_protocol_messages(
            service, task_id, owner_id, after_seq
        )
        if messages is None:
            await websocket.close(code=4404, reason="Coding task not found")
            return

        caught_up_seq = messages[-1]["head_seq"]
        await websocket.accept(subprotocol="neos.coding.v1")
        for message in messages:
            await websocket.send_json(message)

        while True:
            client_message = asyncio.create_task(websocket.receive_json())
            live_event = asyncio.create_task(subscription.get())
            done, pending = await asyncio.wait(
                {client_message, live_event},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            if client_message in done:
                message = client_message.result()
                if message.get("type") == "ping":
                    await websocket.send_json({"v": 1, "type": "pong"})
            if live_event in done:
                event = live_event.result()
                if event.seq > caught_up_seq:
                    await websocket.send_json(event_response(event))
                    caught_up_seq = event.seq
    except WebSocketDisconnect:
        return
    finally:
        await subscription.close()
