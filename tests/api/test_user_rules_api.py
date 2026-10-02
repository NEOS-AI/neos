"""Q2: the user rule API. Rules are the caller's own; another user's rule id is a 404."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import neos.api.handlers.user_rule_handlers as mod
from neos.api.dependencies.auth import get_current_user
from neos.coding.application.user_rules import InMemoryUserRuleStore

pytestmark = pytest.mark.no_db


@pytest.fixture
def api():
    store = InMemoryUserRuleStore(max_rules=2)
    user = SimpleNamespace(user_id="alice")
    app = FastAPI()
    app.include_router(mod.router)
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[mod.get_user_rule_store] = lambda: store
    return TestClient(app), user, store


def test_create_and_list(api) -> None:
    http, _user, _store = api

    created = http.post(
        "/coding/approval-rules",
        json={"effect": "block", "tool": "execute.v1", "argv_prefix": ["git", "push"]},
    )
    listed = http.get("/coding/approval-rules")

    assert created.status_code == 201
    body = created.json()
    assert body["rule_id"].startswith("ur_")
    assert (body["effect"], body["tool"], body["argv_prefix"]) == (
        "block", "execute.v1", ["git", "push"]
    )
    assert listed.json() == [body]


async def test_someone_elses_rule_is_404(api) -> None:
    http, _user, store = api
    bobs = await store.create("bob", effect="block", tool="execute.v1")

    assert http.delete(f"/coding/approval-rules/{bobs.rule_id}").status_code == 404
    assert http.get("/coding/approval-rules").json() == []
    assert await store.list_for_user("bob") == [bobs]


def test_delete_own(api) -> None:
    http, _user, _store = api
    rule_id = http.post("/coding/approval-rules", json={"effect": "allow", "tool": "x.v1"}).json()[
        "rule_id"
    ]

    assert http.delete(f"/coding/approval-rules/{rule_id}").status_code == 204
    assert http.get("/coding/approval-rules").json() == []


def test_conflict_and_limit_are_409_with_a_code(api) -> None:
    http, _user, _store = api
    body = {"effect": "block", "tool": "execute.v1"}
    http.post("/coding/approval-rules", json=body)

    duplicate = http.post("/coding/approval-rules", json=body)
    http.post("/coding/approval-rules", json={"effect": "allow", "tool": "execute.v1"})
    over = http.post("/coding/approval-rules", json={"effect": "require", "tool": "execute.v1"})

    assert (duplicate.status_code, duplicate.json()["detail"]["code"]) == (409, "rule_exists")
    assert (over.status_code, over.json()["detail"]["code"]) == (409, "rule_limit")


@pytest.mark.parametrize(
    "body",
    [
        {"effect": "permit", "tool": "execute.v1"},
        {"effect": "block", "tool": ""},
        {"effect": "block", "tool": "write_file.v1", "argv_prefix": ["x"]},
        {"effect": "block", "tool": "execute.v1", "argv_prefix": ["--force"]},
    ],
)
def test_malformed_rules_are_422(api, body) -> None:
    http, _user, _store = api

    assert http.post("/coding/approval-rules", json=body).status_code == 422


def test_the_default_app_does_not_mount_the_rule_routes() -> None:
    from tests.api.test_retired_routes import _routes

    served = _routes()
    assert ("POST", "/api/v1/coding/tasks") in served
    assert not [path for _method, path in served if "approval-rules" in path]
