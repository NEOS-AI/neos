"""Q3: the owner's standing-question API, and what is absent when it is off."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import neos.api.handlers.standing_question_handlers as mod
from neos.api.dependencies.auth import get_current_user
from neos.standing.questions import InMemoryQuestionStore

pytestmark = pytest.mark.no_db

NOW = datetime(2026, 10, 2, 9, 0, tzinfo=UTC)


class World:
    def __init__(self, *, max_per_agent=2, min_interval=360) -> None:
        self.store = InMemoryQuestionStore({"sa_1": ("alice", True), "sa_2": ("bob", True)})
        self.user = SimpleNamespace(user_id="alice")
        app = FastAPI()
        app.include_router(mod.router)
        app.dependency_overrides.update(
            {
                get_current_user: lambda: self.user,
                mod.get_question_store: lambda: self.store,
                mod.get_question_settings: lambda: (max_per_agent, min_interval),
                mod.get_clock: lambda: (lambda: NOW),
            }
        )
        self.http = TestClient(app)

    def create(self, agent_id="sa_1", **body):
        payload = {"question": "What changed in rates?", "cron_expression": "0 9 * * *", **body}
        return self.http.post(f"/standing-agents/{agent_id}/questions", json=payload)


@pytest.fixture
def world():
    return World()


def test_create_list_disable_delete(world) -> None:
    created = world.create()
    assert created.status_code == 201
    body = created.json()
    assert body["agent_id"] == "sa_1" and body["enabled"] is True
    assert body["next_run_at"].startswith("2026-10-03T09:00:00")
    question_id = body["question_id"]

    assert [q["question_id"] for q in world.http.get("/standing-agents/sa_1/questions").json()] == [
        question_id
    ]
    patched = world.http.patch(
        f"/standing-agents/sa_1/questions/{question_id}", json={"enabled": False}
    )
    assert patched.status_code == 200 and patched.json()["enabled"] is False
    assert world.http.get(f"/standing-agents/sa_1/questions/{question_id}/runs").json() == []
    assert world.http.delete(f"/standing-agents/sa_1/questions/{question_id}").status_code == 204
    assert world.http.get("/standing-agents/sa_1/questions").json() == []


def test_bad_input_is_unprocessable(world) -> None:
    assert world.create(question="   ").json()["detail"] == "empty_question"
    assert world.create(cron_expression="nope").json()["detail"] == "invalid_cron"
    too_often = world.create(cron_expression="*/10 * * * *")
    assert (too_often.status_code, too_often.json()["detail"]) == (422, "cron_too_frequent")


def test_the_per_agent_limit_is_a_conflict(world) -> None:
    world.create()
    world.create()

    third = world.create()

    assert (third.status_code, third.json()["detail"]) == (409, "too_many_questions")


def test_someone_elses_agent_and_questions_are_not_found(world) -> None:
    assert world.create(agent_id="sa_2").status_code == 404
    question_id = world.create().json()["question_id"]
    world.user = SimpleNamespace(user_id="bob")

    assert world.http.get("/standing-agents/sa_1/questions").json() == []
    assert world.http.patch(
        f"/standing-agents/sa_1/questions/{question_id}", json={"enabled": False}
    ).status_code == 404
    assert world.http.delete(f"/standing-agents/sa_1/questions/{question_id}").status_code == 404
    assert world.http.get(
        f"/standing-agents/sa_1/questions/{question_id}/runs"
    ).status_code == 404


def test_a_question_is_addressed_through_its_own_agent(world) -> None:
    question_id = world.create().json()["question_id"]

    assert world.http.patch(
        f"/standing-agents/sa_other/questions/{question_id}", json={"enabled": False}
    ).status_code == 404


def test_the_default_app_serves_no_question_routes_and_beat_has_no_poller() -> None:
    from neos.workflow.celery_app import app, configure_standing_question_beat_schedule
    from tests.api.test_retired_routes import _routes

    served = _routes()
    assert ("POST", "/api/v1/coding/tasks") in served
    assert not [path for _method, path in served if "/questions" in path and "standing" in path]
    assert "poll-standing-questions" not in app.conf.beat_schedule

    schedule: dict = {}
    configure_standing_question_beat_schedule(schedule, enabled=True)
    assert schedule["poll-standing-questions"]["task"] == "neos.tasks.poll_standing_questions"
    configure_standing_question_beat_schedule(schedule, enabled=False)
    assert schedule == {}


def test_the_poller_task_is_registered_under_its_beat_name() -> None:
    import neos.tasks as tasks

    assert tasks.poll_standing_questions.name == "neos.tasks.poll_standing_questions"


def test_defaults_are_off() -> None:
    from neos.config.schema import AppConfig

    questions = AppConfig().standing_agents.questions
    assert questions.enabled is False
    assert questions.min_interval_minutes == 360
    assert questions.max_per_agent == 5
