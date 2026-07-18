from fastapi import FastAPI
from fastapi.testclient import TestClient

from neos.api.handlers.coding_handlers import get_coding_service
from neos.api.handlers.coding_handlers import get_ws_ticket_store
from neos.api.handlers.coding_ws_handlers import router
from neos.api.handlers.coding_ws_handlers import replay_protocol_messages
from neos.api.handlers.coding_ws_handlers import get_coding_event_broker
from neos.coding.application.task_service import (
    CodingTaskService,
    InMemoryCodingTaskRepository,
)
from neos.coding.events.store import InMemoryCodingEventStore
from neos.coding.events.broker import InProcessCodingEventBroker
from neos.coding.auth.ws_tickets import InMemoryWsTicketStore
from neos.utils.jwt import create_access_token


async def test_protocol_sends_hello_replay_and_caught_up() -> None:
    service = CodingTaskService(
        InMemoryCodingTaskRepository(), InMemoryCodingEventStore()
    )
    task = await service.create_task(owner_id="u1", prompt="Fix it")

    messages = await replay_protocol_messages(service, task.task_id, "u1", 0)

    assert [message["type"] for message in messages] == [
        "hello",
        "task.created",
        "caught_up",
    ]
    assert messages[0]["head_seq"] == 1
    assert messages[1]["seq"] == 1


async def test_protocol_hides_foreign_task() -> None:
    service = CodingTaskService(
        InMemoryCodingTaskRepository(), InMemoryCodingEventStore()
    )
    task = await service.create_task(owner_id="u1", prompt="Fix it")

    assert await replay_protocol_messages(service, task.task_id, "u2", 0) is None


def test_authenticated_websocket_replays_owned_task() -> None:
    service = CodingTaskService(
        InMemoryCodingTaskRepository(), InMemoryCodingEventStore()
    )
    import asyncio

    task = asyncio.run(service.create_task(owner_id="u1", prompt="Fix it"))
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_coding_service] = lambda: service
    token = create_access_token({"user_id": "u1"})

    with TestClient(app).websocket_connect(
        f"/api/v1/coding/ws?task_id={task.task_id}&after_seq=0&access_token={token}",
        subprotocols=["neos.coding.v1"],
    ) as socket:
        assert socket.receive_json()["type"] == "hello"
        assert socket.receive_json()["type"] == "task.created"
        assert socket.receive_json()["type"] == "caught_up"


def test_websocket_rejects_invalid_token_before_accept() -> None:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    import pytest

    with pytest.raises(Exception):
        with TestClient(app).websocket_connect(
            "/api/v1/coding/ws?task_id=ct_missing&access_token=invalid",
            subprotocols=["neos.coding.v1"],
        ):
            pass


def test_websocket_pushes_live_events_after_caught_up() -> None:
    import asyncio
    from datetime import UTC, datetime

    from neos.coding.domain.events import make_event

    service = CodingTaskService(
        InMemoryCodingTaskRepository(), InMemoryCodingEventStore()
    )
    task = asyncio.run(service.create_task(owner_id="u1", prompt="Fix it"))
    broker = InProcessCodingEventBroker()
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_coding_service] = lambda: service
    app.dependency_overrides[get_coding_event_broker] = lambda: broker
    token = create_access_token({"user_id": "u1"})

    with TestClient(app) as client:
        with client.websocket_connect(
            f"/api/v1/coding/ws?task_id={task.task_id}&after_seq=0&access_token={token}",
            subprotocols=["neos.coding.v1"],
        ) as socket:
            assert socket.receive_json()["type"] == "hello"
            assert socket.receive_json()["type"] == "task.created"
            assert socket.receive_json()["type"] == "caught_up"
            event = make_event(
                task_id=task.task_id,
                seq=2,
                event_type="text.delta",
                payload={"part_id": "answer", "delta": "done"},
                now=datetime(2026, 7, 18, tzinfo=UTC),
            )
            assert client.portal is not None
            client.portal.call(broker.publish, event)

            live = socket.receive_json()
            assert live["type"] == "text.delta"
            assert live["seq"] == 2


def test_websocket_accepts_single_use_task_ticket() -> None:
    import asyncio

    service = CodingTaskService(
        InMemoryCodingTaskRepository(), InMemoryCodingEventStore()
    )
    task = asyncio.run(service.create_task(owner_id="u1", prompt="Fix it"))
    tickets = InMemoryWsTicketStore()
    ticket = asyncio.run(tickets.issue(owner_id="u1", task_id=task.task_id))
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_coding_service] = lambda: service
    app.dependency_overrides[get_ws_ticket_store] = lambda: tickets

    with TestClient(app).websocket_connect(
        f"/api/v1/coding/ws?task_id={task.task_id}&after_seq=0&ticket={ticket}",
        subprotocols=["neos.coding.v1"],
    ) as socket:
        assert socket.receive_json()["type"] == "hello"

    import pytest

    with pytest.raises(Exception):
        with TestClient(app).websocket_connect(
            f"/api/v1/coding/ws?task_id={task.task_id}&ticket={ticket}",
            subprotocols=["neos.coding.v1"],
        ):
            pass
