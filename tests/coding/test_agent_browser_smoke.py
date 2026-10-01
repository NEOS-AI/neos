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
    await store.put("alice", "site", env_name="SITE_PASSWORD", value=PASSWORD)

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
