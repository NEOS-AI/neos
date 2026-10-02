"""Q10b: the resume route (only a person) and the agent's notice target.

Off is absence: the default app serves neither, and turning standing agents on
mounts the resume route but not the notice target until notices are on.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import neos.api.handlers.standing_pause_handlers as mod
from neos.api.dependencies.auth import get_current_user
from neos.coding.domain.errors import CodingTaskNotFound
from neos.standing.notifications import InMemoryNotificationStore, NotifyTarget

pytestmark = pytest.mark.no_db


class Runs:
    def __init__(self) -> None:
        self.paused = {"ct_1": "alice"}
        self.calls = []

    async def resume(self, *, task_id, owner_id):
        self.calls.append((task_id, owner_id))
        owner = self.paused.get(task_id)
        if task_id == "ct_running":
            return None
        if owner is None or owner != owner_id:
            raise CodingTaskNotFound(task_id)
        del self.paused[task_id]
        return SimpleNamespace(checkpoint_id="cc_1")


class World:
    def __init__(self) -> None:
        self.runs = Runs()
        self.notices = InMemoryNotificationStore({"sa_1": "alice"})
        self.user = SimpleNamespace(user_id="alice")
        app = FastAPI()
        app.include_router(mod.resume_router)
        app.include_router(mod.notify_router)
        app.dependency_overrides.update(
            {
                get_current_user: lambda: self.user,
                mod.get_coding_run_service: lambda: self.runs,
                mod.get_notification_store: lambda: self.notices,
            }
        )
        self.http = TestClient(app)


@pytest.fixture
def world():
    return World()


def test_the_owner_resumes_a_paused_task(world) -> None:
    response = world.http.post("/coding/tasks/ct_1/resume")

    assert response.status_code == 202
    assert response.json() == {"task_id": "ct_1", "status": "running"}
    assert world.runs.calls == [("ct_1", "alice")]


def test_a_task_that_is_not_paused_is_a_conflict(world) -> None:
    response = world.http.post("/coding/tasks/ct_running/resume")

    assert response.status_code == 409
    assert response.json()["detail"] == "task_not_paused"


def test_someone_elses_task_is_not_found(world) -> None:
    world.user = SimpleNamespace(user_id="mallory")

    response = world.http.post("/coding/tasks/ct_1/resume")

    assert response.status_code == 404
    assert world.runs.paused == {"ct_1": "alice"}


def test_the_notice_target_round_trip(world) -> None:
    assert world.http.get("/standing-agents/sa_1/notify-target").status_code == 404

    put = world.http.put(
        "/standing-agents/sa_1/notify-target",
        json={"channel_type": "telegram", "channel_id": " 4242 "},
    )
    assert put.status_code == 200
    assert put.json() == {"channel_type": "telegram", "channel_id": "4242"}
    assert world.notices.targets["sa_1"] == NotifyTarget("telegram", "4242")
    assert world.http.get("/standing-agents/sa_1/notify-target").json()["channel_id"] == "4242"

    assert world.http.delete("/standing-agents/sa_1/notify-target").status_code == 204
    assert world.http.delete("/standing-agents/sa_1/notify-target").status_code == 404


def test_a_target_is_a_known_channel_on_ones_own_agent(world) -> None:
    bad_type = world.http.put(
        "/standing-agents/sa_1/notify-target", json={"channel_type": "email", "channel_id": "x"}
    )
    blank = world.http.put(
        "/standing-agents/sa_1/notify-target", json={"channel_type": "slack", "channel_id": "  "}
    )
    world.user = SimpleNamespace(user_id="mallory")
    foreign = world.http.put(
        "/standing-agents/sa_1/notify-target", json={"channel_type": "slack", "channel_id": "C1"}
    )

    assert (bad_type.status_code, blank.status_code, foreign.status_code) == (422, 422, 404)
    assert world.notices.targets == {}


def test_the_default_app_serves_neither() -> None:
    from tests.api.test_retired_routes import _routes

    served = _routes()
    assert ("POST", "/api/v1/coding/tasks") in served
    assert ("POST", "/api/v1/coding/tasks/{task_id}/resume") not in served
    assert not [path for _method, path in served if path.endswith("/notify-target")]


def test_defaults_are_off() -> None:
    from neos.config.schema import AppConfig

    standing = AppConfig().standing_agents
    assert standing.budget.enforce is False
    assert standing.budget.warn_ratio == 0.8
    assert standing.notifications.enabled is False
