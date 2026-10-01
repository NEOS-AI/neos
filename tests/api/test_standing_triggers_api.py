"""Q4a: the trigger API (design §2.3).

Two routers. The owner's routes sit behind the usual auth dependency; the
delivery route has none -- the signature is the authentication. Every way a
delivery can fail to authenticate (unknown trigger, wrong signature, stale
clock, malformed header) answers with the same 401, so a stranger cannot learn
which trigger ids exist.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import neos.api.handlers.standing_trigger_handlers as mod
from neos.api.channels.inbound_idempotency import InMemoryChannelInboundIdempotencyStore
from neos.api.dependencies.auth import get_current_user
from neos.coding.application.task_service import (
    CodingTaskService,
    InMemoryCodingTaskRepository,
)
from neos.coding.events.store import InMemoryCodingEventStore
from neos.standing.store import InMemoryStandingAgentStore
from neos.standing.triggers import InMemoryTriggerStore, sign_delivery

pytestmark = pytest.mark.no_db

KEY = "k" * 32
NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)
TS = str(int(NOW.timestamp()))


class World:
    def __init__(self, *, max_body=1024) -> None:
        self.agents = InMemoryStandingAgentStore()
        self.triggers = InMemoryTriggerStore(self.agents)
        self.coding = CodingTaskService(InMemoryCodingTaskRepository(), InMemoryCodingEventStore())
        self.user = SimpleNamespace(user_id="alice")
        app = FastAPI()
        app.include_router(mod.router)
        app.include_router(mod.delivery_router)
        overrides = {
            get_current_user: lambda: self.user,
            mod.get_standing_agent_store: lambda: self.agents,
            mod.get_trigger_store: lambda: self.triggers,
            mod.get_task_opener: lambda: self.coding,
            mod.get_idempotency_store: lambda: self.idempotency,
            mod.get_envelope: lambda: None,
            mod.get_trigger_settings: lambda: (KEY, max_body, 300),
            mod.get_clock: lambda: (lambda: NOW),
        }
        app.dependency_overrides.update(overrides)
        self.idempotency = InMemoryChannelInboundIdempotencyStore()
        self.http = TestClient(app)


@pytest.fixture
def world():
    return World()


async def _agent(world, owner="alice"):
    return await world.agents.create(owner, "Dot")


def _create(world, agent_id, **body):
    return world.http.post(
        f"/standing-agents/{agent_id}/triggers",
        json={"prompt_template": "Summarise it.", **body},
    )


def _deliver(world, trigger_id, secret, *, body=b'{"a": 1}', delivery="d1", ts=TS, sig=None):
    headers = {
        "X-Neos-Timestamp": ts,
        "X-Neos-Delivery": delivery,
        "X-Neos-Signature": sig or sign_delivery(secret, ts, delivery, body),
        "Content-Type": "application/json",
    }
    return world.http.post(f"/standing-triggers/{trigger_id}/deliveries", content=body,
                           headers=headers)


async def test_create_shows_the_secret_once(world) -> None:
    agent = await _agent(world)

    created = _create(world, agent.agent_id, filters=[{"path": "a", "equals": 1}])
    listed = world.http.get(f"/standing-agents/{agent.agent_id}/triggers")

    assert created.status_code == 201
    body = created.json()
    assert len(body["secret"]) == 64
    assert body["delivery_path"] == f"/api/v1/standing-triggers/{body['trigger_id']}/deliveries"
    assert body["filters"] == [{"path": "a", "equals": 1}]
    assert listed.status_code == 200
    assert [t["trigger_id"] for t in listed.json()] == [body["trigger_id"]]
    assert "secret" not in listed.json()[0]


async def test_someone_elses_agent_is_404_on_every_owner_verb(world) -> None:
    bobs = await _agent(world, owner="bob")
    trigger = await world.triggers.create("bob", bobs.agent_id, prompt_template="p")
    base = f"/standing-agents/{bobs.agent_id}/triggers"

    assert _create(world, bobs.agent_id).status_code == 404
    assert world.http.get(base).status_code == 404
    assert world.http.patch(f"{base}/{trigger.trigger_id}", json={"enabled": False}).status_code == 404
    assert world.http.delete(f"{base}/{trigger.trigger_id}").status_code == 404
    assert (await world.triggers.get_owned("bob", trigger.trigger_id)).enabled is True


async def test_a_trigger_is_only_reachable_under_its_own_agent_path(world) -> None:
    agent = await _agent(world)
    trigger = await world.triggers.create("alice", agent.agent_id, prompt_template="p")

    wrong = world.http.patch(f"/standing-agents/sa_other/triggers/{trigger.trigger_id}",
                             json={"enabled": False})
    right = world.http.patch(f"/standing-agents/{agent.agent_id}/triggers/{trigger.trigger_id}",
                             json={"enabled": False})

    assert wrong.status_code == 404
    assert right.status_code == 200
    assert right.json()["enabled"] is False


async def test_bad_input_is_422(world) -> None:
    agent = await _agent(world)
    base = f"/standing-agents/{agent.agent_id}/triggers"
    trigger = await world.triggers.create("alice", agent.agent_id, prompt_template="p")

    assert _create(world, agent.agent_id, prompt_template=" ").status_code == 422
    assert _create(world, agent.agent_id, filters=[{"path": ""}]).status_code == 422
    assert world.http.patch(f"{base}/{trigger.trigger_id}", json={}).status_code == 422


async def test_delete_takes_the_trigger_away(world) -> None:
    agent = await _agent(world)
    body = _create(world, agent.agent_id).json()

    deleted = world.http.delete(f"/standing-agents/{agent.agent_id}/triggers/{body['trigger_id']}")

    assert deleted.status_code == 204
    assert _deliver(world, body["trigger_id"], body["secret"]).status_code == 401


async def test_a_signed_delivery_is_accepted_and_opens_a_task(world) -> None:
    agent = await _agent(world)
    body = _create(world, agent.agent_id).json()

    response = _deliver(world, body["trigger_id"], body["secret"])
    again = _deliver(world, body["trigger_id"], body["secret"])

    assert response.status_code == 202
    fired = response.json()
    assert fired["status"] == "fired"
    task = (await world.coding.snapshot(task_id=fired["task_id"], owner_id="alice")).task
    assert task.agent_id == agent.agent_id
    assert again.json() == {"status": "duplicate", "task_id": fired["task_id"], "reason": None}


async def test_every_authentication_failure_is_the_same_401(world) -> None:
    agent = await _agent(world)
    body = _create(world, agent.agent_id).json()
    trigger_id, secret = body["trigger_id"], body["secret"]

    failures = [
        _deliver(world, "st_unknown", secret),
        _deliver(world, trigger_id, "wrong-secret"),
        _deliver(world, trigger_id, secret, ts=str(int(NOW.timestamp()) - 301)),
        _deliver(world, trigger_id, secret, delivery="dot.ted"),
        _deliver(world, trigger_id, secret, sig="v1=" + "0" * 64),
        world.http.post(f"/standing-triggers/{trigger_id}/deliveries", content=b"{}"),
    ]

    assert {(r.status_code, json.dumps(r.json())) for r in failures} == {
        (401, json.dumps({"detail": "invalid signature"}))
    }
    assert await world.coding.list_owned("alice", limit=10) == []


async def test_an_unknown_trigger_signed_with_its_would_be_secret_is_still_401(world) -> None:
    """The master key derives a secret for any id; an id that is not stored is still no trigger."""
    from neos.standing.triggers import trigger_secret

    assert _deliver(world, "st_nope", trigger_secret(KEY, "st_nope")).status_code == 401


async def test_a_body_over_the_limit_is_413_before_the_signature(world) -> None:
    agent = await _agent(world)
    body = _create(world, agent.agent_id).json()

    response = _deliver(world, body["trigger_id"], body["secret"], body=b"x" * 1025)
    at_limit = _deliver(world, body["trigger_id"], body["secret"], body=b"x" * 1024)

    assert response.status_code == 413
    assert at_limit.status_code == 202


async def test_a_refusal_is_reported_in_the_body(world) -> None:
    agent = await _agent(world)
    body = _create(world, agent.agent_id).json()
    world.http.patch(f"/standing-agents/{agent.agent_id}/triggers/{body['trigger_id']}",
                     json={"enabled": False})

    response = _deliver(world, body["trigger_id"], body["secret"])

    assert response.status_code == 202
    assert response.json() == {"status": "refused", "task_id": None, "reason": "trigger_disabled"}


async def test_no_master_key_verifies_nothing(world) -> None:
    agent = await _agent(world)
    body = _create(world, agent.agent_id).json()
    world.http.app.dependency_overrides[mod.get_trigger_settings] = lambda: ("", 1024, 300)
    from neos.standing.triggers import trigger_secret

    response = _deliver(world, body["trigger_id"], trigger_secret("", body["trigger_id"]))

    assert response.status_code == 401


def test_the_default_app_does_not_mount_the_trigger_routes() -> None:
    from tests.api.test_retired_routes import _routes

    served = _routes()
    assert ("POST", "/api/v1/coding/tasks") in served
    assert not [path for _method, path in served if "/standing-triggers" in path]
    assert not [path for _method, path in served if path.endswith("/triggers")]


def test_triggers_on_without_a_long_enough_key_does_not_start() -> None:
    from neos.config.schema import AppConfig

    on = {"standing_agents": {"enabled": True, "triggers": {"enabled": True}}}
    with pytest.raises(ValueError, match="standing_trigger_signing_key"):
        AppConfig(**on)
    with pytest.raises(ValueError, match="standing_trigger_signing_key"):
        AppConfig(**on, secrets={"standing_trigger_signing_key": "k" * 31})
    config = AppConfig(**on, secrets={"standing_trigger_signing_key": "k" * 32})
    assert config.standing_agents.triggers.enabled is True
    assert AppConfig().standing_agents.triggers.enabled is False
    assert AppConfig().standing_agents.budget.enabled is False


def test_the_key_comes_from_the_environment_by_name() -> None:
    from pathlib import Path

    from neos.config.loader import SECRET_ENV_KEYS, SECRET_ENV_MAPPING

    assert "NEOS_TRIGGER_SIGNING_KEY" in SECRET_ENV_KEYS
    assert SECRET_ENV_MAPPING["NEOS_TRIGGER_SIGNING_KEY"] == "secrets.standing_trigger_signing_key"
    template = (Path(__file__).resolve().parents[2] / ".env.template").read_text()
    assert "\nNEOS_TRIGGER_SIGNING_KEY=\n" in template
