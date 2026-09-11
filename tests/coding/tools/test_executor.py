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
        self.files: dict[str, bytes] = {}
        self.revision = 7
        self.command_result = CommandResult(0, b"stdout", b"stderr")
        self.error: Exception | None = None

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
        return FileEntry(path, "file", len(self.files[path]), NOW)

    async def read_file(self, path: str) -> bytes:
        self._raise()
        if path not in self.files:
            raise FileNotFoundError(path)
        self.called = ("read_file", path)
        return self.files[path]

    async def write_file(self, path: str, content: bytes) -> int:
        self._raise()
        self.files[path] = content
        self.revision += 1
        self.called = ("write_file", (path, content))
        return self.revision

    async def search_text(self, query: str, **kwargs: Any) -> tuple[SearchMatch, ...]:
        self._raise()
        self.called = ("search_text", (query, kwargs))
        return (SearchMatch("a.py", 2, 3, "needle"),)

    async def glob_files(self, pattern: str, *, limit: int = 100) -> tuple[str, ...]:
        self._raise()
        self.called = ("glob_files", (pattern, limit))
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
    assert session.called == (
        "search_text",
        (
            "needle",
            {
                "paths": ("src",),
                "regex": False,
                "limit": 10,
                "before": 2,
                "after": 3,
            },
        ),
    )


@pytest.mark.asyncio
async def test_glob_files_forwards_pattern_and_limit() -> None:
    session = FakeSession()
    result = await SandboxToolExecutor(10, 10).execute(
        session, call("glob_files.v1", {"pattern": "**/*.py", "limit": 12})
    )
    assert result.status == "ok"
    assert session.called == ("glob_files", ("**/*.py", 12))
    assert result.entries == ({"path": "**/*.py"},)


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
async def test_load_skill_pdf_returns_catalog_markdown() -> None:
    session = FakeSession()
    session.error = SandboxTimeout("load_skill must not touch the sandbox")
    result = await SandboxToolExecutor(10, 10).execute(
        session, call("load_skill.v1", {"name": "pdf"})
    )

    assert (result.status, result.reason_code) == ("ok", "ok")
    assert session.called is None
    assert result.entries is not None
    entry = result.entries[0]
    assert entry["name"] == "pdf"
    assert "PDF" in str(entry["markdown"])


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
    assert session.files["app.py"] == b"foo foo"


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
