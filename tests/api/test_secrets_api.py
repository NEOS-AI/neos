"""Q6: the vault API. Values are write-only -- no response ever carries one."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import neos.api.handlers.secret_handlers as mod
from neos.api.dependencies.auth import get_current_user
from neos.coding.secrets import InMemorySecretStore

pytestmark = pytest.mark.no_db

TOKEN = "ghp_live_0123456789abcdefghij"


@pytest.fixture
def api():
    store = InMemorySecretStore(max_secrets=1)
    app = FastAPI()
    app.include_router(mod.router)
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(user_id="alice")
    app.dependency_overrides[mod.get_secret_store] = lambda: store
    return TestClient(app), store


def test_put_and_list_never_return_the_value(api) -> None:
    http, store = api

    put = http.put("/coding/secrets/github", json={"env_name": "GH_TOKEN", "value": TOKEN})
    listed = http.get("/coding/secrets")

    assert put.status_code == 200
    assert put.json()["env_name"] == "GH_TOKEN"
    assert listed.json()[0]["name"] == "github"
    assert TOKEN not in put.text + listed.text


def test_a_bad_value_is_refused_without_echoing_it(api) -> None:
    http, _store = api
    long_value = "s" * 9000

    response = http.put("/coding/secrets/github", json={"env_name": "GH_TOKEN", "value": long_value})

    assert response.status_code == 422
    assert long_value not in response.text


async def test_someone_elses_secret_is_404_and_the_limit_is_409(api) -> None:
    http, store = api
    await store.put("bob", "npm", env_name="NPM_TOKEN", value=TOKEN)

    assert http.delete("/coding/secrets/npm").status_code == 404
    assert http.put("/coding/secrets/a", json={"env_name": "A_TOKEN", "value": TOKEN}).status_code == 200
    limit = http.put("/coding/secrets/b", json={"env_name": "B_TOKEN", "value": TOKEN})
    assert limit.status_code == 409 and limit.json()["detail"]["code"] == "secret_limit"
    assert http.delete("/coding/secrets/a").status_code == 204


def test_the_default_app_does_not_mount_the_vault() -> None:
    from tests.api.test_retired_routes import _routes

    served = _routes()
    # The neighbour is visible -- otherwise "absent" proves nothing (app.routes hides included routers).
    assert ("POST", "/api/v1/coding/tasks") in served
    assert not [path for _method, path in served if path.startswith("/api/v1/coding/secrets")]


def test_broker_on_without_a_long_enough_key_does_not_start() -> None:
    from neos.config.schema import AppConfig

    on = {"coding_model": {"secret_broker": True}}
    with pytest.raises(ValueError, match="secret_broker_key"):
        AppConfig(**on)
    with pytest.raises(ValueError, match="secret_broker_key"):
        AppConfig(**on, secrets={"secret_broker_key": "k" * 31})
    assert AppConfig(**on, secrets={"secret_broker_key": "k" * 32}).coding_model.secret_broker
    assert AppConfig().coding_model.secret_broker is False


def test_the_key_comes_from_the_environment_by_name() -> None:
    from pathlib import Path

    from neos.config.loader import SECRET_ENV_KEYS, SECRET_ENV_MAPPING
    from neos.config.schema import SECRET_BROKER_KEY_MIN_CHARS
    from neos.coding.secrets import SECRET_BROKER_KEY_MIN_CHARS as SAME

    assert "NEOS_SECRET_BROKER_KEY" in SECRET_ENV_KEYS
    assert SECRET_ENV_MAPPING["NEOS_SECRET_BROKER_KEY"] == "secrets.secret_broker_key"
    assert SECRET_BROKER_KEY_MIN_CHARS == SAME
    template = (Path(__file__).resolve().parents[2] / ".env.template").read_text()
    assert "\nNEOS_SECRET_BROKER_KEY=\n" in template
