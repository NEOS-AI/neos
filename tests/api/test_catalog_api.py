"""GET /api/v1/models — catalog picker payload."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import neos.api.handlers.catalog_handlers as catalog_handlers
from neos.api.dependencies.auth import get_current_active_user
from neos.config.schema import AppConfig
from neos.database.connection import get_db


pytestmark = pytest.mark.no_db

CURRENT_PICKER_IDS = {
    "anthropic/claude-sonnet-5",
    "anthropic/claude-opus-5.5",
    "anthropic/claude-haiku-4.5",
    "anthropic/claude-sonnet-4.5",
    "anthropic/claude-sonnet-4.5-thinking",
    "openai/gpt-6-sol",
    "openai/gpt-6-luna",
}

HIDDEN_FROM_PICKER = {
    "openai/gpt-6-astra",
    "gpt-6-astra",
    "gemini-1.5-pro-latest",
    "claude-opus-4-8",
}


def _user() -> SimpleNamespace:
    return SimpleNamespace(user_id="owner", is_active=True)


def _app(*, authenticate: bool) -> FastAPI:
    app = FastAPI()
    app.include_router(catalog_handlers.router)

    async def override_get_db():
        yield None

    app.dependency_overrides[get_db] = override_get_db
    if authenticate:
        app.dependency_overrides[get_current_active_user] = lambda: _user()
    return app


def _enable_picker_api(monkeypatch) -> None:
    monkeypatch.setattr(
        catalog_handlers.settings.config.model_catalog, "picker_api", True
    )


def test_picker_api_defaults_false() -> None:
    assert AppConfig().model_catalog.picker_api is False
    assert AppConfig().model_catalog.default_unknown_claude_adaptive is False
    assert AppConfig().model_catalog.live_anthropic is False


def test_catalog_route_registered() -> None:
    assert "/models" in {route.path for route in catalog_handlers.router.routes}
    main_source = Path("neos/main.py").read_text(encoding="utf-8")
    assert "_include_router_for_runtime(catalog_router" in main_source


def test_flag_off_does_not_leak_catalog() -> None:
    from neos.config.settings import settings

    assert settings.config.model_catalog.picker_api is False

    with TestClient(_app(authenticate=True)) as client:
        response = client.get("/models")

    assert response.status_code == 404
    body = response.text
    for leaked in CURRENT_PICKER_IDS | HIDDEN_FROM_PICKER:
        assert leaked not in body
    assert "models" not in response.json() or "claude" not in body


def test_flag_on_requires_auth(monkeypatch) -> None:
    _enable_picker_api(monkeypatch)

    with TestClient(_app(authenticate=False)) as client:
        response = client.get("/models")

    assert response.status_code == 401


def test_flag_on_returns_seven_picker_rows_and_gateway_remaps(monkeypatch) -> None:
    _enable_picker_api(monkeypatch)

    with TestClient(_app(authenticate=True)) as client:
        response = client.get("/models")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, max-age=60"
    payload = response.json()
    assert payload["version"] == 1
    assert payload["default_id"] == "anthropic/claude-sonnet-5"
    assert payload["etag"]
    assert response.headers["etag"].strip('"') == payload["etag"]

    by_id = {row["id"]: row for row in payload["models"]}
    assert set(by_id) == CURRENT_PICKER_IDS
    assert by_id["anthropic/claude-sonnet-5"]["catalog_id"] == "claude-sonnet-5"
    assert by_id["anthropic/claude-sonnet-5"]["default"] is True
    assert by_id["anthropic/claude-haiku-4.5"]["catalog_id"] == (
        "claude-haiku-4-5-20251001"
    )
    thinking = by_id["anthropic/claude-sonnet-4.5-thinking"]
    assert thinking["catalog_id"] == "claude-sonnet-4-5-20250929"
    assert thinking["provider"] == "reasoning"
    assert thinking["default"] is False

    for hidden in HIDDEN_FROM_PICKER:
        assert hidden not in by_id
        assert hidden not in {row["catalog_id"] for row in payload["models"]}

    assert payload["remaps"]["anthropic/claude-opus-4.5"] == "anthropic/claude-opus-5.5"
    assert payload["remaps"]["openai/gpt-4o"] == "openai/gpt-6-sol"
    assert all(
        "effort_levels" in row and "effort_default" in row
        for row in payload["models"]
    )
    assert "anthropic/claude-haiku-4.5" not in payload["remaps"]
    visible = set(by_id)
    assert set(payload["remaps"].values()) <= visible


def test_etag_includes_routing_defaults(monkeypatch) -> None:
    _enable_picker_api(monkeypatch)

    with TestClient(_app(authenticate=True)) as client:
        first = client.get("/models")
        monkeypatch.setattr(
            catalog_handlers.settings.config.model_routing.anthropic,
            "everyday",
            "opus-5.5",
        )
        second = client.get("/models")

    assert first.status_code == second.status_code == 200
    assert first.json()["etag"] != second.json()["etag"]
    assert second.json()["default_id"] == "anthropic/claude-opus-5.5"


def test_etag_includes_yaml_identity(monkeypatch) -> None:
    _enable_picker_api(monkeypatch)
    monkeypatch.setattr(catalog_handlers, "_yaml_identity", lambda: "yaml-a")

    with TestClient(_app(authenticate=True)) as client:
        first = client.get("/models")
        monkeypatch.setattr(catalog_handlers, "_yaml_identity", lambda: "yaml-b")
        second = client.get("/models")

    assert first.json()["etag"] != second.json()["etag"]


def test_empty_catalog_returns_503(monkeypatch) -> None:
    from neos.config.model_config import ModelCatalog

    _enable_picker_api(monkeypatch)
    monkeypatch.setattr(catalog_handlers.model_config, "_catalog", ModelCatalog())

    with TestClient(_app(authenticate=True)) as client:
        response = client.get("/models")

    assert response.status_code == 503
    assert "claude" not in response.text
