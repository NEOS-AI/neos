"""Q6 in the loop: the owner's vault is bound to one executor call, never stored.

Real `evaluate_approval`, real `SandboxToolExecutor`. The plaintext must not
appear in any checkpoint or event; the transcript keeps the reference.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from neos.coding.application.user_rules import InMemoryUserRuleStore
from neos.coding.domain.approvals import evaluate_approval
from neos.coding.sandbox.base import CommandResult
from neos.coding.secrets import InMemorySecretStore
from neos.coding.tools.executor import SandboxToolExecutor
from neos.coding.tools.registry import CodingToolRegistry
from tests.coding.loop.test_anthropic_loop import (
    INPUT,
    Bindings,
    Session,
    completed,
    harness,
    tool_call,
)
from tests.coding.loop.test_child_gate import (
    _child_calls,
    _denials,
    _spawn,
)
from tests.coding.loop.test_spawn_subagent import _flag_on, _init_repo, _text

pytestmark = pytest.mark.no_db

TOKEN = "ghp_live_0123456789abcdefghij"
OWNED = replace(INPUT, owner_id="alice", mode="autonomous")
GH = {"argv": ["gh", "api", "user"], "env": {"GH_TOKEN": "secret://github"}}


class EchoSession(Session):
    """Prints the environment it was given -- the worst-case tool."""

    def __init__(self) -> None:
        super().__init__()
        self.requests = []
        self.sandbox_id = "sb_1"

    async def execute(self, request):
        self.requests.append(request)
        return CommandResult(0, f"token={request.secret_env.get('GH_TOKEN')}\n".encode(), b"")


async def _vault():
    store = InMemorySecretStore()
    await store.put("alice", "github", env_name="GH_TOKEN", value=TOKEN)
    return store


def _loop(secrets, rules, session):
    bindings = Bindings()
    bindings.session = session
    h = harness(
        [[tool_call("g1", "execute.v1", GH), completed()], [completed()]],
        executor=SandboxToolExecutor(4096, 10),
        bindings=bindings,
        approval_evaluator=evaluate_approval,
    )
    h.loop._tools = CodingToolRegistry.default(
        command_allowlist=frozenset({"gh"}), secret_env_refs=True
    )
    h.loop._secrets = secrets
    h.loop._user_rules = rules
    return h


async def _step(h, input, checkpoint=None):
    return [event async for event in h.loop.run(input, checkpoint, h.deps)]


def _everything_stored(h) -> str:
    return repr(
        [c.loop_state for c in h.repository.checkpoints]
        + [e.payload for e in h.events.items]
    )


@pytest.mark.asyncio
async def test_an_owner_allow_runs_it_and_nothing_stored_holds_the_value() -> None:
    rules = InMemoryUserRuleStore()
    await rules.create("alice", effect="allow", tool="execute.v1", argv_prefix=["gh"])
    session = EchoSession()
    h = _loop(await _vault(), rules, session)

    events = await _step(h, OWNED)

    assert [e.type for e in events if e.type == "tool.denied"] == []
    assert session.requests[0].secret_env == {"GH_TOKEN": TOKEN}
    stored = _everything_stored(h)
    assert TOKEN not in stored
    assert "secret://github" in stored


@pytest.mark.asyncio
async def test_unattended_without_a_rule_is_refused_before_the_vault_is_read() -> None:
    class Counting(InMemorySecretStore):
        reads = 0

        async def resolve(self, user_id, names):
            Counting.reads += 1
            return await super().resolve(user_id, names)

    store = Counting()
    await store.put("alice", "github", env_name="GH_TOKEN", value=TOKEN)
    session = EchoSession()
    h = _loop(store, InMemoryUserRuleStore(), session)

    events = await _step(h, OWNED)

    assert [e.payload.get("reason_code") for e in events if e.type == "tool.denied"] == [
        "policy_secret_ref_unapproved"
    ]
    assert session.requests == []
    assert Counting.reads == 0


@pytest.mark.asyncio
async def test_another_users_vault_is_not_this_tasks() -> None:
    rules = InMemoryUserRuleStore()
    await rules.create("bob", effect="allow", tool="execute.v1", argv_prefix=["gh"])
    store = InMemorySecretStore()
    await store.put("bob", "github", env_name="GH_TOKEN", value=TOKEN)
    session = EchoSession()
    h = _loop(store, rules, session)

    await _step(h, replace(OWNED, owner_id="bob"))
    assert session.requests[0].secret_env == {"GH_TOKEN": TOKEN}

    alice = EchoSession()
    h2 = _loop(store, rules, alice)
    events = await _step(h2, replace(OWNED, owner_id="alice"))
    assert alice.requests == []
    assert "policy_secret_ref_unapproved" in repr([e.payload for e in events])


@pytest.mark.asyncio
async def test_a_child_cannot_use_secrets_even_with_the_owners_allow(tmp_path: Path) -> None:
    """S8. Mutation: drop the child check -> the allow rule lets the child run it.

    `GH_PAT`, not `GH_TOKEN`: the subagent checkpoint already redacts `*_TOKEN`
    keys, so a `GH_TOKEN` reference reaches the child's validator as
    `<redacted>` and is refused there (closed, but not by this rule).
    """
    pat = {"argv": ["gh", "api", "user"], "env": {"GH_PAT": "secret://github"}}
    from neos.subagent.catalog import SpecRegistry
    from neos.subagent.memory import InMemorySubagentStore
    from neos.subagent.ports import SystemClock
    from neos.subagent.runtime import SubagentRuntime
    from neos.subagent.stepper import ChildStepper
    from neos.coding.subagent_port import CodingToolPort
    from tests.coding.loop.test_child_gate import _PortExecutor
    from tests.coding.loop.test_spawn_subagent import ScriptedCodingModel, _NullSink

    executor = _PortExecutor()
    port = CodingToolPort(
        registry=CodingToolRegistry.default(
            command_allowlist=frozenset({"gh"}), secret_env_refs=True
        ),
        executor=executor,
    )
    runtime = SubagentRuntime(
        store=InMemorySubagentStore(),
        catalog=SpecRegistry(),
        stepper=ChildStepper(
            model=ScriptedCodingModel([_child_calls("execute.v1", pat), _text("done")]),
            tools=port,
        ),
        events=_NullSink(),
        clock=SystemClock(),
    )
    rules = InMemoryUserRuleStore()
    await rules.create("alice", effect="allow", tool="execute.v1", argv_prefix=["gh"])
    h = harness(
        _spawn("implement"),
        config=_flag_on(approval_allow_tools=("spawn_agent.v1",)),
        subagents=runtime,
        bindings=Bindings(workspace=_init_repo(tmp_path)),
        approval_evaluator=evaluate_approval,
    )
    # One flag feeds both registries in production (`runtime.py`): the port's and the parent's.
    h.loop._tools = port._registry
    h.loop._secrets = await _vault()
    h.loop._user_rules = rules

    checkpoint = None
    for _ in range(6):
        events = [e async for e in h.loop.run(replace(OWNED, mode="interactive"), checkpoint, h.deps)]
        if any(e.type == "tool.completed" for e in events):
            break
        checkpoint = h.repository.checkpoints[-1]

    assert executor.calls == []
    assert [d.payload["reason_code"] for d in _denials(h)] == ["policy_secret_ref_child"]
