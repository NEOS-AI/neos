"""Q14c: the agent browser inside the managed sandbox -- guard parity over the wire.

docs/Q14_AGENT_BROWSER_DESIGN_261001.md §8. No vendor is involved: the "sandbox" is an
in-memory byte pipe to a real `BrowserGuest` that drives the Q14a fake driver. The page's
requests therefore travel guest -> wire -> host judge -> wire -> guest, exactly the path a
vendor exec stdio would carry. Every guard test runs twice -- `host` (the fake driver
straight under the session, as Q14a tests it) and `managed` (the same fake behind the
wire) -- and must give the same answer. The decision each test pins is named (MB1..);
the mutation it bites is in its docstring.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from dataclasses import dataclass, field

import pytest

from neos.coding.browser.driver import BrowserActionError, InterceptedRequest
from neos.coding.browser.guest import BrowserGuest
from neos.coding.browser.managed_driver import BROWSER_GUEST_ARGV, ManagedBrowserDriver
from neos.coding.browser.playwright_driver import PlaywrightDriver
from neos.coding.browser.session import BrowserLimits, BrowserSessions, build_browser_sessions
from neos.coding.browser.wire import (
    BODY_LIMIT_BYTES,
    PROTOCOL_VERSION,
    WireInvalid,
    encode_frame,
    guest_bundle_digest,
    request_from_wire,
    response_from_wire,
)
from neos.coding.tools.executor import SandboxToolExecutor
from neos.config.schema import MANAGED_BROWSER_MAX_BODY_BYTES, AppConfig
from tests.coding.test_agent_browser import (
    HOSTS,
    PASSWORD,
    Clock,
    FakeDriver,
    Fetcher,
    Workspace,
    World,
    _browse,
    _enable,
    _fill,
    _registry,
    _resolve,
    _vault,
)

pytestmark = pytest.mark.no_db


# -- an in-memory "sandbox" ------------------------------------------------------------


class _Pipe:
    def __init__(self) -> None:
        self.buf = bytearray()
        self.cond = asyncio.Condition()
        self.closed = False


class _End:
    """One end of a duplex byte pipe -- the `SandboxdChannel` shape a vendor stdio has."""

    def __init__(self, inbox: _Pipe, outbox: _Pipe, wire: list[bytes]) -> None:
        self._in = inbox
        self._out = outbox
        self._wire = wire

    async def read_exactly(self, size: int) -> bytes:
        async with self._in.cond:
            await self._in.cond.wait_for(lambda: len(self._in.buf) >= size or self._in.closed)
            if len(self._in.buf) < size:
                raise ConnectionError("closed")
            data = bytes(self._in.buf[:size])
            del self._in.buf[:size]
            return data

    async def write(self, data: bytes) -> None:
        if self._out.closed:
            raise ConnectionError("closed")
        self._wire.append(data)
        async with self._out.cond:
            self._out.buf += data
            self._out.cond.notify_all()

    async def close(self) -> None:
        for pipe in (self._in, self._out):
            async with pipe.cond:
                pipe.closed = True
                pipe.cond.notify_all()


@dataclass
class Sandbox:
    """What one task's managed sandbox holds: the guest and every byte that crossed."""

    driver: FakeDriver
    guest: BrowserGuest
    task: asyncio.Task
    host_end: _End
    wire: list[bytes] = field(default_factory=list)

    def bytes(self) -> bytes:
        return b"".join(self.wire)


class Opener:
    """Stands in for the B2 opener: one guest per task, recorded."""

    def __init__(self, world: World | None = None, *, guest_kwargs=None, fail: bool = False) -> None:
        self.world = world or World()
        self.opened: list[str] = []
        self.sandboxes: dict[str, Sandbox] = {}
        self.guest_kwargs = guest_kwargs or {}
        self.fail = fail

    async def open(self, task_id: str):
        self.opened.append(task_id)
        if self.fail:
            raise RuntimeError("no allocation for this task")
        to_guest, to_host = _Pipe(), _Pipe()
        wire: list[bytes] = []
        host_end, guest_end = _End(to_host, to_guest, wire), _End(to_guest, to_host, wire)
        driver = FakeDriver(self.world)
        guest = BrowserGuest(driver, guest_end, **self.guest_kwargs)
        task = asyncio.create_task(guest.run())
        self.sandboxes[task_id] = Sandbox(driver, guest, task, host_end, wire)
        return host_end


def _managed_sessions(opener: Opener, *, fetcher=None, clock=None, **limits) -> BrowserSessions:
    return BrowserSessions(
        ManagedBrowserDriver(opener, handshake_timeout_sec=2),
        BrowserLimits(**limits),
        allowlist=lambda: HOSTS,
        fetch=fetcher or Fetcher(),
        clock=clock or Clock(),
    )


@dataclass
class Rig:
    """One browser, either straight (`host`) or behind the wire (`managed`)."""

    kind: str
    sessions: BrowserSessions
    opener: Opener | None
    host_driver: FakeDriver | None

    def page(self, task: str = "ct_1"):
        if self.opener is None:
            return self.host_driver.contexts[-1].page
        return self.opener.sandboxes[task].driver.contexts[-1].page

    def context(self, task: str = "ct_1"):
        if self.opener is None:
            return self.host_driver.contexts[-1]
        return self.opener.sandboxes[task].driver.contexts[-1]


def _rig(kind: str, world: World | None = None, *, fetcher=None, clock=None, **limits) -> Rig:
    world = world or World()
    if kind == "host":
        driver = FakeDriver(world)
        sessions = BrowserSessions(
            driver,
            BrowserLimits(**limits),
            allowlist=lambda: HOSTS,
            fetch=fetcher or Fetcher(),
            clock=clock or Clock(),
        )
        return Rig(kind, sessions, None, driver)
    opener = Opener(world)
    return Rig(kind, _managed_sessions(opener, fetcher=fetcher, clock=clock, **limits), opener, None)


async def _run(sessions, call, *, task="ct_1", secrets=None):
    return await SandboxToolExecutor(1 << 20, 10).execute(
        Workspace(), call, secrets=secrets, browser=sessions.bind(task)
    )


KINDS = ["host", "managed"]


# -- MB1 · W2: every request the page makes still meets the host judge --------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize(
    "url, reason",
    [
        ("https://cdn.evil.test/x.js", "policy_web_fetch_host_denied"),
        ("https://internal.example.org/x.js", "web_fetch_ssrf"),  # resolves to 10.0.0.7
        ("http://docs.example.com/x.js", "browser_scheme_denied"),
        ("https://user@docs.example.com/x.js", "web_fetch_userinfo"),
        ("https://docs.example.com/x.js?token=abc", "web_fetch_blocked"),
        ("https://169.254.169.254/latest/meta-data", "policy_web_fetch_host_denied"),
    ],
)
async def test_subresources_from_the_sandbox_meet_the_same_guard(monkeypatch, kind, url, reason) -> None:
    """MB1. Mutation: let `_Connection._route` fetch without `serve` (answer every route
    from the fetcher directly) -> the private subresource is fetched in `managed` only."""
    _enable(monkeypatch)
    _resolve(monkeypatch, {"internal.example.org": "10.0.0.7"})
    fetcher = Fetcher()
    rig = _rig(kind, World(subresources=(url,)), fetcher=fetcher)
    try:
        result = await _run(
            rig.sessions, _browse(_registry(), action="navigate", url="https://docs.example.com/")
        )
    finally:
        await rig.sessions.close_all()

    assert result.status == "ok"
    assert [r.url for r in fetcher.sent] == ["https://docs.example.com/"]
    assert result.entries[0]["blocked_requests"] == {reason: 1}


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", KINDS)
async def test_a_navigation_off_the_allowlist_never_reaches_the_browser(monkeypatch, kind) -> None:
    _enable(monkeypatch)
    _resolve(monkeypatch)
    rig = _rig(kind)
    try:
        result = await _run(rig.sessions, _browse(_registry(), action="navigate", url="https://evil.test/"))
        assert (result.status, result.reason_code) == ("denied", "policy_web_fetch_host_denied")
        assert rig.page().url() == "about:blank"
    finally:
        await rig.sessions.close_all()


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["PUT", "DELETE", "PATCH"])
async def test_a_guest_request_with_another_method_is_refused_by_the_host(monkeypatch, method) -> None:
    """MB1: the guest is a page, not a judge -- its route frames are judged like any request."""
    _enable(monkeypatch)
    _resolve(monkeypatch)
    fetcher = Fetcher()
    rig = _rig("managed", fetcher=fetcher)
    try:
        await _run(rig.sessions, _browse(_registry(), action="navigate", url="https://docs.example.com/"))
        guest = rig.opener.sandboxes["ct_1"].guest
        assert await guest._serve(InterceptedRequest("https://docs.example.com/api", method)) is None
        assert rig.sessions._sessions["ct_1"].blocked["browser_method_denied"] == 1
        assert [r.method for r in fetcher.sent] == ["GET"]
    finally:
        await rig.sessions.close_all()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "request_frame",
    [
        {"url": "https://docs.example.com/", "method": "GET", "body": "not base64!"},
        {"url": "https://docs.example.com/", "method": "GET", "body": "a!Gk="},  # lenient b64 = "hi"
        {"url": "https://docs.example.com/", "method": "G E T"},
        {"url": 7, "method": "GET"},
        {"url": "https://docs.example.com/", "method": "GET", "headers": {"x": 1}},
        "https://docs.example.com/",
    ],
)
async def test_a_malformed_route_frame_is_aborted_not_fetched(monkeypatch, request_frame) -> None:
    """MB1. A guest that sends garbage gets an abort; nothing leaves the host."""
    _enable(monkeypatch)
    _resolve(monkeypatch)
    fetcher = Fetcher()
    rig = _rig("managed", fetcher=fetcher)
    try:
        await _run(rig.sessions, _browse(_registry(), action="navigate", url="https://docs.example.com/"))
        sandbox = rig.opener.sandboxes["ct_1"]
        guest = sandbox.guest
        future = asyncio.get_running_loop().create_future()
        guest._routes[999] = future
        await guest._stream.write({"route": 999, "request": request_frame})
        answer = await asyncio.wait_for(future, 2)
        assert answer == {"route": 999, "abort": True}
        assert len(fetcher.sent) == 1
    finally:
        await rig.sessions.close_all()


# -- W9: what the model sees is scrubbed the same way --------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", KINDS)
async def test_password_fields_are_masked_the_same_way(monkeypatch, kind) -> None:
    """W9 parity. Mutation: drop `password_values` from `_RemotePage` (return ()) -> the
    sandbox's password field value reaches the result in `managed`."""
    _enable(monkeypatch)
    _resolve(monkeypatch)
    world = World(snapshot='- textbox "Password": s3cr3t-value [ref=e2]', passwords=("s3cr3t-value",))
    rig = _rig(kind, world)
    try:
        result = await _run(rig.sessions, _browse(_registry(), action="navigate", url="https://docs.example.com/"))
    finally:
        await rig.sessions.close_all()
    assert "s3cr3t-value" not in result.entries[0]["text"]
    assert "<masked:password>" in result.entries[0]["text"]
    assert result.entries[0]["text"].startswith("<untrusted") or "untrusted" in result.entries[0]["text"]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("error, reason", [(BrowserActionError("timeout"), "browser_timeout"),
                                           (RuntimeError("page says sk-live-ABCDEF"), "browser_action_failed")])
async def test_a_driver_failure_is_a_code_and_its_words_stay_in_the_sandbox(monkeypatch, kind, error, reason) -> None:
    """W9 over the wire. Mutation: send `str(error)` in the guest's reply -> the page's
    words cross the wire (and could reach a log on the vendor's relay)."""
    _enable(monkeypatch)
    _resolve(monkeypatch)
    rig = _rig(kind, World(raise_on={"click": error}))
    registry = _registry()
    try:
        await _run(rig.sessions, _browse(registry, action="navigate", url="https://docs.example.com/"))
        result = await _run(rig.sessions, _browse(registry, action="click", ref="e1"))
    finally:
        await rig.sessions.close_all()
    assert (result.status, result.reason_code) == ("error", reason)
    assert "sk-live-ABCDEF" not in json.dumps(result.to_mapping(), default=str)
    if kind == "managed":
        assert b"sk-live-ABCDEF" not in rig.opener.sandboxes["ct_1"].bytes()


# -- MB4: no secret crosses the vendor channel -----------------------------------------------


@pytest.mark.asyncio
async def test_a_managed_browser_refuses_logins_before_opening_the_vault(monkeypatch) -> None:
    """MB4 (Q6b C1). Mutation: drop the `confidential_channel` check in `_fill_secret` ->
    the vault is opened and the password is written onto the wire to the sandbox."""
    _enable(monkeypatch)
    _resolve(monkeypatch)
    rig = _rig("managed")
    registry = _registry()
    looked_up: list[list[str]] = []
    vault = await _vault()

    async def lookup(names):
        looked_up.append(list(names))
        return await vault(names)

    try:
        await _run(rig.sessions, _browse(registry, action="navigate", url="https://login.example.com/"))
        result = await _run(rig.sessions, _fill(registry, submit=True), secrets=lookup)
    finally:
        await rig.sessions.close_all()

    assert (result.status, result.reason_code) == ("denied", "browser_secret_channel_unavailable")
    assert looked_up == []
    assert rig.page().filled == {}
    wire = rig.opener.sandboxes["ct_1"].bytes()
    assert PASSWORD.encode() not in wire and b'"fill"' not in wire


@pytest.mark.asyncio
async def test_the_host_browser_still_logs_in(monkeypatch) -> None:
    """MB4 is narrowing for managed only: the host driver declares a private channel."""
    _enable(monkeypatch)
    _resolve(monkeypatch)
    rig = _rig("host", World(submit_to="https://login.example.com/session"))
    registry = _registry()
    await _run(rig.sessions, _browse(registry, action="navigate", url="https://login.example.com/"))
    result = await _run(rig.sessions, _fill(registry, submit=True), secrets=await _vault())
    assert result.status == "ok"
    assert rig.page().filled == {"e2": PASSWORD}
    assert PlaywrightDriver.confidential_channel is True
    assert ManagedBrowserDriver.confidential_channel is False


@pytest.mark.asyncio
async def test_a_driver_that_declares_nothing_gets_no_secrets(monkeypatch) -> None:
    """MB4 fails closed: a driver without the attribute is read as not private."""
    _enable(monkeypatch)
    _resolve(monkeypatch)

    class Undeclared(FakeDriver):
        pass

    del FakeDriver.confidential_channel
    try:
        driver = Undeclared()
        sessions = BrowserSessions(driver, BrowserLimits(), allowlist=lambda: HOSTS, fetch=Fetcher(), clock=Clock())
        registry = _registry()
        await _run(sessions, _browse(registry, action="navigate", url="https://login.example.com/"))
        result = await _run(sessions, _fill(registry), secrets=await _vault())
    finally:
        FakeDriver.confidential_channel = True
    assert result.reason_code == "browser_secret_channel_unavailable"


# -- W6 · X5: sessions close in the sandbox too ---------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", KINDS)
async def test_closing_a_task_closes_its_context_where_it_lives(monkeypatch, kind) -> None:
    """X5 parity (fail/cancel call `sessions.close`). Mutation: make `_RemoteContext.close`
    only close the channel without the `close` call -> the guest's context stays open."""
    _enable(monkeypatch)
    _resolve(monkeypatch)
    rig = _rig(kind)
    await _run(rig.sessions, _browse(_registry(), action="navigate", url="https://docs.example.com/"))
    context = rig.context()

    await rig.sessions.close("ct_1")

    assert context.closed
    assert not rig.sessions.is_open("ct_1")
    if kind == "managed":
        sandbox = rig.opener.sandboxes["ct_1"]
        await asyncio.wait_for(sandbox.task, 2)  # the guest finished
        assert await sandbox.guest._serve(InterceptedRequest("https://docs.example.com/", "GET")) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", KINDS)
async def test_an_idle_session_is_swept_where_it_lives(monkeypatch, kind) -> None:
    _enable(monkeypatch)
    _resolve(monkeypatch)
    clock = Clock()
    rig = _rig(kind, clock=clock, idle_timeout_sec=10)
    await _run(rig.sessions, _browse(_registry(), action="navigate", url="https://docs.example.com/"))
    context = rig.context()
    clock.now += 11

    await rig.sessions.sweep()

    assert context.closed and not rig.sessions.is_open("ct_1")


@pytest.mark.asyncio
async def test_each_task_gets_its_own_sandbox_and_capacity_still_holds(monkeypatch) -> None:
    """W6 + MB3: one channel per task; the process cap refuses before opening another."""
    _enable(monkeypatch)
    _resolve(monkeypatch)
    rig = _rig("managed", max_contexts=2)
    call = _browse(_registry(), action="navigate", url="https://docs.example.com/")
    try:
        for task in ("ct_1", "ct_2"):
            assert (await _run(rig.sessions, call, task=task)).status == "ok"
        third = await _run(rig.sessions, call, task="ct_3")
    finally:
        await rig.sessions.close_all()
    assert (third.status, third.reason_code) == ("denied", "browser_capacity")
    assert rig.opener.opened == ["ct_1", "ct_2"]


@pytest.mark.asyncio
async def test_a_lost_channel_fails_the_call_by_code(monkeypatch) -> None:
    _enable(monkeypatch)
    _resolve(monkeypatch)
    rig = _rig("managed")
    registry = _registry()
    try:
        await _run(rig.sessions, _browse(registry, action="navigate", url="https://docs.example.com/"))
        await rig.opener.sandboxes["ct_1"].host_end.close()
        result = await _run(rig.sessions, _browse(registry, action="snapshot"))
    finally:
        await rig.sessions.close_all()
    assert (result.status, result.reason_code) == ("error", "browser_action_failed")


# -- W12: children, DA and prefetch hold no handle -- the sandbox is never asked ------------


@pytest.mark.asyncio
async def test_no_handle_means_no_sandbox_channel(monkeypatch) -> None:
    """W12 parity: the executor without a handle (child, DA, prefetch) refuses by name and
    the opener is never called."""
    _enable(monkeypatch)
    opener = Opener()
    _managed_sessions(opener)
    result = await SandboxToolExecutor(1 << 20, 10).execute(
        Workspace(), _browse(_registry(), action="navigate", url="https://docs.example.com/"), browser=None
    )
    assert (result.status, result.reason_code) == ("denied", "browser_unavailable")
    assert opener.opened == []


# -- MB2 · MB5: the guest has to prove which guest it is -------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "guest_kwargs",
    [{"digest": "sha256:" + "0" * 64}, {"digest": None}],
    ids=["other-bundle", "matching-bundle"],
)
async def test_the_handshake_pins_the_guest_bundle(monkeypatch, guest_kwargs) -> None:
    """MB5. Mutation: drop the digest comparison in `handshake` -> a guest built from
    other source is driven."""
    _enable(monkeypatch)
    _resolve(monkeypatch)
    opener = Opener(guest_kwargs=guest_kwargs)
    sessions = _managed_sessions(opener)
    try:
        result = await _run(sessions, _browse(_registry(), action="navigate", url="https://docs.example.com/"))
    finally:
        await sessions.close_all()
    if guest_kwargs["digest"]:
        assert (result.status, result.reason_code) == ("error", "browser_unavailable")
        assert opener.sandboxes["ct_1"].driver.contexts == []  # never opened
    else:
        assert result.status == "ok"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "hello",
    [
        {"hello": {"protocol": PROTOCOL_VERSION + 1, "bundle_digest": guest_bundle_digest()}},
        {"hello": "hi"},
        {"reply": 1, "ok": True},
        None,  # a guest that never speaks
    ],
)
async def test_a_bad_or_silent_hello_is_browser_unavailable(monkeypatch, hello) -> None:
    _enable(monkeypatch)
    _resolve(monkeypatch)

    sent: list[bytes] = []

    class Silent:
        async def open(self, task_id):
            to_guest, to_host = _Pipe(), _Pipe()
            host = _End(to_host, to_guest, sent)
            guest = _End(to_guest, to_host, [])
            if hello is not None:
                await guest.write(encode_frame(hello))
            return host

    sessions = BrowserSessions(
        ManagedBrowserDriver(Silent(), handshake_timeout_sec=0.2),
        BrowserLimits(),
        allowlist=lambda: HOSTS,
        fetch=Fetcher(),
        clock=Clock(),
    )
    result = await _run(sessions, _browse(_registry(), action="navigate", url="https://docs.example.com/"))
    assert (result.status, result.reason_code) == ("error", "browser_unavailable")
    assert sent == []  # MB5: nothing is asked of a guest that has not proven itself


@pytest.mark.asyncio
async def test_a_guest_speaking_another_protocol_is_never_driven(monkeypatch) -> None:
    """MB5. Mutation: drop the protocol comparison in `handshake` -> it is driven."""
    _enable(monkeypatch)
    _resolve(monkeypatch)
    monkeypatch.setattr("neos.coding.browser.guest.PROTOCOL_VERSION", PROTOCOL_VERSION + 1)
    opener = Opener()
    sessions = _managed_sessions(opener)
    try:
        result = await _run(sessions, _browse(_registry(), action="navigate", url="https://docs.example.com/"))
    finally:
        await sessions.close_all()
    assert (result.status, result.reason_code) == ("error", "browser_unavailable")
    assert opener.sandboxes["ct_1"].driver.contexts == []


@pytest.mark.asyncio
async def test_a_context_has_an_owner_task() -> None:
    """MB2: the sandbox is the task's -- a context without an owner is not opened."""
    opener = Opener()

    async def serve(request):
        return None

    with pytest.raises(BrowserActionError):
        await ManagedBrowserDriver(opener).new_context(serve)
    assert opener.opened == []


@pytest.mark.asyncio
async def test_a_channel_lost_mid_call_fails_now_not_at_the_timeout(monkeypatch) -> None:
    """Mutation: drop failing the pending calls when the reader ends -> the call waits
    out its timeout and comes back `browser_timeout`."""
    _enable(monkeypatch)
    _resolve(monkeypatch)
    rig = _rig("managed", action_timeout_sec=1)
    registry = _registry()
    try:
        await _run(rig.sessions, _browse(registry, action="navigate", url="https://docs.example.com/"))
        sandbox = rig.opener.sandboxes["ct_1"]
        original = sandbox.guest._op

        async def die(op, args):
            if op == "click":
                await sandbox.host_end.close()
                await asyncio.sleep(3600)
            return await original(op, args)

        sandbox.guest._op = die
        result = await _run(rig.sessions, _browse(registry, action="click", ref="e1"))
        # the guest does not wait on a call nobody can answer any more
        await asyncio.wait_for(sandbox.task, 2)
    finally:
        await rig.sessions.close_all()
    assert (result.status, result.reason_code) == ("error", "browser_action_failed")


@pytest.mark.asyncio
async def test_no_allocation_is_browser_unavailable_not_a_host_browser(monkeypatch) -> None:
    """MB2: when the sandbox cannot be reached the browser is unavailable -- the host
    Chromium is never a fallback."""
    _enable(monkeypatch)
    _resolve(monkeypatch)
    opener = Opener(fail=True)
    sessions = _managed_sessions(opener)
    result = await _run(sessions, _browse(_registry(), action="navigate", url="https://docs.example.com/"))
    assert (result.status, result.reason_code) == ("error", "browser_unavailable")
    assert opener.opened == ["ct_1"]


@pytest.mark.asyncio
async def test_a_lying_guest_cannot_widen_anything(monkeypatch) -> None:
    """MB1: what the guest says is material for masking, not authority. A guest that
    answers with the wrong types makes the action fail by code."""
    _enable(monkeypatch)
    _resolve(monkeypatch)
    rig = _rig("managed")
    registry = _registry()
    try:
        await _run(rig.sessions, _browse(registry, action="navigate", url="https://docs.example.com/"))
        guest = rig.opener.sandboxes["ct_1"].guest
        original = guest._op

        async def lie(op, args):
            if op == "title":
                return {"not": "a string"}
            return await original(op, args)

        guest._op = lie
        result = await _run(rig.sessions, _browse(registry, action="snapshot"))
    finally:
        await rig.sessions.close_all()
    assert (result.status, result.reason_code) == ("error", "browser_action_failed")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message",
    [
        {"call": 1, "op": "eval", "args": {}},
        {"call": 2, "op": "goto", "args": {"url": "https://docs.example.com/"}},  # no timeout
        {"call": 3, "op": "click", "args": {"ref": "e1", "timeout_ms": 1}},  # before open
    ],
)
async def test_the_guest_answers_unknown_or_early_calls_with_failed(message) -> None:
    to_guest, to_host = _Pipe(), _Pipe()
    host = _End(to_host, to_guest, [])
    guest = BrowserGuest(FakeDriver(), _End(to_guest, to_host, []))
    from neos.coding.browser.wire import FrameStream

    stream = FrameStream(host)
    task = asyncio.create_task(guest.run())
    try:
        assert "hello" in await stream.read()
        await stream.write(message)
        reply = await asyncio.wait_for(stream.read(), 2)
    finally:
        await host.close()
        await asyncio.wait_for(task, 2)
    assert reply["ok"] is False and reply["error"] == "failed"
    assert set(reply) <= {"reply", "ok", "error", "url"}


# -- the wire ------------------------------------------------------------------------------


def test_the_body_limit_fits_a_frame_and_matches_the_config_layer() -> None:
    from neos.coding.sandboxd.guest import MAX_FRAME_BYTES

    assert BODY_LIMIT_BYTES == MANAGED_BROWSER_MAX_BODY_BYTES
    assert BODY_LIMIT_BYTES * 4 // 3 + 64 * 1024 < MAX_FRAME_BYTES


@pytest.mark.parametrize(
    "value",
    [{"status": 99, "body": ""}, {"status": True, "body": ""}, {"status": 200, "body": None},
     {"status": 200, "body": "", "headers": [("a", "b")]}],
)
def test_a_malformed_response_is_refused(value) -> None:
    with pytest.raises(WireInvalid):
        response_from_wire(value)


def test_the_request_round_trips() -> None:
    from neos.coding.browser.wire import request_to_wire

    original = InterceptedRequest("https://docs.example.com/a", "POST", {"a": "b"}, b"\x00x=1")
    assert request_from_wire(json.loads(json.dumps(request_to_wire(original)))) == original


def test_the_bundle_digest_covers_every_guest_file(tmp_path) -> None:
    """MB5. Mutation: drop a file from `_BUNDLE` -> editing it no longer changes the digest."""
    from neos.coding.browser import wire

    root = tmp_path / "neos"
    source = wire.Path(wire.__file__).resolve().parents[2]
    for name in wire._BUNDLE:
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(source / name, root / name)
    baseline = guest_bundle_digest(str(root))
    assert baseline == guest_bundle_digest()
    for name in ("coding/browser/guest.py", "coding/browser/playwright_driver.py", "coding/sandboxd/guest.py"):
        path = root / name
        original = path.read_bytes()
        path.write_bytes(original + b"\n# changed\n")
        assert guest_bundle_digest(str(root)) != baseline, name
        path.write_bytes(original)


def test_the_guest_argv_runs_the_guest_module() -> None:
    assert BROWSER_GUEST_ARGV[-1] == "neos.coding.browser.guest"


# -- MB2 · MB3: config and factory ------------------------------------------------------------


_MANAGED_PLANE = {
    "environment": "development",
    "sandbox": {"provider": "managed", "managed": {"enabled": True}},
    "secrets": {
        "managed_provider_reference_key": "A" * 43 + "=",
        "managed_coding_ownership_key": "B" * 43 + "=",
    },
}


def _browser(**browser):
    return {"browser": {"enabled": True, **browser}, "web_fetch_hosts": ["docs.example.com"]}


def test_the_default_provider_is_the_host_browser() -> None:
    """MB3: the new key defaults to today's browser; the factory builds the host driver."""
    config = AppConfig(coding_model=_browser())
    assert config.coding_model.browser.provider == "host"
    sessions = build_browser_sessions(config)
    assert isinstance(sessions._driver, PlaywrightDriver)
    assert AppConfig().coding_model.browser.provider == "host"
    assert build_browser_sessions(AppConfig()) is None


def test_a_managed_browser_needs_the_managed_plane() -> None:
    """MB3. Mutation: drop the managed-plane check from `validate_coding_browser` -> a
    managed browser validates on a memory sandbox."""
    with pytest.raises(ValueError, match="managed sandbox"):
        AppConfig(coding_model=_browser(provider="managed"))
    config = AppConfig(**_MANAGED_PLANE, coding_model=_browser(provider="managed"))
    assert config.coding_model.browser.provider == "managed"


def test_a_managed_browser_does_not_lift_the_outside_development_consent() -> None:
    """MB3 narrowing only: W3 stays until B2 passes."""
    production = {**_MANAGED_PLANE, "environment": "production"}
    with pytest.raises(ValueError, match="allow_outside_development"):
        AppConfig(**production, coding_model=_browser(provider="managed"))


@pytest.mark.parametrize("field_name", ["max_response_bytes", "max_request_body_bytes"])
def test_a_managed_browser_caps_bodies_at_the_frame_limit(field_name) -> None:
    with pytest.raises(ValueError, match="frame limit"):
        AppConfig(
            **_MANAGED_PLANE,
            coding_model=_browser(provider="managed", **{field_name: MANAGED_BROWSER_MAX_BODY_BYTES + 1}),
        )
    # the host browser keeps its own (larger) ceiling
    AppConfig(coding_model=_browser(**{field_name: MANAGED_BROWSER_MAX_BODY_BYTES + 1}))


def test_the_factory_refuses_a_managed_browser_without_an_opener() -> None:
    """MB2. Mutation: fall back to `PlaywrightDriver` when no opener is injected -> the
    host Chromium runs while the config says managed."""
    config = AppConfig(**_MANAGED_PLANE, coding_model=_browser(provider="managed"))
    with pytest.raises(ValueError, match="B2"):
        build_browser_sessions(config)
    sessions = build_browser_sessions(config, managed_channels=Opener())
    assert isinstance(sessions._driver, ManagedBrowserDriver)


def test_the_factory_rechecks_the_managed_plane() -> None:
    """A config built around validation does not open a managed browser off the plane."""
    browser = AppConfig(**_MANAGED_PLANE, coding_model=_browser(provider="managed")).coding_model
    unchecked = AppConfig.model_construct(
        environment="development", coding_model=browser, sandbox=AppConfig().sandbox
    )
    with pytest.raises(ValueError, match="managed sandbox plane"):
        build_browser_sessions(unchecked, managed_channels=Opener())
