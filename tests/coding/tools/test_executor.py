from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import PurePosixPath
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
from neos.coding.tools.executor import SandboxToolExecutor, ToolResult
from neos.coding.tools.registry import ToolRisk, ValidatedToolCall

pytestmark = pytest.mark.no_db

NOW = datetime(2026, 7, 19, tzinfo=UTC)


class FakeSession:
    sandbox_id = "sandbox-1"

    def __init__(self) -> None:
        self.called: tuple[str, Any] | None = None
        self.files: dict[str, bytes] = {}
        self.modified: dict[str, datetime] = {}
        self.revision = 7
        self.command_result = CommandResult(0, b"stdout", b"stderr")
        self.error: Exception | None = None
        self.search_matches: tuple[SearchMatch, ...] = (
            SearchMatch("a.py", 2, 3, "needle"),
        )

    async def workspace_revision(self) -> int:
        return self.revision

    def _raise(self) -> None:
        if self.error is not None:
            raise self.error

    async def list_tree(self, path: str = ".") -> tuple[FileEntry, ...]:
        self._raise()
        self.called = ("list_tree", path)
        return tuple(FileEntry(f"{path}/{index}", "file", index, NOW) for index in range(3))

    async def stat(self, path: str) -> FileEntry:
        self._raise()
        if path not in self.files:
            raise SandboxPolicyViolation("workspace_path_not_resolvable")
        self.called = ("stat", path)
        return FileEntry(
            path,
            "file",
            len(self.files[path]),
            self.modified.get(path, NOW),
        )

    async def read_file(self, path: str) -> bytes:
        self._raise()
        if path not in self.files:
            raise FileNotFoundError(path)
        self.called = ("read_file", path)
        return self.files[path]

    async def write_file(
        self, path: str, content: bytes, *, parents: bool = False
    ) -> int:
        self._raise()
        parent = str(PurePosixPath(path).parent)
        if parent not in {".", ""} and not parents:
            raise SandboxPolicyViolation("workspace_path_not_resolvable")
        self.files[path] = content
        self.modified[path] = NOW
        self.revision += 1
        self.called = ("write_file", (path, content))
        return self.revision

    async def search_text(self, query: str, **kwargs: Any) -> tuple[SearchMatch, ...]:
        self._raise()
        self.called = ("search_text", (query, kwargs))
        return self.search_matches

    async def glob_files(
        self, pattern: str, *, limit: int = 100, path: str | None = None
    ) -> tuple[str, ...]:
        self._raise()
        self.called = ("glob_files", (pattern, limit, path))
        return (f"{pattern}",)

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
    if name == "execute.v1":
        risk = ToolRisk.COMMAND
    elif name in {"write_file.v1", "edit_file.v1"}:
        risk = ToolRisk.WORKSPACE_WRITE
    elif name == "ask_user.v1":
        risk = ToolRisk.USER_QUESTION
    else:
        risk = ToolRisk.READ_ONLY
    return ValidatedToolCall(name, input, risk)


@pytest.mark.asyncio
async def test_read_file_truncates_and_checksums_original_content() -> None:
    session = FakeSession()
    session.files["a.txt"] = b"abcdef"
    executor = SandboxToolExecutor(max_preview_bytes=4, max_entries=10)
    result = await executor.execute(session, call("read_file.v1", {"path": "a.txt"}))
    numbered = b"     1|abcdef"
    assert result.status == "ok"
    assert result.preview == numbered[:4].decode()
    assert result.original_bytes == 6
    assert result.truncated is True
    assert result.checksum == hashlib.sha256(numbered).hexdigest()
    assert result.workspace_revision == "7"


@pytest.mark.asyncio
async def test_read_file_decodes_invalid_utf8_with_replacement() -> None:
    session = FakeSession()
    session.files["a"] = b"a\xffb"
    result = await SandboxToolExecutor(32, 10).execute(
        session, call("read_file.v1", {"path": "a"})
    )
    assert result.preview == "     1|a\ufffdb"


class RangeFakeSession(FakeSession):
    async def read_file(
        self, path: str, *, offset: int = 1, limit: int | None = None
    ) -> bytes:
        self._raise()
        if path not in self.files:
            raise FileNotFoundError(path)
        self.called = ("read_file", path, offset, limit)
        text = self.files[path].decode("utf-8")
        lines = text.splitlines(keepends=True)
        start = max(offset - 1, 0)
        end = None if limit is None else start + limit
        return "".join(lines[start:end]).encode("utf-8")


@pytest.mark.asyncio
async def test_read_file_offset_limit_uses_cat_n_prefixes() -> None:
    session = FakeSession()
    session.files["lines.txt"] = b"alpha\nbeta\ngamma\n"
    result = await SandboxToolExecutor(64, 10).execute(
        session,
        call("read_file.v1", {"path": "lines.txt", "offset": 2, "limit": 1}),
    )
    assert result.status == "ok"
    assert result.preview == "     2|beta\n"
    assert result.original_bytes == len(b"alpha\nbeta\ngamma\n")
    assert result.truncated is True
    assert result.start_line == 2
    assert result.total_lines == 3
    assert result.unchanged is False


@pytest.mark.asyncio
async def test_read_file_does_not_reslice_sandbox_range() -> None:
    session = RangeFakeSession()
    session.files["lines.txt"] = b"alpha\nbeta\ngamma\n"
    result = await SandboxToolExecutor(64, 10).execute(
        session,
        call("read_file.v1", {"path": "lines.txt", "offset": 2, "limit": 1}),
    )
    assert result.status == "ok"
    assert result.preview == "     2|beta\n"
    assert result.start_line == 2
    assert result.truncated is True


@pytest.mark.asyncio
async def test_read_file_works_when_path_is_seeded() -> None:
    session = FakeSession()
    session.files["seeded.txt"] = b"hello"
    result = await SandboxToolExecutor(64, 10).execute(
        session, call("read_file.v1", {"path": "seeded.txt"})
    )
    assert result.status == "ok"
    assert result.preview == "     1|hello"
    assert result.original_bytes == 5
    assert result.truncated is False
    assert result.start_line == 1
    assert result.total_lines == 1


@pytest.mark.asyncio
async def test_read_file_normalizes_crlf_and_strips_bom() -> None:
    session = FakeSession()
    session.files["win.txt"] = b"\xef\xbb\xbfalpha\r\nbeta\r\n"
    result = await SandboxToolExecutor(64, 10).execute(
        session, call("read_file.v1", {"path": "win.txt"})
    )
    assert result.status == "ok"
    assert result.preview == "     1|alpha\n     2|beta\n"
    assert result.start_line == 1
    assert result.total_lines == 2


@pytest.mark.asyncio
async def test_read_file_returns_unchanged_stub_for_same_range() -> None:
    session = FakeSession()
    session.files["a.txt"] = b"hello\n"
    executor = SandboxToolExecutor(64, 10)
    first = await executor.execute(session, call("read_file.v1", {"path": "a.txt"}))
    second = await executor.execute(session, call("read_file.v1", {"path": "a.txt"}))
    stamps = executor.export_read_stamps()

    assert first.status == "ok"
    assert first.unchanged is False
    assert first.preview == "     1|hello\n"
    assert second.status == "ok"
    assert second.unchanged is True
    assert "unchanged" in second.preview.lower()
    assert "File unchanged since last read." in second.preview
    assert stamps["a.txt"]["offset"] == 1
    assert stamps["a.txt"]["limit"] is None


@pytest.mark.asyncio
async def test_read_file_after_write_is_not_unchanged() -> None:
    session = FakeSession()
    session.files["a.txt"] = b"old"
    executor = SandboxToolExecutor(64, 10)
    await executor.execute(session, call("read_file.v1", {"path": "a.txt"}))
    await executor.execute(
        session, call("write_file.v1", {"path": "a.txt", "content": "new"})
    )
    result = await executor.execute(session, call("read_file.v1", {"path": "a.txt"}))
    assert result.status == "ok"
    assert result.unchanged is False
    assert result.preview == "     1|new"


@pytest.mark.asyncio
async def test_read_file_denies_binary_extension_and_nul() -> None:
    session = FakeSession()
    session.files["photo.PNG"] = b"not-really-png"
    session.files["blob.bin"] = b"head\x00tail"
    executor = SandboxToolExecutor(64, 10)
    image = await executor.execute(session, call("read_file.v1", {"path": "photo.PNG"}))
    session.files["blob"] = b"head\x00tail"
    nul = await executor.execute(session, call("read_file.v1", {"path": "blob"}))

    assert image.status in {"denied", "error"}
    assert image.reason_code in {"policy_binary_file", "error/binary_file", "binary_file"}
    assert nul.status in {"denied", "error"}
    assert nul.reason_code in {"policy_binary_file", "error/binary_file", "binary_file"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "input", "method"),
    [
        ("list_tree.v1", {"path": "src"}, "list_tree"),
        ("stat.v1", {"path": "a.py"}, "stat"),
        ("search_text.v1", {"query": "x", "paths": ["src"], "regex": True, "limit": 4}, "search_text"),
        ("glob_files.v1", {"pattern": "**/*.py", "limit": 12}, "glob_files"),
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
    if name == "stat.v1":
        session.files[str(input["path"])] = b"data"
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
    assert (result.status, result.reason_code) == ("error", "command_failed")


@pytest.mark.asyncio
async def test_execute_git_injects_no_pager_and_no_ext_diff() -> None:
    session = FakeSession()
    result = await SandboxToolExecutor(10, 10).execute(
        session,
        call(
            "execute.v1",
            {
                "argv": ["git", "status", "--short"],
                "cwd": ".",
                "env": {},
                "stdin": "",
                "timeout_sec": 1,
                "max_output_bytes": 10,
            },
        ),
    )

    assert result.status == "ok"
    assert session.called is not None
    request = session.called[1]
    assert request.argv[0] == "git"
    assert "--no-pager" in request.argv
    assert "--no-ext-diff" in request.argv
    assert request.argv.index("--no-pager") < request.argv.index("status")
    assert request.argv.index("--no-ext-diff") < request.argv.index("status")


@pytest.mark.asyncio
async def test_execute_never_serializes_environment_values() -> None:
    result = await SandboxToolExecutor(10, 10).execute(
        FakeSession(),
        call("execute.v1", {"argv": ["pytest", "-q"], "cwd": ".", "env": {"TOKEN": "secret"}, "stdin": "", "timeout_sec": 1, "max_output_bytes": 10}),
    )
    payload = json.dumps(result.to_mapping())
    assert "secret" not in payload
    assert "-q" not in payload
    assert result.audit == {"executable_category": "other"}


@pytest.mark.asyncio
async def test_execute_normalizes_hostile_executable_audit_category() -> None:
    result = await SandboxToolExecutor(10, 10).execute(
        FakeSession(),
        call("execute.v1", {"argv": ["secret-client"], "cwd": ".", "env": {}, "stdin": "", "timeout_sec": 1, "max_output_bytes": 10}),
    )

    assert result.audit == {"executable_category": "other"}


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
@pytest.mark.parametrize(
    "code",
    ["workspace_path_escape", "file_too_large", "policy_secret_path_denied"],
)
async def test_known_sandbox_policy_codes_pass_through(code: str) -> None:
    session = FakeSession()
    session.error = SandboxPolicyViolation(code)
    result = await SandboxToolExecutor(10, 10).execute(
        session, call("read_file.v1", {"path": "a.txt"})
    )
    assert (result.status, result.reason_code) == ("denied", code)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("code", "hint"),
    [
        ("workspace_path_is_not_file", "file"),
        ("workspace_path_escape", "workspace"),
        ("file_too_large", "offset"),
    ],
)
async def test_fs_policy_denial_includes_fix_note(code: str, hint: str) -> None:
    session = FakeSession()
    session.error = SandboxPolicyViolation(code)
    result = await SandboxToolExecutor(10, 10).execute(
        session, call("read_file.v1", {"path": "a.txt"})
    )
    payload = json.dumps(result.to_mapping())
    assert (result.status, result.reason_code) == ("denied", code)
    assert result.fix_note is not None
    assert hint in result.fix_note.casefold()
    assert result.to_mapping()["fix_note"] == result.fix_note
    assert "a.txt" not in result.fix_note
    assert code in payload


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
async def test_search_text_forwards_before_and_after() -> None:
    session = FakeSession()
    result = await SandboxToolExecutor(10, 10).execute(
        session,
        call(
            "search_text.v1",
            {
                "query": "needle",
                "paths": ["src"],
                "regex": False,
                "limit": 10,
                "before": 2,
                "after": 3,
            },
        ),
    )
    assert result.status == "ok"
    forwarded = session.called[1][1]
    assert forwarded["paths"] == ("src",)
    assert forwarded["regex"] is False
    assert forwarded["limit"] == 11
    assert forwarded["before"] == 2
    assert forwarded["after"] == 3
    assert forwarded["output_mode"] == "content"
    assert forwarded["max_columns"] == 500
    assert result.entries == (
        {
            "path": "a.py",
            "line": 2,
            "column": 3,
            "text": "needle",
            "before": (),
            "after": (),
        },
    )


@pytest.mark.asyncio
async def test_search_text_files_mode_returns_unique_paths_only() -> None:
    session = FakeSession()
    session.search_matches = (
        SearchMatch("a.py", 1, 1, "needle"),
        SearchMatch("a.py", 4, 2, "needle"),
        SearchMatch("b.py", 2, 1, "needle"),
    )
    result = await SandboxToolExecutor(10, 10).execute(
        session,
        call(
            "search_text.v1",
            {
                "query": "needle",
                "paths": ["src"],
                "regex": False,
                "limit": 10,
                "output_mode": "files",
            },
        ),
    )

    assert result.status == "ok"
    assert session.called is not None
    assert session.called[1][1]["output_mode"] == "files"
    assert result.entries == ({"path": "a.py"}, {"path": "b.py"})


@pytest.mark.asyncio
async def test_search_text_count_mode_returns_path_and_match_count() -> None:
    session = FakeSession()
    session.search_matches = (
        SearchMatch("a.py", 1, 1, "needle"),
        SearchMatch("a.py", 4, 2, "needle"),
        SearchMatch("b.py", 2, 1, "needle"),
    )
    result = await SandboxToolExecutor(10, 10).execute(
        session,
        call(
            "search_text.v1",
            {
                "query": "needle",
                "paths": ["src"],
                "regex": False,
                "limit": 10,
                "output_mode": "count",
            },
        ),
    )

    assert result.status == "ok"
    assert session.called is not None
    assert session.called[1][1]["output_mode"] == "count"
    assert result.entries == (
        {"path": "a.py", "count": 2},
        {"path": "b.py", "count": 1},
    )


@pytest.mark.asyncio
async def test_search_text_forwards_grep_schema_extras() -> None:
    session = FakeSession()
    result = await SandboxToolExecutor(10, 10).execute(
        session,
        call(
            "search_text.v1",
            {
                "query": "needle",
                "paths": ["src"],
                "regex": False,
                "limit": 10,
                "ignore_case": True,
                "multiline": True,
                "context": 2,
                "path": "src",
            },
        ),
    )
    assert result.status == "ok"
    forwarded = session.called[1][1]
    assert forwarded["ignore_case"] is True
    assert forwarded["multiline"] is True
    assert forwarded["context"] == 2
    assert forwarded["path"] == "src"
    assert forwarded["limit"] == 11
    assert forwarded["max_columns"] == 500


@pytest.mark.asyncio
async def test_search_text_forwards_exclude_and_max_columns() -> None:
    session = FakeSession()
    result = await SandboxToolExecutor(10, 10).execute(
        session,
        call(
            "search_text.v1",
            {
                "query": "needle",
                "paths": ["src"],
                "regex": False,
                "limit": 10,
                "max_columns": 80,
                "exclude": ["**/*.min.js"],
            },
        ),
    )
    assert result.status == "ok"
    forwarded = session.called[1][1]
    assert forwarded["max_columns"] == 80
    assert forwarded["exclude"] == ("**/*.min.js",)


@pytest.mark.asyncio
async def test_search_text_head_limit_sets_truncated() -> None:
    session = FakeSession()
    session.search_matches = (
        SearchMatch("a.py", 1, 1, "needle"),
        SearchMatch("b.py", 2, 1, "needle"),
        SearchMatch("c.py", 3, 1, "needle"),
    )
    result = await SandboxToolExecutor(10, 10).execute(
        session,
        call(
            "search_text.v1",
            {
                "query": "needle",
                "paths": ["**/*"],
                "regex": False,
                "limit": 100,
                "head_limit": 2,
            },
        ),
    )
    assert result.status == "ok"
    forwarded = session.called[1][1]
    assert forwarded["limit"] == 3
    assert [entry["path"] for entry in result.entries] == ["a.py", "b.py"]
    assert result.truncated is True


@pytest.mark.asyncio
async def test_glob_files_forwards_pattern_and_limit() -> None:
    session = FakeSession()
    result = await SandboxToolExecutor(10, 10).execute(
        session, call("glob_files.v1", {"pattern": "**/*.py", "limit": 12})
    )
    assert result.status == "ok"
    assert session.called == ("glob_files", ("**/*.py", 13, None))
    assert result.entries == ({"path": "**/*.py"},)
    assert result.truncated is False


def _allow_web_fetch_host(monkeypatch, host: str = "docs.example.com") -> None:
    monkeypatch.setattr(
        "neos.coding.tools.executor._web_fetch_hosts", lambda: (host,)
    )


def _resolve_web_fetch_ips(monkeypatch, *ips: str) -> None:
    import socket

    def fake_getaddrinfo(host, port, *args, **kwargs):
        results = []
        for ip in ips:
            if ":" in ip:
                results.append(
                    (socket.AF_INET6, socket.SOCK_STREAM, 6, "", (ip, 0, 0, 0))
                )
            else:
                results.append(
                    (socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))
                )
        return results

    monkeypatch.setattr(
        "neos.coding.tools.executor.socket.getaddrinfo", fake_getaddrinfo
    )


@pytest.mark.asyncio
async def test_web_fetch_denied_when_allowlist_empty(monkeypatch) -> None:
    monkeypatch.setattr(
        "neos.coding.tools.executor._web_fetch_hosts", lambda: ()
    )
    result = await SandboxToolExecutor(10, 10).execute(
        FakeSession(),
        call("web_fetch.v1", {"url": "https://example.com/doc"}),
    )
    assert (result.status, result.reason_code) == (
        "denied",
        "policy_web_fetch_host_denied",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query",
    [
        "token=abc",
        "Token=abc",
        "api_key=abc",
        "access_token=abc",
        "password=abc",
        "secret=abc",
        "authorization=abc",
        "key=abc",
        "foo=1&ACCESS_TOKEN=abc",
    ],
)
async def test_web_fetch_blocks_secret_query_param_names(
    monkeypatch, query: str
) -> None:
    _allow_web_fetch_host(monkeypatch)
    _resolve_web_fetch_ips(monkeypatch, "1.2.3.4")
    result = await SandboxToolExecutor(10, 10).execute(
        FakeSession(),
        call(
            "web_fetch.v1",
            {"url": f"https://docs.example.com/doc?{query}"},
        ),
    )
    payload = json.dumps(result.to_mapping())
    assert result.status == "error"
    assert result.reason_code == "web_fetch_blocked"
    assert "1.2.3.4" not in payload
    assert "abc" not in payload


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "ip",
    [
        "169.254.169.254",
        "169.254.1.1",
        "127.0.0.1",
        "0.0.0.1",
        "10.1.2.3",
        "172.16.0.1",
        "192.168.1.8",
        "100.64.0.1",
        "::1",
        "::",
        "fc00::1",
        "fe80::1",
    ],
)
async def test_web_fetch_blocks_resolved_private_and_link_local_ips(
    monkeypatch, ip: str
) -> None:
    _allow_web_fetch_host(monkeypatch)
    _resolve_web_fetch_ips(monkeypatch, ip)
    result = await SandboxToolExecutor(10, 10).execute(
        FakeSession(),
        call("web_fetch.v1", {"url": "https://docs.example.com/doc"}),
    )
    payload = json.dumps(result.to_mapping())
    assert result.status == "error"
    assert result.reason_code == "web_fetch_ssrf"
    assert ip not in payload


@pytest.mark.asyncio
async def test_web_fetch_blocks_if_any_resolved_address_is_private(
    monkeypatch,
) -> None:
    _allow_web_fetch_host(monkeypatch)
    _resolve_web_fetch_ips(monkeypatch, "1.2.3.4", "10.0.0.1")
    result = await SandboxToolExecutor(10, 10).execute(
        FakeSession(),
        call("web_fetch.v1", {"url": "https://docs.example.com/doc"}),
    )
    payload = json.dumps(result.to_mapping())
    assert (result.status, result.reason_code) == ("error", "web_fetch_ssrf")
    assert "10.0.0.1" not in payload
    assert "1.2.3.4" not in payload


@pytest.mark.asyncio
async def test_web_fetch_denies_dns_failure(monkeypatch) -> None:
    import socket

    _allow_web_fetch_host(monkeypatch)

    def fail_getaddrinfo(*args, **kwargs):
        raise socket.gaierror(8, "nodename nor servname provided")

    monkeypatch.setattr(
        "neos.coding.tools.executor.socket.getaddrinfo", fail_getaddrinfo
    )
    result = await SandboxToolExecutor(10, 10).execute(
        FakeSession(),
        call("web_fetch.v1", {"url": "https://docs.example.com/doc"}),
    )
    payload = json.dumps(result.to_mapping())
    assert (result.status, result.reason_code) == ("error", "web_fetch_ssrf")
    assert "nodename" not in payload


@pytest.mark.asyncio
async def test_web_fetch_keeps_scheme_and_empty_allowlist_before_ssrf(
    monkeypatch,
) -> None:
    _allow_web_fetch_host(monkeypatch)
    _resolve_web_fetch_ips(monkeypatch, "1.2.3.4")
    ftp = await SandboxToolExecutor(10, 10).execute(
        FakeSession(),
        call("web_fetch.v1", {"url": "ftp://docs.example.com/doc"}),
    )
    monkeypatch.setattr(
        "neos.coding.tools.executor._web_fetch_hosts", lambda: ()
    )
    empty = await SandboxToolExecutor(10, 10).execute(
        FakeSession(),
        call("web_fetch.v1", {"url": "https://docs.example.com/doc?token=abc"}),
    )
    assert (ftp.status, ftp.reason_code) == (
        "denied",
        "policy_web_fetch_host_denied",
    )
    assert (empty.status, empty.reason_code) == (
        "denied",
        "policy_web_fetch_host_denied",
    )


def _fake_web_response(
    body: bytes,
    url: str = "https://docs.example.com/doc",
    content_type: str = "text/plain",
):
    from email.message import EmailMessage

    class FakeResponse:
        def __init__(self) -> None:
            self.headers = EmailMessage()
            self.headers["Content-Type"] = content_type

        def geturl(self) -> str:
            return url

        def read(self, _n: int = -1) -> bytes:
            return body

        def close(self) -> None:
            return None

    return FakeResponse()


@pytest.mark.asyncio
async def test_web_fetch_disables_env_proxy(monkeypatch) -> None:
    import urllib.request

    seen: list[object] = []

    class FakeOpener:
        def open(self, request, timeout=None):
            del request, timeout
            return _fake_web_response(b"hello")

    def capture(*handlers, **kwargs):
        del kwargs
        seen.extend(handlers)
        return FakeOpener()

    _allow_web_fetch_host(monkeypatch)
    _resolve_web_fetch_ips(monkeypatch, "1.2.3.4")
    monkeypatch.setattr(
        "neos.coding.tools.executor.urllib.request.build_opener", capture
    )
    result = await SandboxToolExecutor(32, 10).execute(
        FakeSession(),
        call("web_fetch.v1", {"url": "https://docs.example.com/doc"}),
    )

    assert result.status == "ok"
    proxies = [
        handler
        for handler in seen
        if isinstance(handler, urllib.request.ProxyHandler)
    ]
    assert proxies
    assert proxies[0].proxies == {}


@pytest.mark.asyncio
async def test_web_fetch_allows_public_allowlisted_host(monkeypatch) -> None:
    class FakeOpener:
        def open(self, request, timeout=None):
            del request, timeout
            return _fake_web_response(b"hello")

    _allow_web_fetch_host(monkeypatch)
    _resolve_web_fetch_ips(monkeypatch, "1.2.3.4")
    monkeypatch.setattr(
        "neos.coding.tools.executor.urllib.request.build_opener",
        lambda *args, **kwargs: FakeOpener(),
    )
    result = await SandboxToolExecutor(32, 10).execute(
        FakeSession(),
        call("web_fetch.v1", {"url": "https://docs.example.com/doc"}),
    )
    assert result.status == "ok"
    assert result.entries == (
        {"url": "https://docs.example.com/doc", "text": "hello"},
    )


@pytest.mark.asyncio
async def test_web_fetch_rejects_userinfo_and_upgrades_http(monkeypatch) -> None:
    opened: list[str] = []

    class FakeOpener:
        def open(self, request, timeout=None):
            del timeout
            opened.append(request.full_url)
            return _fake_web_response(b"hello", url=request.full_url)

    _allow_web_fetch_host(monkeypatch)
    _resolve_web_fetch_ips(monkeypatch, "1.2.3.4")
    monkeypatch.setattr(
        "neos.coding.tools.executor.urllib.request.build_opener",
        lambda *args, **kwargs: FakeOpener(),
    )
    userinfo = await SandboxToolExecutor(32, 10).execute(
        FakeSession(),
        call("web_fetch.v1", {"url": "https://user:pass@docs.example.com/doc"}),
    )
    upgraded = await SandboxToolExecutor(32, 10).execute(
        FakeSession(),
        call("web_fetch.v1", {"url": "http://docs.example.com/doc"}),
    )
    assert userinfo.status in {"denied", "error"}
    assert "userinfo" in userinfo.reason_code or userinfo.reason_code in {
        "web_fetch_blocked",
        "web_fetch_userinfo",
        "policy_web_fetch_userinfo",
    }
    assert upgraded.status == "ok"
    assert opened == ["https://docs.example.com/doc"]


@pytest.mark.asyncio
async def test_web_fetch_rejects_unsupported_type_and_strips_html(
    monkeypatch,
) -> None:
    payloads = [
        _fake_web_response(b"\x89PNG", content_type="image/png"),
        _fake_web_response(
            b"<html><script>alert(1)</script><p>Hello</p></html>",
            content_type="text/html; charset=utf-8",
        ),
    ]

    class FakeOpener:
        def open(self, request, timeout=None):
            del request, timeout
            return payloads.pop(0)

    _allow_web_fetch_host(monkeypatch)
    _resolve_web_fetch_ips(monkeypatch, "1.2.3.4")
    monkeypatch.setattr(
        "neos.coding.tools.executor.urllib.request.build_opener",
        lambda *args, **kwargs: FakeOpener(),
    )
    binary = await SandboxToolExecutor(64, 10).execute(
        FakeSession(),
        call("web_fetch.v1", {"url": "https://docs.example.com/doc"}),
    )
    html = await SandboxToolExecutor(64, 10).execute(
        FakeSession(),
        call("web_fetch.v1", {"url": "https://docs.example.com/doc"}),
    )
    assert (binary.status, binary.reason_code) == (
        "error",
        "web_fetch_unsupported_type",
    )
    assert html.status == "ok"
    text = html.entries[0]["text"]
    assert "Hello" in text
    assert "<p>" not in text
    assert "alert(1)" not in text


@pytest.mark.asyncio
async def test_web_fetch_does_not_follow_redirect_to_private_ip(
    monkeypatch,
) -> None:
    import urllib.error
    from email.message import EmailMessage

    opened: list[str] = []

    class FakeOpener:
        def open(self, request, timeout=None):
            del timeout
            url = request.full_url
            opened.append(url)
            headers = EmailMessage()
            headers["Location"] = "http://169.254.169.254/latest"
            raise urllib.error.HTTPError(
                url, 302, "Found", headers, __import__("io").BytesIO()
            )

    _allow_web_fetch_host(monkeypatch)
    _resolve_web_fetch_ips(monkeypatch, "1.2.3.4")
    monkeypatch.setattr(
        "neos.coding.tools.executor.urllib.request.build_opener",
        lambda *args, **kwargs: FakeOpener(),
    )
    result = await SandboxToolExecutor(10, 10).execute(
        FakeSession(),
        call("web_fetch.v1", {"url": "https://docs.example.com/open"}),
    )
    payload = json.dumps(result.to_mapping())
    assert result.status in {"error", "denied"}
    assert result.reason_code in {"web_fetch_ssrf", "policy_web_fetch_host_denied"}
    assert opened == ["https://docs.example.com/open"]
    assert "169.254" not in payload


@pytest.mark.asyncio
async def test_search_tools_returns_matching_tool_schema() -> None:
    session = FakeSession()
    session.error = SandboxTimeout("search_tools must not touch the sandbox")
    glob_result = await SandboxToolExecutor(10, 10).execute(
        session, call("search_tools.v1", {"query": "glob"})
    )
    spawn_result = await SandboxToolExecutor(10, 10).execute(
        session, call("search_tools.v1", {"query": "spawn"})
    )
    assert glob_result.status == "ok"
    assert spawn_result.status == "ok"
    assert session.called is None
    glob_names = {entry["name"] for entry in glob_result.entries}
    spawn_names = {entry["name"] for entry in spawn_result.entries}
    assert "glob_files.v1" in glob_names or "spawn_agent.v1" in spawn_names
    match = next(
        entry
        for entry in (*glob_result.entries, *spawn_result.entries)
        if entry["name"] in {"glob_files.v1", "spawn_agent.v1"}
    )
    assert "description" in match
    assert "input_schema" in match


@pytest.mark.asyncio
async def test_spawn_agent_returns_delegated_without_sandbox_io() -> None:
    session = FakeSession()
    session.error = SandboxTimeout("spawn_agent must not write")
    result = await SandboxToolExecutor(10, 10).execute(
        session,
        call("spawn_agent.v1", {"prompt": "find the bug", "max_turns": 3}),
    )
    assert (result.status, result.reason_code) == ("ok", "ok")
    assert session.called is None
    assert result.entries == ({"delegated": True},)


@pytest.mark.asyncio
async def test_todo_write_returns_ok_entries_without_sandbox_io() -> None:
    session = FakeSession()
    session.error = SandboxTimeout("todo_write must not touch the sandbox")
    todos = [
        {"id": "t1", "content": "Read the file", "status": "in_progress"},
        {"content": "Edit the file", "status": "pending"},
        {"content": "Run tests", "status": "completed"},
    ]
    result = await SandboxToolExecutor(10, 10).execute(
        session, call("todo_write.v1", {"todos": todos})
    )

    assert (result.status, result.reason_code) == ("ok", "ok")
    assert session.called is None
    assert result.entries == (
        {"id": "t1", "content": "Read the file", "status": "in_progress"},
        {"content": "Edit the file", "status": "pending"},
        {"content": "Run tests", "status": "completed"},
    )


@pytest.mark.asyncio
async def test_set_phase_returns_ok_entries_without_sandbox_io() -> None:
    session = FakeSession()
    session.error = SandboxTimeout("set_phase must not touch the sandbox")
    result = await SandboxToolExecutor(10, 10).execute(
        session, call("set_phase.v1", {"phase": "explore"})
    )

    assert (result.status, result.reason_code) == ("ok", "ok")
    assert session.called is None
    assert result.entries == ({"phase": "explore"},)


@pytest.mark.asyncio
async def test_ask_user_returns_ok_entries_without_sandbox_io() -> None:
    session = FakeSession()
    session.error = SandboxTimeout("ask_user must not touch the sandbox")
    questions = ["Which runner?", "Keep the hook?"]
    result = await SandboxToolExecutor(10, 10).execute(
        session, call("ask_user.v1", {"questions": questions})
    )

    assert (result.status, result.reason_code) == ("ok", "ok")
    assert session.called is None
    assert result.entries[0]["questions"] == questions
    assert result.entries[0]["answers"] == []
    assert result.entries[0]["pairs"][0]["question"] == "Which runner?"


@pytest.mark.asyncio
async def test_load_skill_verify_returns_bundled_markdown() -> None:
    session = FakeSession()
    session.error = SandboxTimeout("load_skill must not touch the sandbox")
    result = await SandboxToolExecutor(10, 10).execute(
        session, call("load_skill.v1", {"name": "verify"})
    )

    assert (result.status, result.reason_code) == ("ok", "ok")
    assert session.called is None
    text = json.dumps(result.to_mapping())
    assert "Do not skip hooks" in text or "hooks" in text


@pytest.mark.asyncio
async def test_load_skill_unknown_name_is_denied() -> None:
    result = await SandboxToolExecutor(10, 10).execute(
        FakeSession(), call("load_skill.v1", {"name": "foo"})
    )

    assert result.status == "denied"
    assert result.reason_code == "unknown_skill"


@pytest.mark.asyncio
async def test_load_skill_research_name_is_not_on_coding_catalog() -> None:
    session = FakeSession()
    session.error = SandboxTimeout("load_skill must not touch the sandbox")
    result = await SandboxToolExecutor(10, 10).execute(
        session, call("load_skill.v1", {"name": "pdf"})
    )

    assert (result.status, result.reason_code) == ("denied", "unknown_skill")
    assert session.called is None


@pytest.mark.asyncio
async def test_load_skill_path_traversal_is_denied() -> None:
    result = await SandboxToolExecutor(10, 10).execute(
        FakeSession(), call("load_skill.v1", {"name": "../../../etc/passwd"})
    )

    assert (result.status, result.reason_code) == ("denied", "unknown_skill")



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


@pytest.mark.asyncio
async def test_write_new_path_succeeds_without_prior_read() -> None:
    session = FakeSession()
    result = await SandboxToolExecutor(10, 10).execute(
        session, call("write_file.v1", {"path": "new.txt", "content": "hi"})
    )
    assert result.status == "ok"
    assert session.files["new.txt"] == b"hi"
    assert session.called == ("write_file", ("new.txt", b"hi"))
    assert result.workspace_revision == "8"


@pytest.mark.asyncio
async def test_write_existing_path_without_read_is_denied() -> None:
    session = FakeSession()
    session.files["exists.txt"] = b"old"
    result = await SandboxToolExecutor(10, 10).execute(
        session, call("write_file.v1", {"path": "exists.txt", "content": "new"})
    )
    assert (result.status, result.reason_code) == (
        "denied",
        "precondition_read_required",
    )
    assert session.files["exists.txt"] == b"old"
    assert session.called is None or session.called[0] != "write_file"


@pytest.mark.asyncio
async def test_write_existing_path_after_stale_read_is_denied() -> None:
    session = FakeSession()
    session.files["exists.txt"] = b"old"
    executor = SandboxToolExecutor(64, 10)
    await executor.execute(session, call("read_file.v1", {"path": "exists.txt"}))
    session.files["exists.txt"] = b"changed-on-disk"
    session.modified["exists.txt"] = datetime(2026, 8, 1, tzinfo=UTC)

    result = await executor.execute(
        session, call("write_file.v1", {"path": "exists.txt", "content": "new"})
    )

    assert (result.status, result.reason_code) == (
        "denied",
        "precondition_stale_read",
    )
    assert session.files["exists.txt"] == b"changed-on-disk"


async def test_write_existing_path_after_read_succeeds() -> None:
    session = FakeSession()
    session.files["exists.txt"] = b"old"
    executor = SandboxToolExecutor(64, 10)
    read = await executor.execute(
        session, call("read_file.v1", {"path": "exists.txt"})
    )
    assert read.status == "ok"
    result = await executor.execute(
        session, call("write_file.v1", {"path": "exists.txt", "content": "new"})
    )
    assert result.status == "ok"
    assert session.files["exists.txt"] == b"new"
    assert result.workspace_revision == "8"


@pytest.mark.asyncio
async def test_edit_unique_old_string_after_read_replaces_once() -> None:
    session = FakeSession()
    session.files["app.py"] = b"foo bar foo"
    executor = SandboxToolExecutor(64, 10)
    await executor.execute(session, call("read_file.v1", {"path": "app.py"}))
    result = await executor.execute(
        session,
        call(
            "edit_file.v1",
            {"path": "app.py", "old_string": "bar", "new_string": "baz"},
        ),
    )
    assert result.status == "ok"
    assert session.files["app.py"] == b"foo baz foo"
    assert result.workspace_revision == "8"


@pytest.mark.asyncio
async def test_edit_non_unique_old_string_without_replace_all_is_denied() -> None:
    session = FakeSession()
    session.files["app.py"] = b"foo foo"
    executor = SandboxToolExecutor(64, 10)
    await executor.execute(session, call("read_file.v1", {"path": "app.py"}))
    result = await executor.execute(
        session,
        call(
            "edit_file.v1",
            {"path": "app.py", "old_string": "foo", "new_string": "bar"},
        ),
    )
    assert (result.status, result.reason_code) == (
        "denied",
        "edit_old_string_not_unique",
    )
    assert result.matches == 2
    assert session.files["app.py"] == b"foo foo"


@pytest.mark.asyncio
async def test_edit_noop_old_equals_new_is_denied() -> None:
    session = FakeSession()
    session.files["app.py"] = b"foo"
    executor = SandboxToolExecutor(64, 10)
    await executor.execute(session, call("read_file.v1", {"path": "app.py"}))
    result = await executor.execute(
        session,
        call(
            "edit_file.v1",
            {"path": "app.py", "old_string": "foo", "new_string": "foo"},
        ),
    )
    assert (result.status, result.reason_code) == ("denied", "edit_noop")
    assert session.files["app.py"] == b"foo"


@pytest.mark.asyncio
async def test_edit_missing_old_string_is_denied() -> None:
    session = FakeSession()
    session.files["app.py"] = b"foo"
    executor = SandboxToolExecutor(64, 10)
    await executor.execute(session, call("read_file.v1", {"path": "app.py"}))
    result = await executor.execute(
        session,
        call(
            "edit_file.v1",
            {"path": "app.py", "old_string": "zzz", "new_string": "bar"},
        ),
    )
    assert (result.status, result.reason_code) == (
        "denied",
        "edit_old_string_not_found",
    )
    assert session.files["app.py"] == b"foo"


@pytest.mark.asyncio
async def test_edit_without_prior_read_is_denied() -> None:
    session = FakeSession()
    session.files["app.py"] = b"foo"
    result = await SandboxToolExecutor(64, 10).execute(
        session,
        call(
            "edit_file.v1",
            {"path": "app.py", "old_string": "foo", "new_string": "bar"},
        ),
    )
    assert (result.status, result.reason_code) == (
        "denied",
        "precondition_read_required",
    )
    assert session.files["app.py"] == b"foo"


@pytest.mark.asyncio
async def test_edit_empty_old_string_creates_missing_or_empty_file() -> None:
    session = FakeSession()
    executor = SandboxToolExecutor(64, 10)
    created = await executor.execute(
        session,
        call(
            "edit_file.v1",
            {"path": "new.py", "old_string": "", "new_string": "print(1)\n"},
        ),
    )
    session.files["empty.py"] = b""
    await executor.execute(session, call("read_file.v1", {"path": "empty.py"}))
    filled = await executor.execute(
        session,
        call(
            "edit_file.v1",
            {"path": "empty.py", "old_string": "", "new_string": "ok\n"},
        ),
    )

    assert created.status == "ok"
    assert session.files["new.py"] == b"print(1)\n"
    assert filled.status == "ok"
    assert session.files["empty.py"] == b"ok\n"


@pytest.mark.asyncio
async def test_edit_empty_old_string_denies_existing_nonempty_file() -> None:
    session = FakeSession()
    session.files["app.py"] = b"already here"
    executor = SandboxToolExecutor(64, 10)
    await executor.execute(session, call("read_file.v1", {"path": "app.py"}))
    result = await executor.execute(
        session,
        call(
            "edit_file.v1",
            {"path": "app.py", "old_string": "", "new_string": "new\n"},
        ),
    )

    assert (result.status, result.reason_code) == ("denied", "edit_create_existing")
    assert session.files["app.py"] == b"already here"


@pytest.mark.asyncio
async def test_edit_empty_new_string_deletes_following_newline() -> None:
    session = FakeSession()
    session.files["app.py"] = b"keep\nremove\nnext\n"
    executor = SandboxToolExecutor(64, 10)
    await executor.execute(session, call("read_file.v1", {"path": "app.py"}))
    result = await executor.execute(
        session,
        call(
            "edit_file.v1",
            {"path": "app.py", "old_string": "remove", "new_string": ""},
        ),
    )

    assert result.status == "ok"
    assert session.files["app.py"] == b"keep\nnext\n"


@pytest.mark.asyncio
async def test_edit_matches_crlf_text_and_restores_original_eol() -> None:
    session = FakeSession()
    session.files["win.txt"] = b"alpha\r\nbeta\r\n"
    executor = SandboxToolExecutor(64, 10)
    await executor.execute(session, call("read_file.v1", {"path": "win.txt"}))
    result = await executor.execute(
        session,
        call(
            "edit_file.v1",
            {"path": "win.txt", "old_string": "beta", "new_string": "gamma"},
        ),
    )

    assert result.status == "ok"
    assert session.files["win.txt"] == b"alpha\r\ngamma\r\n"


@pytest.mark.asyncio
async def test_edit_replace_all_replaces_every_occurrence() -> None:
    session = FakeSession()
    session.files["app.py"] = b"foo foo"
    executor = SandboxToolExecutor(64, 10)
    await executor.execute(session, call("read_file.v1", {"path": "app.py"}))
    result = await executor.execute(
        session,
        call(
            "edit_file.v1",
            {
                "path": "app.py",
                "old_string": "foo",
                "new_string": "bar",
                "replace_all": True,
            },
        ),
    )
    assert result.status == "ok"
    assert session.files["app.py"] == b"bar bar"


@pytest.mark.asyncio
async def test_known_reads_allow_write_on_a_fresh_executor() -> None:
    session = FakeSession()
    session.files["exists.txt"] = b"old"
    first = SandboxToolExecutor(64, 10)
    await first.execute(session, call("read_file.v1", {"path": "exists.txt"}))
    second = SandboxToolExecutor(64, 10)
    denied = await second.execute(
        session, call("write_file.v1", {"path": "exists.txt", "content": "new"})
    )
    allowed = await second.execute(
        session,
        call("write_file.v1", {"path": "exists.txt", "content": "new"}),
        known_reads=frozenset({"exists.txt"}),
    )
    assert (denied.status, denied.reason_code) == (
        "denied",
        "precondition_read_required",
    )
    assert allowed.status == "ok"
    assert session.files["exists.txt"] == b"new"


@pytest.mark.asyncio
async def test_write_after_hydrate_from_known_stamps_denies_stale_read() -> None:
    session = FakeSession()
    session.files["exists.txt"] = b"changed-on-disk"
    session.modified["exists.txt"] = datetime(2026, 8, 1, tzinfo=UTC)
    result = await SandboxToolExecutor(64, 10).execute(
        session,
        call("write_file.v1", {"path": "exists.txt", "content": "new"}),
        known_reads=frozenset({"exists.txt"}),
        known_stamps={
            "exists.txt": {
                "mtime": NOW.isoformat(),
                "digest": hashlib.sha256(b"old").hexdigest(),
                "full": True,
            }
        },
    )
    assert (result.status, result.reason_code) == (
        "denied",
        "precondition_stale_read",
    )
    assert session.files["exists.txt"] == b"changed-on-disk"


@pytest.mark.asyncio
async def test_write_after_hydrate_from_partial_stamp_is_denied() -> None:
    session = FakeSession()
    session.files["exists.txt"] = b"old"
    result = await SandboxToolExecutor(64, 10).execute(
        session,
        call("write_file.v1", {"path": "exists.txt", "content": "new"}),
        known_reads=frozenset({"exists.txt"}),
        known_stamps={
            "exists.txt": {
                "mtime": NOW.isoformat(),
                "digest": hashlib.sha256(b"old").hexdigest(),
                "full": False,
            }
        },
    )
    assert (result.status, result.reason_code) == (
        "denied",
        "precondition_read_required",
    )
    assert session.files["exists.txt"] == b"old"


@pytest.mark.asyncio
async def test_memory_sandbox_write_creates_new_file_without_prior_read(
    tmp_path,
) -> None:
    from neos.coding.sandbox.base import SandboxLimits
    from neos.coding.sandbox.memory import MemorySandboxProvider

    provider = MemorySandboxProvider(root=tmp_path)
    sandbox = await provider.create(
        owner_id="u1", limits=SandboxLimits.safe_defaults()
    )
    session = await provider.open_session(sandbox.sandbox_id)
    result = await SandboxToolExecutor(64, 10).execute(
        session, call("write_file.v1", {"path": "created.py", "content": "ok\n"})
    )
    assert result.status == "ok"
    assert await session.read_file("created.py") == b"ok\n"
    await provider.close()


def test_tool_result_to_mapping_includes_retryable_and_fix() -> None:
    ok = ToolResult.ok(workspace_revision="1")
    mapping = ok.to_mapping()
    assert mapping["retryable"] is False
    assert mapping["fix"] is None

    failed = ToolResult(
        "error",
        "sandbox_not_found",
        None,
        None,
        False,
        None,
        "unknown",
        retryable=True,
        fix={"parents": True},
    )
    failed_mapping = failed.to_mapping()
    assert failed_mapping["retryable"] is True
    assert failed_mapping["fix"] == {"parents": True}
    json.dumps(failed_mapping)


@pytest.mark.asyncio
async def test_execute_merges_retryable_fix_once_into_same_call() -> None:
    class FixOnceExecutor(SandboxToolExecutor):
        def __init__(self) -> None:
            super().__init__(10, 10)
            self.seen: list[tuple[str, dict[str, object]]] = []

        async def _execute(self, session, call, *, known_reads):
            payload = dict(call.input)
            self.seen.append((call.name, payload))
            if payload.get("parents") is True:
                return ToolResult.ok(workspace_revision="8")
            return ToolResult(
                "error",
                "sandbox_not_found",
                None,
                None,
                False,
                None,
                "unknown",
                retryable=True,
                fix={"parents": True},
            )

    executor = FixOnceExecutor()
    result = await executor.execute(
        FakeSession(),
        call("write_file.v1", {"path": "nested/a.txt", "content": "hi"}),
    )

    assert result.status == "ok"
    assert executor.seen == [
        ("write_file.v1", {"path": "nested/a.txt", "content": "hi"}),
        (
            "write_file.v1",
            {"path": "nested/a.txt", "content": "hi", "parents": True},
        ),
    ]


@pytest.mark.asyncio
async def test_execute_stops_when_retried_call_repeats_reason_code() -> None:
    class AlwaysRetryableExecutor(SandboxToolExecutor):
        def __init__(self) -> None:
            super().__init__(10, 10)
            self.seen: list[dict[str, object]] = []

        async def _execute(self, session, call, *, known_reads):
            self.seen.append(dict(call.input))
            return ToolResult(
                "error",
                "sandbox_not_found",
                None,
                None,
                False,
                None,
                "unknown",
                retryable=True,
                fix={"parents": True},
            )

    executor = AlwaysRetryableExecutor()
    result = await executor.execute(
        FakeSession(),
        call("write_file.v1", {"path": "nested/a.txt", "content": "hi"}),
    )

    assert (result.status, result.reason_code) == ("error", "sandbox_not_found")
    assert result.retryable is True
    assert result.fix == {"parents": True}
    assert executor.seen == [
        {"path": "nested/a.txt", "content": "hi"},
        {"path": "nested/a.txt", "content": "hi", "parents": True},
    ]


@pytest.mark.asyncio
async def test_write_missing_parent_is_retryable_and_retries_with_parents_fix() -> None:
    session = FakeSession()
    result = await SandboxToolExecutor(10, 10).execute(
        session,
        call("write_file.v1", {"path": "nested/a.txt", "content": "hi"}),
    )

    assert result.status == "ok"
    assert session.files["nested/a.txt"] == b"hi"
    assert session.called == ("write_file", ("nested/a.txt", b"hi"))
    assert result.workspace_revision == "8"


@pytest.mark.asyncio
async def test_write_missing_parent_retries_against_memory_session(
    tmp_path,
) -> None:
    from neos.coding.sandbox.base import SandboxLimits
    from neos.coding.sandbox.memory import MemorySandboxProvider

    provider = MemorySandboxProvider(root=tmp_path)
    sandbox = await provider.create(
        owner_id="u1", limits=SandboxLimits.safe_defaults()
    )
    inner = await provider.open_session(sandbox.sandbox_id)

    class TrackingSession:
        def __init__(self) -> None:
            self.parents_seen: list[bool] = []

        def __getattr__(self, name: str) -> Any:
            return getattr(inner, name)

        async def write_file(
            self, path: str, content: bytes, *, parents: bool = True
        ) -> int:
            self.parents_seen.append(parents)
            return await inner.write_file(path, content, parents=parents)

    session = TrackingSession()
    result = await SandboxToolExecutor(10, 10).execute(
        session,
        call("write_file.v1", {"path": "nested/a.txt", "content": "hi"}),
    )

    assert result.status == "ok"
    assert session.parents_seen == [False, True]
    assert await inner.read_file("nested/a.txt") == b"hi"
    assert result.workspace_revision == "1"
    await provider.close()


@pytest.mark.asyncio
async def test_edit_missing_parent_is_retryable_and_retries_with_parents_fix() -> None:
    session = FakeSession()
    session.files["nested/app.py"] = b"foo"
    executor = SandboxToolExecutor(64, 10)
    await executor.execute(session, call("read_file.v1", {"path": "nested/app.py"}))
    result = await executor.execute(
        session,
        call(
            "edit_file.v1",
            {
                "path": "nested/app.py",
                "old_string": "foo",
                "new_string": "bar",
            },
        ),
    )

    assert result.status == "ok"
    assert session.files["nested/app.py"] == b"bar"
    assert result.workspace_revision == "8"


@pytest.mark.asyncio
async def test_write_missing_parent_second_failure_does_not_loop() -> None:
    class AlwaysMissingParentSession(FakeSession):
        def __init__(self) -> None:
            super().__init__()
            self.writes: list[tuple[str, bool]] = []

        async def write_file(self, path: str, content: bytes) -> int:
            self.writes.append((path, False))
            raise SandboxPolicyViolation("workspace_path_not_resolvable")

    session = AlwaysMissingParentSession()
    result = await SandboxToolExecutor(10, 10).execute(
        session,
        call("write_file.v1", {"path": "nested/a.txt", "content": "hi"}),
    )

    assert (result.status, result.reason_code) == (
        "error",
        "workspace_path_not_resolvable",
    )
    assert result.retryable is True
    assert result.fix == {"parents": True}
    assert "workspace_path_not_resolvable" in json.dumps(result.to_mapping())
    assert session.writes == [
        ("nested/a.txt", False),
        ("nested/a.txt", False),
    ]


@pytest.mark.asyncio
async def test_execute_does_not_retry_without_fix_or_when_not_retryable() -> None:
    class RecordingExecutor(SandboxToolExecutor):
        def __init__(self, result: ToolResult) -> None:
            super().__init__(10, 10)
            self.result = result
            self.calls = 0

        async def _execute(self, session, call, *, known_reads):
            self.calls += 1
            return self.result

    retryable_without_fix = RecordingExecutor(
        ToolResult(
            "error",
            "sandbox_not_found",
            None,
            None,
            False,
            None,
            "unknown",
            retryable=True,
        )
    )
    nonretryable_with_fix = RecordingExecutor(
        ToolResult(
            "error",
            "sandbox_not_found",
            None,
            None,
            False,
            None,
            "unknown",
            retryable=False,
            fix={"parents": True},
        )
    )

    first = await retryable_without_fix.execute(
        FakeSession(), call("write_file.v1", {"path": "a", "content": "x"})
    )
    second = await nonretryable_with_fix.execute(
        FakeSession(), call("write_file.v1", {"path": "a", "content": "x"})
    )

    assert first.retryable is True
    assert first.fix is None
    assert second.retryable is False
    assert second.fix == {"parents": True}
    assert retryable_without_fix.calls == 1
    assert nonretryable_with_fix.calls == 1


class HashingSession(FakeSession):
    def __init__(self) -> None:
        super().__init__()
        self.read_calls: list[str] = []
        self.hash_calls: list[str] = []

    async def read_file(self, path: str) -> bytes:
        self.read_calls.append(path)
        raise SandboxPolicyViolation("file_read_limit_exceeded")

    async def hash_file(self, path: str) -> str:
        self.hash_calls.append(path)
        return hashlib.sha256(self.files[path]).hexdigest()

    async def read_file_for_edit(self, path: str) -> bytes:
        return self.files[path]


@pytest.mark.asyncio
async def test_stale_since_read_uses_hash_not_preview_read() -> None:
    session = HashingSession()
    session.files["big.txt"] = b"changed-on-disk" + (b"x" * 80)
    session.modified["big.txt"] = datetime(2026, 8, 1, tzinfo=UTC)
    result = await SandboxToolExecutor(64, 10).execute(
        session,
        call("write_file.v1", {"path": "big.txt", "content": "new"}),
        known_reads=frozenset({"big.txt"}),
        known_stamps={
            "big.txt": {
                "mtime": NOW.isoformat(),
                "digest": hashlib.sha256(b"old").hexdigest(),
                "full": True,
            }
        },
    )

    assert (result.status, result.reason_code) == (
        "denied",
        "precondition_stale_read",
    )
    assert session.hash_calls == ["big.txt"]
    assert session.read_calls == []


@pytest.mark.asyncio
async def test_edit_uses_edit_read_not_preview_cap() -> None:
    session = HashingSession()
    session.files["big.txt"] = b"alpha beta"
    session.modified["big.txt"] = NOW
    result = await SandboxToolExecutor(64, 10).execute(
        session,
        call(
            "edit_file.v1",
            {"path": "big.txt", "old_string": "beta", "new_string": "gamma"},
        ),
        known_reads=frozenset({"big.txt"}),
        known_stamps={
            "big.txt": {
                "mtime": NOW.isoformat(),
                "digest": hashlib.sha256(b"alpha beta").hexdigest(),
                "full": True,
            }
        },
    )

    assert result.status == "ok"
    assert session.files["big.txt"] == b"alpha gamma"
    assert session.read_calls == []
