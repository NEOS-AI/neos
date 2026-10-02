"""Q6: the credential broker -- references, scrubbing, the gate and the sandbox boundary.

docs/Q6_CREDENTIAL_BROKER_DESIGN_261001.md. The decision each test pins is named
(S1..S9); the mutation it bites is in its docstring where it is not obvious.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from neos.coding.domain.approvals import (
    ApprovalGate,
    ApprovalMode,
    ApprovalPolicyOutcome,
    UserApprovalRule,
    UserRuleEffect,
    adaptive_denial_reason,
    evaluate_approval,
    policy_denial_reason,
)
from neos.coding.sandbox.base import (
    CommandRequest,
    CommandResult,
    SandboxLimits,
    SandboxPolicyViolation,
)
from neos.coding.secrets import (
    InMemorySecretStore,
    ResolvedSecret,
    ResolvedSecrets,
    SecretLimit,
    SecretNotFound,
    derive_secret_key,
    secret_env_refs,
    secret_ref_name,
)
from neos.coding.tools.executor import SandboxToolExecutor
from neos.coding.tools.registry import CodingToolRegistry, ToolValidationError

pytestmark = pytest.mark.no_db

TOKEN = "ghp_live_0123456789abcdefghij"


def _registry(*, on: bool, allow=frozenset({"gh", sys.executable.rsplit("/", 1)[-1]})):
    return CodingToolRegistry.default(
        command_allowlist=frozenset(allow),
        allowed_env_names=frozenset({"LANG"}),
        secret_env_refs=on,
    )


def _call(env, argv=("gh", "api", "user"), *, on=True):
    return _registry(on=on).validate("execute.v1", {"argv": list(argv), "env": env})


# -- references (S1 · S2) ------------------------------------------------------


def test_a_reference_is_the_whole_value_only() -> None:
    assert secret_ref_name("secret://github") == "github"
    assert secret_ref_name("token=secret://github") is None
    assert secret_ref_name("secret://GitHub") is None
    assert secret_ref_name("secret://") is None
    assert secret_ref_name(None) is None
    assert secret_env_refs({"GH_TOKEN": "secret://github", "LANG": "C"}) == {
        "GH_TOKEN": "github"
    }


# -- scrubbing (S6) --------------------------------------------------------------


def _resolved(**values: tuple[str, str]) -> ResolvedSecrets:
    return ResolvedSecrets(
        {name: ResolvedSecret(env, value) for name, (env, value) in values.items()}
    )


def test_scrub_replaces_the_value_itself_with_its_reference() -> None:
    resolved = _resolved(github=("GH_TOKEN", TOKEN))

    out = resolved.scrub_bytes(f"token {TOKEN} again {TOKEN}\n".encode())

    assert out == b"token <redacted:secret://github> again <redacted:secret://github>\n"


def test_scrub_catches_a_value_regex_rules_would_miss() -> None:
    """The exact value is known only here -- `redact.py` patterns know shapes."""
    odd = "correct-horse-battery-staple"
    out = _resolved(db=("DB_PASSWORD", odd)).scrub_text(f"pw={odd}")

    assert odd not in out


def test_a_truncated_tail_prefix_is_scrubbed_only_when_truncated() -> None:
    """Mutation: ignore `truncated` -> the first half of the token survives."""
    resolved = _resolved(github=("GH_TOKEN", TOKEN))
    cut = f"x {TOKEN[:12]}".encode()

    assert resolved.scrub_bytes(cut, truncated=True) == b"x <redacted:secret://github>"
    assert resolved.scrub_bytes(cut, truncated=False) == cut
    # Shorter than four characters is noise, not a secret prefix.
    assert resolved.scrub_bytes(b"x ghp", truncated=True) == b"x ghp"


def test_resolved_values_never_show_in_repr() -> None:
    resolved = _resolved(github=("GH_TOKEN", TOKEN))
    request = CommandRequest(argv=("gh",), secret_env={"GH_TOKEN": TOKEN})

    assert TOKEN not in repr(resolved)
    assert TOKEN not in repr(resolved.values["github"])
    assert TOKEN not in repr(request)


# -- the vault contract (memory; Postgres in test_secret_store.py) -----------------


@pytest.mark.asyncio
async def test_memory_vault_is_per_user_and_write_only() -> None:
    store = InMemorySecretStore(max_secrets=1)
    created = await store.put("alice", "github", env_name="GH_TOKEN", value=TOKEN)

    assert created.name == "github" and created.env_name == "GH_TOKEN"
    assert TOKEN not in repr(await store.list_for_user("alice"))
    assert (await store.resolve("alice", ["github"])).values["github"].value == TOKEN
    with pytest.raises(SecretNotFound):
        await store.resolve("bob", ["github"])
    # Replacing is not a second secret -- the limit counts names.
    await store.put("alice", "github", env_name="GH_TOKEN", value=TOKEN + "x")
    with pytest.raises(SecretLimit):
        await store.put("alice", "npm", env_name="NPM_TOKEN", value=TOKEN)
    assert await store.delete("bob", "github") is False
    assert await store.delete("alice", "github") is True


@pytest.mark.parametrize(
    ("name", "env_name", "value"),
    [
        ("GitHub", "GH_TOKEN", TOKEN),
        ("github", "LD_PRELOAD", TOKEN),
        ("github", "PATH", TOKEN),
        ("github", "gh_token", TOKEN),
        ("github", "GH_TOKEN", "short"),
    ],
)
@pytest.mark.asyncio
async def test_the_vault_refuses_bad_shapes(name, env_name, value) -> None:
    with pytest.raises(ValueError) as error:
        await InMemorySecretStore().put("alice", name, env_name=env_name, value=value)
    assert value not in str(error.value) or value == TOKEN


def test_key_derivation_needs_a_long_master() -> None:
    with pytest.raises(ValueError):
        derive_secret_key("short")
    assert len(derive_secret_key("k" * 32)) == 32
    assert derive_secret_key("k" * 32) != derive_secret_key("j" * 32)


# -- the validator (S3 · S9) -------------------------------------------------------


def test_flag_off_the_validator_is_unchanged() -> None:
    """S9: off, a non-allowlisted name is refused exactly as before."""
    with pytest.raises(ToolValidationError) as error:
        _call({"GH_TOKEN": "secret://github"}, on=False)
    assert error.value.reason_code == "policy_environment_name_denied"


def test_flag_on_only_a_reference_opens_a_new_name() -> None:
    assert _call({"GH_TOKEN": "secret://github"}).input["env"] == {
        "GH_TOKEN": "secret://github"
    }
    for env in (
        {"GH_TOKEN": TOKEN},  # a plain value still needs the allowlist
        {"LD_PRELOAD": "secret://github"},  # interpreted by the loader
        {"PATH": "secret://github"},  # set by the sandbox
    ):
        with pytest.raises(ToolValidationError):
            _call(env)


# -- the gate (S7) -----------------------------------------------------------------


def _gate(**kwargs) -> ApprovalGate:
    return ApprovalGate(secret_broker=True, **kwargs)


def _allow_gh() -> UserApprovalRule:
    return UserApprovalRule("ur_1", UserRuleEffect.ALLOW, "execute.v1", ("gh",))


def test_flag_off_the_gate_does_not_know_references() -> None:
    call = _call({"GH_TOKEN": "secret://github"})
    gate = ApprovalGate(allow_tools=frozenset({"execute.v1"}))

    assert evaluate_approval(call, gate) is ApprovalPolicyOutcome.ALLOW


@pytest.mark.parametrize(
    "gate",
    [
        _gate(allow_tools=frozenset({"execute.v1"})),
        _gate(approved_always=frozenset({"execute.v1"})),
        _gate(mode=ApprovalMode.AUTO, always_allow=frozenset({"execute.v1"})),
    ],
    ids=["operator-allow", "remembered", "auto-mode"],
)
def test_nothing_but_a_person_or_the_owner_lifts_a_reference(gate) -> None:
    """Mutation: move the secret check below the operator allow list -> ALLOW."""
    call = _call({"GH_TOKEN": "secret://github"})

    assert evaluate_approval(call, gate) is ApprovalPolicyOutcome.REQUIRE_APPROVAL


def test_the_owners_allow_rule_lifts_it_and_their_block_still_wins() -> None:
    call = _call({"GH_TOKEN": "secret://github"})
    block = UserApprovalRule("ur_2", UserRuleEffect.BLOCK, "execute.v1", ("gh",))

    assert evaluate_approval(call, _gate(user_rules=(_allow_gh(),))) is ApprovalPolicyOutcome.ALLOW
    assert (
        evaluate_approval(call, _gate(user_rules=(_allow_gh(), block)))
        is ApprovalPolicyOutcome.DENY
    )


def test_unattended_without_a_rule_is_refused_with_its_own_reason() -> None:
    call = _call({"GH_TOKEN": "secret://github"})
    gate = _gate(unattended=True)

    outcome = evaluate_approval(call, gate)  # folds for unattended itself

    assert outcome is ApprovalPolicyOutcome.DENY
    assert policy_denial_reason(call, gate) == "policy_secret_ref_unapproved"
    assert "allow rule" in adaptive_denial_reason("policy_secret_ref_unapproved")


def test_user_only_is_still_first() -> None:
    call = _call({"GH_TOKEN": "secret://github"}, argv=("gh", "auth", "login"))

    assert evaluate_approval(call, _gate(user_rules=(_allow_gh(),))) is ApprovalPolicyOutcome.DENY


# -- the executor (S1 · S2 · S3 · S6) ------------------------------------------------


@dataclass
class RecordingSession:
    stdout: bytes = b""
    raise_on_execute: Exception | None = None
    requests: list[CommandRequest] = field(default_factory=list)
    sandbox_id: str = "sb_1"

    async def execute(self, request: CommandRequest) -> CommandResult:
        self.requests.append(request)
        if self.raise_on_execute is not None:
            raise self.raise_on_execute
        return CommandResult(0, self.stdout, b"")

    async def workspace_revision(self) -> int:
        return 1


async def _vault(**secrets: tuple[str, str]):
    store = InMemorySecretStore()
    for name, (env, value) in secrets.items():
        await store.put("alice", name, env_name=env, value=value)

    async def lookup(names):
        return await store.resolve("alice", names)

    return lookup


@pytest.mark.asyncio
async def test_the_executor_resolves_into_secret_env_and_scrubs_output() -> None:
    session = RecordingSession(stdout=f"logged in with {TOKEN}\n".encode())
    call = _call({"GH_TOKEN": "secret://github", "LANG": "C"})
    lookup = await _vault(github=("GH_TOKEN", TOKEN))

    result = await SandboxToolExecutor(4096, 10).execute(session, call, secrets=lookup)

    [request] = session.requests
    assert request.secret_env == {"GH_TOKEN": TOKEN}
    assert request.env == {"LANG": "C"}
    assert call.input["env"]["GH_TOKEN"] == "secret://github"  # the ledger keeps the reference
    assert TOKEN not in str(result.to_mapping())
    assert "<redacted:secret://github>" in result.stdout["preview"]
    assert result.audit["secret_refs"] == ["github"]


@pytest.mark.asyncio
async def test_without_a_vault_the_reference_is_a_literal() -> None:
    """S9: off, the executor never resolves -- `secret://x` is just text."""
    session = RecordingSession()
    call = SandboxToolExecutor(4096, 10)
    validated = _registry(on=False).validate(
        "execute.v1", {"argv": ["gh"], "env": {}}
    )
    literal = type(validated)(
        validated.name, {**validated.input, "env": {"HOME": "secret://github"}}, validated.risk
    )

    await call.execute(session, literal)

    assert session.requests[0].env == {"HOME": "secret://github"}
    assert session.requests[0].secret_env == {}


@pytest.mark.parametrize(
    ("secrets", "status", "reason"),
    [
        ({}, "denied", "secret_not_found"),
        ({"github": ("GITHUB_TOKEN", TOKEN)}, "denied", "secret_env_name_mismatch"),
    ],
)
@pytest.mark.asyncio
async def test_unresolvable_references_never_run(secrets, status, reason) -> None:
    session = RecordingSession()
    lookup = await _vault(**secrets)

    result = await SandboxToolExecutor(4096, 10).execute(
        session, _call({"GH_TOKEN": "secret://github"}), secrets=lookup
    )

    assert (result.status, result.reason_code) == (status, reason)
    assert session.requests == []


@pytest.mark.asyncio
async def test_an_unreadable_vault_is_an_error_not_a_literal() -> None:
    async def down(names):
        raise ConnectionError("db down")

    session = RecordingSession()
    result = await SandboxToolExecutor(4096, 10).execute(
        session, _call({"GH_TOKEN": "secret://github"}), secrets=down
    )

    assert (result.status, result.reason_code) == ("error", "secret_store_unavailable")
    assert session.requests == []


@pytest.mark.asyncio
async def test_a_sandbox_that_cannot_carry_secrets_is_a_named_denial() -> None:
    session = RecordingSession(raise_on_execute=SandboxPolicyViolation("secret_env_unsupported"))
    lookup = await _vault(github=("GH_TOKEN", TOKEN))

    result = await SandboxToolExecutor(4096, 10).execute(
        session, _call({"GH_TOKEN": "secret://github"}), secrets=lookup
    )

    assert (result.status, result.reason_code) == ("denied", "secret_env_unsupported")


# -- the sandbox boundary ------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_sandbox_gives_the_process_the_secret_but_not_path(tmp_path: Path) -> None:
    from neos.coding.sandbox.memory import MemorySandboxProvider

    provider = MemorySandboxProvider(root=tmp_path)
    sandbox = await provider.create(owner_id="u1", limits=SandboxLimits.safe_defaults())
    session = await provider.open_session(sandbox.sandbox_id)
    await session.write_file(
        "show.py",
        b"import os\nprint(os.environ.get('GH_TOKEN'), os.environ['PATH'] == 'evil')\n",
    )

    result = await session.execute(
        CommandRequest(
            argv=(sys.executable, "show.py"),
            secret_env={"GH_TOKEN": TOKEN, "PATH": "evil"},
        )
    )

    assert result.stdout.decode().split() == [TOKEN, "False"]
    await provider.close()


@pytest.mark.asyncio
async def test_docker_puts_the_name_on_argv_and_the_value_in_the_cli_env() -> None:
    """The value must not reach `docker exec`'s argv -- the host `ps` shows it."""
    from datetime import UTC, datetime

    from tests.coding.sandbox.test_docker_provider import (
        DockerCommandResult,
        ScriptedDockerRunner,
        _config,
    )
    from neos.coding.sandbox.docker import DockerSandboxProvider

    class EnvRunner(ScriptedDockerRunner):
        def __init__(self) -> None:
            super().__init__()
            self.envs = []

        async def run(self, *args, timeout_sec, allowed_exit_codes=(0,), input=b"", env=None):
            self.envs.append(env)
            return await super().run(
                *args, timeout_sec=timeout_sec, allowed_exit_codes=allowed_exit_codes, input=input
            )

    runner = EnvRunner()
    provider = DockerSandboxProvider(
        runner=runner, config=_config(), clock=lambda: datetime(2026, 10, 1, tzinfo=UTC)
    )
    sandbox = await provider.create(owner_id="u1", limits=SandboxLimits.safe_defaults())
    session = await provider.open_session(sandbox.sandbox_id)
    runner.results.extend(
        [DockerCommandResult(0, b"{}", b""), DockerCommandResult(0, b"", b""), DockerCommandResult(0, b"{}", b"")]
    )

    await session.execute(CommandRequest(argv=("gh", "api"), secret_env={"GH_TOKEN": TOKEN}))

    exec_args = runner.calls[-2]
    assert ("--env", "GH_TOKEN") == exec_args[exec_args.index("GH_TOKEN") - 1 : exec_args.index("GH_TOKEN") + 1]
    assert not any(TOKEN in arg for arg in exec_args)
    assert runner.envs[-2] == {"GH_TOKEN": TOKEN}


@pytest.mark.asyncio
async def test_the_docker_cli_process_inherits_the_secret(monkeypatch) -> None:
    import asyncio

    import neos.coding.sandbox.command as command_mod

    seen = {}

    async def create_subprocess_exec(*args, **kwargs):
        seen.update(kwargs)
        raise FileNotFoundError("docker")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_subprocess_exec)
    with pytest.raises(FileNotFoundError):
        await command_mod._execute_docker("exec", timeout_sec=1, env={"GH_TOKEN": TOKEN})

    assert seen["env"]["GH_TOKEN"] == TOKEN
    assert "PATH" in seen["env"]  # the CLI still finds its own config
    seen.clear()
    with pytest.raises(FileNotFoundError):
        await command_mod._execute_docker("exec", timeout_sec=1)
    assert seen["env"] is None
