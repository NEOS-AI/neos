"""Q14c smoke: the managed-browser wire against a real Chromium in a separate process.

Skipped unless `NEOS_BROWSER_SMOKE=1` (the Q14a convention). No vendor and no network:
the "sandbox" is a local child process running `python -m neos.coding.browser.guest`
(the `BROWSER_GUEST_ARGV` module) whose stdin/stdout stand in for the vendor exec stdio.
Chromium in that process cannot resolve any name; every byte it renders came over the
wire from the host judge, which "fetches" from a canned site.

What this proves that the in-memory parity tests cannot: the guest module really drives
Playwright, `route.fulfill` works with answers that crossed a process boundary as frames,
the private-address image is refused by the host, a plain-text form post goes through the
host, and `browser_fill_secret.v1` is refused before any vault access (MB4).
What it does **not** prove: anything about E2B or Modal (§8 checklist).
"""

from __future__ import annotations

import asyncio
import os
import re
import socket
import sys

import pytest

from neos.coding.browser.driver import ServedResponse
from neos.coding.browser.managed_driver import BROWSER_GUEST_ARGV, ManagedBrowserDriver
from neos.coding.browser.session import BrowserLimits, BrowserSessions
from neos.coding.sandboxd.client import StreamSandboxdChannel
from neos.coding.tools.executor import SandboxToolExecutor
from neos.coding.tools.registry import (
    BROWSER_SECRET_TOOL,
    BROWSER_TOOL,
    BROWSER_TOOL_NAMES,
    CodingToolRegistry,
)

pytestmark = [
    pytest.mark.no_db,
    pytest.mark.skipif(
        os.environ.get("NEOS_BROWSER_SMOKE") != "1", reason="set NEOS_BROWSER_SMOKE=1"
    ),
]

LOGIN = b"""<!doctype html><html><head><title>Sign in</title>
<script>
  try { new WebSocket("wss://login.example.com/ws"); } catch (e) {}
  fetch("https://login.example.com/api", {method: "PUT"}).catch(() => {});
</script></head><body>
<h1>Sign in</h1>
<img src="https://10.0.0.1/pixel.png">
<form method="post" action="/session">
  <label>User <input type="text" name="user"></label>
  <label>Password <input type="password" name="password"></label>
  <button type="submit">Go</button>
</form></body></html>"""
DONE = b"<!doctype html><html><head><title>Welcome</title></head><body><h1>Welcome back</h1></body></html>"


class LocalGuestProcess:
    """Opens one guest process per task -- the shape of the B2 opener, minus the vendor."""

    def __init__(self) -> None:
        self.processes: list[asyncio.subprocess.Process] = []

    async def open(self, task_id: str):
        args = list(BROWSER_GUEST_ARGV[1:])
        if os.environ.get("NEOS_BROWSER_SMOKE_SANDBOX") != "1":
            args.append("--no-chromium-sandbox")
        if os.environ.get("NEOS_BROWSER_SMOKE_CHROMIUM"):
            args += ["--executable-path", os.environ["NEOS_BROWSER_SMOKE_CHROMIUM"]]
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            limit=32 * 1024 * 1024,
        )
        self.processes.append(process)
        return StreamSandboxdChannel(process.stdout, process.stdin)

    async def reap(self) -> list[int | None]:
        codes = []
        for process in self.processes:
            try:
                codes.append(await asyncio.wait_for(process.wait(), 20))
            except TimeoutError:
                process.kill()
                codes.append(None)
        return codes


@pytest.mark.asyncio
async def test_a_real_chromium_behind_the_wire_browses_through_the_host(monkeypatch) -> None:
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

    guests = LocalGuestProcess()
    sessions = BrowserSessions(
        ManagedBrowserDriver(guests, handshake_timeout_sec=60),
        BrowserLimits(),
        allowlist=lambda: ("login.example.com",),
        fetch=fetch,
    )
    registry = CodingToolRegistry.default(command_allowlist=frozenset({"git"}), secret_env_refs=True)
    executor = SandboxToolExecutor(1 << 20, 10)
    looked_up = []

    async def lookup(names):
        looked_up.append(names)
        raise AssertionError("the vault must not be opened for a managed browser")

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
        assert entry.get("blocked_requests", {}).get("policy_web_fetch_host_denied", 0) >= 1
        user = re.search(r'textbox "User"[^\n]*\[ref=(\w+)\]', entry["text"]).group(1)
        password = re.search(r'textbox "Password"[^\n]*\[ref=(\w+)\]', entry["text"]).group(1)

        refused = await run(
            BROWSER_SECRET_TOOL,
            {"ref": password, "secret": "secret://site", "origin": "https://login.example.com"},
            secrets=lookup,
        )
        assert (refused.status, refused.reason_code) == ("denied", "browser_secret_channel_unavailable")
        assert looked_up == []

        typed = await run(BROWSER_TOOL, {"action": "type", "ref": user, "text": "alice", "submit": True})
        assert typed.status == "ok", typed
        after = await run(BROWSER_TOOL, {"action": "snapshot"})
        assert "Welcome back" in after.entries[0]["text"]
        posts = [r for r in sent if r.method == "POST"]
        assert posts and "user=alice" in posts[0].body.decode()
        assert not any(r.method == "PUT" for r in sent)
        assert not any("10.0.0.1" in r.url for r in sent)
    finally:
        await sessions.close_all()
    assert await guests.reap() == [0]  # `close` ends the guest process cleanly
