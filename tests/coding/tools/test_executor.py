from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

import pytest

from neos.coding.sandbox.base import (
    CommandRequest,
    CommandResult,
    FileEntry,
    SandboxNotFound,
    SandboxPolicyViolation,
    SandboxTimeout,
    SearchMatch,
)
from neos.coding.tools.executor import SandboxToolExecutor
from neos.coding.tools.registry import ToolRisk, ValidatedToolCall


NOW = datetime(2026, 7, 19, tzinfo=UTC)


class FakeSession:
    sandbox_id = "sandbox-1"

    def __init__(self) -> None:
        self.called: tuple[str, Any] | None = None
        self.file_content = b"abcdef"
        self.command_result = CommandResult(0, b"stdout", b"stderr")
        self.error: Exception | None = None

    async def workspace_revision(self) -> int:
        return 7

    def _raise(self) -> None:
        if self.error is not None:
            raise self.error

    async def list_tree(self, path: str = ".") -> tuple[FileEntry, ...]:
        self._raise()
        self.called = ("list_tree", path)
        return tuple(FileEntry(f"{path}/{index}", "file", index, NOW) for index in range(3))

    async def stat(self, path: str) -> FileEntry:
        self._raise()
        self.called = ("stat", path)
        return FileEntry(path, "file", 3, NOW)

    async def read_file(self, path: str) -> bytes:
        self._raise()
        self.called = ("read_file", path)
        return self.file_content

    async def write_file(self, path: str, content: bytes) -> int:
        self._raise()
        self.called = ("write_file", (path, content))
        return 8

    async def search_text(self, query: str, **kwargs: Any) -> tuple[SearchMatch, ...]:
        self._raise()
        self.called = ("search_text", (query, kwargs))
        return (SearchMatch("a.py", 2, 3, "needle"),)

    async def git_status(self) -> CommandResult:
        self._raise()
        self.called = ("git_status", None)
        return self.command_result

    async def git_diff(self, *, staged: bool = False) -> CommandResult:
        self._raise()
        self.called = ("git_diff", staged)
        return self.command_result

    async def git_log(self, *, limit: int = 20) -> CommandResult:
        self._raise()
        self.called = ("git_log", limit)
        return self.command_result

    async def execute(self, request: CommandRequest) -> CommandResult:
        self._raise()
        self.called = ("execute", request)
        return self.command_result


def call(name: str, input: dict[str, object]) -> ValidatedToolCall:
    risk = ToolRisk.COMMAND if name == "execute.v1" else ToolRisk.READ_ONLY
    if name == "write_file.v1":
        risk = ToolRisk.WORKSPACE_WRITE
    return ValidatedToolCall(name, input, risk)


@pytest.mark.asyncio
async def test_read_file_truncates_and_checksums_original_content() -> None:
    session = FakeSession()
    executor = SandboxToolExecutor(max_preview_bytes=4, max_entries=10)
    result = await executor.execute(session, call("read_file.v1", {"path": "a.txt"}))
    assert result.status == "ok"
    assert result.preview == "abcd"
    assert result.original_bytes == 6
    assert result.truncated is True
    assert result.checksum == hashlib.sha256(b"abcdef").hexdigest()
    assert result.workspace_revision == "7"


@pytest.mark.asyncio
async def test_read_file_decodes_invalid_utf8_with_replacement() -> None:
    session = FakeSession()
    session.file_content = b"a\xffb"
    result = await SandboxToolExecutor(10, 10).execute(
        session, call("read_file.v1", {"path": "a"})
    )
    assert result.preview == "a\ufffdb"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "input", "method"),
    [
        ("list_tree.v1", {"path": "src"}, "list_tree"),
        ("stat.v1", {"path": "a.py"}, "stat"),
        ("search_text.v1", {"query": "x", "paths": ["src"], "regex": True, "limit": 4}, "search_text"),
        ("git_status.v1", {}, "git_status"),
        ("git_diff.v1", {"staged": True}, "git_diff"),
        ("git_log.v1", {"limit": 4}, "git_log"),
        ("write_file.v1", {"path": "a", "content": "text"}, "write_file"),
        (
            "execute.v1",
            {"argv": ["pytest", "-q"], "cwd": ".", "env": {}, "stdin": "", "timeout_sec": 2.0, "max_output_bytes": 5},
            "execute",
        ),
    ],
)
async def test_dispatches_every_non_read_registered_tool(
    name: str, input: dict[str, object], method: str
) -> None:
    session = FakeSession()
    result = await SandboxToolExecutor(10, 10).execute(session, call(name, input))
    assert session.called is not None and session.called[0] == method
    assert result.status == "ok"
    assert result.workspace_revision == ("8" if name == "write_file.v1" else "7")


@pytest.mark.asyncio
async def test_list_tree_bounds_entries_and_serializes_json_safely() -> None:
    result = await SandboxToolExecutor(10, 2).execute(
        FakeSession(), call("list_tree.v1", {"path": "."})
    )
    assert len(result.entries) == 2
    assert result.truncated is True
    json.dumps(result.to_mapping())


@pytest.mark.asyncio
async def test_command_bounds_stdout_and_stderr_separately() -> None:
    session = FakeSession()
    session.command_result = CommandResult(3, b"abcdef", b"uvwxyz")
    result = await SandboxToolExecutor(4, 10).execute(
        session,
        call("execute.v1", {"argv": ["pytest"], "cwd": ".", "env": {}, "stdin": "", "timeout_sec": 1, "max_output_bytes": 4}),
    )
    mapping = result.to_mapping()
    assert mapping["stdout"]["preview"] == "abcd"
    assert mapping["stderr"]["preview"] == "uvwx"
    assert mapping["stdout"]["original_bytes"] == 6
    assert mapping["stderr"]["truncated"] is True
    assert mapping["exit_code"] == 3
    assert result.truncated is True


@pytest.mark.asyncio
async def test_execute_never_serializes_environment_values() -> None:
    result = await SandboxToolExecutor(10, 10).execute(
        FakeSession(),
        call("execute.v1", {"argv": ["pytest", "-q"], "cwd": ".", "env": {"TOKEN": "secret"}, "stdin": "", "timeout_sec": 1, "max_output_bytes": 10}),
    )
    payload = json.dumps(result.to_mapping())
    assert "secret" not in payload
    assert "-q" not in payload
    assert result.audit == {"executable_category": "pytest"}


@pytest.mark.asyncio
async def test_execute_returns_revision_after_command_mutation() -> None:
    class MutatingSession(FakeSession):
        def __init__(self) -> None:
            super().__init__()
            self.revision = 7

        async def workspace_revision(self) -> int:
            return self.revision

        async def execute(self, request: CommandRequest) -> CommandResult:
            self.revision += 1
            return await super().execute(request)

    result = await SandboxToolExecutor(10, 10).execute(
        MutatingSession(),
        call("execute.v1", {"argv": ["pytest"], "cwd": ".", "env": {}, "stdin": "", "timeout_sec": 1, "max_output_bytes": 10}),
    )

    assert result.workspace_revision == "8"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "status", "reason"),
    [
        (SandboxTimeout("details"), "error", "sandbox_timeout"),
        (SandboxPolicyViolation("outside_workspace"), "denied", "sandbox_policy_violation"),
        (SandboxNotFound("private path"), "error", "sandbox_not_found"),
    ],
)
async def test_maps_sandbox_errors_without_leaking_messages(
    error: Exception, status: str, reason: str
) -> None:
    session = FakeSession()
    session.error = error
    result = await SandboxToolExecutor(10, 10).execute(
        session, call("read_file.v1", {"path": "missing"})
    )
    assert (result.status, result.reason_code) == (status, reason)
    assert str(error) not in json.dumps(result.to_mapping())


@pytest.mark.asyncio
async def test_command_timed_out_flag_maps_to_timeout() -> None:
    session = FakeSession()
    session.command_result = CommandResult(None, b"partial", b"", timed_out=True)
    result = await SandboxToolExecutor(10, 10).execute(
        session,
        call("execute.v1", {"argv": ["pytest"], "cwd": ".", "env": {}, "stdin": "", "timeout_sec": 1, "max_output_bytes": 10}),
    )
    assert (result.status, result.reason_code) == ("error", "sandbox_timeout")


@pytest.mark.asyncio
async def test_unknown_validated_call_fails_closed() -> None:
    result = await SandboxToolExecutor(10, 10).execute(
        FakeSession(), call("future.v1", {})
    )
    assert (result.status, result.reason_code) == ("denied", "unknown_tool")


@pytest.mark.asyncio
async def test_original_error_is_sanitized_when_revision_lookup_also_fails() -> None:
    class BrokenRevisionSession(FakeSession):
        async def workspace_revision(self) -> int:
            raise SandboxNotFound("revision secret")

    session = BrokenRevisionSession()
    session.error = SandboxPolicyViolation("input secret")
    result = await SandboxToolExecutor(10, 10).execute(
        session, call("read_file.v1", {"path": "sensitive-name"})
    )

    assert (result.status, result.reason_code) == (
        "denied",
        "sandbox_policy_violation",
    )
    assert result.workspace_revision == "unknown"
    payload = json.dumps(result.to_mapping())
    assert "input secret" not in payload
    assert "revision secret" not in payload
    assert "sensitive-name" not in payload
