from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neos.api.dependencies.auth import get_current_user
from neos.api.handlers.coding_handlers import (
    get_coding_command_service,
    router,
)
from neos.coding.commands.service import CodingCommandService
from neos.coding.commands.types import CommandStatus
from neos.coding.domain.phases import SteeringMode

pytestmark = pytest.mark.no_db


class _Runs:
    def __init__(self) -> None:
        self.steered: list[str] = []

    async def steer(self, *, task_id, owner_id, instruction, mode):
        del task_id, owner_id
        assert mode is SteeringMode.SAFE_POINT
        self.steered.append(instruction)
        return SimpleNamespace(steering_id="cs_1")


class _Snapshots:
    def __init__(self, *, missing: bool = False) -> None:
        self.missing = missing

    async def get_owned(self, task_id, owner_id):
        del owner_id
        if self.missing:
            return None
        return SimpleNamespace(
            task=SimpleNamespace(status=SimpleNamespace(value="running")),
            latest_checkpoint=SimpleNamespace(
                loop_state={
                    "cost_micros": 12,
                    "input_tokens": 8,
                    "output_tokens": 2,
                    "transcript": [
                        {
                            "role": "user",
                            "content": [{"type": "text", "text": "secret sk-" + ("b" * 20)}],
                        }
                    ],
                }
            ),
        )


def _client(service: CodingCommandService, user_id: str = "u1") -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        user_id=user_id
    )
    app.dependency_overrides[get_coding_command_service] = lambda: service
    return TestClient(app)


def test_list_commands_includes_loop_disabled() -> None:
    client = _client(CodingCommandService(runs=_Runs(), snapshots=_Snapshots()))
    response = client.get("/api/v1/coding/commands")
    assert response.status_code == 200
    names = {item["name"]: item for item in response.json()["commands"]}
    assert names["compact"]["enabled"] is True
    assert names["loop"]["enabled"] is False
    assert names["clear"]["family"] == "control"


def test_post_compact_queues() -> None:
    runs = _Runs()
    client = _client(CodingCommandService(runs=runs, snapshots=_Snapshots()))
    response = client.post(
        "/api/v1/coding/tasks/ct_1/commands",
        json={"text": "/compact keep the plan"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == CommandStatus.QUEUED.value
    assert body["name"] == "compact"
    assert runs.steered == ["/compact keep the plan"]


def test_post_loop_is_denied() -> None:
    runs = _Runs()
    client = _client(CodingCommandService(runs=runs, snapshots=_Snapshots()))
    response = client.post(
        "/api/v1/coding/tasks/ct_1/commands",
        json={"text": "/loop 5m check deploy"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == CommandStatus.DENIED.value
    assert runs.steered == []


def test_post_unknown_is_400() -> None:
    client = _client(CodingCommandService(runs=_Runs(), snapshots=_Snapshots()))
    response = client.post(
        "/api/v1/coding/tasks/ct_1/commands",
        json={"text": "/not-real"},
    )
    assert response.status_code == 400


def test_post_plain_text_is_400() -> None:
    client = _client(CodingCommandService(runs=_Runs(), snapshots=_Snapshots()))
    response = client.post(
        "/api/v1/coding/tasks/ct_1/commands",
        json={"text": "please compact"},
    )
    assert response.status_code == 400


def test_post_cost_and_export() -> None:
    client = _client(CodingCommandService(runs=_Runs(), snapshots=_Snapshots()))
    cost = client.post(
        "/api/v1/coding/tasks/ct_1/commands", json={"text": "/cost"}
    )
    export = client.post(
        "/api/v1/coding/tasks/ct_1/commands", json={"text": "/export"}
    )
    assert cost.status_code == 200
    assert cost.json()["payload"]["cost_micros"] == 12
    assert export.status_code == 200
    assert "sk-" not in str(export.json())
    assert "loop_state" not in export.json()["payload"]


def test_post_cost_missing_task_is_404() -> None:
    client = _client(
        CodingCommandService(runs=_Runs(), snapshots=_Snapshots(missing=True))
    )
    response = client.post(
        "/api/v1/coding/tasks/ct_missing/commands", json={"text": "/cost"}
    )
    assert response.status_code == 404
    assert response.json()["detail"] == {
        "code": "coding_task_not_found",
        "message": "Coding task not found",
    }
