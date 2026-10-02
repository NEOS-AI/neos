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
from neos.coding.application.task_service import (
    CodingTaskService,
    InMemoryCodingTaskRepository,
)
from neos.coding.events.store import InMemoryCodingEventStore
from neos.standing.activity import InMemoryActivitySource
from neos.standing.store import InMemoryStandingAgentStore
from neos.standing.tasks import open_agent_task

pytestmark = pytest.mark.no_db


def _app(store, coding, user):
    app = FastAPI()
    app.include_router(mod.router)
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[mod.get_standing_agent_store] = lambda: store
    app.dependency_overrides[mod.get_task_opener] = lambda: coding
    app.dependency_overrides[mod.get_inventory_reader] = lambda: (
        lambda _owner: (["slack"], ["- pdf: read PDFs"])
    )
    return app


def _coding():
    return CodingTaskService(InMemoryCodingTaskRepository(), InMemoryCodingEventStore())


@pytest.fixture
def api():
    store = InMemoryStandingAgentStore()
    user = SimpleNamespace(user_id="alice")
    return TestClient(_app(store, _coding(), user)), user


@pytest.fixture
def feed_api():
    """The API plus the coding service the agent opens tasks in."""
    store = InMemoryStandingAgentStore()
    repo, events = InMemoryCodingTaskRepository(), InMemoryCodingEventStore()
    coding = CodingTaskService(repo, events)
    user = SimpleNamespace(user_id="alice")
    app = _app(store, coding, user)
    app.dependency_overrides[mod.get_activity_source] = lambda: InMemoryActivitySource(
        repo, events
    )
    return TestClient(app), user, store, coding


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


# -- activity feed (Q13d) ---------------------------------------------------


async def test_the_feed_pages_with_next_and_sends_the_ledger_shape(feed_api) -> None:
    """Creating the agent already opened its self-introduction (Q13f), so the
    feed starts with that task; a second task follows."""
    http, _, store, coding = feed_api
    created = _create(http).json()
    agent_id = created["agent_id"]
    task = await open_agent_task(store, coding, owner_id="alice", prompt="look")

    first = http.get(f"/standing-agents/{agent_id}/activity", params={"limit": 1}).json()
    second = http.get(
        f"/standing-agents/{agent_id}/activity", params={"after": first["next"]}
    ).json()
    empty = http.get(
        f"/standing-agents/{agent_id}/activity", params={"after": second["next"]}
    ).json()

    assert [(e["task_id"], e["type"]) for e in first["events"]] == [
        (created["onboarding_task_id"], "task.created")
    ]
    assert first["events"][0]["payload"]["actor"] == f"agent:{agent_id}"
    assert [(e["task_id"], e["seq"]) for e in second["events"]] == [(task.task_id, 1)]
    assert empty == {"events": [], "next": second["next"]}


def test_someone_elses_feed_is_a_404(feed_api) -> None:
    http, user, _, _ = feed_api
    agent_id = _create(http).json()["agent_id"]
    user.user_id = "bob"

    assert http.get(f"/standing-agents/{agent_id}/activity").status_code == 404


def test_an_unreadable_cursor_is_unprocessable(feed_api) -> None:
    http, _, _, _ = feed_api
    agent_id = _create(http).json()["agent_id"]

    response = http.get(f"/standing-agents/{agent_id}/activity", params={"after": "x"})

    assert response.status_code == 422


# -- self-introduction (Q13f) --------------------------------------------------


def test_creating_an_agent_opens_its_background_self_introduction(feed_api) -> None:
    http, _, _, coding = feed_api

    created = _create(http).json()

    task = coding.tasks._tasks[created["onboarding_task_id"]]
    assert task.mode.value == "background"
    assert task.agent_id == created["agent_id"]
    assert "slack" in task.prompt and "pdf: read PDFs" in task.prompt


def test_the_agent_is_made_even_if_the_self_introduction_cannot_start(feed_api) -> None:
    http, _, _, _ = feed_api
    http.app.dependency_overrides[mod.get_inventory_reader] = lambda: _broken

    response = _create(http)

    assert response.status_code == 201
    assert response.json()["onboarding_task_id"] is None
    assert http.get("/standing-agents/me").status_code == 200


def _broken(_owner):
    raise RuntimeError("inventory down")
