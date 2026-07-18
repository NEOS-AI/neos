import asyncio
from dataclasses import dataclass

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect

from neos.api.handlers.coding_handlers import event_response
from neos.api.handlers.coding_handlers import get_coding_service
from neos.api.handlers.coding_handlers import get_ws_ticket_store
from neos.coding.application.task_service import CodingTaskService
from neos.coding.runtime import get_coding_event_transport
from neos.coding.transport.base import CodingEventTransport, CodingTicketStore
from neos.coding.transport.redis_events import CodingEventSubscriptionClosed
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
    result = await build_replay_messages(
        service, task_id, owner_id, after_seq
    )
    return result.messages if result is not None else None


@dataclass(frozen=True, slots=True)
class ReplayResult:
    messages: list[dict]
    last_contiguous_seq: int
    requires_resync: bool


def _resync_message(task_id: str, *, head_seq: int, after_seq: int) -> dict:
    return {
        "v": 1,
        "type": "resync_required",
        "task_id": task_id,
        "head_seq": head_seq,
        "after_seq": after_seq,
    }


async def build_replay_messages(
    service: CodingTaskService,
    task_id: str,
    owner_id: str,
    after_seq: int,
    *,
    page_size: int = 500,
    max_events: int = 20_000,
) -> ReplayResult | None:
    snapshot = await service.snapshot(task_id, owner_id)
    if snapshot is None:
        return None
    head_seq = snapshot.head_seq
    messages = [
        {
            "v": 1,
            "type": "hello",
            "task_id": task_id,
            "head_seq": head_seq,
            "heartbeat_ms": 30_000,
        }
    ]
    cursor = after_seq
    if cursor > head_seq or head_seq - cursor > max_events:
        messages.append(
            _resync_message(task_id, head_seq=head_seq, after_seq=cursor)
        )
        return ReplayResult(messages, cursor, True)

    while cursor < head_seq:
        page = await service.events.list_after(
            task_id,
            after_seq=cursor,
            limit=min(page_size, head_seq - cursor),
        )
        if not page:
            messages.append(
                _resync_message(task_id, head_seq=head_seq, after_seq=cursor)
            )
            return ReplayResult(messages, cursor, True)
        advanced = False
        for event in page:
            if event.seq > head_seq:
                break
            if event.seq != cursor + 1:
                messages.append(
                    _resync_message(task_id, head_seq=head_seq, after_seq=cursor)
                )
                return ReplayResult(messages, cursor, True)
            messages.append(event_response(event))
            cursor = event.seq
            advanced = True
        if not advanced:
            messages.append(
                _resync_message(task_id, head_seq=head_seq, after_seq=cursor)
            )
            return ReplayResult(messages, cursor, True)

    messages.append(
        {
            "v": 1,
            "type": "caught_up",
            "task_id": task_id,
            "head_seq": head_seq,
        }
    )
    return ReplayResult(messages, cursor, False)


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
        replay = await build_replay_messages(
            service, task_id, owner_id, after_seq
        )
        if replay is None:
            await websocket.close(code=4404, reason="Coding task not found")
            return

        await websocket.accept(subprotocol="neos.coding.v1")
        for message in replay.messages:
            await websocket.send_json(message)
        if replay.requires_resync:
            await websocket.close(code=1012, reason="Replay resync required")
            return
        caught_up_seq = replay.last_contiguous_seq

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
                if event.seq <= caught_up_seq:
                    continue
                if event.seq == caught_up_seq + 1:
                    await websocket.send_json(event_response(event))
                    caught_up_seq = event.seq
                    continue
                await websocket.send_json(
                    _resync_message(
                        task_id,
                        head_seq=event.seq,
                        after_seq=caught_up_seq,
                    )
                )
                await websocket.close(code=1012, reason="Live event gap")
                return
    except WebSocketDisconnect:
        return
    except CodingEventSubscriptionClosed:
        await websocket.close(code=1012, reason="Event subscription closed")
        return
    finally:
        await subscription.close()
