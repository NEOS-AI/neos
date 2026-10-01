"""Q14b: a stored secret is typed only into the browser origins its owner bound it to,
and a failed or cancelled task's browser session closes on that path, not by sweep.

docs/Q14_AGENT_BROWSER_DESIGN_261001.md §7 (X1..X7). The Postgres half of the vault
contract is `tests/coding/test_secret_store_origins.py`; it runs `origin_contract` too.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import neos.api.handlers.secret_handlers as handlers
from neos.api.dependencies.auth import get_current_user
from neos.coding.domain.approvals import adaptive_denial_reason
from neos.coding.domain.phases import CodingRunStatus
from neos.coding.loop.durable import DurableCodingLoop
from neos.coding.secrets import (
    MAX_BROWSER_ORIGINS,
    InMemorySecretStore,
    parse_browser_origins,
)
from tests.coding.application.test_run_service import (
    ModelCheckpointLoop,
    make_run_service,
    run_fixture,
)
from tests.coding.fakes import InMemoryCodingRunRepository
from tests.coding.test_agent_browser import (
    PASSWORD,
    FakeDriver,
    World,
    _browse,
    _enable,
    _fill,
    _registry,
    _resolve,
    _run,
    _sessions,
)

LOGIN = "https://login.example.com"
TOKEN = "ghp_live_0123456789abcdefghij"


# -- X1: the vault's shape -------------------------------------------------------------


@pytest.mark.no_db
def test_origins_take_the_tool_inputs_canonical_form() -> None:
    """X1: the same normaliser as `browser_fill_secret.v1`'s `origin`, so membership is
    string equality. Mutation: store the raw string -> `https://Login.Example.com:443/`
    never equals the tool's `https://login.example.com`."""
    assert parse_browser_origins(
        ["https://Login.Example.com:443/", LOGIN, "https://a.example.org:8443"]
    ) == ("https://a.example.org:8443", LOGIN)
    assert parse_browser_origins(None) == ()


@pytest.mark.no_db
@pytest.mark.parametrize(
    "origin",
    [
        "http://login.example.com",  # https only
        "https://login.example.com/path",
        "https://user@login.example.com",
        "https://10.0.0.1",  # an IP can never be an allowlisted host
        "https://*.example.com",
        "https://localhost",  # one label
        "login.example.com",
        "",
        7,
    ],
)
def test_origins_refuse_what_could_never_be_an_allowlisted_page(origin) -> None:
    with pytest.raises(ValueError) as error:
        parse_browser_origins([origin])
    assert "https origins" in str(error.value)


@pytest.mark.no_db
def test_at_most_eight_origins() -> None:
    many = [f"https://h{i}.example.com" for i in range(MAX_BROWSER_ORIGINS + 1)]
    assert len(parse_browser_origins(many[:-1])) == MAX_BROWSER_ORIGINS
    with pytest.raises(ValueError, match="at most"):
        parse_browser_origins(many)


async def origin_contract(store, alice: str, bob: str) -> None:
    """X1 · X2 · S3: both stores keep the same contract. Called by the Postgres test too."""
    plain = await store.put(alice, "site", env_name="SITE_PASSWORD", value=TOKEN)
    assert plain.browser_origins == ()
    assert (await store.resolve(alice, ["site"])).values["site"].browser_origins == ()

    bound = await store.put(
        alice,
        "site",
        env_name="SITE_PASSWORD",
        value=TOKEN,
        browser_origins=["https://Login.Example.com/", "https://a.example.org:8443"],
    )
    expected = ("https://a.example.org:8443", LOGIN)
    [listed] = await store.list_for_user(alice)
    resolved = (await store.resolve(alice, ["site"])).values["site"]
    assert bound.browser_origins == listed.browser_origins == expected
    # env_name (S3) is untouched -- execute.v1 and connectors read the same row
    assert (resolved.env_name, resolved.value, resolved.browser_origins) == (
        "SITE_PASSWORD",
        TOKEN,
        expected,
    )

    # the same name under another owner is that owner's own, unbound row
    await store.put(bob, "site", env_name="SITE_PASSWORD", value=TOKEN + "b")
    assert (await store.resolve(bob, ["site"])).values["site"].browser_origins == ()
    assert (await store.resolve(alice, ["site"])).values["site"].browser_origins == expected

    # X2: a PUT replaces the row -- leaving origins out unbinds it
    await store.put(alice, "site", env_name="SITE_PASSWORD", value=TOKEN)
    assert (await store.resolve(alice, ["site"])).values["site"].browser_origins == ()

    with pytest.raises(ValueError):
        await store.put(
            alice, "site", env_name="SITE_PASSWORD", value=TOKEN, browser_origins=["http://x.example.com"]
        )


@pytest.mark.no_db
async def test_the_memory_vault_keeps_the_origin_contract() -> None:
    await origin_contract(InMemorySecretStore(), "q14b_alice", "q14b_bob")


# -- X1: the browser refuses what the owner did not bind -------------------------------------


async def _lookup_for(store, owner):
    async def lookup(names):
        return await store.resolve(owner, names)

    return lookup


async def _fill_with(monkeypatch, origins, *, owner="alice", store=None):
    _enable(monkeypatch)
    _resolve(monkeypatch)
    if store is None:
        store = InMemorySecretStore()
        await store.put(owner, "site", env_name="SITE_PASSWORD", value=PASSWORD, browser_origins=origins)
    sessions = _sessions(FakeDriver(World()))
    registry = _registry()
    await _run(sessions, _browse(registry, action="navigate", url=LOGIN + "/"))
    result = await _run(sessions, _fill(registry, origin=LOGIN), secrets=await _lookup_for(store, owner))
    return sessions, result


@pytest.mark.no_db
async def test_an_unbound_secret_is_typed_nowhere(monkeypatch) -> None:
    """X1 fail closed: a 077-era row (no origins) is not fillable on any page -- even the
    allowlisted page the model names. Mutation: drop the binding check in
    `BrowserSessions._fill_secret` -> the password goes into the field."""
    sessions, result = await _fill_with(monkeypatch, ())

    assert (result.status, result.reason_code) == ("denied", "secret_origin_mismatch")
    session = sessions._sessions["ct_1"]
    assert session.page.filled == {} and session.typed == {}
    assert PASSWORD not in json.dumps(result.to_mapping(), default=str)
    assert "not allowed on this site" in adaptive_denial_reason("secret_origin_mismatch")


@pytest.mark.no_db
async def test_a_secret_bound_elsewhere_is_refused_here(monkeypatch) -> None:
    """X1. Mutation: only refuse an *empty* binding (`if not secret.browser_origins`) ->
    a secret bound to docs.example.com is typed into login.example.com."""
    sessions, result = await _fill_with(monkeypatch, ("https://docs.example.com",))

    assert (result.status, result.reason_code) == ("denied", "secret_origin_mismatch")
    assert sessions._sessions["ct_1"].page.filled == {}


@pytest.mark.no_db
async def test_a_secret_bound_here_is_typed(monkeypatch) -> None:
    sessions, result = await _fill_with(monkeypatch, ("https://docs.example.com", LOGIN))

    assert result.status == "ok", result
    assert sessions._sessions["ct_1"].page.filled == {"e2": PASSWORD}


@pytest.mark.no_db
async def test_another_owners_binding_does_not_open_mine(monkeypatch) -> None:
    """Cross-owner: alice bound `site` to the login origin; bob's task resolves bob's own
    unbound `site`. Mutation: let the memory vault return origins by name only (first
    owner's row) -> bob's task types bob's password where only alice allowed hers."""
    store = InMemorySecretStore()
    await store.put("alice", "site", env_name="SITE_PASSWORD", value=TOKEN, browser_origins=[LOGIN])
    await store.put("bob", "site", env_name="SITE_PASSWORD", value=PASSWORD)

    sessions, result = await _fill_with(monkeypatch, (), owner="bob", store=store)

    assert (result.status, result.reason_code) == ("denied", "secret_origin_mismatch")
    assert sessions._sessions["ct_1"].page.filled == {}


# -- X1 · X2: the vault API ------------------------------------------------------------------


@pytest.fixture
def api():
    store = InMemorySecretStore()
    app = FastAPI()
    app.include_router(handlers.router)
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(user_id="alice")
    app.dependency_overrides[handlers.get_secret_store] = lambda: store
    return TestClient(app), store


@pytest.mark.no_db
def test_the_api_takes_and_lists_origins_never_the_value(api) -> None:
    http, _store = api

    put = http.put(
        "/coding/secrets/site",
        json={"env_name": "SITE_PASSWORD", "value": TOKEN, "browser_origins": ["https://Login.Example.com"]},
    )
    listed = http.get("/coding/secrets")

    assert put.status_code == 200
    assert put.json()["browser_origins"] == [LOGIN]
    assert listed.json()[0]["browser_origins"] == [LOGIN]
    assert TOKEN not in put.text + listed.text


@pytest.mark.no_db
def test_the_api_put_without_origins_unbinds_and_a_bad_origin_is_422(api) -> None:
    """X2. Mutation: keep the stored origins when the body omits them -> a rotated value
    stays fillable where the owner's new PUT no longer says so."""
    http, _store = api
    http.put(
        "/coding/secrets/site",
        json={"env_name": "SITE_PASSWORD", "value": TOKEN, "browser_origins": [LOGIN]},
    )

    rotated = http.put("/coding/secrets/site", json={"env_name": "SITE_PASSWORD", "value": TOKEN + "2"})
    bad = http.put(
        "/coding/secrets/site",
        json={"env_name": "SITE_PASSWORD", "value": TOKEN, "browser_origins": ["https://10.0.0.1"]},
    )

    assert rotated.json()["browser_origins"] == []
    assert bad.status_code == 422 and TOKEN not in bad.text


# -- X5: failed and cancelled tasks close their session on that path -------------------------


class BrowserLoop(ModelCheckpointLoop):
    """The run-service fake loop with the real `DurableCodingLoop.close_task_browser`."""

    close_task_browser = DurableCodingLoop.close_task_browser

    def __init__(self, sessions) -> None:
        super().__init__()
        self._browser = sessions


async def _open_two(monkeypatch):
    _enable(monkeypatch)
    _resolve(monkeypatch)
    driver = FakeDriver(World())
    sessions = _sessions(driver)
    registry = _registry()
    for task in ("ct_1", "ct_2"):
        await _run(sessions, _browse(registry, action="navigate", url="https://docs.example.com/"), task=task)
    return sessions, driver


@pytest.mark.no_db
async def test_a_failed_task_closes_its_browser_now(monkeypatch) -> None:
    """X5. Mutation: drop `_close_task_browser` from `fail_active_run` -> the failed
    task's context (and its logged-in cookies) lives until the idle sweep."""
    sessions, driver = await _open_two(monkeypatch)
    repository = InMemoryCodingRunRepository(active_run=run_fixture("cr_1"), task_prompts={"ct_1": "Fix it"})
    repository.task_statuses["ct_1"] = "running"
    service = await make_run_service(repository, loop=BrowserLoop(sessions))

    event = await service.fail_active_run(task_id="ct_1", worker_id="w", error_code="model_output_incomplete")

    assert event.type == "run.failed"
    assert not sessions.is_open("ct_1") and driver.contexts[0].closed
    assert sessions.is_open("ct_2")  # only that task's


@pytest.mark.no_db
async def test_a_cancelled_task_closes_its_browser_now(monkeypatch) -> None:
    """X5. Mutation: drop `_close_task_browser` from `_cancel_active_run` -> a stopped
    task keeps its page open."""
    sessions, driver = await _open_two(monkeypatch)
    repository = InMemoryCodingRunRepository(active_run=run_fixture("cr_1"))
    repository.task_statuses["ct_1"] = "running"
    service = await make_run_service(repository, loop=BrowserLoop(sessions))

    await service.stop(task_id="ct_1", owner_id="u1")

    assert repository.active_run.status is CodingRunStatus.CANCELLED
    assert not sessions.is_open("ct_1") and driver.contexts[0].closed
    assert sessions.is_open("ct_2")


@pytest.mark.no_db
async def test_a_close_failure_does_not_stop_the_cancel() -> None:
    class Broken(ModelCheckpointLoop):
        async def close_task_browser(self, task_id):
            raise RuntimeError("driver gone")

    repository = InMemoryCodingRunRepository(active_run=run_fixture("cr_1"))
    repository.task_statuses["ct_1"] = "running"
    service = await make_run_service(repository, loop=Broken())

    await service.stop(task_id="ct_1", owner_id="u1")

    assert repository.active_run.status is CodingRunStatus.CANCELLED


# -- W11 extended: flag off --------------------------------------------------------------------


@pytest.mark.no_db
async def test_flag_off_the_terminal_hook_is_a_no_op() -> None:
    """W11/X7: with the browser off (`_browser is None`) the loop's hook does nothing, and a
    loop without the hook (older fakes) still fails and cancels exactly as before."""
    off = BrowserLoop(None)
    await off.close_task_browser("ct_1")

    repository = InMemoryCodingRunRepository(active_run=run_fixture("cr_1"), task_prompts={"ct_1": "Fix it"})
    repository.task_statuses["ct_1"] = "running"
    service = await make_run_service(repository, loop=ModelCheckpointLoop())
    event = await service.fail_active_run(task_id="ct_1", worker_id="w", error_code="x")
    assert event.type == "run.failed"


@pytest.mark.no_db
def test_flag_off_the_registry_and_execute_secrets_are_unchanged() -> None:
    """W11/X7: Q14b adds no tool, no validation reason and no input field; an unbound
    secret still resolves with its env_name for execute.v1 (S3)."""
    from neos.coding.tools.registry import _BrowserFillSecretInput

    assert set(_BrowserFillSecretInput.model_fields) == {"ref", "secret", "origin", "submit"}


@pytest.mark.no_db
async def test_an_unbound_secret_still_resolves_for_its_env_name() -> None:
    """X1: binding is browser-only (the Q6 execute and Q11 connector tests put unbound
    secrets and still pass). Mutation: refuse unbound secrets in `resolve` -> every
    077-era secret breaks for execute.v1 and the connectors."""
    store = InMemorySecretStore()
    await store.put("alice", "gh", env_name="GH_TOKEN", value=TOKEN)

    resolved = await store.resolve("alice", ["gh"])

    assert (resolved.values["gh"].env_name, resolved.values["gh"].value) == ("GH_TOKEN", TOKEN)

