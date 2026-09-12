import sys
from dataclasses import replace
from pathlib import Path

import pytest

from neos.coding.sandbox.base import (
    CommandRequest,
    CommandResult,
    SandboxLimits,
    SandboxNotFound,
    SandboxPolicyViolation,
    SandboxState,
)
from neos.coding.sandbox.memory import MemorySandboxProvider

pytestmark = pytest.mark.no_db


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


async def test_memory_list_tree_includes_src_app(tmp_path: Path) -> None:
    provider = MemorySandboxProvider(root=tmp_path)
    sandbox = await provider.create(
        owner_id="u1",
        limits=SandboxLimits.safe_defaults(),
    )
    session = await provider.open_session(sandbox.sandbox_id)
    await session.write_file("src/app.py", b"print(1)\n")

    entries = await session.list_tree(".")
    paths = [entry.path for entry in entries]

    assert "src" in paths
    assert "src/app.py" in paths
    await provider.close()


async def test_memory_list_tree_skips_git_env_and_node_modules(
    tmp_path: Path,
) -> None:
    provider = MemorySandboxProvider(root=tmp_path)
    sandbox = await provider.create(
        owner_id="u1",
        limits=SandboxLimits.safe_defaults(),
    )
    session = await provider.open_session(sandbox.sandbox_id)
    await session.write_file("src/app.py", b"print(1)\n")
    workspace = provider.workspace_path(sandbox.sandbox_id)
    objects = workspace / ".git" / "objects"
    objects.mkdir(parents=True)
    (objects / "pack").write_text("blob\n", encoding="utf-8")
    (workspace / ".env").write_text("SECRET=1\n", encoding="utf-8")
    nested = workspace / "node_modules" / "pkg"
    nested.mkdir(parents=True)
    (nested / "index.js").write_text("module.exports = 1\n", encoding="utf-8")

    entries = await session.list_tree(".")
    paths = [entry.path for entry in entries]

    assert "src" in paths
    assert "src/app.py" in paths
    assert ".git" not in paths
    assert ".env" not in paths
    assert "node_modules" not in paths
    assert not any(path.startswith(".git/") for path in paths)
    assert not any(path.startswith("node_modules/") for path in paths)
    await provider.close()


async def test_memory_search_skips_node_modules_and_gitignore(tmp_path: Path) -> None:
    provider = MemorySandboxProvider(root=tmp_path)
    sandbox = await provider.create(
        owner_id="u1",
        limits=SandboxLimits.safe_defaults(),
    )
    session = await provider.open_session(sandbox.sandbox_id)
    workspace = provider.workspace_path(sandbox.sandbox_id)
    (workspace / "src").mkdir()
    (workspace / "src" / "app.py").write_text("needle\n", encoding="utf-8")
    nested = workspace / "node_modules" / "pkg"
    nested.mkdir(parents=True)
    (nested / "index.js").write_text("needle\n", encoding="utf-8")
    (workspace / ".gitignore").write_text("ignored.py\n", encoding="utf-8")
    (workspace / "ignored.py").write_text("needle\n", encoding="utf-8")

    matches = await session.search_text("needle")
    files = await session.glob_files("**/*")

    assert [match.path for match in matches] == ["src/app.py"]
    assert "node_modules/pkg/index.js" not in files
    assert "ignored.py" not in files
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


async def test_memory_write_file_parents_false_requires_existing_parent(
    tmp_path: Path,
) -> None:
    provider = MemorySandboxProvider(root=tmp_path)
    sandbox = await provider.create(
        owner_id="u1",
        limits=SandboxLimits.safe_defaults(),
    )
    session = await provider.open_session(sandbox.sandbox_id)

    with pytest.raises((FileNotFoundError, SandboxPolicyViolation)):
        await session.write_file("nested/a.txt", b"x", parents=False)

    created = await session.write_file("nested/a.txt", b"x", parents=True)
    defaulted = await session.write_file("src/app.py", b"print(1)\n")

    assert created == 1
    assert defaulted == 2
    assert await session.read_file("nested/a.txt") == b"x"
    assert await session.read_file("src/app.py") == b"print(1)\n"
    await provider.close()


async def test_memory_write_refuses_symlink_leaf_and_parent(
    tmp_path: Path,
) -> None:
    provider = MemorySandboxProvider(root=tmp_path)
    sandbox = await provider.create(
        owner_id="u1",
        limits=SandboxLimits.safe_defaults(),
    )
    session = await provider.open_session(sandbox.sandbox_id)
    workspace = provider.workspace_path(sandbox.sandbox_id)
    outside = tmp_path / "outside-secret"
    outside.write_bytes(b"secret")
    outside_dir = tmp_path / "outside-dir"
    outside_dir.mkdir()
    (workspace / "inside.txt").write_bytes(b"orig")
    (workspace / "link.txt").symlink_to(outside)
    (workspace / "inside-link.txt").symlink_to(workspace / "inside.txt")
    (workspace / "ext").symlink_to(outside_dir)

    with pytest.raises(SandboxPolicyViolation, match="workspace_symlink_leaf"):
        await session.write_file("link.txt", b"new")
    with pytest.raises(SandboxPolicyViolation, match="workspace_symlink_leaf"):
        await session.write_file("inside-link.txt", b"new")
    with pytest.raises(
        SandboxPolicyViolation, match="workspace_symlink_parent"
    ):
        await session.write_file("ext/x.txt", b"x")

    await session.write_file("ok.txt", b"complete")

    assert outside.read_bytes() == b"secret"
    assert (workspace / "inside.txt").read_bytes() == b"orig"
    assert (workspace / "link.txt").is_symlink()
    assert not (outside_dir / "x.txt").exists()
    assert await session.read_file("ok.txt") == b"complete"
    leftovers = [
        path
        for path in workspace.iterdir()
        if path.name.startswith(".neos-write-") or path.name.endswith(".tmp")
    ]
    assert leftovers == []
    await provider.close()


async def test_search_and_glob_do_not_follow_directory_symlinks(
    tmp_path: Path,
) -> None:
    provider = MemorySandboxProvider(root=tmp_path)
    sandbox = await provider.create(
        owner_id="u1",
        limits=SandboxLimits.safe_defaults(),
    )
    session = await provider.open_session(sandbox.sandbox_id)
    workspace = provider.workspace_path(sandbox.sandbox_id)
    outside = tmp_path / "outside-secret-dir"
    outside.mkdir()
    (outside / "secret.txt").write_text("SECRET_NEEDLE\n", encoding="utf-8")
    (workspace / "link").symlink_to(outside)
    await session.write_file("src/app.py", b"SECRET_NEEDLE\n")

    matches = await session.search_text("SECRET_NEEDLE")
    files = await session.glob_files("**/*")

    assert [match.path for match in matches] == ["src/app.py"]
    assert "link/secret.txt" not in files
    assert not any(path.startswith("link/") for path in files)
    await provider.close()


async def test_read_file_range_bypasses_whole_file_size_cap(
    tmp_path: Path,
) -> None:
    provider = MemorySandboxProvider(root=tmp_path)
    sandbox = await provider.create(
        owner_id="u1",
        limits=replace(SandboxLimits.safe_defaults(), max_output_bytes=20),
    )
    session = await provider.open_session(sandbox.sandbox_id)
    await session.write_file("big.txt", b"line1\nline2\nline3\n" + (b"x" * 80) + b"\n")
    await session.write_file("wide.txt", b"y" * 50 + b"\n")

    with pytest.raises(SandboxPolicyViolation, match="file_read_limit_exceeded"):
        await session.read_file("big.txt")

    assert await session.read_file("big.txt", offset=2, limit=1) == b"line2\n"
    assert await session.read_file("big.txt", offset=1, limit=2) == b"line1\nline2\n"
    capped = await session.read_file("wide.txt", offset=1, limit=1)
    assert capped == b"y" * 20
    await provider.close()


async def test_search_text_optional_kwargs_and_binary_skip(
    tmp_path: Path,
) -> None:
    provider = MemorySandboxProvider(root=tmp_path)
    sandbox = await provider.create(
        owner_id="u1",
        limits=SandboxLimits.safe_defaults(),
    )
    session = await provider.open_session(sandbox.sandbox_id)
    await session.write_file("src/a.py", b"Hello NEEDLE\nfoo\nbar\n")
    await session.write_file("src/b.py", b"needle\n")
    await session.write_file("other.py", b"needle\n")
    await session.write_file("bin.dat", b"needle\x00more")
    await session.write_file("multi.py", b"start\nmiddle\nend\n")
    await session.write_file("long.py", b"x" * 600 + b"needle\n")

    cased = await session.search_text("hello", ignore_case=True)
    scoped = await session.search_text("needle", path="src", ignore_case=True)
    one_file = await session.search_text("needle", path="src/b.py")
    with_context = await session.search_text(
        "NEEDLE",
        path="src/a.py",
        context=1,
        before=0,
        after=0,
    )
    multiline = await session.search_text(
        "start.*end",
        path="multi.py",
        regex=True,
        multiline=True,
    )
    per_line = await session.search_text(
        "start.*end",
        path="multi.py",
        regex=True,
    )
    truncated = await session.search_text("needle", path="long.py", max_columns=10)
    visible = await session.search_text("needle")

    assert [match.path for match in cased] == ["src/a.py"]
    assert {match.path for match in scoped} == {"src/a.py", "src/b.py"}
    assert [match.path for match in one_file] == ["src/b.py"]
    assert with_context[0].before == ()
    assert with_context[0].after == ("foo",)
    assert len(multiline) == 1
    assert multiline[0].line == 1
    assert per_line == ()
    assert truncated[0].text == "x" * 10
    assert [match.path for match in visible] == [
        "long.py",
        "other.py",
        "src/b.py",
    ]
    await provider.close()


async def test_glob_files_returns_files_only(tmp_path: Path) -> None:
    provider = MemorySandboxProvider(root=tmp_path)
    sandbox = await provider.create(
        owner_id="u1",
        limits=SandboxLimits.safe_defaults(),
    )
    session = await provider.open_session(sandbox.sandbox_id)
    await session.write_file("src/app.py", b"print(1)\n")

    files = await session.glob_files("**/*")

    assert "src/app.py" in files
    assert "src" not in files
    await provider.close()


async def test_nested_gitignore_hides_files_from_search_and_glob(
    tmp_path: Path,
) -> None:
    provider = MemorySandboxProvider(root=tmp_path)
    sandbox = await provider.create(
        owner_id="u1",
        limits=SandboxLimits.safe_defaults(),
    )
    session = await provider.open_session(sandbox.sandbox_id)
    workspace = provider.workspace_path(sandbox.sandbox_id)
    (workspace / "src").mkdir()
    (workspace / "other").mkdir()
    (workspace / "src" / ".gitignore").write_text("*.tmp\n", encoding="utf-8")
    (workspace / "src" / "hidden.tmp").write_text("needle\n", encoding="utf-8")
    (workspace / "src" / "keep.py").write_text("needle\n", encoding="utf-8")
    (workspace / "other" / "visible.tmp").write_text("needle\n", encoding="utf-8")

    matches = await session.search_text("needle")
    files = await session.glob_files("**/*")

    assert {match.path for match in matches} == {"src/keep.py", "other/visible.tmp"}
    assert "src/hidden.tmp" not in files
    assert "other/visible.tmp" in files
    await provider.close()


async def test_git_commands_disable_external_diff_and_pager(
    tmp_path: Path,
) -> None:
    provider = MemorySandboxProvider(root=tmp_path)
    sandbox = await provider.create(
        owner_id="u1",
        limits=SandboxLimits.safe_defaults(),
    )
    session = await provider.open_session(sandbox.sandbox_id)
    captured: list[tuple[str, ...]] = []

    async def wrapped(request: CommandRequest) -> CommandResult:
        captured.append(request.argv)
        return CommandResult(exit_code=0, stdout=b"", stderr=b"")

    session.execute = wrapped  # type: ignore[method-assign]

    await session.git_status()
    await session.git_diff()
    await session.git_diff(staged=True)
    await session.git_log(limit=5)

    assert len(captured) == 4
    for argv in captured:
        assert argv[0] == "git"
        assert "--no-pager" in argv or (
            "-c" in argv and "core.pager=cat" in argv
        )
    assert "--no-ext-diff" in captured[1]
    assert "--no-ext-diff" in captured[2]
    assert "--cached" in captured[2]
    assert "--no-ext-diff" in captured[3]
    await provider.close()


async def test_read_file_denies_secret_and_leaf_symlink(tmp_path: Path) -> None:
    provider = MemorySandboxProvider(root=tmp_path)
    sandbox = await provider.create(
        owner_id="u1",
        limits=SandboxLimits.safe_defaults(),
    )
    session = await provider.open_session(sandbox.sandbox_id)
    workspace = provider.workspace_path(sandbox.sandbox_id)
    (workspace / "src").mkdir()
    (workspace / "src" / "app.py").write_bytes(b"print(1)\n")
    (workspace / ".env").write_bytes(b"SECRET=1\n")
    (workspace / "env-link").symlink_to(workspace / ".env")
    (workspace / "app-link").symlink_to(workspace / "src" / "app.py")
    (workspace / "real").mkdir()
    (workspace / "real" / "ok.txt").write_bytes(b"ok\n")
    (workspace / "ext").symlink_to(workspace / "real")

    with pytest.raises(SandboxPolicyViolation, match="workspace_secret_path"):
        await session.read_file(".env")
    with pytest.raises(
        SandboxPolicyViolation,
        match="workspace_symlink_leaf|workspace_secret_path",
    ):
        await session.read_file("env-link")
    with pytest.raises(SandboxPolicyViolation, match="workspace_symlink_leaf"):
        await session.read_file("app-link")

    assert await session.read_file("ext/ok.txt") == b"ok\n"
    assert await session.read_file("src/app.py") == b"print(1)\n"
    await provider.close()


async def test_search_text_skips_oversized_files(tmp_path: Path) -> None:
    provider = MemorySandboxProvider(root=tmp_path)
    sandbox = await provider.create(
        owner_id="u1",
        limits=replace(SandboxLimits.safe_defaults(), max_output_bytes=64),
    )
    session = await provider.open_session(sandbox.sandbox_id)
    await session.write_file("small.txt", b"needle in small\n")
    await session.write_file("huge.txt", b"needle " + (b"x" * 200) + b"\n")

    matches = await session.search_text("needle")

    assert [match.path for match in matches] == ["small.txt"]
    await provider.close()


async def test_execute_assembles_guest_env_without_host_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", "/host/secret/bin:/usr/bin")
    monkeypatch.setenv("HOME", "/host/home")
    monkeypatch.setenv("TMPDIR", "/host/tmp")
    provider = MemorySandboxProvider(root=tmp_path)
    sandbox = await provider.create(
        owner_id="u1",
        limits=SandboxLimits.safe_defaults(),
    )
    session = await provider.open_session(sandbox.sandbox_id)
    workspace = provider.workspace_path(sandbox.sandbox_id)

    result = await session.execute(
        CommandRequest(
            argv=(
                sys.executable,
                "-c",
                "import os; print(os.environ.get('PATH','')); "
                "print(os.environ.get('HOME','')); "
                "print(os.environ.get('TMPDIR',''))",
            )
        )
    )
    overlaid = await session.execute(
        CommandRequest(
            argv=(sys.executable, "-c", "import os; print(os.environ['PATH'])"),
            env={"PATH": "/custom/bin"},
        )
    )

    lines = result.stdout.decode().splitlines()
    assert result.exit_code == 0
    assert lines[0] == "/usr/bin:/bin"
    assert lines[1] == str(workspace)
    assert lines[2] in {str(workspace / ".tmp"), "/tmp"}
    assert "/host/secret/bin" not in result.stdout.decode()
    assert "/host/home" not in result.stdout.decode()
    assert overlaid.stdout.decode().strip() == "/custom/bin"
    await provider.close()


async def test_fingerprint_does_not_follow_directory_symlink(
    tmp_path: Path,
) -> None:
    provider = MemorySandboxProvider(root=tmp_path)
    sandbox = await provider.create(
        owner_id="u1",
        limits=SandboxLimits.safe_defaults(),
    )
    session = await provider.open_session(sandbox.sandbox_id)
    workspace = provider.workspace_path(sandbox.sandbox_id)
    outside = tmp_path / "outside-secret-dir"
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_text("v1", encoding="utf-8")
    (workspace / "link").symlink_to(outside)

    assert await session.workspace_revision() == 0
    secret.write_text("v2", encoding="utf-8")
    await session.execute(
        CommandRequest(argv=(sys.executable, "-c", "pass"))
    )

    assert await session.workspace_revision() == 0
    await provider.close()
