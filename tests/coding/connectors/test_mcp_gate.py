"""Q11a in the registry, the gate, the loop and the runtime.

The existing gate applies to connector tools **unchanged** (M4 · M7 · M11 · M12):
risk comes from the operator's declaration, a server credential is an S7 secret,
a child never calls one, and with the flag off nothing differs from today (M10).
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest

import neos.utils.anthropic_client as anthropic_client_module
from neos.coding import runtime as runtime_module
from neos.coding.application.user_rules import InMemoryUserRuleStore
from neos.coding.connectors.catalog import ConnectorCatalog, declare_tools
from neos.coding.connectors.runner import ConnectorRunner
from neos.coding.domain.approvals import (
    ApprovalGate,
    ApprovalMode,
    ApprovalPolicyOutcome,
    UserApprovalRule,
    UserRuleEffect,
    approval_display_summary,
    approval_event_display_summary,
    evaluate_approval,
    policy_denial_reason,
)
from neos.coding.prompts.builder import build_coding_system_prompt
from neos.coding.secrets import InMemorySecretStore
from neos.coding.tools.executor import SandboxToolExecutor
from neos.coding.tools.registry import CodingToolRegistry, ToolRisk, ToolValidationError
from neos.config.schema import AppConfig, CodingMcpConfig, CodingMcpServerConfig

pytestmark = pytest.mark.no_db

FAKE = str(Path(__file__).with_name("fake_mcp_server.py"))
TOKEN = "svc_live_0123456789abcdefghij"
SEARCH = "mcp__docs__search"
DELETE = "mcp__docs__delete_page"
WHOAMI = "mcp__docs__whoami"


def _server(**overrides) -> CodingMcpServerConfig:
    fields = {
        "name": "docs",
        "transport": "stdio",
        "command": [sys.executable, FAKE],
        "env": {"FAKE_MCP_MODE": "ok"},
        "tool_risks": {"search": "read_only", "delete_page": "command"},
    }
    fields.update(overrides)
    return CodingMcpServerConfig(**fields)


def _catalog(server=None) -> ConnectorCatalog:
    server = server or _server()
    listed = [
        {"name": "search", "inputSchema": {"type": "object"}},
        {"name": "delete_page", "inputSchema": {"type": "object"}},
        {"name": "whoami", "inputSchema": {"type": "object"}},
    ]
    return ConnectorCatalog(
        tools=declare_tools(server, listed, max_tools=64),
        servers={server.name: server},
        settings=CodingMcpConfig(enabled=True, servers=[server]),
    )


def _registry(catalog=None) -> CodingToolRegistry:
    return CodingToolRegistry.default(
        command_allowlist=frozenset({"pytest"}), secret_env_refs=True, connectors=catalog
    )


def _secret_catalog() -> ConnectorCatalog:
    return _catalog(
        _server(
            env={"FAKE_MCP_MODE": "ok", "FAKE_TOKEN": "secret://svc"},
            tool_risks={"whoami": "read_only"},
        )
    )


# -- M10: off is today ----------------------------------------------------------------


def test_flag_off_the_registry_is_todays() -> None:
    """M10. Off and "on with nothing declared" both offer exactly today's tools and prompt."""
    today = CodingToolRegistry.default(command_allowlist=frozenset({"pytest"}))
    empty = ConnectorCatalog(tools=(), servers={}, settings=CodingMcpConfig())

    for registry in (_registry(None), _registry(empty)):
        for kwargs in ({}, {"declare_deferred": True}, {"phase": "explore"}):
            assert registry.definitions(**kwargs) == today.definitions(**kwargs)
        assert build_coding_system_prompt(registry.definitions()) == build_coding_system_prompt(
            today.definitions()
        )
    with pytest.raises(ToolValidationError) as error:
        _registry(None).validate(SEARCH, {})
    assert error.value.reason_code == "policy_unknown_tool"


def test_flag_off_never_discovers(monkeypatch) -> None:
    """M10. Mutation: discover regardless of the flag -> a process spawns at every boot."""
    from neos.coding.connectors import catalog as catalog_module

    async def boom(*args, **kwargs):
        raise AssertionError("discovery ran with the flag off")

    monkeypatch.setattr(catalog_module, "discover_catalog", boom)
    config = AppConfig.model_validate({"coding_model": {"mcp": {"servers": [_server().model_dump()]}}})

    assert catalog_module.build_connector_catalog(config.coding_model) is None
    assert AppConfig().coding_model.mcp.enabled is False


def _runtime_config(mcp: dict | None) -> AppConfig:
    coding = {
        "enabled": True,
        "input_cost_micros_per_million": 1,
        "output_cost_micros_per_million": 1,
    }
    if mcp is not None:
        coding["mcp"] = mcp
    return AppConfig.model_validate(
        {
            "coding_model": coding,
            "sandbox": {"enabled": True},
            "secrets": {"anthropic_api_key": "test"},
        }
    )


def test_the_runtime_wires_one_catalog_into_registry_prompt_and_executor(monkeypatch) -> None:
    """Mutation: drop `connectors=` from the registry or the executor -> one side is blind."""
    monkeypatch.setattr(anthropic_client_module, "AsyncAnthropic", lambda **kwargs: object())

    off = runtime_module._prepare_real_coding_loop(config=_runtime_config(None))(object())
    on = runtime_module._prepare_real_coding_loop(
        config=_runtime_config({"enabled": True, "servers": [_server().model_dump()]})
    )(object())

    assert off._executor._connectors is None
    assert "mcp__" not in off._config.system
    names = [item.name for item in on._tools.definitions()]
    assert names[-2:] == [SEARCH, DELETE]
    assert names[:-2] == [item.name for item in off._tools.definitions()]
    assert f"- {SEARCH}: [MCP connector docs, risk read_only]" in on._config.system
    assert on._executor._connectors.tool(SEARCH) is not None


# -- M4: the declared risk is the risk the gate sees ---------------------------------


def test_validation_carries_the_declared_risk_and_the_server_refs() -> None:
    registry = _registry(_secret_catalog())

    call = registry.validate(WHOAMI, {})

    assert call.risk is ToolRisk.READ_ONLY
    assert call.secret_refs == ("svc",)
    with pytest.raises(ToolValidationError) as error:
        _registry(_catalog()).validate(WHOAMI, {})  # listed, never declared
    assert error.value.reason_code == "policy_unknown_tool"


def test_a_read_only_connector_runs_and_a_command_one_asks() -> None:
    registry = _registry(_catalog())

    assert evaluate_approval(registry.validate(SEARCH, {}), ApprovalGate()) is ApprovalPolicyOutcome.ALLOW
    assert (
        evaluate_approval(registry.validate(DELETE, {}), ApprovalGate())
        is ApprovalPolicyOutcome.REQUIRE_APPROVAL
    )


def test_background_sees_only_declared_read_only_connectors() -> None:
    """Q1 unchanged: the ceiling reads the declared risk."""
    registry = _registry(_catalog())
    gate = ApprovalGate(read_only_ceiling=True, unattended=True)

    assert evaluate_approval(registry.validate(SEARCH, {}), gate) is ApprovalPolicyOutcome.ALLOW
    delete = registry.validate(DELETE, {})
    assert evaluate_approval(delete, gate) is ApprovalPolicyOutcome.DENY
    assert policy_denial_reason(delete, gate) == "policy_mode_ceiling"


def test_owner_rules_name_connector_tools() -> None:
    """Q2 unchanged: a block wins over read-only; an allow lifts a command's approval."""
    registry = _registry(_catalog())
    block = UserApprovalRule("ur_1", UserRuleEffect.BLOCK, SEARCH)
    allow = UserApprovalRule("ur_2", UserRuleEffect.ALLOW, DELETE)

    search = registry.validate(SEARCH, {})
    assert evaluate_approval(search, ApprovalGate(user_rules=(block,))) is ApprovalPolicyOutcome.DENY
    assert (
        evaluate_approval(registry.validate(DELETE, {}), ApprovalGate(user_rules=(allow,)))
        is ApprovalPolicyOutcome.ALLOW
    )


# -- M7: a server credential is an S7 secret -----------------------------------------


@pytest.mark.parametrize(
    "gate",
    [
        ApprovalGate(secret_broker=True, allow_tools=frozenset({WHOAMI})),
        ApprovalGate(secret_broker=True, approved_always=frozenset({WHOAMI})),
        ApprovalGate(secret_broker=True, mode=ApprovalMode.AUTO, always_allow=frozenset({WHOAMI})),
        ApprovalGate(secret_broker=True),
    ],
    ids=["operator-allow", "remembered", "auto-mode", "read-only-default"],
)
def test_a_credentialed_connector_needs_a_person_even_when_read_only(gate) -> None:
    """M7. Mutation: drop `secret_refs` from `carries_secret_refs` -> READ_ONLY just runs."""
    call = _registry(_secret_catalog()).validate(WHOAMI, {})

    assert evaluate_approval(call, gate) is ApprovalPolicyOutcome.REQUIRE_APPROVAL


def test_the_owners_allow_lifts_it_and_unattended_has_its_own_reason() -> None:
    call = _registry(_secret_catalog()).validate(WHOAMI, {})
    allow = UserApprovalRule("ur_1", UserRuleEffect.ALLOW, WHOAMI)

    assert (
        evaluate_approval(call, ApprovalGate(secret_broker=True, user_rules=(allow,)))
        is ApprovalPolicyOutcome.ALLOW
    )
    gate = ApprovalGate(secret_broker=True, unattended=True)
    assert evaluate_approval(call, gate) is ApprovalPolicyOutcome.DENY
    assert policy_denial_reason(call, gate) == "policy_secret_ref_unapproved"


def test_the_approval_card_shows_arguments_and_secret_names_never_values() -> None:
    call = _registry(_secret_catalog()).validate(WHOAMI, {"q": "find me"})

    summary = approval_display_summary(call)

    assert summary["operation"] == WHOAMI
    assert '"q": "find me"' in summary["arguments"]
    assert summary["secret_refs"] == ["svc"]
    assert "arguments" not in approval_event_display_summary(summary)
    assert TOKEN not in repr(summary)


def test_a_credentialed_call_is_never_speculated() -> None:
    """Both speculative paths (batch, prefetch) share `speculation_safe`; neither has the vault.

    Mutation: drop `carries_secret_refs` from it -> the batch takes the call and the
    prefetch runs it without the owner's vault (the loop test below then goes red too).
    """
    from neos.coding.tools.orchestrator import partition_leading_readonly, speculation_safe

    plain = _registry(_catalog()).validate(SEARCH, {})
    credentialed = _registry(_secret_catalog()).validate(WHOAMI, {})

    assert speculation_safe(plain) is True
    assert speculation_safe(credentialed) is False
    batch, rest = partition_leading_readonly((plain, credentialed, plain))
    assert batch == (plain,) and rest == (credentialed, plain)


# -- the loop: vault bound to one call, nothing stored holds the value ----------------


from tests.coding.loop.test_anthropic_loop import (  # noqa: E402
    INPUT,
    Bindings,
    Session,
    completed,
    harness,
    tool_call,
)

OWNED = replace(INPUT, owner_id="alice", mode="autonomous")


async def _vault():
    store = InMemorySecretStore()
    await store.put("alice", "svc", env_name="FAKE_TOKEN", value=TOKEN)
    return store


def _loop(catalog, *, secrets, rules, calls):
    bindings = Bindings()
    session = Session()
    session.sandbox_id = "sb_1"
    bindings.session = session
    h = harness(
        [[tool_call("m1", WHOAMI, {}), completed()], [completed()]],
        executor=SandboxToolExecutor(65536, 10, connectors=ConnectorRunner(catalog)),
        bindings=bindings,
        approval_evaluator=evaluate_approval,
    )
    h.loop._tools = _registry(catalog)
    h.loop._secrets = secrets
    h.loop._user_rules = rules
    return h


@pytest.mark.asyncio
async def test_an_owner_allow_runs_the_connector_and_nothing_stored_holds_the_value() -> None:
    rules = InMemoryUserRuleStore()
    await rules.create("alice", effect="allow", tool=WHOAMI)
    h = _loop(_secret_catalog(), secrets=await _vault(), rules=rules, calls=[])

    events = [e async for e in h.loop.run(OWNED, None, h.deps)]

    assert [e.type for e in events if e.type == "tool.denied"] == []
    stored = repr(
        [c.loop_state for c in h.repository.checkpoints] + [e.payload for e in h.events.items]
    )
    assert "<redacted:secret://svc>" in stored  # the server echoed it; we scrubbed it
    assert TOKEN not in stored
    assert "untrusted_document" in stored


@pytest.mark.asyncio
async def test_unattended_without_a_rule_never_resolves_or_connects() -> None:
    class Counting(InMemorySecretStore):
        reads = 0

        async def resolve(self, user_id, names):
            Counting.reads += 1
            return await super().resolve(user_id, names)

    store = Counting()
    await store.put("alice", "svc", env_name="FAKE_TOKEN", value=TOKEN)
    h = _loop(_secret_catalog(), secrets=store, rules=InMemoryUserRuleStore(), calls=[])

    events = [e async for e in h.loop.run(OWNED, None, h.deps)]

    assert [e.payload.get("reason_code") for e in events if e.type == "tool.denied"] == [
        "policy_secret_ref_unapproved"
    ]
    assert Counting.reads == 0


# -- M11: children never call connectors ---------------------------------------------


def test_no_subagent_spec_lists_a_connector_tool() -> None:
    from neos.subagent.catalog import _SPECS

    assert _SPECS  # the table really was read
    for spec in _SPECS.values():
        assert not any(name.startswith("mcp__") for name in spec.allowed_tools), spec.name


@pytest.mark.asyncio
async def test_the_child_gate_refuses_a_connector_even_if_a_spec_lists_it(
    tmp_path: Path, monkeypatch
) -> None:
    """M11. Mutation: drop the CHILD-GATE name check -> the widened child runs the connector."""
    from neos.coding import subagent_port
    from neos.coding.subagent_port import CodingToolPort
    from neos.subagent.catalog import SpecRegistry, lookup_spec
    from neos.subagent.memory import InMemorySubagentStore
    from neos.subagent.ports import SystemClock
    from neos.subagent.runtime import SubagentRuntime
    from neos.subagent.stepper import ChildStepper
    from tests.coding.loop.test_child_gate import _child_calls, _denials, _PortExecutor
    from tests.coding.loop.test_spawn_subagent import (
        ScriptedCodingModel,
        _flag_on,
        _init_repo,
        _NullSink,
        _text,
    )
    from tests.coding.loop.test_child_gate import _spawn

    def widened(name):
        spec = lookup_spec(name)
        return replace(spec, allowed_tools=spec.allowed_tools | {SEARCH})

    # Widen both lists the child passes before the gate: the stepper's and the port's.
    monkeypatch.setattr(subagent_port, "lookup_spec", widened)
    specs = SpecRegistry()
    specs.register(widened("explore"))
    executor = _PortExecutor()
    registry = _registry(_catalog())
    port = CodingToolPort(registry=registry, executor=executor)
    runtime = SubagentRuntime(
        store=InMemorySubagentStore(),
        catalog=specs,
        stepper=ChildStepper(
            model=ScriptedCodingModel([_child_calls(SEARCH, {}), _text("done")]),
            tools=port,
        ),
        events=_NullSink(),
        clock=SystemClock(),
    )
    h = harness(
        _spawn("explore"),
        config=_flag_on(approval_allow_tools=("spawn_agent.v1",)),
        subagents=runtime,
        bindings=Bindings(workspace=_init_repo(tmp_path)),
        approval_evaluator=evaluate_approval,
    )
    h.loop._tools = registry

    checkpoint = None
    for _ in range(6):
        events = [e async for e in h.loop.run(replace(OWNED, mode="interactive"), checkpoint, h.deps)]
        if any(e.type == "tool.completed" for e in events):
            break
        checkpoint = h.repository.checkpoints[-1]

    assert executor.calls == []
    assert [d.payload["reason_code"] for d in _denials(h)] == ["policy_connector_child"]
