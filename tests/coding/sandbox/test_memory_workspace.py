import sys
from pathlib import Path

import pytest

from neos.coding.sandbox.base import (
    CommandRequest,
    SandboxLimits,
    SandboxNotFound,
    SandboxPolicyViolation,
    SandboxState,
)
from neos.coding.sandbox.memory import MemorySandboxProvider


async def test_memory_session_reads_searches_and_executes(
    tmp_path: Path,
) -> None:
    provider = MemorySandboxProvider(root=tmp_path)
    sandbox = await provider.create(
        owner_id="u1",
        limits=SandboxLimits.safe_defaults(),
    )
    session = await provider.open_session(sandbox.sandbox_id)

    revision = await session.write_file(
        "src/app.py",
        b"print('needle')\n",
    )

    assert sandbox.state is SandboxState.RUNNING
    assert revision == 1
    assert await session.read_file("src/app.py") == b"print('needle')\n"
    matches = await session.search_text(
        "needle",
        paths=("src/**",),
        regex=False,
        limit=10,
    )
    assert [(match.path, match.line) for match in matches] == [
        ("src/app.py", 1)
    ]
    result = await session.execute(
        CommandRequest(argv=(sys.executable, "src/app.py"))
    )
    assert result.exit_code == 0
    assert result.stdout == b"needle\n"
    await provider.close()


async def test_memory_session_exposes_read_only_git_inspection(
    tmp_path: Path,
) -> None:
    provider = MemorySandboxProvider(root=tmp_path)
    sandbox = await provider.create(
        owner_id="u1",
        limits=SandboxLimits.safe_defaults(),
    )
    session = await provider.open_session(sandbox.sandbox_id)
    await session.execute(CommandRequest(argv=("git", "init", "-q")))
    await session.write_file("tracked.txt", b"content")

    status = await session.git_status()

    assert status.exit_code == 0
    assert b"tracked.txt" in status.stdout
    await provider.close()


async def test_memory_command_mutation_advances_revision(tmp_path: Path) -> None:
    provider = MemorySandboxProvider(root=tmp_path)
    sandbox = await provider.create(
        owner_id="u1",
        limits=SandboxLimits.safe_defaults(),
    )
    session = await provider.open_session(sandbox.sandbox_id)

    assert await session.workspace_revision() == 0
    result = await session.execute(
        CommandRequest(
            argv=(sys.executable, "-c", "open('generated.txt', 'w').write('x')")
        )
    )

    assert result.exit_code == 0
    assert await session.workspace_revision() == 1
    await provider.close()


async def test_memory_session_rejects_environment_outside_allowlist(
    tmp_path: Path,
) -> None:
    provider = MemorySandboxProvider(
        root=tmp_path,
        allowed_env_names=frozenset({"LANG"}),
    )
    sandbox = await provider.create(
        owner_id="u1",
        limits=SandboxLimits.safe_defaults(),
    )
    session = await provider.open_session(sandbox.sandbox_id)

    with pytest.raises(SandboxPolicyViolation, match="environment_not_allowed"):
        await session.execute(
            CommandRequest(argv=("env",), env={"TOKEN": "secret"})
        )
    await provider.close()


async def test_destroy_is_idempotent_and_removes_workspace(
    tmp_path: Path,
) -> None:
    provider = MemorySandboxProvider(root=tmp_path)
    sandbox = await provider.create(
        owner_id="u1",
        limits=SandboxLimits.safe_defaults(),
    )
    workspace = provider.workspace_path(sandbox.sandbox_id)

    await provider.destroy(sandbox.sandbox_id)
    await provider.destroy(sandbox.sandbox_id)

    assert not workspace.exists()
    with pytest.raises(SandboxNotFound):
        await provider.get(sandbox.sandbox_id)
