"""Q14a smoke: the real Playwright driver, with Chromium cut off from the network.

Skipped unless `NEOS_BROWSER_SMOKE=1` and Playwright's Chromium is installed
(`playwright install chromium`). No network is used: the host side "fetches" from a
canned site, and Chromium itself cannot resolve any name (W2). What this proves that
the fake cannot: `route.fulfill` serves pages to a browser with no DNS, `aria-ref=`
refs from `aria_snapshot(mode="ai")` drive fill/click, a login form posts through the
host, and the typed password never comes back.
"""

from __future__ import annotations

import json
import os
import re
import socket

import pytest

from neos.coding.browser.driver import ServedResponse
from neos.coding.browser.playwright_driver import PlaywrightDriver
from neos.coding.browser.session import BrowserLimits, BrowserSessions
from neos.coding.secrets import InMemorySecretStore
from neos.coding.tools.executor import SandboxToolExecutor
from neos.coding.tools.registry import BROWSER_SECRET_TOOL, BROWSER_TOOL, BROWSER_TOOL_NAMES, CodingToolRegistry

pytestmark = [
    pytest.mark.no_db,
    pytest.mark.skipif(
        os.environ.get("NEOS_BROWSER_SMOKE") != "1", reason="set NEOS_BROWSER_SMOKE=1"
    ),
]

PASSWORD = "smoke-pass-0123456789"
LOGIN = b"""<!doctype html><html><head><title>Sign in</title>
<script>
  try { new WebSocket("wss://login.example.com/ws"); } catch (e) {}
  fetch("https://login.example.com/api", {method: "PUT"}).catch(() => {});
</script></head><body>
<h1>Sign in</h1>
<img src="https://10.0.0.1/pixel.png">
<form method="post" action="/session">
  <label>Password <input type="password" name="password"></label>
  <button type="submit">Go</button>
</form></body></html>"""
DONE = b"<!doctype html><html><head><title>Welcome</title></head><body><h1>Welcome back</h1></body></html>"


@pytest.mark.asyncio
async def test_a_real_chromium_logs_in_through_the_host(monkeypatch) -> None:
    pytest.importorskip("playwright")
    monkeypatch.setattr(
        "neos.coding.tools.registry.optional_tool_enabled", lambda name: name in BROWSER_TOOL_NAMES
    )
    monkeypatch.setattr(
        "neos.coding.tools.executor.socket.getaddrinfo",
        lambda host, port, *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))],
    )
    sent = []

    def fetch(request, *, timeout_sec, max_response_bytes):
        sent.append(request)
        body = DONE if request.url.endswith("/session") else LOGIN
        return ServedResponse(200, {"content-type": "text/html; charset=utf-8"}, body)

    driver = PlaywrightDriver(
        chromium_sandbox=os.environ.get("NEOS_BROWSER_SMOKE_SANDBOX") == "1",
        # another installed Chromium build, when this Playwright's own is not downloaded
        executable_path=os.environ.get("NEOS_BROWSER_SMOKE_CHROMIUM") or None,
    )
    sessions = BrowserSessions(
        driver, BrowserLimits(), allowlist=lambda: ("login.example.com",), fetch=fetch
    )
    registry = CodingToolRegistry.default(command_allowlist=frozenset({"git"}), secret_env_refs=True)
    store = InMemorySecretStore()
    await store.put(
        "alice",
        "site",
        env_name="SITE_PASSWORD",
        value=PASSWORD,
        browser_origins=["https://login.example.com"],
    )

    async def lookup(names):
        return await store.resolve("alice", names)

    executor = SandboxToolExecutor(1 << 20, 10)

    class Workspace:
        sandbox_id = "sb_1"

        async def workspace_revision(self):
            return 1

    async def run(name, input, secrets=None):
        return await executor.execute(
            Workspace(), registry.validate(name, input), secrets=secrets, browser=sessions.bind("ct_1")
        )

    try:
        opened = await run(BROWSER_TOOL, {"action": "navigate", "url": "https://login.example.com/"})
        if opened.reason_code == "browser_unavailable":
            pytest.skip("Chromium is not installed for this Playwright")
        assert opened.status == "ok", opened
        entry = opened.entries[0]
        assert entry["title"] == "Sign in"
        blocked = entry.get("blocked_requests", {})
        assert blocked.get("policy_web_fetch_host_denied", 0) >= 1  # the 10.0.0.1 pixel
        ref = re.search(r'textbox "Password"[^\n]*\[ref=(\w+)\]', entry["text"]).group(1)

        result = await run(
            BROWSER_SECRET_TOOL,
            {"ref": ref, "secret": "secret://site", "origin": "https://login.example.com", "submit": True},
            secrets=lookup,
        )
        assert result.status == "ok", result
        posts = [r for r in sent if r.method == "POST"]
        assert posts and f"password={PASSWORD}" in posts[0].body.decode()
        after = await run(BROWSER_TOOL, {"action": "snapshot"})
        assert "Welcome back" in after.entries[0]["text"]
        for item in (opened, result, after):
            assert PASSWORD not in json.dumps(item.to_mapping(), default=str)
        assert not any(r.method == "PUT" for r in sent)
    finally:
        await sessions.close_all()


# -- Q14b: things only a real Chromium can answer -----------------------------------------


def _q14b_setup(monkeypatch, fetch):
    pytest.importorskip("playwright")
    monkeypatch.setattr(
        "neos.coding.tools.registry.optional_tool_enabled", lambda name: name in BROWSER_TOOL_NAMES
    )
    monkeypatch.setattr(
        "neos.coding.tools.executor.socket.getaddrinfo",
        lambda host, port, *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))],
    )
    driver = PlaywrightDriver(
        chromium_sandbox=os.environ.get("NEOS_BROWSER_SMOKE_SANDBOX") == "1",
        executable_path=os.environ.get("NEOS_BROWSER_SMOKE_CHROMIUM") or None,
    )
    sessions = BrowserSessions(
        driver, BrowserLimits(), allowlist=lambda: ("login.example.com",), fetch=fetch
    )
    registry = CodingToolRegistry.default(command_allowlist=frozenset({"git"}), secret_env_refs=True)
    executor = SandboxToolExecutor(1 << 20, 10)

    class Workspace:
        sandbox_id = "sb_1"

        async def workspace_revision(self):
            return 1

    async def run(name, input, secrets=None):
        return await executor.execute(
            Workspace(), registry.validate(name, input), secrets=secrets, browser=sessions.bind("ct_1")
        )

    return sessions, run


def _served(raw_headers: bytes, body: bytes, status: int = 200) -> ServedResponse:
    """Headers go through the real `egress._response_headers` -- the code under test."""
    import http.client
    import io

    from neos.coding.browser.egress import _response_headers

    message = http.client.parse_headers(io.BytesIO(raw_headers + b"\r\n"))
    return ServedResponse(status, _response_headers(message), body)


@pytest.mark.asyncio
async def test_a_cookie_login_with_two_set_cookie_headers_keeps_both(monkeypatch) -> None:
    """Q14b X4: `_response_headers` joins several Set-Cookie with "\\n" for
    `route.fulfill`. Playwright 1.61's Chromium route splits that value back into one
    header per cookie (`splitSetCookieHeader` in crNetworkManager). Proven here end to
    end: both cookies come back on the next request the host fetches. Mutation: join
    Set-Cookie with ", " like other headers -> Chromium keeps one mangled cookie."""
    sent = []
    home = b"<!doctype html><html><head><title>Home</title></head><body><h1>Home</h1></body></html>"

    def fetch(request, *, timeout_sec, max_response_bytes):
        sent.append(request)
        html = b"Content-Type: text/html; charset=utf-8\r\n"
        if request.url.endswith("/session"):
            return _served(
                html
                + b"Set-Cookie: sid=s-0123456789; Path=/; Secure; HttpOnly\r\n"
                + b"Set-Cookie: csrf=c-9876543210; Path=/; Secure\r\n",
                DONE,
            )
        return _served(html, home if request.url.endswith("/home") else LOGIN)

    sessions, run = _q14b_setup(monkeypatch, fetch)
    store = InMemorySecretStore()
    await store.put(
        "alice", "site", env_name="SITE_PASSWORD", value=PASSWORD, browser_origins=["https://login.example.com"]
    )

    async def lookup(names):
        return await store.resolve("alice", names)

    try:
        opened = await run(BROWSER_TOOL, {"action": "navigate", "url": "https://login.example.com/"})
        if opened.reason_code == "browser_unavailable":
            pytest.skip("Chromium is not installed for this Playwright")
        ref = re.search(r'textbox "Password"[^\n]*\[ref=(\w+)\]', opened.entries[0]["text"]).group(1)
        filled = await run(
            BROWSER_SECRET_TOOL,
            {"ref": ref, "secret": "secret://site", "origin": "https://login.example.com", "submit": True},
            secrets=lookup,
        )
        assert filled.status == "ok", filled
        home_result = await run(BROWSER_TOOL, {"action": "navigate", "url": "https://login.example.com/home"})
        assert home_result.status == "ok", home_result

        [home_request] = [r for r in sent if r.url.endswith("/home")]
        cookie = {k.lower(): v for k, v in home_request.headers.items()}.get("cookie", "")
        assert "sid=s-0123456789" in cookie and "csrf=c-9876543210" in cookie, cookie
    finally:
        await sessions.close_all()


@pytest.mark.asyncio
async def test_a_password_in_a_child_frame_is_masked(monkeypatch) -> None:
    """Q14b X6: the frame's own script echoes its password field into text the snapshot
    shows. Mutation: read `input[type=password]` in the main frame only -> the framed
    value reaches the tool result."""
    secret_value = "frame-secret-4321"
    top = (
        b"<!doctype html><html><head><title>Outer</title></head><body><h1>Outer</h1>"
        b'<iframe src="https://login.example.com/frame" title="login"></iframe></body></html>'
    )
    frame = (
        b"<!doctype html><html><body><input type=password id=p aria-label=Pass>"
        b"<p id=o></p><script>p.value='" + secret_value.encode() + b"';"
        b"o.textContent='echo ' + p.value;</script></body></html>"
    )

    def fetch(request, *, timeout_sec, max_response_bytes):
        body = frame if request.url.endswith("/frame") else top
        return ServedResponse(200, {"content-type": "text/html; charset=utf-8"}, body)

    sessions, run = _q14b_setup(monkeypatch, fetch)
    try:
        opened = await run(BROWSER_TOOL, {"action": "navigate", "url": "https://login.example.com/"})
        if opened.reason_code == "browser_unavailable":
            pytest.skip("Chromium is not installed for this Playwright")
        assert opened.status == "ok", opened
        text = opened.entries[0]["text"]
        assert "echo <masked:password>" in text, text  # the frame is in the snapshot
        assert secret_value not in json.dumps(opened.to_mapping(), default=str)
    finally:
        await sessions.close_all()
