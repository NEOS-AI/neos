from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from neos.api.dependencies.auth import get_current_user
from neos.api.handlers.coding_handlers import (
    get_coding_service,
    get_ws_ticket_store,
    router,
)
from neos.coding.auth.ws_tickets import InMemoryWsTicketStore
from neos.coding.application.task_service import (
    CodingTaskService,
    InMemoryCodingTaskRepository,
)
from neos.coding.events.store import InMemoryCodingEventStore


def make_client(user_id="u1"):
    app = FastAPI()
    service = CodingTaskService(
        InMemoryCodingTaskRepository(), InMemoryCodingEventStore()
    )
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        user_id=user_id
    )
    app.dependency_overrides[get_coding_service] = lambda: service
    return TestClient(app), service


def test_create_task_returns_202_and_replayable_created_event() -> None:
    client, _ = make_client()

    created = client.post("/api/v1/coding/tasks", json={"prompt": "Fix it"})

    assert created.status_code == 202
    task_id = created.json()["task_id"]
    replay = client.get(f"/api/v1/coding/tasks/{task_id}/events?after_seq=0")
    assert replay.status_code == 200
    assert replay.json()["events"][0]["type"] == "task.created"


def test_foreign_task_is_hidden_as_404() -> None:
    owner, service = make_client("owner")
    task_id = owner.post(
        "/api/v1/coding/tasks", json={"prompt": "Fix it"}
    ).json()["task_id"]
    foreign, _ = make_client("foreign")
    foreign.app.dependency_overrides[get_coding_service] = lambda: service

    response = foreign.get(f"/api/v1/coding/tasks/{task_id}/snapshot")

    assert response.status_code == 404


def test_owner_can_issue_task_bound_websocket_ticket() -> None:
    client, _ = make_client("u1")
    client.app.dependency_overrides[get_ws_ticket_store] = (
        lambda: InMemoryWsTicketStore()
    )
    task_id = client.post(
        "/api/v1/coding/tasks", json={"prompt": "Fix it"}
    ).json()["task_id"]

    response = client.post(f"/api/v1/coding/tasks/{task_id}/ws-ticket")

    assert response.status_code == 201
    assert response.json()["ticket"].startswith("cwt_")
    assert response.json()["expires_in"] == 30


def test_foreign_user_cannot_issue_websocket_ticket() -> None:
    owner, service = make_client("owner")
    task_id = owner.post(
        "/api/v1/coding/tasks", json={"prompt": "Fix it"}
    ).json()["task_id"]
    foreign, _ = make_client("foreign")
    foreign.app.dependency_overrides[get_coding_service] = lambda: service

    response = foreign.post(f"/api/v1/coding/tasks/{task_id}/ws-ticket")

    assert response.status_code == 404
