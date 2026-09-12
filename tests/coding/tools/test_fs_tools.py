from __future__ import annotations

import os
from pathlib import Path

import pytest

from neos.coding.domain.approvals import (
    ApprovalGate,
    ApprovalMode,
    ApprovalPolicyOutcome,
    evaluate_approval,
)
from neos.coding.phases import hidden_tools_for_phase
from neos.coding.sandbox.base import SandboxLimits
from neos.coding.sandbox.memory import MemorySandboxProvider
from neos.coding.tools.executor import SandboxToolExecutor
from neos.coding.tools.registry import CodingToolRegistry, ToolRisk

pytestmark = pytest.mark.no_db


def registry() -> CodingToolRegistry:
    return CodingToolRegistry.default(
        command_allowlist=frozenset({"pytest", "mkdir", "rm", "mv", "chmod"}),
        allowed_env_names=frozenset(),
    )


async def memory_session(tmp_path: Path):
    provider = MemorySandboxProvider(root=tmp_path)
    sandbox = await provider.create(
        owner_id="u1",
        limits=SandboxLimits.safe_defaults(),
    )
    session = await provider.open_session(sandbox.sandbox_id)
    return provider, session


def test_mkdir_is_workspace_write_and_parents_default_false() -> None:
    tools = registry()
    defaulted = tools.validate("mkdir.v1", {"path": "src/./pkg"})
    nested = tools.validate(
        "mkdir.v1", {"path": "src/pkg/nested", "parents": True}
    )
    denied = tools.decide(
        "mkdir.v1", {"path": "src/pkg", "parents": "sometimes"}
    )

    assert defaulted.risk is ToolRisk.WORKSPACE_WRITE
    assert defaulted.input == {"path": "src/pkg", "parents": False}
    assert nested.input["parents"] is True
    assert denied.allowed is False
    assert denied.reason_code == "policy_schema_invalid"


@pytest.mark.parametrize(
    ("path", "reason"),
    [
        ("../outside", "policy_workspace_path_"),
        (".git/hooks/x", "policy_protected_git_path"),
        (".env", "policy_secret_path_denied"),
        ("svc/.ENV", "policy_secret_path_denied"),
    ],
)
def test_mkdir_denies_escape_git_and_secret_paths(path: str, reason: str) -> None:
    decision = registry().decide("mkdir.v1", {"path": path})

    assert decision.allowed is False
    assert decision.reason_code.startswith(reason)


@pytest.mark.asyncio
async def test_mkdir_creates_directory_and_requires_parents(
    tmp_path: Path,
) -> None:
    provider, session = await memory_session(tmp_path)
    tools = registry()
    executor = SandboxToolExecutor(32, 10)

    missing = await executor.execute(
        session, tools.validate("mkdir.v1", {"path": "src/pkg"})
    )
    created = await executor.execute(
        session,
        tools.validate("mkdir.v1", {"path": "src/pkg", "parents": True}),
    )
    leaf = await executor.execute(
        session, tools.validate("mkdir.v1", {"path": "src/pkg/leaf"})
    )
    workspace = provider.workspace_path(session.sandbox_id)

    assert missing.status == "error"
    assert missing.reason_code == "workspace_path_not_resolvable"
    assert created.status == "ok"
    assert leaf.status == "ok"
    assert (workspace / "src" / "pkg" / "leaf").is_dir()
    await provider.close()


def test_rm_is_workspace_write_and_recursive_default_false() -> None:
    tools = registry()
    defaulted = tools.validate("rm.v1", {"path": "src/./gone.txt"})
    recursive = tools.validate(
        "rm.v1", {"path": "src/pkg", "recursive": True}
    )
    denied = tools.decide(
        "rm.v1", {"path": "src/pkg", "recursive": "sometimes"}
    )

    assert defaulted.risk is ToolRisk.WORKSPACE_WRITE
    assert defaulted.input == {"path": "src/gone.txt", "recursive": False}
    assert recursive.input["recursive"] is True
    assert denied.allowed is False
    assert denied.reason_code == "policy_schema_invalid"


@pytest.mark.parametrize(
    ("path", "reason"),
    [
        (".env", "policy_secret_path_denied"),
        ("svc/.ENV", "policy_secret_path_denied"),
        ("id_rsa", "policy_secret_path_denied"),
        ("../outside", "policy_workspace_path_"),
    ],
)
def test_rm_refuses_secret_and_escape_paths(path: str, reason: str) -> None:
    decision = registry().decide("rm.v1", {"path": path})

    assert decision.allowed is False
    assert decision.reason_code.startswith(reason)


@pytest.mark.asyncio
async def test_rm_refuses_non_empty_dir_unless_recursive(
    tmp_path: Path,
) -> None:
    provider, session = await memory_session(tmp_path)
    tools = registry()
    executor = SandboxToolExecutor(32, 10)
    workspace = provider.workspace_path(session.sandbox_id)
    await executor.execute(
        session,
        tools.validate("mkdir.v1", {"path": "src/pkg", "parents": True}),
    )
    (workspace / "src" / "pkg" / "a.txt").write_text("x", encoding="utf-8")
    (workspace / "src" / "file.txt").write_text("y", encoding="utf-8")

    nonempty = await executor.execute(
        session, tools.validate("rm.v1", {"path": "src/pkg"})
    )
    file_ok = await executor.execute(
        session, tools.validate("rm.v1", {"path": "src/file.txt"})
    )
    recursive = await executor.execute(
        session,
        tools.validate("rm.v1", {"path": "src/pkg", "recursive": True}),
    )

    assert nonempty.status == "denied"
    assert nonempty.reason_code == "workspace_directory_not_empty"
    assert file_ok.status == "ok"
    assert recursive.status == "ok"
    assert not (workspace / "src" / "file.txt").exists()
    assert not (workspace / "src" / "pkg").exists()
    await provider.close()


def test_mv_is_workspace_write_and_overwrite_default_false() -> None:
    tools = registry()
    defaulted = tools.validate("mv.v1", {"src": "src/./a.txt", "dest": "src/./b.txt"})
    over = tools.validate(
        "mv.v1",
        {"src": "a.txt", "dest": "b.txt", "overwrite": True},
    )
    denied = tools.decide(
        "mv.v1",
        {"src": "a.txt", "dest": "b.txt", "overwrite": "sometimes"},
    )

    assert defaulted.risk is ToolRisk.WORKSPACE_WRITE
    assert defaulted.input == {
        "src": "src/a.txt",
        "dest": "src/b.txt",
        "overwrite": False,
    }
    assert over.input["overwrite"] is True
    assert denied.allowed is False
    assert denied.reason_code == "policy_schema_invalid"


@pytest.mark.parametrize(
    ("src", "dest", "reason"),
    [
        (".env", "leaked.txt", "policy_secret_path_denied"),
        ("ok.txt", "svc/.ENV", "policy_secret_path_denied"),
        ("../outside", "ok.txt", "policy_workspace_path_"),
        ("ok.txt", "../outside", "policy_workspace_path_"),
        (".git/hooks/x", "ok.txt", "policy_protected_git_path"),
    ],
)
def test_mv_denies_secret_escape_and_git_paths(
    src: str, dest: str, reason: str
) -> None:
    decision = registry().decide("mv.v1", {"src": src, "dest": dest})

    assert decision.allowed is False
    assert decision.reason_code.startswith(reason)


@pytest.mark.asyncio
async def test_mv_refuses_existing_dest_unless_overwrite(
    tmp_path: Path,
) -> None:
    provider, session = await memory_session(tmp_path)
    tools = registry()
    executor = SandboxToolExecutor(32, 10)
    workspace = provider.workspace_path(session.sandbox_id)
    (workspace / "a.txt").write_text("aaa", encoding="utf-8")
    (workspace / "b.txt").write_text("bbb", encoding="utf-8")
    (workspace / "c.txt").write_text("ccc", encoding="utf-8")

    blocked = await executor.execute(
        session, tools.validate("mv.v1", {"src": "a.txt", "dest": "b.txt"})
    )
    moved = await executor.execute(
        session,
        tools.validate(
            "mv.v1", {"src": "c.txt", "dest": "d.txt"}
        ),
    )
    replaced = await executor.execute(
        session,
        tools.validate(
            "mv.v1",
            {"src": "a.txt", "dest": "b.txt", "overwrite": True},
        ),
    )

    assert blocked.status == "denied"
    assert blocked.reason_code == "workspace_path_exists"
    assert moved.status == "ok"
    assert replaced.status == "ok"
    assert (workspace / "b.txt").read_text(encoding="utf-8") == "aaa"
    assert not (workspace / "a.txt").exists()
    assert (workspace / "d.txt").read_text(encoding="utf-8") == "ccc"
    assert not (workspace / "c.txt").exists()
    await provider.close()


def test_chmod_is_workspace_write_and_numeric_mode_only() -> None:
    tools = registry()
    octal = tools.validate("chmod.v1", {"path": "src/./a.py", "mode": "644"})
    prefixed = tools.validate("chmod.v1", {"path": "a.py", "mode": "0755"})
    as_int = tools.validate("chmod.v1", {"path": "a.py", "mode": 0o600})
    symbolic = tools.decide("chmod.v1", {"path": "a.py", "mode": "u+w"})
    named = tools.decide("chmod.v1", {"path": "a.py", "mode": "rwxr-xr-x"})

    assert octal.risk is ToolRisk.WORKSPACE_WRITE
    assert octal.input == {"path": "src/a.py", "mode": 0o644}
    assert prefixed.input["mode"] == 0o755
    assert as_int.input["mode"] == 0o600
    assert symbolic.allowed is False
    assert symbolic.reason_code == "policy_schema_invalid"
    assert named.allowed is False
    assert named.reason_code == "policy_schema_invalid"


def test_chmod_refuses_world_writable_on_secrets() -> None:
    tools = registry()
    denied = tools.decide("chmod.v1", {"path": ".env", "mode": "666"})
    cased = tools.decide("chmod.v1", {"path": "svc/.ENV", "mode": "662"})
    private = tools.validate("chmod.v1", {"path": ".env", "mode": "600"})

    assert denied.allowed is False
    assert denied.reason_code == "policy_secret_path_denied"
    assert cased.allowed is False
    assert cased.reason_code == "policy_secret_path_denied"
    assert private.input["mode"] == 0o600


def test_chmod_instruction_files_require_existing_always_ask() -> None:
    tools = registry()
    call = tools.validate("chmod.v1", {"path": "AGENTS.md", "mode": "644"})
    gate = ApprovalGate(approved_always=frozenset({"chmod.v1"}))
    auto = ApprovalGate(
        mode=ApprovalMode.AUTO,
        always_allow=frozenset({"chmod.v1"}),
    )

    assert call.risk is ToolRisk.WORKSPACE_WRITE
    assert evaluate_approval(call) is ApprovalPolicyOutcome.REQUIRE_APPROVAL
    assert evaluate_approval(call, gate) is ApprovalPolicyOutcome.REQUIRE_APPROVAL
    assert evaluate_approval(call, auto) is ApprovalPolicyOutcome.REQUIRE_APPROVAL


@pytest.mark.asyncio
async def test_chmod_sets_numeric_mode(tmp_path: Path) -> None:
    provider, session = await memory_session(tmp_path)
    tools = registry()
    executor = SandboxToolExecutor(32, 10)
    workspace = provider.workspace_path(session.sandbox_id)
    target = workspace / "a.py"
    target.write_text("print(1)\n", encoding="utf-8")
    target.chmod(0o600)

    result = await executor.execute(
        session, tools.validate("chmod.v1", {"path": "a.py", "mode": "644"})
    )

    assert result.status == "ok"
    assert target.stat().st_mode & 0o777 == 0o644
    await provider.close()


def test_glob_files_accepts_optional_workspace_path() -> None:
    tools = registry()
    defaulted = tools.validate("glob_files.v1", {"pattern": "**/*.py"})
    scoped = tools.validate(
        "glob_files.v1", {"pattern": "*.py", "path": "src/./lib", "limit": 20}
    )
    escaped = tools.decide(
        "glob_files.v1", {"pattern": "*.py", "path": "../secret"}
    )

    assert defaulted.risk is ToolRisk.READ_ONLY
    assert defaulted.input["path"] is None
    assert defaulted.input["limit"] == 100
    assert scoped.input["path"] == "src/lib"
    assert scoped.input["limit"] == 20
    assert escaped.allowed is False
    assert escaped.reason_code.startswith("policy_workspace_path_")


@pytest.mark.asyncio
async def test_glob_files_sorts_mtime_desc_and_sets_truncated(
    tmp_path: Path,
) -> None:
    provider, session = await memory_session(tmp_path)
    tools = registry()
    executor = SandboxToolExecutor(32, 10)
    workspace = provider.workspace_path(session.sandbox_id)
    older = workspace / "older.py"
    newer = workspace / "newer.py"
    older.write_text("old\n", encoding="utf-8")
    newer.write_text("new\n", encoding="utf-8")
    os.utime(older, (1_700_000_000, 1_700_000_000))
    os.utime(newer, (1_800_000_000, 1_800_000_000))
    (workspace / "src").mkdir()
    (workspace / "src" / "only.txt").write_text("src\n", encoding="utf-8")

    newest = await executor.execute(
        session, tools.validate("glob_files.v1", {"pattern": "*.py"})
    )
    limited = await executor.execute(
        session,
        tools.validate("glob_files.v1", {"pattern": "*.py", "limit": 1}),
    )
    scoped = await executor.execute(
        session,
        tools.validate("glob_files.v1", {"pattern": "*.txt", "path": "src"}),
    )

    assert newest.status == "ok"
    assert [entry["path"] for entry in newest.entries] == ["newer.py", "older.py"]
    assert newest.truncated is False
    assert [entry["path"] for entry in limited.entries] == ["newer.py"]
    assert limited.truncated is True
    assert [entry["path"] for entry in scoped.entries] == ["src/only.txt"]
    assert scoped.truncated is False
    await provider.close()


@pytest.mark.parametrize("phase", ["explore", "plan", "verify"])
def test_fs_write_tools_hidden_like_other_writes(phase: str) -> None:
    hidden = hidden_tools_for_phase(phase)
    names = [item.name for item in registry().definitions(phase=phase)]

    for name in ("mkdir.v1", "rm.v1", "mv.v1", "chmod.v1", "write_file.v1"):
        assert name in hidden
        assert name not in names
    assert "glob_files.v1" in names


@pytest.mark.parametrize(
    ("argv", "tool", "denied"),
    [
        (["mkdir", "src/pkg"], "mkdir.v1", "mkdir"),
        (["rm", "src/gone.txt"], "rm.v1", "rm"),
        (["mv", "a.txt", "b.txt"], "mv.v1", "mv"),
        (["chmod", "644", "a.py"], "chmod.v1", "chmod"),
        (["env", "mkdir", "src/pkg"], "mkdir.v1", "mkdir"),
        (["env", "chmod", "755", "a.py"], "chmod.v1", "chmod"),
    ],
)
def test_execute_prefers_dedicated_fs_tools(
    argv: list[str], tool: str, denied: str
) -> None:
    decision = registry().decide("execute.v1", {"argv": argv})

    assert decision.allowed is False
    assert decision.reason_code == "policy_dedicated_tool_required"
    assert decision.fix_note is not None
    assert tool in decision.fix_note
    assert denied in decision.fix_note
