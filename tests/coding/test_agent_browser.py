"""Q14a: the agent browser -- flag-off identity, the egress guard, Q6 login, scrubbing,
the session lifecycle and where the browser is never exposed (children, DA).

docs/Q14_AGENT_BROWSER_DESIGN_261001.md. The decision each test pins is named
(W1..W12); the mutation it bites is in its docstring.
"""

from __future__ import annotations

import json
import socket
from dataclasses import dataclass, field

import pytest

from neos.coding.browser.driver import (
    BrowserActionError,
    InterceptedRequest,
    ServedResponse,
)
from neos.coding.browser.egress import EgressRefused, fetch_one_hop
from neos.coding.browser.session import (
    BrowserLimits,
    BrowserSessions,
    build_browser_sessions,
)
from neos.coding.domain.approvals import (
    ApprovalGate,
    ApprovalMode,
    ApprovalPolicyOutcome,
    UserApprovalRule,
    UserRuleEffect,
    approval_display_summary,
    evaluate_approval,
    policy_denial_reason,
)
from neos.coding.secrets import InMemorySecretStore, carries_secret_refs
from neos.coding.tools.executor import SandboxToolExecutor
from neos.coding.tools.registry import (
    BROWSER_SECRET_TOOL,
    BROWSER_TOOL,
    BROWSER_TOOL_NAMES,
    CodingToolRegistry,
    ToolRisk,
    ToolValidationError,
)
from neos.config.schema import CODING_BROWSER_TOOL_NAMES, AppConfig

pytestmark = pytest.mark.no_db

PASSWORD = "hunter2-correct-horse-battery"
HOSTS = ("docs.example.com", "login.example.com", ".example.org")


# -- fakes ---------------------------------------------------------------------------
#
# The fake implements `neos.coding.browser.driver`'s protocol only -- each method there
# names the one Playwright call the real driver makes, so the fake invents no field.


@dataclass
class World:
    """What the fake browser's pages say and do."""

    snapshot: str = '- heading "Docs" [ref=e1]\n- textbox "Password" [ref=e2]'
    title: str = "Docs"
    subresources: tuple[str, ...] = ()
    passwords: tuple[str, ...] = ()
    element_origins: dict[str, str] = field(default_factory=dict)
    submit_to: str | None = None  # where Enter posts the filled fields
    echo_filled: bool = False  # the page writes what was typed back into its text
    raise_on: dict[str, Exception] = field(default_factory=dict)


class FakePage:
    def __init__(self, world: World, serve) -> None:
        self.world = world
        self.serve = serve
        self._url = "about:blank"
        self.filled: dict[str, str] = {}

    def _maybe_raise(self, name: str) -> None:
        if name in self.world.raise_on:
            raise self.world.raise_on[name]

    def url(self) -> str:
        return self._url

    async def title(self) -> str:
        return self.world.title + (" " + " ".join(self.filled.values()) if self.world.echo_filled else "")

    async def goto(self, url: str, *, timeout_ms: float):
        self._maybe_raise("goto")
        served = await self.serve(InterceptedRequest(url, "GET"))
        if served is None:
            raise BrowserActionError("failed")
        self._url = url
        for sub in self.world.subresources:
            await self.serve(InterceptedRequest(sub, "GET"))
        return served.status

    async def snapshot(self, *, timeout_ms: float) -> str:
        self._maybe_raise("snapshot")
        text = self.world.snapshot
        if self.world.echo_filled:
            text += "".join(f"\n- text: {value}" for value in self.filled.values())
        return text

    async def password_values(self) -> tuple[str, ...]:
        return self.world.passwords

    async def element_origin(self, ref: str, *, timeout_ms: float) -> str:
        from neos.coding.browser.egress import request_origin

        return self.world.element_origins.get(ref) or request_origin(self._url) or ""

    async def click(self, ref: str, *, timeout_ms: float) -> None:
        self._maybe_raise("click")

    async def fill(self, ref: str, value: str, *, timeout_ms: float) -> None:
        self.filled[ref] = value

    async def press_enter(self, ref: str, *, timeout_ms: float) -> None:
        if self.world.submit_to:
            body = "&".join(f"{k}={v}" for k, v in self.filled.items()).encode()
            await self.serve(InterceptedRequest(self.world.submit_to, "POST", {}, body))


class FakeContext:
    def __init__(self, world: World, serve) -> None:
        self.page = FakePage(world, serve)
        self.closed = False

    async def open_page(self):
        return self.page

    async def close(self) -> None:
        self.closed = True


class FakeDriver:
    confidential_channel = True  # the host driver's value (Q14c MB4)

    def __init__(self, world: World | None = None, *, fail: bool = False) -> None:
        self.world = world or World()
        self.contexts: list[FakeContext] = []
        self.fail = fail

    async def new_context(self, serve, *, task_id: str = ""):
        if self.fail:
            raise RuntimeError("no chromium")
        context = FakeContext(self.world, serve)
        self.contexts.append(context)
        return context

    async def aclose(self) -> None:
        return None


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@dataclass
class Fetcher:
    """Stands in for `fetch_one_hop`: records what the host sent out."""

    sent: list[InterceptedRequest] = field(default_factory=list)

    def __call__(self, request, *, timeout_sec, max_response_bytes):
        self.sent.append(request)
        return ServedResponse(200, {"content-type": "text/html"}, b"<html></html>")


def _resolve(monkeypatch, mapping: dict[str, str] | None = None, default: str = "93.184.216.34"):
    mapping = mapping or {}

    def fake_getaddrinfo(host, port, *args, **kwargs):
        ip = mapping.get(host, default)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]

    monkeypatch.setattr("neos.coding.tools.executor.socket.getaddrinfo", fake_getaddrinfo)


def _sessions(driver=None, *, clock=None, fetcher=None, **limits):
    return BrowserSessions(
        driver or FakeDriver(),
        BrowserLimits(**limits),
        allowlist=lambda: HOSTS,
        fetch=fetcher or Fetcher(),
        clock=clock or Clock(),
    )


def _enable(monkeypatch) -> None:
    def enabled(name: str) -> bool:
        return name in BROWSER_TOOL_NAMES

    monkeypatch.setattr("neos.coding.tools.registry.optional_tool_enabled", enabled)


def _registry(*, broker: bool = True) -> CodingToolRegistry:
    return CodingToolRegistry.default(command_allowlist=frozenset({"git"}), secret_env_refs=broker)


def _browse(registry, **input):
    return registry.validate(BROWSER_TOOL, input)


def _fill(registry, ref="e2", secret="secret://site", origin="https://login.example.com", **extra):
    return registry.validate(
        BROWSER_SECRET_TOOL, {"ref": ref, "secret": secret, "origin": origin, **extra}
    )


async def _vault(value: str = PASSWORD, origins=("https://login.example.com",)):
    store = InMemorySecretStore()
    await store.put("alice", "site", env_name="SITE_PASSWORD", value=value, browser_origins=origins)

    async def lookup(names):
        return await store.resolve("alice", names)

    return lookup


class Workspace:
    sandbox_id = "sb_1"

    async def workspace_revision(self) -> int:
        return 1


async def _run(sessions, call, *, task="ct_1", secrets=None):
    return await SandboxToolExecutor(1 << 20, 10).execute(
        Workspace(), call, secrets=secrets, browser=sessions.bind(task)
    )


# -- W11: flag off is today ----------------------------------------------------------


class _Before(CodingToolRegistry):
    """The registry as it was before Q14a -- the same specs minus the browser."""

    _TOOL_SPECS = tuple(
        tool for tool in CodingToolRegistry._TOOL_SPECS if tool.name not in BROWSER_TOOL_NAMES
    )


def _surface(registry) -> str:
    names = sorted({t.name for t in CodingToolRegistry._TOOL_SPECS})
    out = []
    for phase in ("explore", "plan", "implement", "verify"):
        for declare in (False, True):
            out.append(
                [d.__dict__ if hasattr(d, "__dict__") else repr(d) for d in registry.definitions(phase=phase, declare_deferred=declare)]
            )
        out.append([repr(d) for d in registry.definitions(phase=phase, revealed=frozenset(names))])
        out.append(type(registry).deferred_tool_names(phase=phase, subagent_enabled=True))
    for query in ("browser", "select:browser.v1,browser_fill_secret.v1", "+web fetch", "secret"):
        out.append(type(registry).search_definitions(query, subagent_enabled=True))
    out.append(sorted(registry._tools))
    return json.dumps(out, default=repr, sort_keys=True)


def test_flag_off_the_tool_surface_is_byte_identical() -> None:
    """W11. Mutation: drop the browser from `_OPTIONAL_TOOL_FLAGS` -> it becomes a
    deferred tool and shows up in the declared array and in search_tools.v1."""
    now = _registry()
    before = _Before.default(command_allowlist=frozenset({"git"}), secret_env_refs=True)

    assert _surface(now) == _surface(before)


@pytest.mark.parametrize("name", sorted(BROWSER_TOOL_NAMES))
def test_flag_off_the_names_are_unknown_exactly_as_before(name) -> None:
    """W11. Mutation: let validate report `policy_media_tool_disabled` -> a new reason."""
    with pytest.raises(ToolValidationError) as error:
        _registry().validate(name, {"action": "snapshot"})
    assert error.value.reason_code == "policy_unknown_tool"


def test_the_flag_is_read_per_call_not_only_at_construction(monkeypatch) -> None:
    """W11. Mutation: drop the per-call flag check in `validate` -> a registry built
    while on keeps validating browser calls after the flag goes off."""
    _enable(monkeypatch)
    registry = _registry()
    monkeypatch.setattr("neos.coding.tools.registry.optional_tool_enabled", lambda name: False)
    with pytest.raises(ToolValidationError) as error:
        _browse(registry, action="snapshot")
    assert error.value.reason_code == "policy_unknown_tool"


def test_flag_off_no_loop_or_prompt_reads_the_browser() -> None:
    """W11: the off loop passes no `browser` kwarg (fakes with old signatures keep
    working) and the event vocabulary has no browser kind."""
    import inspect

    from neos.coding.loop import durable

    source = inspect.getsource(durable.DurableCodingLoop._execute_validated)
    assert "if self._browser is not None and task_id" in source
    kinds = json.loads(open("tests/fixtures/coding_event_kinds.json").read())
    assert not any("browser" in json.dumps(kind) for kind in kinds)


def test_the_config_layer_names_the_same_tools() -> None:
    assert CODING_BROWSER_TOOL_NAMES == BROWSER_TOOL_NAMES


# -- W4: two tools, both COMMAND ---------------------------------------------------------


def test_flag_on_both_tools_are_advertised_as_command(monkeypatch) -> None:
    _enable(monkeypatch)
    registry = _registry()
    names = [d.name for d in registry.definitions()]

    assert BROWSER_TOOL in names and BROWSER_SECRET_TOOL in names
    assert BROWSER_TOOL not in registry.deferred_tool_names()
    assert _browse(registry, action="snapshot").risk is ToolRisk.COMMAND
    assert _fill(registry).risk is ToolRisk.COMMAND


@pytest.mark.parametrize(
    "input",
    [
        {"action": "navigate"},
        {"action": "navigate", "url": "https://docs.example.com", "ref": "e1"},
        {"action": "click"},
        {"action": "click", "ref": "e1", "text": "x"},
        {"action": "type", "ref": "e1"},
        {"action": "snapshot", "url": "https://docs.example.com"},
        {"action": "click", "ref": "button.submit"},  # refs only, no selectors
        {"action": "eval", "text": "1"},
    ],
)
def test_each_action_takes_only_its_fields(monkeypatch, input) -> None:
    _enable(monkeypatch)
    with pytest.raises(ToolValidationError) as error:
        _registry().validate(BROWSER_TOOL, input)
    assert error.value.reason_code == "policy_schema_invalid"


def test_a_secret_reference_cannot_be_typed_as_text(monkeypatch) -> None:
    _enable(monkeypatch)
    with pytest.raises(ToolValidationError) as error:
        _browse(_registry(), action="type", ref="e2", text="secret://site")
    assert error.value.reason_code == "policy_browser_use_fill_secret"


def test_fill_secret_needs_the_q6_broker_and_a_bare_origin(monkeypatch) -> None:
    """W7. Mutation: drop the broker check -> a fill with no vault validates."""
    _enable(monkeypatch)
    with pytest.raises(ToolValidationError) as error:
        _fill(_registry(broker=False))
    assert error.value.reason_code == "policy_browser_secret_disabled"

    assert _fill(_registry(), origin="https://Login.Example.com:443/").input["origin"] == (
        "https://login.example.com"
    )
    for origin in (
        "http://login.example.com",
        "https://login.example.com/path",
        "https://user@login.example.com",
        "https://login.example.com/?q=1",
    ):
        with pytest.raises(ToolValidationError):
            _fill(_registry(), origin=origin)
    with pytest.raises(ToolValidationError):
        _fill(_registry(), secret="site")


# -- W3 · W10: config fails closed -------------------------------------------------------


def _config(**browser):
    return {"browser": {"enabled": True, **browser}, "web_fetch_hosts": ["docs.example.com"]}


def test_outside_development_needs_the_operator_flag() -> None:
    """W3 (B2 not met). Mutation: drop the environment check -> production starts."""
    with pytest.raises(ValueError, match="B2"):
        AppConfig(environment="production", coding_model=_config())
    assert AppConfig(
        environment="production", coding_model=_config(allow_outside_development=True)
    ).coding_model.browser.enabled
    assert AppConfig(coding_model=_config()).coding_model.browser.enabled


@pytest.mark.parametrize(
    "coding",
    [
        {"browser": {"enabled": True}},
        {"browser": {"enabled": True}, "web_fetch_hosts": ["10.0.0.1"]},
        {"browser": {"enabled": True}, "web_fetch_hosts": [".com"]},
        {"browser": {"enabled": True}, "web_fetch_hosts": ["*.example.com"]},
        {**_config(), "approval_allow_tools": ["browser.v1"]},
        {**_config(), "approval_always_allow": ["browser_fill_secret.v1"]},
        {"browser": {"enabled": True, "idle_timeout_sec": 600, "max_lifetime_sec": 300},
         "web_fetch_hosts": ["docs.example.com"]},
    ],
)
def test_bad_browser_configs_do_not_start(coding) -> None:
    with pytest.raises(ValueError):
        AppConfig(coding_model=coding)


def test_the_factory_rechecks_the_environment() -> None:
    """W3: a config built around validation still does not open outside development."""
    assert build_browser_sessions(AppConfig()) is None
    unchecked = AppConfig.model_construct(
        environment="production", coding_model=AppConfig(coding_model=_config()).coding_model
    )
    with pytest.raises(ValueError):
        build_browser_sessions(unchecked)


# -- W4 · W7: the gate --------------------------------------------------------------------


def test_background_refuses_every_browser_call_even_when_allowed(monkeypatch) -> None:
    """W4 (Q1 ceiling). Mutation: register browser.v1 as READ_ONLY -> background runs it."""
    _enable(monkeypatch)
    registry = _registry()
    allow = UserApprovalRule("ur_1", UserRuleEffect.ALLOW, BROWSER_TOOL)
    gate = ApprovalGate(
        read_only_ceiling=True,
        allow_tools=frozenset({BROWSER_TOOL}),
        user_rules=(allow,),
        secret_broker=True,
    )
    for call in (_browse(registry, action="snapshot"), _fill(registry)):
        assert evaluate_approval(call, gate) is ApprovalPolicyOutcome.DENY
        assert policy_denial_reason(call, gate) == "policy_mode_ceiling"


def test_browsing_needs_approval_by_default_and_an_owner_rule_lifts_it(monkeypatch) -> None:
    _enable(monkeypatch)
    call = _browse(_registry(), action="navigate", url="https://docs.example.com/")
    allow = UserApprovalRule("ur_1", UserRuleEffect.ALLOW, BROWSER_TOOL)
    block = UserApprovalRule("ur_2", UserRuleEffect.BLOCK, BROWSER_TOOL)

    assert evaluate_approval(call, ApprovalGate()) is ApprovalPolicyOutcome.REQUIRE_APPROVAL
    assert evaluate_approval(call, ApprovalGate(user_rules=(allow,))) is ApprovalPolicyOutcome.ALLOW
    assert (
        evaluate_approval(call, ApprovalGate(user_rules=(allow, block)))
        is ApprovalPolicyOutcome.DENY
    )


@pytest.mark.parametrize(
    "gate",
    [
        ApprovalGate(secret_broker=True, allow_tools=frozenset({BROWSER_SECRET_TOOL})),
        ApprovalGate(secret_broker=True, approved_always=frozenset({BROWSER_SECRET_TOOL})),
        ApprovalGate(
            secret_broker=True,
            mode=ApprovalMode.AUTO,
            always_allow=frozenset({BROWSER_SECRET_TOOL}),
        ),
        # an allow rule on browsing is not an allow rule on secrets (why there are two tools)
        ApprovalGate(
            secret_broker=True,
            user_rules=(UserApprovalRule("ur_1", UserRuleEffect.ALLOW, BROWSER_TOOL),),
        ),
    ],
    ids=["operator-allow", "remembered", "auto-mode", "browse-rule"],
)
def test_a_login_needs_a_person_or_the_owners_rule_for_logins(monkeypatch, gate) -> None:
    """W7 = Q6 S7 reused. Mutation: drop the browser branch from `carries_secret_refs`
    -> the operator allow list runs a login nobody approved."""
    _enable(monkeypatch)
    call = _fill(_registry())

    assert carries_secret_refs(call)
    assert evaluate_approval(call, gate) is ApprovalPolicyOutcome.REQUIRE_APPROVAL


def test_the_owners_login_rule_lifts_it_and_unattended_is_refused_by_name(monkeypatch) -> None:
    _enable(monkeypatch)
    call = _fill(_registry())
    rule = UserApprovalRule("ur_1", UserRuleEffect.ALLOW, BROWSER_SECRET_TOOL)

    assert (
        evaluate_approval(call, ApprovalGate(secret_broker=True, user_rules=(rule,)))
        is ApprovalPolicyOutcome.ALLOW
    )
    unattended = ApprovalGate(secret_broker=True, unattended=True)
    assert evaluate_approval(call, unattended) is ApprovalPolicyOutcome.DENY
    assert policy_denial_reason(call, unattended) == "policy_secret_ref_unapproved"


def test_the_approval_card_shows_where_and_which_reference(monkeypatch) -> None:
    _enable(monkeypatch)
    summary = approval_display_summary(_fill(_registry(), submit=True))
    assert summary["origin"] == "https://login.example.com"
    assert summary["secret_ref"] == "secret://site"
    navigate = approval_display_summary(
        _browse(_registry(), action="navigate", url="https://docs.example.com/a")
    )
    assert navigate["url"] == "https://docs.example.com/a"


# -- W2: every request passes the web_fetch guard -------------------------------------------


@pytest.mark.asyncio
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
async def test_subresources_go_through_the_same_guard(monkeypatch, url, reason) -> None:
    """W2. Mutation: skip `_web_fetch_safety_reason` in `egress_refusal` -> the private
    subresource is fetched."""
    _enable(monkeypatch)
    _resolve(monkeypatch, {"internal.example.org": "10.0.0.7"})
    fetcher = Fetcher()
    sessions = _sessions(FakeDriver(World(subresources=(url,))), fetcher=fetcher)

    result = await _run(sessions, _browse(_registry(), action="navigate", url="https://docs.example.com/"))

    assert result.status == "ok"
    assert [r.url for r in fetcher.sent] == ["https://docs.example.com/"]
    assert result.entries[0]["blocked_requests"] == {reason: 1}


@pytest.mark.asyncio
async def test_a_redirect_target_is_judged_again(monkeypatch) -> None:
    """W2: the host never follows a redirect; the browser's next request comes back here."""
    _resolve(monkeypatch, {"docs.example.com": "93.184.216.34", "evil.example.org": "127.0.0.1"})
    sessions = _sessions()
    serve = sessions._server({"session": None})
    assert await serve(InterceptedRequest("https://evil.example.org/", "GET")) is None

    import neos.coding.browser.egress as egress

    class Opened:
        status = 302
        headers = {"Location": "https://evil.example.org/"}

    calls = []

    class Opener:
        def open(self, request, timeout):
            calls.append(request.full_url)
            import urllib.error
            from email.message import Message

            message = Message()
            message["Location"] = "https://evil.example.org/"
            raise urllib.error.HTTPError(request.full_url, 302, "Found", message, None)

    monkeypatch.setattr(egress.urllib.request, "build_opener", lambda *handlers: Opener())
    served = fetch_one_hop(
        InterceptedRequest("https://docs.example.com/", "GET"), timeout_sec=1, max_response_bytes=10
    )
    assert served.status == 302 and served.headers["location"] == "https://evil.example.org/"
    assert calls == ["https://docs.example.com/"]


def test_the_fetch_pins_a_public_address_or_refuses(monkeypatch) -> None:
    _resolve(monkeypatch, default="10.1.2.3")
    with pytest.raises(EgressRefused) as error:
        fetch_one_hop(
            InterceptedRequest("https://docs.example.com/", "GET"),
            timeout_sec=1,
            max_response_bytes=10,
        )
    assert error.value.reason == "web_fetch_ssrf"


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["PUT", "DELETE", "PATCH"])
async def test_methods_beyond_get_head_post_are_refused(monkeypatch, method) -> None:
    _resolve(monkeypatch)
    sessions = _sessions()
    _enable(monkeypatch)
    await _run(sessions, _browse(_registry(), action="navigate", url="https://docs.example.com/"))
    session = sessions._sessions["ct_1"]
    serve = sessions._server({"session": session})
    assert await serve(InterceptedRequest("https://docs.example.com/api", method)) is None
    assert session.blocked["browser_method_denied"] == 1


@pytest.mark.asyncio
async def test_a_navigation_off_the_allowlist_is_a_named_denial(monkeypatch) -> None:
    _enable(monkeypatch)
    _resolve(monkeypatch)
    driver = FakeDriver()
    result = await _run(_sessions(driver), _browse(_registry(), action="navigate", url="https://evil.test/"))

    assert (result.status, result.reason_code) == ("denied", "policy_web_fetch_host_denied")
    assert driver.contexts[0].page.url() == "about:blank"


# -- W7 · W8 · W9: login through Q6 and scrubbing ------------------------------------------------


async def _logged_in(monkeypatch, world: World, *, fetcher=None):
    _enable(monkeypatch)
    _resolve(monkeypatch)
    sessions = _sessions(FakeDriver(world), fetcher=fetcher)
    registry = _registry()
    await _run(sessions, _browse(registry, action="navigate", url="https://login.example.com/"))
    result = await _run(sessions, _fill(registry, submit=True), secrets=await _vault())
    return sessions, registry, result


@pytest.mark.asyncio
async def test_a_secret_is_typed_but_never_returned(monkeypatch) -> None:
    """W9. Mutation: drop `scrub.scrub_text` from the snapshot -> the echoed password
    reaches the tool result."""
    world = World(echo_filled=True, submit_to="https://login.example.com/session")
    fetcher = Fetcher()
    sessions, registry, result = await _logged_in(monkeypatch, world, fetcher=fetcher)

    page = sessions._sessions["ct_1"].page
    assert page.filled == {"e2": PASSWORD}
    assert result.status == "ok"
    assert PASSWORD not in json.dumps(result.to_mapping(), default=str)
    assert "<redacted:secret://site>" in result.entries[0]["text"]
    assert result.audit == {"secret_refs": ["site"]}
    # the same-origin form post carried it out -- that is the login
    assert PASSWORD in fetcher.sent[-1].body.decode()
    later = await _run(sessions, _browse(registry, action="snapshot"))
    assert PASSWORD not in json.dumps(later.to_mapping(), default=str)


@pytest.mark.asyncio
async def test_password_fields_are_masked_even_when_not_ours(monkeypatch) -> None:
    _enable(monkeypatch)
    _resolve(monkeypatch)
    world = World(snapshot='- textbox "Password": s3cr3t-value [ref=e2]', passwords=("s3cr3t-value",))
    result = await _run(_sessions(FakeDriver(world)), _browse(_registry(), action="navigate", url="https://docs.example.com/"))

    assert "s3cr3t-value" not in result.entries[0]["text"]
    assert "<masked:password>" in result.entries[0]["text"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url, body",
    [
        ("https://docs.example.com/collect", PASSWORD.encode()),
        ("https://docs.example.com/collect?p=" + PASSWORD, None),
        ("https://docs.example.com/c", ("p=" + PASSWORD.replace("-", "%2D")).encode()),
        ("https://docs.example.com/c", json.dumps({"p": PASSWORD}).encode()),
    ],
)
async def test_a_typed_secret_cannot_leave_for_another_origin(monkeypatch, url, body) -> None:
    """W8. Mutation: drop `carries_secret_elsewhere` -> page script ships the password to
    another allowlisted host."""
    sessions, _registry_, _ = await _logged_in(monkeypatch, World())
    session = sessions._sessions["ct_1"]
    serve = sessions._server({"session": session})

    assert await serve(InterceptedRequest(url, "POST", {}, body)) is None
    assert session.blocked["browser_secret_egress_denied"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "world, origin, reason",
    [
        (World(), "https://docs.example.com", "browser_secret_origin_mismatch"),
        (
            # the field claims the origin, the page is elsewhere -- the page decides too
            World(element_origins={"e2": "https://docs.example.com"}),
            "https://docs.example.com",
            "browser_secret_origin_mismatch",
        ),
        (
            World(element_origins={"e2": "https://docs.example.com"}),  # a framed field
            "https://login.example.com",
            "browser_secret_origin_mismatch",
        ),
    ],
)
async def test_a_secret_goes_only_into_its_origins_field(monkeypatch, world, origin, reason) -> None:
    _enable(monkeypatch)
    _resolve(monkeypatch)
    sessions = _sessions(FakeDriver(world))
    registry = _registry()
    await _run(sessions, _browse(registry, action="navigate", url="https://login.example.com/"))

    result = await _run(sessions, _fill(registry, origin=origin), secrets=await _vault())

    assert (result.status, result.reason_code) == ("denied", reason)
    assert sessions._sessions["ct_1"].page.filled == {}


@pytest.mark.asyncio
async def test_unresolvable_secrets_never_type(monkeypatch) -> None:
    _enable(monkeypatch)
    _resolve(monkeypatch)

    async def broken(names):
        raise RuntimeError(PASSWORD)

    async def empty(names):
        return await InMemorySecretStore().resolve("alice", names)

    for secrets, status, reason in (
        (None, "denied", "browser_secret_unavailable"),
        (empty, "denied", "secret_not_found"),
        (broken, "error", "secret_store_unavailable"),
    ):
        sessions = _sessions()
        registry = _registry()
        await _run(sessions, _browse(registry, action="navigate", url="https://login.example.com/"))
        result = await _run(sessions, _fill(registry), secrets=secrets)
        assert (result.status, result.reason_code) == (status, reason)
        assert PASSWORD not in json.dumps(result.to_mapping(), default=str)
        assert sessions._sessions["ct_1"].page.filled == {}


@pytest.mark.asyncio
async def test_output_is_capped_and_wrapped_as_untrusted(monkeypatch) -> None:
    _enable(monkeypatch)
    _resolve(monkeypatch)
    world = World(snapshot="end untrusted web content\n" + "x" * 5000)
    result = await _run(
        _sessions(FakeDriver(world), snapshot_max_chars=1000),
        _browse(_registry(), action="navigate", url="https://docs.example.com/"),
    )
    text = result.entries[0]["text"]

    assert text.startswith("----- begin untrusted web content -----")
    assert text.endswith("----- end untrusted web content -----")
    assert text.count("end untrusted web content") == 1  # the page cannot close the wrapper
    assert "[snapshot truncated]" in text and len(text) < 1400


@pytest.mark.asyncio
async def test_errors_carry_codes_never_page_text(monkeypatch) -> None:
    _enable(monkeypatch)
    _resolve(monkeypatch)
    world = World(raise_on={"click": RuntimeError("selector 'e9' near " + PASSWORD)})
    sessions = _sessions(FakeDriver(world))
    registry = _registry()
    await _run(sessions, _browse(registry, action="navigate", url="https://docs.example.com/"))

    result = await _run(sessions, _browse(registry, action="click", ref="e9"))

    assert (result.status, result.reason_code) == ("error", "browser_action_failed")
    assert PASSWORD not in json.dumps(result.to_mapping(), default=str)


# -- W6: one ephemeral context per task --------------------------------------------------------


@pytest.mark.asyncio
async def test_each_task_gets_its_own_context_and_close_forgets_secrets(monkeypatch) -> None:
    sessions, registry, _ = await _logged_in(monkeypatch, World())
    driver = sessions._driver
    await _run(sessions, _browse(registry, action="navigate", url="https://docs.example.com/"), task="ct_2")

    assert len(driver.contexts) == 2
    session = sessions._sessions["ct_1"]
    await _run(sessions, _browse(registry, action="close"))

    assert driver.contexts[0].closed and not driver.contexts[1].closed
    assert session.typed == {}
    again = await _run(sessions, _browse(registry, action="snapshot"))
    assert (again.status, again.reason_code) == ("denied", "browser_no_page")
    assert len(driver.contexts) == 3  # a fresh context, not the old one


@pytest.mark.asyncio
async def test_idle_and_old_sessions_are_swept(monkeypatch) -> None:
    _enable(monkeypatch)
    _resolve(monkeypatch)
    clock = Clock()
    driver = FakeDriver()
    sessions = _sessions(driver, clock=clock, idle_timeout_sec=60, max_lifetime_sec=600)
    registry = _registry()
    await _run(sessions, _browse(registry, action="navigate", url="https://docs.example.com/"))

    clock.now += 61
    await sessions.sweep()
    assert driver.contexts[0].closed and not sessions.is_open("ct_1")

    await _run(sessions, _browse(registry, action="navigate", url="https://docs.example.com/"))
    for _ in range(13):
        clock.now += 50
        await _run(sessions, _browse(registry, action="snapshot"))
    assert driver.contexts[1].closed  # lived past max_lifetime_sec while busy


@pytest.mark.asyncio
async def test_caps_on_contexts_navigations_and_requests(monkeypatch) -> None:
    _enable(monkeypatch)
    _resolve(monkeypatch)
    registry = _registry()
    sessions = _sessions(max_contexts=1, max_navigations=2)
    nav = _browse(registry, action="navigate", url="https://docs.example.com/")
    await _run(sessions, nav)
    await _run(sessions, nav)

    assert (await _run(sessions, nav)).reason_code == "browser_navigation_cap"
    assert (await _run(sessions, nav, task="ct_2")).reason_code == "browser_capacity"

    world = World(subresources=tuple(f"https://docs.example.com/{i}.js" for i in range(5)))
    capped = _sessions(FakeDriver(world), max_requests=3)
    result = await _run(capped, nav)
    assert result.entries[0]["blocked_requests"] == {"browser_request_cap": 3}


@pytest.mark.asyncio
async def test_no_browser_means_a_named_denial_not_a_fallback(monkeypatch) -> None:
    """W1: without Chromium (or without a bound handle) nothing else browses instead."""
    _enable(monkeypatch)
    call = _browse(_registry(), action="snapshot")

    unbound = await SandboxToolExecutor(4096, 10).execute(Workspace(), call)
    assert (unbound.status, unbound.reason_code) == ("denied", "browser_unavailable")
    broken = await _run(_sessions(FakeDriver(fail=True)), call)
    assert (broken.status, broken.reason_code) == ("error", "browser_unavailable")


# -- W12: never children, never the DA research path -------------------------------------------


def test_no_subagent_spec_can_name_a_browser_tool() -> None:
    """W12. Mutation: add browser.v1 to the explore spec -> a child is offered it."""
    from neos.subagent.catalog import _SPECS

    assert all(not (spec.allowed_tools & BROWSER_TOOL_NAMES) for spec in _SPECS.values())


@pytest.mark.asyncio
async def test_the_child_port_refuses_the_browser_even_when_on(monkeypatch) -> None:
    from types import SimpleNamespace

    from neos.coding.subagent_port import CodingToolPort, CodingToolPortError

    _enable(monkeypatch)
    port = CodingToolPort(registry=_registry(), executor=SandboxToolExecutor(4096, 10))
    for spec in ("explore", "implement"):
        view = port.for_ticket(SimpleNamespace(spec=spec, parent_id="ct_1"))
        assert all(d.name not in BROWSER_TOOL_NAMES for d in view.definitions())
        with pytest.raises(CodingToolPortError, match="tool_not_allowed"):
            await view.execute(BROWSER_TOOL, {"action": "snapshot"})


@pytest.mark.asyncio
async def test_the_da_research_port_cannot_expose_the_browser_even_when_on(monkeypatch) -> None:
    """W12 / dots §5 D6. Mutation: add browser.v1 to research_gate.CODING_TOOLS -> the
    research worker is offered a browser."""
    from neos.workflow.deep_analysis.research_gate import CODING_TOOLS
    from neos.workflow.deep_analysis.research_tools import CodingSurface, ResearchToolPort

    _enable(monkeypatch)

    async def authorize(validated):
        return validated, None

    port = ResearchToolPort(
        fetch_fn=None,
        store=None,
        sandbox=None,
        cap_bytes=1,
        coding=CodingSurface(
            registry=_registry(),
            executor=SandboxToolExecutor(4096, 10),
            session=Workspace(),
            authorize=authorize,
        ),
    )

    assert not CODING_TOOLS & BROWSER_TOOL_NAMES
    assert all(d.name not in BROWSER_TOOL_NAMES for d in port.definitions())
    for name in sorted(BROWSER_TOOL_NAMES):
        assert await port.execute(name, {"action": "snapshot"}) == {"error": "tool_not_allowed"}
