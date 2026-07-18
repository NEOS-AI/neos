from fastapi import FastAPI
from fastapi.testclient import TestClient

from neos.api.handlers.coding_handlers import get_coding_service
from neos.api.handlers.coding_handlers import get_ws_ticket_store
from neos.api.handlers.coding_ws_handlers import router
from neos.api.handlers.coding_ws_handlers import build_replay_messages
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


class FakePagedEvents:
    def __init__(self, events):
        self._events = events
        self.after_seq_calls = []

    async def list_after(self, task_id, *, after_seq, limit):
        self.after_seq_calls.append(after_seq)
        return [event for event in self._events if event.seq > after_seq][:limit]


class FakePagedService:
    def __init__(self, events, head_seq):
        from types import SimpleNamespace

        self.events = FakePagedEvents(events)
        self._snapshot = SimpleNamespace(head_seq=head_seq)

    async def snapshot(self, task_id, owner_id):
        return self._snapshot


def make_events(count, *, skip_seq=None):
    from datetime import UTC, datetime

    from neos.coding.domain.events import make_event

    return [
        make_event(
            task_id="ct_1",
            seq=seq,
            event_type="text.delta",
            payload={"delta": str(seq)},
            now=datetime(2026, 7, 18, tzinfo=UTC),
        )
        for seq in range(1, count + 1)
        if seq != skip_seq
    ]


async def test_replay_pages_5001_events_before_caught_up() -> None:
    service = FakePagedService(make_events(5001), head_seq=5001)

    result = await build_replay_messages(service, "ct_1", "u1", 0)

    assert result is not None
    assert len([message for message in result.messages if "seq" in message]) == 5001
    assert result.messages[-1] == {
        "v": 1,
        "type": "caught_up",
        "task_id": "ct_1",
        "head_seq": 5001,
    }
    assert service.events.after_seq_calls == list(range(0, 5001, 500))


async def test_replay_requires_resync_above_limit_without_partial_caught_up() -> None:
    service = FakePagedService([], head_seq=20_001)

    result = await build_replay_messages(service, "ct_1", "u1", 0)

    assert result is not None
    assert result.requires_resync is True
    assert result.messages[-1]["type"] == "resync_required"
    assert all(message["type"] != "caught_up" for message in result.messages)
    assert service.events.after_seq_calls == []


async def test_replay_requires_resync_on_missing_expected_sequence() -> None:
    service = FakePagedService(make_events(4, skip_seq=3), head_seq=4)

    result = await build_replay_messages(service, "ct_1", "u1", 0)

    assert result is not None
    assert result.last_contiguous_seq == 2
    assert result.requires_resync is True
    assert result.messages[-1]["type"] == "resync_required"


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


def test_websocket_ignores_live_duplicate_then_sends_next_sequence() -> None:
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
            f"/api/v1/coding/ws?task_id={task.task_id}&access_token={token}",
            subprotocols=["neos.coding.v1"],
        ) as socket:
            for _ in range(3):
                socket.receive_json()
            assert client.portal is not None
            for seq in (1, 2):
                client.portal.call(
                    broker.publish,
                    make_event(
                        task_id=task.task_id,
                        seq=seq,
                        event_type="text.delta",
                        payload={"delta": str(seq)},
                        now=datetime(2026, 7, 18, tzinfo=UTC),
                    ),
                )

            assert socket.receive_json()["seq"] == 2


def test_websocket_live_gap_forces_resync() -> None:
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
            f"/api/v1/coding/ws?task_id={task.task_id}&access_token={token}",
            subprotocols=["neos.coding.v1"],
        ) as socket:
            for _ in range(3):
                socket.receive_json()
            assert client.portal is not None
            client.portal.call(
                broker.publish,
                make_event(
                    task_id=task.task_id,
                    seq=3,
                    event_type="text.delta",
                    payload={"delta": "gap"},
                    now=datetime(2026, 7, 18, tzinfo=UTC),
                ),
            )

            message = socket.receive_json()
            assert message["type"] == "resync_required"
            assert message["after_seq"] == 1


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
