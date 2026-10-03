"""Q16a: the reference bridge client -- confined, read-only, never executes.

The client runs on the user's machine. These tests use real files under tmp_path;
the end-to-end test wires the real client loop to the real server socket session.
"""

from __future__ import annotations

import ast
import asyncio
import json
import os
from pathlib import Path

import pytest

from neos.bridge.client import _encode_result, run_bridge, serve
from neos.bridge.tools import BridgeToolError, LocalReadOnlyTools

pytestmark = pytest.mark.no_db

BRIDGE_SRC = Path(__file__).resolve().parents[2] / "neos" / "bridge"


@pytest.fixture
def shared(tmp_path: Path) -> Path:
    root = tmp_path / "shared"
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "a.md").write_text("hello device\n")
    (root / ".env").write_text("TOKEN=ghp_live_secret_value_123456\n")
    (root / ".ssh").mkdir()
    (root / ".ssh" / "id_rsa").write_text("PRIVATE")
    (root / "blob.bin").write_bytes(b"\x00\x01\x02binary")
    (tmp_path / "outside.txt").write_text("not yours")
    return root


def _tools(root: Path, **kw) -> LocalReadOnlyTools:
    return LocalReadOnlyTools(root, **kw)


def _code(fn, *args, **kwargs) -> str:
    with pytest.raises(BridgeToolError) as error:
        fn(*args, **kwargs)
    return error.value.code


def test_root_must_be_an_explicit_subfolder(tmp_path: Path, monkeypatch) -> None:
    with pytest.raises(ValueError, match="filesystem root"):
        LocalReadOnlyTools("/")
    monkeypatch.setenv("HOME", str(tmp_path))
    with pytest.raises(ValueError, match="home folder"):
        LocalReadOnlyTools(tmp_path)
    with pytest.raises(ValueError, match="existing directory"):
        LocalReadOnlyTools(tmp_path / "missing")


def test_reads_inside_the_root(shared: Path) -> None:
    tools = _tools(shared)
    assert tools.read_file("docs/a.md") == {"text": "hello device\n", "truncated": False, "size": 13}
    assert tools.stat("docs/a.md")["type"] == "file"
    names = [entry["name"] for entry in tools.list_dir(".")["entries"]]
    assert names == ["blob.bin", "docs"]  # .env and .ssh are not even listed


@pytest.mark.parametrize(
    "path",
    ["../outside.txt", "/etc/passwd", "docs/../../outside.txt", "docs/../docs/a.md", "C:/Windows", "~/x", "a\0b", 3],
)
def test_paths_outside_the_root_are_refused(shared: Path, path) -> None:
    """The client refuses `..` outright, like the server's validator -- even when it would
    land inside. Mutation: drop the `..` check -> `docs/../docs/a.md` is read (realpath
    containment alone still stops the escapes)."""
    assert _code(_tools(shared).read_file, path) == "path_escape"


def test_a_symlink_out_of_the_root_is_refused(shared: Path) -> None:
    """Mutation: check only the requested path, not its real path -> the link is followed."""
    (shared / "escape").symlink_to(shared.parent / "outside.txt")
    (shared / "escape_dir").symlink_to(shared.parent)

    tools = _tools(shared)
    assert _code(tools.read_file, "escape") == "path_escape"
    assert _code(tools.list_dir, "escape_dir") == "path_escape"
    assert _code(tools.stat, "escape_dir/outside.txt") == "path_escape"


@pytest.mark.parametrize("path", [".env", ".ssh/id_rsa", "docs/.env.local"])
def test_secret_paths_are_refused_with_the_servers_rule(shared: Path, path) -> None:
    assert _code(_tools(shared).read_file, path) == "secret_path"


def test_a_symlink_to_a_secret_inside_the_root_is_refused(shared: Path) -> None:
    """The real path is checked against the same rule -- `notes.txt -> .env` does not pass."""
    (shared / "notes.txt").symlink_to(shared / ".env")
    assert _code(_tools(shared).read_file, "notes.txt") == "secret_path"


def test_binary_and_caps(shared: Path) -> None:
    tools = _tools(shared, max_read_bytes=4)
    assert _code(tools.read_file, "blob.bin") == "binary_file"
    capped = tools.read_file("docs/a.md")
    assert capped == {"text": "hell", "truncated": True, "size": 13}
    assert _tools(shared).read_file("docs/a.md", max_bytes=5)["text"] == "hello"


def test_a_cut_through_a_multibyte_character_is_not_binary(shared: Path) -> None:
    (shared / "k.md").write_text("가나다")
    assert _tools(shared, max_read_bytes=4).read_file("k.md")["text"] == "가"


def test_listing_is_capped(shared: Path) -> None:
    for index in range(5):
        (shared / f"f{index}").write_text("x")
    listed = _tools(shared).list_dir(".", max_entries=2)
    assert len(listed["entries"]) == 2 and listed["truncated"] is True


def test_directories_and_fifos_are_not_files(shared: Path) -> None:
    assert _code(_tools(shared).read_file, "docs") == "not_a_file"
    if hasattr(os, "mkfifo"):
        os.mkfifo(shared / "pipe")
        assert _code(_tools(shared).read_file, "pipe") == "not_a_file"  # and it did not block


def test_unknown_tools_are_refused(shared: Path) -> None:
    assert _code(_tools(shared).call, "write_file", {"path": "x"}) == "unknown_tool"


def test_the_client_declares_read_only_only(shared: Path) -> None:
    assert {entry["risk"] for entry in _tools(shared).declaration()} == {"read_only"}


def test_the_client_never_executes_anything() -> None:
    """B10. Scans the client's own source: no process, shell, exec or eval anywhere -- except
    `commands.py`, the one module Q16c lets start a process (pinned by
    `test_only_the_command_module_may_start_a_process`).
    Mutation: add `subprocess.run` (or `os.system`) to any other bridge module -> red."""
    forbidden_modules = {"subprocess", "pty", "multiprocessing", "shlex"}
    forbidden_calls = {"system", "popen", "execv", "execve", "execvp", "spawnv", "eval", "exec", "startfile"}
    offenders = []
    for path in sorted(BRIDGE_SRC.glob("*.py")):
        if path.name == "commands.py":
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [alias.name for alias in node.names] + [getattr(node, "module", "") or ""]
                if any(name.split(".")[0] in forbidden_modules for name in names):
                    offenders.append(f"{path.name}: import {names}")
            if isinstance(node, ast.Call):
                func = node.func
                name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
                if name in forbidden_calls or name.startswith(("exec", "spawn", "posix_spawn")):
                    offenders.append(f"{path.name}: {name}()")
    assert offenders == []


def test_an_oversized_answer_is_shrunk_to_fit() -> None:
    payload = {"ok": True, "result": {"text": "x" * 10_000, "truncated": False, "size": 10_000}}
    encoded = _encode_result("r1", payload, 2048)
    assert len(encoded.encode()) <= 2048 and json.loads(encoded)["result"]["truncated"] is True


# -- end to end: client <-> server socket session <-> relay <-> service ----------------


class _Pipe:
    """One socket, two ends: the client speaks `send/recv/async for`, the server
    speaks `send_json/receive_text/close`."""

    def __init__(self) -> None:
        self.to_server: asyncio.Queue = asyncio.Queue()
        self.to_client: asyncio.Queue = asyncio.Queue()
        self.close_code: int | None = None

    # client end
    async def send(self, text: str) -> None:
        await self.to_server.put(text)

    async def recv(self) -> str:
        item = await self.to_client.get()
        if item is None:
            raise ConnectionError("closed")
        return item

    def __aiter__(self):
        return self

    async def __anext__(self) -> str:
        item = await self.to_client.get()
        if item is None:
            raise StopAsyncIteration
        return item

    # server end
    async def send_json(self, message: dict) -> None:
        await self.to_client.put(json.dumps(message))

    async def receive_text(self) -> str:
        return await self.to_server.get()

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.close_code = code
        await self.to_client.put(None)


async def test_end_to_end_a_coding_call_reads_a_real_file_through_the_client(shared: Path) -> None:
    from neos.coding.bridge.catalog import parse_declaration
    from neos.coding.bridge.relay import BridgeView, InProcessDeviceBridgeRelay
    from neos.coding.bridge.service import DeviceBridgeService
    from neos.coding.bridge.session import BridgeSocketSession
    from neos.coding.tools.registry import CodingToolRegistry
    from neos.config.schema import DeviceBridgeConfig

    pipe = _Pipe()
    relay = InProcessDeviceBridgeRelay()
    config = DeviceBridgeConfig()
    client = asyncio.create_task(serve(pipe, _tools(shared)))

    hello = json.loads(await pipe.receive_text())
    view = BridgeView("alice", "dbr_1", "c1", parse_declaration(hello["tools"]), False)

    class Live:
        allow_unattended = False

    async def recheck():
        return Live()

    server = asyncio.create_task(
        BridgeSocketSession(pipe, view, relay, config=config, recheck=recheck).run()
    )
    service = DeviceBridgeService(relay, config)
    while await service.view("alice") is None:
        await asyncio.sleep(0)
    registry = CodingToolRegistry.default(command_allowlist=frozenset({"git"}), device_tools=True)

    read = await service.execute(
        "alice", registry.validate("device_read_file.v1", {"path": "docs/a.md"}), unattended=False
    )
    listed = await service.execute(
        "alice", registry.validate("device_list_dir.v1", {"path": "."}), unattended=False
    )
    escaped = await service.execute(
        "alice", registry.validate("device_read_file.v1", {"path": "docs"}), unattended=False
    )

    assert read.status == "ok" and "hello device" in read.preview
    assert "dir\tdocs/" in listed.preview and ".env" not in listed.preview
    assert (escaped.status, escaped.reason_code) == ("error", "device_not_a_file")

    server.cancel()
    client.cancel()
    for task in (server, client):
        with pytest.raises(BaseException):
            await task


async def test_the_client_stops_on_final_close_codes_and_retries_otherwise(
    shared: Path, monkeypatch
) -> None:
    class Closed(Exception):
        def __init__(self, code: int) -> None:
            self.rcvd = type("Close", (), {"code": code})()

    attempts: list[int] = []
    codes = iter([1006, 4001, 4409])

    class Connection:
        async def __aenter__(self):
            code = next(codes)
            attempts.append(code)
            raise Closed(code)

        async def __aexit__(self, *exc):
            return False

    def connect(url, **kwargs):
        assert kwargs["additional_headers"] == {"Authorization": "Bearer ndb_x"}
        assert "token" not in url
        return Connection()

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(asyncio, "sleep", no_sleep)
    code = await run_bridge("wss://h/ws", "ndb_x", _tools(shared), connect=connect)

    assert code == 4409 and attempts == [1006, 4001, 4409]


async def test_a_rejected_handshake_stops_the_client(shared: Path, monkeypatch) -> None:
    """The server refuses before accepting; a real ASGI server turns that into HTTP 403,
    which carries no close code. Mutation: map only close codes -> it retries forever."""
    from websockets.exceptions import InvalidStatus

    attempts = []

    class Connection:
        async def __aenter__(self):
            attempts.append(1)
            if len(attempts) > 3:
                raise AssertionError("kept retrying a refused token")
            raise InvalidStatus(type("Response", (), {"status_code": 403, "headers": {}})())

        async def __aexit__(self, *exc):
            return False

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(asyncio, "sleep", no_sleep)
    code = await run_bridge("wss://h/ws", "ndb_x", _tools(shared), connect=lambda url, **kw: Connection())

    assert code == 4401 and attempts == [1]
