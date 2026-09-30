"""Q13b: the standing agent API (design §7).

The path takes `{agent_id}` from the first day and the list is an array --
growing past one agent per owner must not break the API. `/me` is a
convenience alias. Someone else's agent answers exactly like a missing one.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import neos.api.handlers.standing_agent_handlers as mod
from neos.api.dependencies.auth import get_current_user
from neos.standing.store import InMemoryStandingAgentStore

pytestmark = pytest.mark.no_db


@pytest.fixture
def api():
    store = InMemoryStandingAgentStore()
    user = SimpleNamespace(user_id="alice")
    app = FastAPI()
    app.include_router(mod.router)
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[mod.get_standing_agent_store] = lambda: store
    return TestClient(app), user


def _create(http, name="Dot"):
    return http.post("/standing-agents", json={"name": name})


def test_create_returns_the_agent(api) -> None:
    http, _ = api
    response = _create(http, "  Dot ")

    assert response.status_code == 201
    body = response.json()
    assert body["agent_id"].startswith("sa_")
    assert body["name"] == "Dot"
    assert body["status"] == "active"
    assert "owner_id" not in body


def test_a_second_agent_is_a_conflict_with_its_reason(api) -> None:
    http, _ = api
    _create(http)

    response = _create(http, "Other")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "one_per_owner"


@pytest.mark.parametrize("name", ["", "   "])
def test_an_empty_name_is_unprocessable(api, name: str) -> None:
    http, _ = api

    assert _create(http, name).status_code == 422


def test_the_list_is_an_array_from_the_first_day(api) -> None:
    http, _ = api
    assert http.get("/standing-agents").json() == []

    agent = _create(http).json()

    assert [item["agent_id"] for item in http.get("/standing-agents").json()] == [
        agent["agent_id"]
    ]


def test_me_is_an_alias_for_the_only_agent(api) -> None:
    """`/me` must not be captured as an agent id."""
    http, _ = api
    assert http.get("/standing-agents/me").status_code == 404

    agent = _create(http).json()

    assert http.get("/standing-agents/me").json()["agent_id"] == agent["agent_id"]


def test_someone_elses_agent_is_a_404_on_every_verb(api) -> None:
    http, user = api
    agent_id = _create(http).json()["agent_id"]
    user.user_id = "bob"

    assert http.get(f"/standing-agents/{agent_id}").status_code == 404
    assert http.patch(f"/standing-agents/{agent_id}", json={"name": "x"}).status_code == 404
    assert http.delete(f"/standing-agents/{agent_id}").status_code == 404
    user.user_id = "alice"
    assert http.get(f"/standing-agents/{agent_id}").json()["name"] == "Dot"


def test_patch_renames_and_pauses(api) -> None:
    http, _ = api
    agent_id = _create(http).json()["agent_id"]

    renamed = http.patch(f"/standing-agents/{agent_id}", json={"name": "Dotty"})
    paused = http.patch(f"/standing-agents/{agent_id}", json={"status": "paused"})

    assert renamed.json()["name"] == "Dotty"
    assert paused.json()["status"] == "paused"


@pytest.mark.parametrize("body", [{"status": "deleted"}, {"name": "  "}, {}])
def test_patch_rejects_what_it_cannot_apply(api, body) -> None:
    http, _ = api
    agent_id = _create(http).json()["agent_id"]

    assert http.patch(f"/standing-agents/{agent_id}", json=body).status_code == 422


def test_delete_then_it_is_gone_and_a_new_one_may_be_made(api) -> None:
    http, _ = api
    agent_id = _create(http).json()["agent_id"]

    assert http.delete(f"/standing-agents/{agent_id}").status_code == 204
    assert http.get(f"/standing-agents/{agent_id}").status_code == 404
    assert _create(http).status_code == 201


def test_the_feature_is_off_by_default() -> None:
    from neos.config.schema import AppConfig

    assert AppConfig().standing_agents.enabled is False


def test_the_default_app_does_not_mount_the_routes() -> None:
    """Flag off means no route at all, not a route that refuses (design §7).

    `app.routes` holds `_IncludedRouter` wrappers whose own `path` is not the
    route's -- the first draft of this test read it directly and passed with the
    flag inverted. Read what is served, the way `test_retired_routes` does, and
    prove the reader sees a neighbour."""
    from tests.api.test_retired_routes import _routes

    served = _routes()
    assert ("POST", "/api/v1/coding/tasks") in served
    assert not [path for _method, path in served if "/standing-agents" in path]
