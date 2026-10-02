"""Q16b: the reference client's one write tool -- confined, atomic, digest-keyed.

Real files under tmp_path. The end-to-end test wires the real client to the real
server socket session, relay and service.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import stat
from pathlib import Path

import pytest

from neos.bridge.client import serve
from neos.bridge.tools import BridgeToolError, LocalReadOnlyTools, LocalWritableTools

pytestmark = pytest.mark.no_db


def _sha(data: str | bytes) -> str:
    raw = data.encode() if isinstance(data, str) else data
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture
def shared(tmp_path: Path) -> Path:
    root = tmp_path / "shared"
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "a.md").write_text("hello device\n")
    (tmp_path / "outside.txt").write_text("not yours")
    (tmp_path / "outside").mkdir()
    return root


def _tools(root: Path, **kw) -> LocalWritableTools:
    return LocalWritableTools(root, **kw)


def _code(fn, *args, **kwargs) -> str:
    with pytest.raises(BridgeToolError) as error:
        fn(*args, **kwargs)
    return error.value.code


def _leftovers(root: Path) -> list[str]:
    return sorted(p.name for p in root.rglob(".neos-bridge-*"))


# -- declaration -----------------------------------------------------------------------


def test_writes_are_declared_only_by_the_writable_tools(shared: Path) -> None:
    assert {e["risk"] for e in LocalReadOnlyTools(shared).declaration()} == {"read_only"}
    assert _tools(shared).declaration()[-1] == {"name": "write_file", "risk": "workspace_write"}
    assert _code(LocalReadOnlyTools(shared).call, "write_file", {"path": "x"}) == "unknown_tool"


# -- the digest discipline (BW5) -------------------------------------------------------


def test_overwrite_needs_the_digest_of_a_full_read(shared: Path) -> None:
    """Mutation: skip the `read_required` branch -> an unread file is overwritten; or hand out a
    digest on a truncated read -> a partial view becomes an overwrite key."""
    tools = _tools(shared)
    target = shared / "docs" / "a.md"

    assert _code(tools.write_file, "docs/a.md", "new") == "read_required"
    assert "sha256" not in _tools(shared, max_read_bytes=4).read_file("docs/a.md")
    read = tools.read_file("docs/a.md")
    assert read["sha256"] == _sha("hello device\n")

    written = tools.write_file("docs/a.md", "new text\n", base_sha256=read["sha256"])

    assert written == {"sha256": _sha("new text\n"), "size": 9, "created": False}
    assert target.read_text() == "new text\n" and _leftovers(shared) == []


def test_a_stale_digest_is_refused_and_nothing_changes(shared: Path) -> None:
    """Mutation: drop the digest comparison -> the user's edit made after the read is lost."""
    tools = _tools(shared)
    base = tools.read_file("docs/a.md")["sha256"]
    (shared / "docs" / "a.md").write_text("the user edited this\n")

    assert _code(tools.write_file, "docs/a.md", "agent text", base_sha256=base) == "stale_read"
    assert (shared / "docs" / "a.md").read_text() == "the user edited this\n"
    assert _code(tools.write_file, "docs/a.md", "x", base_sha256="nothex") == "stale_read"
    assert _leftovers(shared) == []


def test_the_digest_is_checked_again_right_before_the_swap(shared: Path, monkeypatch) -> None:
    """The file changes between the first check and the rename. Mutation: drop the second
    check -> the late edit is overwritten."""
    import neos.bridge.tools as module

    tools = _tools(shared)
    base = tools.read_file("docs/a.md")["sha256"]
    real = module._current_digest
    calls = {"n": 0}

    def racing(parent, name):
        calls["n"] += 1
        if calls["n"] == 2:
            (shared / "docs" / "a.md").write_text("late edit\n")
        return real(parent, name)

    monkeypatch.setattr(module, "_current_digest", racing)
    assert _code(tools.write_file, "docs/a.md", "agent", base_sha256=base) == "stale_read"
    assert (shared / "docs" / "a.md").read_text() == "late edit\n" and _leftovers(shared) == []


def test_create_only_never_clobbers(shared: Path, monkeypatch) -> None:
    """A missing file is created only with no digest, and never over one that appears.
    Mutation: create with `os.replace` instead of `os.link` -> the racing file is clobbered."""
    tools = _tools(shared)
    assert tools.write_file("docs/new.md", "fresh\n") == {
        "sha256": _sha("fresh\n"),
        "size": 6,
        "created": True,
    }
    assert _code(tools.write_file, "docs/gone.md", "x", base_sha256=_sha("x")) == "stale_read"

    real_link = os.link

    def racing_link(src, dst, **kw):
        (shared / "docs" / "race.md").write_text("someone else\n")
        return real_link(src, dst, **kw)

    monkeypatch.setattr(os, "link", racing_link)
    assert _code(tools.write_file, "docs/race.md", "mine\n") == "stale_read"
    assert (shared / "docs" / "race.md").read_text() == "someone else\n"
    assert _leftovers(shared) == []


def test_a_replayed_write_is_stale(shared: Path) -> None:
    """A write that runs twice (lost claim, retried timeout) finds the digest already moved."""
    tools = _tools(shared)
    base = tools.read_file("docs/a.md")["sha256"]
    tools.write_file("docs/a.md", "one\n", base_sha256=base)

    assert _code(tools.write_file, "docs/a.md", "one\n", base_sha256=base) == "stale_read"
    tools.write_file("docs/b.md", "made\n")
    assert _code(tools.write_file, "docs/b.md", "made\n") == "read_required"


# -- confinement (BW6) -----------------------------------------------------------------


@pytest.mark.parametrize(
    "path,code",
    [
        ("../outside.txt", "path_escape"),
        ("/etc/hosts", "path_escape"),
        ("docs/../../outside.txt", "path_escape"),
        ("~/x", "path_escape"),
        ("a\0b", "path_escape"),
        (".env", "secret_path"),
        (".bashrc", "write_path_refused"),
        ("docs/.git/hooks/pre-commit", "secret_path"),
        (".github/workflows/x.yml", "write_path_refused"),
        ("docs/run.command", "write_path_refused"),
        ("docs/x.desktop", "write_path_refused"),
        (".", "write_path_refused"),
    ],
)
def test_write_paths_outside_the_root_are_refused(shared: Path, path, code) -> None:
    """Mutation: drop `device_write_refusal` on the client -> `.bashrc` is written."""
    assert _code(_tools(shared).write_file, path, "x") == code
    assert not (shared / ".bashrc").exists()


def test_writes_never_follow_a_symlink_anywhere_in_the_path(shared: Path) -> None:
    """A link inside the root that stays inside the root is still refused for writes.
    Mutation: rely on realpath containment -> `inner/a.md` writes through the link."""
    (shared / "inner").symlink_to(shared / "docs")
    (shared / "out").symlink_to(shared.parent / "outside")
    (shared / "docs" / "link.md").symlink_to(shared / "docs" / "a.md")
    (shared / "docs" / "dangling.md").symlink_to(shared.parent / "outside" / "new.md")
    tools = _tools(shared)
    base = _sha("hello device\n")

    assert _code(tools.write_file, "inner/a.md", "x", base_sha256=base) == "path_escape"
    assert _code(tools.write_file, "out/new.md", "x") == "path_escape"
    assert _code(tools.write_file, "docs/link.md", "x", base_sha256=base) == "path_escape"
    assert _code(tools.write_file, "docs/dangling.md", "x") == "path_escape"
    assert (shared / "docs" / "a.md").read_text() == "hello device\n"
    assert list((shared.parent / "outside").iterdir()) == []


def test_a_swapped_parent_directory_is_not_followed(shared: Path, monkeypatch) -> None:
    """The realpath check passes, then `docs` is swapped for a link to outside (simulated by
    making realpath lie). The fd walk opens each component with O_NOFOLLOW and refuses.
    Mutation: open the parent by path instead of walking fds -> the write lands outside."""
    import neos.bridge.tools as module

    tools = _tools(shared)
    (shared / "docs").rename(shared / "docs_moved")
    (shared / "docs").symlink_to(shared.parent / "outside")
    real_realpath = module.os.path.realpath

    def lying(path):
        resolved = real_realpath(path)
        outside = str(shared.parent / "outside")
        return resolved.replace(outside, str(shared / "docs")) if resolved.startswith(outside) else resolved

    monkeypatch.setattr(module.os.path, "realpath", lying)
    assert _code(tools.write_file, "docs/new.md", "x") == "path_escape"
    assert list((shared.parent / "outside").iterdir()) == []


def test_executable_files_are_never_written_and_new_files_are_not_executable(shared: Path) -> None:
    """Mutation: keep the old mode on overwrite without the exec check -> agent text lands in
    an executable; or create with 0o755 -> a new script is runnable."""
    script = shared / "docs" / "build.sh"
    script.write_text("echo hi\n")
    script.chmod(0o755)
    tools = _tools(shared)

    assert _code(tools.write_file, "docs/build.sh", "rm -rf ~\n", base_sha256=_sha("echo hi\n")) == "executable_file"
    assert script.read_text() == "echo hi\n"
    tools.write_file("docs/new.sh", "echo new\n")
    assert stat.S_IMODE((shared / "docs" / "new.sh").stat().st_mode) & 0o111 == 0
    plain = shared / "docs" / "a.md"
    plain.chmod(0o640)
    tools.write_file("docs/a.md", "kept mode\n", base_sha256=_sha("hello device\n"))
    assert stat.S_IMODE(plain.stat().st_mode) == 0o640


def test_a_failed_write_leaves_neither_a_partial_file_nor_a_temp_file(shared: Path, monkeypatch) -> None:
    """Mutation: write in place, or forget the temp cleanup -> a half file or a `.neos-bridge-*`
    file is left behind."""
    tools = _tools(shared)
    base = tools.read_file("docs/a.md")["sha256"]
    real_write = os.write

    def full_disk(fd, data):
        real_write(fd, bytes(data)[:3])
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(os, "write", full_disk)
    assert _code(tools.write_file, "docs/a.md", "a much longer body\n", base_sha256=base) == "no_space"
    assert _code(tools.write_file, "docs/new.md", "a much longer body\n") == "no_space"
    monkeypatch.undo()

    assert (shared / "docs" / "a.md").read_text() == "hello device\n"
    assert not (shared / "docs" / "new.md").exists()
    assert _leftovers(shared) == []


def test_a_hard_link_elsewhere_is_not_written_through(shared: Path) -> None:
    """rename swaps the directory entry: the other name keeps the old inode and content."""
    elsewhere = shared.parent / "outside" / "twin.md"
    os.link(shared / "docs" / "a.md", elsewhere)

    _tools(shared).write_file("docs/a.md", "replaced\n", base_sha256=_sha("hello device\n"))

    assert elsewhere.read_text() == "hello device\n"
    assert (shared / "docs" / "a.md").read_text() == "replaced\n"


def test_write_size_and_text_are_capped_on_both_sides(shared: Path) -> None:
    """The client keeps its own cap and the server's, whichever is lower; text only.
    (The server side is `test_the_service_caps_writes_and_passes_the_cap_on`.)"""
    tools = _tools(shared, max_write_bytes=8)
    assert _code(tools.write_file, "docs/n.md", "123456789") == "too_large"
    assert _code(_tools(shared).write_file, "docs/n.md", "12345", max_bytes=4) == "too_large"
    assert _code(tools.write_file, "docs/n.md", "a\0b") == "binary_file"
    assert _code(tools.write_file, "docs/n.md", b"bytes") == "binary_file"
    assert tools.write_file("docs/n.md", "가")["size"] == 3
    assert _code(tools.write_file, "missing/n.md", "x") == "not_found"
    assert _code(tools.write_file, "docs/a.md/x", "x") == "not_a_directory"
    assert _code(tools.write_file, "docs", "x", base_sha256=_sha("x")) == "not_a_file"


# -- end to end: a coding write lands on a real file through the real client -----------


async def test_end_to_end_read_then_write_through_the_client(shared: Path) -> None:
    from neos.coding.bridge.catalog import parse_declaration
    from neos.coding.bridge.relay import BridgeView, InProcessDeviceBridgeRelay
    from neos.coding.bridge.service import DeviceBridgeService
    from neos.coding.bridge.session import BridgeSocketSession
    from neos.coding.tools.registry import CodingToolRegistry
    from neos.config.schema import DeviceBridgeConfig
    from tests.bridge.test_bridge_client import _Pipe

    pipe = _Pipe()
    relay = InProcessDeviceBridgeRelay()
    config = DeviceBridgeConfig()
    client = asyncio.create_task(serve(pipe, _tools(shared)))
    hello = json.loads(await pipe.receive_text())
    view = BridgeView("alice", "dbr_1", "c1", parse_declaration(hello["tools"], allow_writes=True), False)

    class Live:
        allow_unattended = False
        allow_writes = True

    async def recheck():
        return Live()

    server = asyncio.create_task(BridgeSocketSession(pipe, view, relay, config=config, recheck=recheck).run())
    service = DeviceBridgeService(relay, config)
    while await service.view("alice") is None:
        await asyncio.sleep(0)
    registry = CodingToolRegistry.default(command_allowlist=frozenset({"git"}), device_tools=True)

    async def run(name, args):
        return await service.execute("alice", registry.validate(name, args), unattended=False)

    read = await run("device_read_file.v1", {"path": "docs/a.md"})
    digest = read.preview.rsplit("sha256: ", 1)[1].split(" ", 1)[0]
    blind = await run("device_write_file.v1", {"path": "docs/a.md", "content": "blind\n"})
    written = await run(
        "device_write_file.v1", {"path": "docs/a.md", "content": "via NEOS\n", "base_sha256": digest}
    )
    again = await run(
        "device_write_file.v1", {"path": "docs/a.md", "content": "again\n", "base_sha256": digest}
    )

    assert digest == _sha("hello device\n")
    assert (blind.status, blind.reason_code) == ("denied", "precondition_read_required")
    assert written.status == "ok" and written.checksum == _sha("via NEOS\n")
    assert (again.status, again.reason_code) == ("denied", "precondition_stale_read")
    assert (shared / "docs" / "a.md").read_text() == "via NEOS\n"

    server.cancel()
    client.cancel()
    for task in (server, client):
        with pytest.raises(BaseException):
            await task
