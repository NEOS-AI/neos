from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import neos.api.handlers.model_preference_handlers as mod
from neos.api.dependencies.auth import get_current_user
from neos.database.repositories.model_preference_repository import ModelPreference

pytestmark = pytest.mark.no_db

NOW = datetime(2026, 9, 24, tzinfo=timezone.utc)


class FakeRepo:
    def __init__(self):
        self.rows: dict[tuple[str, str], str] = {}

    async def list_for_user(self, user_id):
        return [ModelPreference(m, e, NOW) for (u, m), e in self.rows.items() if u == user_id]

    async def upsert_effort(self, user_id, model_pin, effort):
        self.rows[(user_id, model_pin)] = effort
        return ModelPreference(model_pin, effort, NOW)

    async def delete(self, user_id, model_pin):
        return self.rows.pop((user_id, model_pin), None) is not None


@pytest.fixture
def client(monkeypatch):
    repo = FakeRepo()
    for name in ("list_for_user", "upsert_effort", "delete"):
        monkeypatch.setattr(mod.ModelPreferenceRepository, name, getattr(repo, name))
    monkeypatch.setattr(
        mod, "effort_levels_for",
        lambda m: ("low", "high") if m in {"claude-opus-5-5", "gpt-6-sol"} else (),
    )
    app = FastAPI()
    app.include_router(mod.router)
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(user_id="u1")
    return TestClient(app), repo


def test_put_then_get(client) -> None:
    http, _ = client
    assert http.put("/users/me/model-preferences/claude-opus-5-5", json={"effort": "high"}).status_code == 200
    body = http.get("/users/me/model-preferences").json()
    assert [(r["model"], r["effort"]) for r in body] == [("claude-opus-5-5", "high")]


def test_put_by_gateway_id_stores_the_pin(client) -> None:
    """Review Focus 1: 경로에 `/` 가 있어도 404 가 아니다."""
    http, repo = client
    r = http.put("/users/me/model-preferences/anthropic/claude-opus-5.5", json={"effort": "low"})
    assert r.status_code == 200
    assert repo.rows == {("u1", "claude-opus-5-5"): "low"}


def test_put_by_retired_pin_stores_the_successor(client) -> None:
    """Review Focus 2."""
    http, repo = client
    r = http.put("/users/me/model-preferences/claude-opus-5", json={"effort": "high"})
    assert r.status_code == 200
    assert repo.rows == {("u1", "claude-opus-5-5"): "high"}


def test_unknown_model_is_404(client) -> None:
    http, _ = client
    assert http.put("/users/me/model-preferences/claude-nope", json={"effort": "low"}).status_code == 404


def test_unsupported_level_is_422_with_the_allowed_list(client) -> None:
    http, repo = client
    r = http.put("/users/me/model-preferences/claude-opus-5-5", json={"effort": "max"})
    assert r.status_code == 422
    assert r.json()["detail"]["allowed"] == ["low", "high"]
    assert repo.rows == {}


def test_model_without_levels_is_422(client) -> None:
    http, _ = client
    r = http.put("/users/me/model-preferences/claude-sonnet-5", json={"effort": "low"})
    assert r.status_code == 422


def test_delete_returns_to_default(client) -> None:
    http, repo = client
    http.put("/users/me/model-preferences/gpt-6-sol", json={"effort": "low"})
    assert http.delete("/users/me/model-preferences/gpt-6-sol").status_code == 204
    assert repo.rows == {}


def test_unauthenticated_is_rejected() -> None:
    app = FastAPI()
    app.include_router(mod.router)
    assert TestClient(app).get("/users/me/model-preferences").status_code in {401, 403}


def test_router_is_registered() -> None:
    # test_catalog_api.py::test_catalog_route_registered 와 같은 방식 --
    # main.app.routes 에는 경로가 없는 _IncludedRouter 가 섞여 있다.
    from pathlib import Path

    assert "/users/me/model-preferences" in {route.path for route in mod.router.routes}
    main_source = Path("neos/main.py").read_text(encoding="utf-8")
    assert "_include_router_for_runtime(model_preference_router" in main_source
