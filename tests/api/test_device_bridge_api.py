"""Q16a: pairing API and the bridge socket endpoint.

The token is shown once and never again; the socket authenticates with it in a
header, refuses anything but a READ_ONLY declaration, and is not mounted when off.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import neos.api.handlers.device_bridge_handlers as http_mod
import neos.api.handlers.device_bridge_ws_handlers as ws_mod
from neos.api.dependencies.auth import get_current_user
from neos.coding.bridge.credentials import InMemoryBridgeCredentialStore, token_hash
from neos.coding.bridge.relay import BridgeView, InProcessDeviceBridgeRelay
from neos.config.schema import DeviceBridgeConfig

pytestmark = pytest.mark.no_db

READ_ONLY = [{"name": n, "risk": "read_only"} for n in ("list_dir", "stat", "read_file")]


@pytest.fixture
def world():
    store = InMemoryBridgeCredentialStore(max_bridges=2)
    relay = InProcessDeviceBridgeRelay()
    app = FastAPI()
    app.include_router(http_mod.router)
    app.include_router(ws_mod.router)
    user = {"id": "alice"}
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(user_id=user["id"])
    app.dependency_overrides[http_mod.get_bridge_credential_store] = lambda: store
    app.dependency_overrides[http_mod.get_device_bridge_relay] = lambda: relay
    app.dependency_overrides[http_mod.get_device_bridge_config] = lambda: DeviceBridgeConfig(
        hello_timeout_seconds=2
    )
    return TestClient(app), store, relay, user


def test_the_token_is_shown_once_and_only_its_hash_is_kept(world) -> None:
    http, store, _relay, _user = world

    created = http.post("/coding/device-bridges", json={"name": "laptop"})
    listed = http.get("/coding/device-bridges")

    assert created.status_code == 201
    token = created.json()["token"]
    assert token.startswith("ndb_") and created.json()["allow_unattended"] is False
    assert token not in listed.text and token_hash(token) not in listed.text + created.text
    [(_info, digest)] = store._rows.values()
    assert digest == token_hash(token)


def test_limits_names_and_someone_elses_bridge(world) -> None:
    http, _store, _relay, user = world
    first = http.post("/coding/device-bridges", json={"name": "laptop"}).json()

    assert http.post("/coding/device-bridges", json={"name": "laptop"}).status_code == 409
    assert http.post("/coding/device-bridges", json={"name": "../x"}).status_code == 422
    assert http.post("/coding/device-bridges", json={"name": "desk"}).status_code == 201
    limit = http.post("/coding/device-bridges", json={"name": "phone"})
    assert limit.status_code == 409 and limit.json()["detail"]["code"] == "device_bridge_limit"

    user["id"] = "bob"
    bridge = first["bridge_id"]
    assert http.patch(f"/coding/device-bridges/{bridge}", json={"allow_unattended": True}).status_code == 404
    assert http.delete(f"/coding/device-bridges/{bridge}").status_code == 404
    assert http.get("/coding/device-bridges").json() == []


def _live(relay, bridge_id):
    view = BridgeView("alice", bridge_id, "c1", frozenset({"read_file"}))
    asyncio.run(relay.attach(view, lambda _m: asyncio.sleep(0)))
    return relay._live["alice"]


def test_changing_or_revoking_kicks_the_live_connection(world) -> None:
    """B1. Mutation: drop the kick -> the live socket keeps the old setting until its next refresh."""
    http, _store, relay, _user = world
    bridge = http.post("/coding/device-bridges", json={"name": "laptop"}).json()["bridge_id"]

    live = _live(relay, bridge)
    assert http.get("/coding/device-bridges").json()[0]["connected"] is True
    patched = http.patch(f"/coding/device-bridges/{bridge}", json={"allow_unattended": True})
    assert patched.json()["allow_unattended"] is True and live.reason == "kicked"

    live = _live(relay, bridge)
    assert http.delete(f"/coding/device-bridges/{bridge}").status_code == 204
    assert live.reason == "kicked" and "alice" not in relay._live


# -- the socket ------------------------------------------------------------------------


def _pair(http) -> str:
    return http.post("/coding/device-bridges", json={"name": "laptop"}).json()["token"]


def _connect(http, token, *, protocol=ws_mod.PROTOCOL):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return http.websocket_connect(
        "/coding/device-bridge/ws", subprotocols=[protocol], headers=headers
    )


@pytest.mark.parametrize(
    "token,protocol,code",
    [
        ("good", "neos.coding.v1", 4406),
        (None, ws_mod.PROTOCOL, 4401),
        ("ndb_" + "A" * 43, ws_mod.PROTOCOL, 4401),
    ],
    ids=["wrong-protocol", "no-token", "unknown-token"],
)
def test_the_socket_refuses_before_accepting(world, token, protocol, code) -> None:
    http, _store, _relay, _user = world
    real = _pair(http)
    with pytest.raises(WebSocketDisconnect) as closed:
        with _connect(http, real if token == "good" else token, protocol=protocol) as ws:
            ws.receive_text()
    assert closed.value.code == code


def test_a_write_declaration_is_refused_whole(world) -> None:
    """B3 at the wire. Mutation: register the READ_ONLY entries and drop the rest -> ready."""
    http, _store, relay, _user = world
    token = _pair(http)
    declaration = READ_ONLY[:2] + [{"name": "read_file", "risk": "workspace_write"}]

    with _connect(http, token) as ws:
        ws.send_text(json.dumps({"type": "hello", "tools": declaration}))
        refused = ws.receive_json()
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_text()

    assert refused == {"v": 1, "type": "refused", "code": "device_tool_risk_refused"}
    assert closed.value.code == ws_mod.CLOSE_REFUSED
    assert relay._live == {}


def test_a_read_only_bridge_is_ready_and_present_for_its_owner_only(world) -> None:
    http, _store, relay, _user = world
    token = _pair(http)

    with _connect(http, token) as ws:
        ws.send_text(json.dumps({"type": "hello", "tools": READ_ONLY}))
        ready = ws.receive_json()
        assert ready["type"] == "ready" and ready["tools"] == ["list_dir", "read_file", "stat"]
        assert set(relay._live) == {"alice"}
        assert relay._live["alice"].view.allow_unattended is False
        ws.send_text(json.dumps({"type": "ping"}))
        assert ws.receive_json() == {"v": 1, "type": "pong"}


def test_without_a_relay_the_socket_is_unavailable(world) -> None:
    http, _store, _relay, _user = world
    token = _pair(http)
    http.app.dependency_overrides[http_mod.get_device_bridge_relay] = lambda: None
    with pytest.raises(WebSocketDisconnect) as closed:
        with _connect(http, token) as ws:
            ws.receive_text()
    assert closed.value.code == ws_mod.CLOSE_UNAVAILABLE


# -- off by default (B12) --------------------------------------------------------------


def test_the_default_app_mounts_neither_the_api_nor_the_socket() -> None:
    from tests.api.test_retired_routes import _routes

    served = _routes()
    # The neighbour is visible -- otherwise "absent" proves nothing (app.routes hides included routers).
    assert ("POST", "/api/v1/coding/tasks") in served
    assert ("WS", "/api/v1/coding/ws") in served
    assert not [p for _m, p in served if p.startswith("/api/v1/coding/device-bridge")]


# -- writes (Q16b, BW2) ----------------------------------------------------------------

WRITE_DECL = READ_ONLY + [{"name": "write_file", "risk": "workspace_write"}]


def test_a_write_declaration_needs_the_credential_to_allow_writes(world) -> None:
    """BW2 at the wire: the client's `--allow-writes` alone is not enough. Mutation: pass
    `allow_writes=True` (or drop the argument's check) in the socket handler -> ready."""
    http, _store, relay, _user = world
    token = _pair(http)

    with _connect(http, token) as ws:
        ws.send_text(json.dumps({"type": "hello", "tools": WRITE_DECL}))
        refused = ws.receive_json()
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_text()
    assert refused == {"v": 1, "type": "refused", "code": "device_writes_not_enabled"}
    assert closed.value.code == ws_mod.CLOSE_REFUSED and relay._live == {}

    created = http.post("/coding/device-bridges", json={"name": "desk", "allow_writes": True}).json()
    assert created["allow_writes"] is True and created["allow_unattended"] is False
    with _connect(http, created["token"]) as ws:
        ws.send_text(json.dumps({"type": "hello", "tools": WRITE_DECL}))
        ready = ws.receive_json()
        assert ready["type"] == "ready" and "write_file" in ready["tools"]
        assert relay._live["alice"].view.tools >= {"write_file"}


def test_flipping_writes_kicks_the_live_connection(world) -> None:
    """Mutation: drop the kick on a write-setting change -> the live socket keeps writing until
    its next refresh (the socket's per-write recheck is the wall behind this one)."""
    http, _store, relay, _user = world
    bridge = http.post("/coding/device-bridges", json={"name": "laptop"}).json()["bridge_id"]
    assert http.get("/coding/device-bridges").json()[0]["allow_writes"] is False

    live = _live(relay, bridge)
    patched = http.patch(f"/coding/device-bridges/{bridge}", json={"allow_writes": True})
    assert patched.status_code == 200 and patched.json()["allow_writes"] is True
    assert patched.json()["allow_unattended"] is False and live.reason == "kicked"

    live = _live(relay, bridge)
    both = http.patch(
        f"/coding/device-bridges/{bridge}", json={"allow_writes": False, "allow_unattended": True}
    ).json()
    assert (both["allow_writes"], both["allow_unattended"]) == (False, True)
    assert live.reason == "kicked"
    assert http.patch(f"/coding/device-bridges/{bridge}", json={}).status_code == 422


def test_the_socket_path_is_the_one_nginx_upgrades() -> None:
    from tests.api.test_nginx_websocket_routes import _socket_paths, _upgrade_locations

    assert "/api/v1/coding/device-bridge/ws" in _socket_paths()
    assert any(p.search("/api/v1/coding/device-bridge/ws") for p in _upgrade_locations())
