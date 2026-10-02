"""Q16c: the pairing API's `allow_commands` and the socket's command declaration (BC2 · BC3)."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import neos.api.handlers.device_bridge_handlers as http_mod
import neos.api.handlers.device_bridge_ws_handlers as ws_mod
from neos.api.dependencies.auth import get_current_user
from neos.coding.bridge.credentials import InMemoryBridgeCredentialStore
from neos.coding.bridge.relay import InProcessDeviceBridgeRelay
from neos.config.schema import DeviceBridgeConfig
from tests.api.test_device_bridge_api import READ_ONLY, _connect, _live

pytestmark = pytest.mark.no_db

COMMAND_DECL = READ_ONLY + [{"name": "run_command", "risk": "command", "executables": ["pytest"]}]


@pytest.fixture
def world():
    store = InMemoryBridgeCredentialStore(max_bridges=3)
    relay = InProcessDeviceBridgeRelay()
    app = FastAPI()
    app.include_router(http_mod.router)
    app.include_router(ws_mod.router)
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(user_id="alice")
    app.dependency_overrides[http_mod.get_bridge_credential_store] = lambda: store
    app.dependency_overrides[http_mod.get_device_bridge_relay] = lambda: relay
    app.dependency_overrides[http_mod.get_device_bridge_config] = lambda: DeviceBridgeConfig(
        hello_timeout_seconds=2, command_allowlist=["pytest", "ruff"]
    )
    return TestClient(app), store, relay


def _hello(http, token, declaration):
    with _connect(http, token) as ws:
        ws.send_text(json.dumps({"type": "hello", "tools": declaration}))
        first = ws.receive_json()
        if first["type"] == "refused":
            with pytest.raises(WebSocketDisconnect) as closed:
                ws.receive_text()
            return first, closed.value.code
        return first, None


def test_a_command_declaration_needs_the_credential_and_the_bound(world) -> None:
    """BC2 · BC3 at the wire. Mutation: pass `allow_commands=True` (or skip the bound) in the
    socket handler -> ready."""
    http, _store, relay = world
    plain = http.post("/coding/device-bridges", json={"name": "laptop"}).json()
    assert plain["allow_commands"] is False

    refused, code = _hello(http, plain["token"], COMMAND_DECL)
    assert refused == {"v": 1, "type": "refused", "code": "device_commands_not_enabled"}
    assert code == ws_mod.CLOSE_REFUSED and relay._live == {}

    allowed = http.post("/coding/device-bridges", json={"name": "desk", "allow_commands": True}).json()
    assert (allowed["allow_commands"], allowed["allow_writes"], allowed["allow_unattended"]) == (
        True,
        False,
        False,
    )
    outside = COMMAND_DECL[:-1] + [{"name": "run_command", "risk": "command", "executables": ["make"]}]
    refused, code = _hello(http, allowed["token"], outside)
    assert refused["code"] == "device_command_not_allowed" and code == ws_mod.CLOSE_REFUSED

    ready, _ = _hello(http, allowed["token"], COMMAND_DECL)
    assert ready["type"] == "ready" and "run_command" in ready["tools"]


def test_flipping_commands_kicks_the_live_connection(world) -> None:
    """Mutation: drop the kick on a command-setting change -> the live socket keeps its commands
    until its next refresh (the socket's per-command recheck is the wall behind this one)."""
    http, _store, relay = world
    bridge = http.post("/coding/device-bridges", json={"name": "laptop"}).json()["bridge_id"]

    live = _live(relay, bridge)
    patched = http.patch(f"/coding/device-bridges/{bridge}", json={"allow_commands": True})
    assert patched.status_code == 200 and patched.json()["allow_commands"] is True
    assert patched.json()["allow_writes"] is False and live.reason == "kicked"

    live = _live(relay, bridge)
    off = http.patch(f"/coding/device-bridges/{bridge}", json={"allow_commands": False}).json()
    assert off["allow_commands"] is False and live.reason == "kicked"
    assert http.get("/coding/device-bridges").json()[0]["allow_commands"] is False
