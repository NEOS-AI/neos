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
    assert matches[0].before == ()
    assert matches[0].after == ()
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


async def test_memory_search_text_includes_clamped_before_after_context(
    tmp_path: Path,
) -> None:
    provider = MemorySandboxProvider(root=tmp_path)
    sandbox = await provider.create(
        owner_id="u1",
        limits=SandboxLimits.safe_defaults(),
    )
    session = await provider.open_session(sandbox.sandbox_id)
    await session.write_file(
        "src/app.py",
        b"alpha\nbeta needle\ngamma\ndelta\n",
    )

    matches = await session.search_text(
        "needle",
        paths=("src/**",),
        before=1,
        after=2,
    )
    clamped = await session.search_text("needle", before=100, after=100)

    assert len(matches) == 1
    assert matches[0].path == "src/app.py"
    assert matches[0].line == 2
    assert matches[0].text == "beta needle"
    assert matches[0].before == ("alpha",)
    assert matches[0].after == ("gamma", "delta")
    assert clamped[0].before == ("alpha",)
    assert clamped[0].after == ("gamma", "delta")
    await provider.close()


async def test_memory_search_text_skips_git_directory(tmp_path: Path) -> None:
    provider = MemorySandboxProvider(root=tmp_path)
    sandbox = await provider.create(
        owner_id="u1",
        limits=SandboxLimits.safe_defaults(),
    )
    session = await provider.open_session(sandbox.sandbox_id)
    await session.write_file("src/app.py", b"print('needle')\n")
    git_dir = provider.workspace_path(sandbox.sandbox_id) / ".git"
    (git_dir / "objects").mkdir(parents=True)
    (git_dir / "HEAD").write_text("needle\n", encoding="utf-8")
    (git_dir / "objects" / "pack").write_text("needle\n", encoding="utf-8")

    matches = await session.search_text("needle")
    files = await session.search_text("needle", output_mode="files")
    counts = await session.search_text("needle", output_mode="count")

    assert [match.path for match in matches] == ["src/app.py"]
    assert [match.path for match in files] == ["src/app.py"]
    assert [(match.path, match.count) for match in counts] == [
        ("src/app.py", 1)
    ]
    await provider.close()


async def test_memory_search_text_files_and_count_modes(tmp_path: Path) -> None:
    provider = MemorySandboxProvider(root=tmp_path)
    sandbox = await provider.create(
        owner_id="u1",
        limits=SandboxLimits.safe_defaults(),
    )
    session = await provider.open_session(sandbox.sandbox_id)
    await session.write_file("src/a.py", b"needle\nkeep\nneedle\n")
    await session.write_file("src/b.py", b"needle\n")
    await session.write_file("README.md", b"other\n")

    files = await session.search_text(
        "needle",
        paths=("src/**",),
        output_mode="files",
    )
    counts = await session.search_text(
        "needle",
        paths=("src/**",),
        output_mode="count",
    )
    limited = await session.search_text(
        "needle",
        paths=("src/**",),
        output_mode="files",
        limit=1,
    )
    content = await session.search_text(
        "needle",
        paths=("src/**",),
        output_mode="content",
        before=1,
        after=1,
    )

    assert [match.path for match in files] == ["src/a.py", "src/b.py"]
    assert [(match.path, match.count) for match in counts] == [
        ("src/a.py", 2),
        ("src/b.py", 1),
    ]
    assert [match.path for match in limited] == ["src/a.py"]
    assert len(content) == 3
    assert content[0].path == "src/a.py"
    assert content[0].text == "needle"
    assert content[0].after == ("keep",)
    await provider.close()


async def test_memory_glob_files_matches_limit_and_rejects_escape(
    tmp_path: Path,
) -> None:
    provider = MemorySandboxProvider(root=tmp_path)
    sandbox = await provider.create(
        owner_id="u1",
        limits=SandboxLimits.safe_defaults(),
    )
    session = await provider.open_session(sandbox.sandbox_id)
    await session.write_file("src/app.py", b"print(1)\n")
    await session.write_file("src/nested/util.py", b"print(2)\n")
    await session.write_file("README.md", b"# readme\n")

    assert await session.glob_files("**/*.py") == (
        "src/app.py",
        "src/nested/util.py",
    )
    assert await session.glob_files("src/*.py") == ("src/app.py",)
    assert await session.glob_files("*.md") == ("README.md",)
    assert await session.glob_files("**/*.py", limit=1) == ("src/app.py",)

    with pytest.raises(SandboxPolicyViolation, match="invalid_glob_request"):
        await session.glob_files("", limit=10)
    with pytest.raises(SandboxPolicyViolation, match="invalid_glob_request"):
        await session.glob_files("**/*.py", limit=0)
    with pytest.raises(SandboxPolicyViolation, match="workspace_path_escape"):
        await session.glob_files("../secret.py")
    await provider.close()
