from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from neos.coding.model.base import ToolDefinition
from neos.coding.sandbox.base import SandboxPolicyViolation
from neos.coding.sandbox.paths import (
    ensure_mutable_workspace_path,
    normalize_workspace_path,
)

_CONTROL_PLANE_TOOLS = frozenset(
    {"subagent_list.v1", "subagent_steer.v1", "await_subagent.v1"}
)
_STEER_TEXT_MAX = 2000
_DEDICATED_EXECUTE_DENY = frozenset(
    {
        "cat",
        "tac",
        "head",
        "tail",
        "less",
        "more",
        "nl",
        "rg",
        "grep",
        "egrep",
        "fgrep",
        "ag",
        "ack",
        "find",
        "fd",
        "fdfind",
        "sed",
        "awk",
        "mkdir",
        "rm",
        "rmdir",
        "mv",
        "chmod",
    }
)
_DEDICATED_TOOL_FOR = {
    "cat": "read_file.v1",
    "tac": "read_file.v1",
    "head": "read_file.v1",
    "tail": "read_file.v1",
    "less": "read_file.v1",
    "more": "read_file.v1",
    "nl": "read_file.v1",
    "rg": "search_text.v1",
    "grep": "search_text.v1",
    "egrep": "search_text.v1",
    "fgrep": "search_text.v1",
    "ag": "search_text.v1",
    "ack": "search_text.v1",
    "find": "glob_files.v1",
    "fd": "glob_files.v1",
    "fdfind": "glob_files.v1",
    "sed": "edit_file.v1",
    "awk": "edit_file.v1",
    "mkdir": "mkdir.v1",
    "rm": "rm.v1",
    "rmdir": "rm.v1",
    "mv": "mv.v1",
    "chmod": "chmod.v1",
}
_POLICY_FIX_NOTES = {
    "policy_inline_interpreter_denied": "run a file with execute.v1, not -c/-e",
    "policy_command_path_denied": "use a workspace-relative path",
    "policy_secret_path_denied": "do not pass secret paths",
    "policy_executable_path_denied": "use a bare executable name",
    "policy_git_operation_denied": "git via execute is status/diff/log only",
    "policy_shell_command_denied": "use argv execute, not a shell -c",
    "policy_network_client_denied": "network clients are not allowed",
    "policy_network_operation_denied": "package install/update is not allowed",
    "policy_dangerous_removal": "refusing a destructive rm operand",
    "policy_executable_not_allowed": "executable is not on the allowlist",
    "policy_protected_git_path": "do not mutate .git",
    "policy_workspace_path_escape": "use a workspace-relative path",
    "policy_workspace_secret_path": "secret paths are not readable",
    "policy_media_tool_disabled": "this optional tool is not enabled",
    "policy_notebook_required": "use notebook_edit.v1 for .ipynb",
    "policy_use_read_image": "use read_image.v1 for images",
    "policy_use_read_pdf": "use read_pdf.v1 for PDFs",
    "policy_browser_use_fill_secret": "use browser_fill_secret.v1 for secrets",
    "policy_browser_secret_disabled": "stored secrets are not enabled",
}
_EXECUTE_WRAPPERS = frozenset(
    {
        "env",
        "busybox",
        "xargs",
        "timeout",
        "nice",
        "nohup",
        "time",
        "stdbuf",
        "command",
    }
)
_PACKAGE_RUNNERS = frozenset({"pnpm", "npm", "yarn", "npx"})
_INLINE_INTERPRETERS = frozenset(
    {"python", "python3", "node", "nodejs", "perl", "ruby", "php", "lua"}
)
_REMOVAL_EXECUTABLES = frozenset({"rm", "rmdir"})
_DANGEROUS_REMOVAL_OPERANDS = frozenset({"/", "/*", "*", "~"})
_DURATION_TOKEN = re.compile(r"^\d+(?:\.\d+)?[smhd]?$")


def is_path_like_operand(
    value: object, *, allow_leading_dash: bool = False
) -> bool:
    if not isinstance(value, str) or not value:
        return False
    if value.startswith("-") and not allow_leading_dash:
        return False
    if value.startswith("."):
        return True
    return "/" in value.replace("\\", "/")


def path_operands_from_argv(argv: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    operands: list[str] = []
    positional = False
    for part in tuple(argv)[1:]:
        if part == "--":
            positional = True
            continue
        if not positional and part.startswith("-") and "=" in part:
            value = part.split("=", 1)[1]
            if is_path_like_operand(value):
                operands.append(value)
            continue
        if is_path_like_operand(part, allow_leading_dash=positional):
            operands.append(part)
    return tuple(operands)


def _command_name(value: str) -> str:
    return PurePosixPath(value).name


def _next_wrapped_command_index(
    wrapper: str, rest: tuple[str, ...]
) -> int | None:
    if wrapper not in _EXECUTE_WRAPPERS:
        return None
    skip_duration = wrapper == "timeout"
    for index, part in enumerate(rest):
        if part == "--":
            return index + 1 if index + 1 < len(rest) else None
        if part.startswith("-"):
            continue
        if wrapper == "env" and "=" in part:
            continue
        if skip_duration and _DURATION_TOKEN.fullmatch(part):
            skip_duration = False
            continue
        return index
    return None


def _package_exec_command_index(name: str, rest: tuple[str, ...]) -> int | None:
    if name not in _PACKAGE_RUNNERS:
        return None
    take_next = False
    for index, part in enumerate(rest):
        if part == "--":
            continue
        if take_next:
            if part.startswith("-"):
                continue
            return index
        if part in {"exec", "dlx"}:
            take_next = True
    return None


def _unwrapped_command_names(argv: tuple[str, ...]) -> tuple[str, ...]:
    if not argv:
        return ()
    names: list[str] = []
    index = 0
    while index < len(argv):
        name = _command_name(argv[index])
        names.append(name)
        rest = argv[index + 1 :]
        next_index = _next_wrapped_command_index(name, rest)
        if next_index is not None:
            index = index + 1 + next_index
            continue
        package_index = _package_exec_command_index(name, rest)
        if package_index is not None:
            index = index + 1 + package_index
            continue
        break
    return tuple(names)


def _command_operands(argv: tuple[str, ...]) -> tuple[str, ...]:
    operands: list[str] = []
    positional = False
    for part in argv[1:]:
        if part == "--":
            positional = True
            continue
        if not positional:
            if part.startswith("-") and "=" in part:
                operands.append(part.split("=", 1)[1])
                continue
            if part.startswith("-"):
                continue
        operands.append(part)
    return tuple(operands)


def _is_git_dangerous_flag(token: str) -> bool:
    if token.startswith("--"):
        return token.startswith("--config-env") or token.startswith("--exec-path")
    return token.startswith("-c")


def _is_inline_interpreter_flag(token: str) -> bool:
    if token.startswith("--eval"):
        return True
    if token.startswith("--"):
        return False
    return (
        token.startswith("-c")
        or token.startswith("-e")
        or token.startswith("-p")
    )


def _subcommand_after(argv: tuple[str, ...], executable: str) -> str | None:
    seen = False
    for part in argv:
        if not seen:
            if _command_name(part) == executable:
                seen = True
            continue
        if part.startswith("-"):
            continue
        return _command_name(part)
    return None


_NUMERIC_MODE = re.compile(r"^0?[0-7]{3,4}$")


def _parse_numeric_mode(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ToolValidationError("policy_schema_invalid")
    if isinstance(value, int):
        if value < 0 or value > 0o7777:
            raise ToolValidationError("policy_schema_invalid")
        return value
    if not _NUMERIC_MODE.fullmatch(value):
        raise ToolValidationError("policy_schema_invalid")
    return int(value, 8)


def _dedicated_tool_fix_note(name: str) -> str:
    tool = _DEDICATED_TOOL_FOR.get(name, "a dedicated tool")
    return f"use {tool} instead of {name}"


def _policy_fix_note(reason_code: str) -> str | None:
    return _POLICY_FIX_NOTES.get(reason_code)


def _operand_escapes_workspace(value: str) -> bool:
    if value.startswith("/") or value.startswith("~"):
        return True
    parts = [
        part
        for part in value.replace("\\", "/").split("/")
        if part not in {"", "."}
    ]
    return ".." in parts


def _definition_match(tool: _RegisteredTool) -> dict[str, object]:
    definition = tool.definition()
    return {
        "name": definition.name,
        "description": definition.description,
        "input_schema": definition.input_schema,
    }


def _select_query_names(query: str) -> tuple[str, ...] | None:
    raw = query.strip()
    if not raw.lower().startswith("select:"):
        return None
    return tuple(part.strip() for part in raw.split(":", 1)[1].split(",") if part.strip())


def _search_query_terms(query: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    required: list[str] = []
    optional: list[str] = []
    for token in query.split():
        if token.startswith("+") and len(token) > 1:
            required.append(token[1:].casefold())
        elif token:
            optional.append(token.casefold())
    return tuple(required), tuple(optional)


#: 트랙 Q14a -- 에이전트 브라우저. 둘로 나눈 이유는 사용자 규칙(Q2)이 **도구 이름**으로
#: 맞추기 때문이다: 소유자가 탐색은 allow 하고 비밀 입력은 계속 승인받게 할 수 있어야 한다.
BROWSER_TOOL = "browser.v1"
BROWSER_SECRET_TOOL = "browser_fill_secret.v1"
BROWSER_TOOL_NAMES = frozenset({BROWSER_TOOL, BROWSER_SECRET_TOOL})

_OPTIONAL_TOOL_FLAGS = {
    "notebook_edit.v1": "notebook_edit",
    "read_image.v1": "image_tool",
    "read_pdf.v1": "pdf_tool",
    "web_search.v1": "web_search",
    BROWSER_TOOL: "browser.enabled",
    BROWSER_SECRET_TOOL: "browser.enabled",
}


def _subagent_tools_enabled() -> bool:
    try:
        from neos.config.settings import settings

        return bool(settings.config.coding_model.subagent_enabled)
    except Exception:
        return False


def optional_tool_enabled(name: str) -> bool:
    field = _OPTIONAL_TOOL_FLAGS.get(name)
    if field is None:
        return False
    try:
        from neos.config.settings import settings

        if "." not in field:
            return bool(getattr(settings.config.coding_model, field, False))
        # 중첩 섹션(트랙 Q14a `browser.enabled`)은 진짜 `True` 만 켠다 -- 가짜 설정
        # 객체의 아무 속성이나 참으로 읽혀 도구가 열리지 않게.
        value: object = settings.config.coding_model
        for part in field.split("."):
            value = getattr(value, part, False)
        return value is True
    except Exception:
        return False


class ToolRisk(StrEnum):
    READ_ONLY = "read_only"
    WORKSPACE_WRITE = "workspace_write"
    COMMAND = "command"
    USER_QUESTION = "user_question"


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    allowed: bool
    reason_code: str
    fix_note: str | None = None


@dataclass(frozen=True, slots=True)
class ValidatedToolCall:
    name: str
    input: Mapping[str, object]
    risk: ToolRisk
    #: 입력 밖에서 이 호출이 풀 비밀 -- 커넥터 서버 설정의 `secret://`(트랙 Q11a, M7).
    #: 게이트는 `carries_secret_refs` 한 판정으로 본다. 내장 도구는 늘 비어 있다.
    secret_refs: tuple[str, ...] = ()


class ToolValidationError(ValueError):
    def __init__(self, reason_code: str, *, fix_note: str | None = None) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code
        self.fix_note = fix_note


class _ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _PathInput(_ToolInput):
    path: str


class _ListTreeInput(_ToolInput):
    path: str = "."


class _SearchTextInput(_ToolInput):
    query: str = Field(min_length=1)
    paths: list[str] = Field(default_factory=lambda: ["**/*"], min_length=1)
    exclude: list[str] = Field(default_factory=list)
    regex: bool = False
    limit: int = Field(default=100, ge=1, le=250)
    head_limit: int | None = Field(default=None, ge=1, le=250)
    before: int = Field(default=0, ge=0, le=20)
    after: int = Field(default=0, ge=0, le=20)
    ignore_case: bool = False
    multiline: bool = False
    context: int = Field(default=0, ge=0, le=20)
    path: str | None = None
    output_mode: Literal["files", "content", "count"] = "content"
    max_columns: int = Field(default=500, ge=0, le=8192)


class _GlobFilesInput(_ToolInput):
    pattern: str = Field(min_length=1)
    limit: int = Field(default=100, ge=1, le=500)
    path: str | None = None


class _WebFetchInput(_ToolInput):
    url: str = Field(min_length=1)


class _WebSearchInput(_ToolInput):
    query: str = Field(min_length=2, max_length=500)
    max_results: int | None = Field(default=None, ge=1, le=10)


#: `aria_snapshot(mode="ai")` 가 붙이는 `[ref=e12]`(iframe 안이면 `f1e12`).
_BROWSER_REF = r"^(?:f[0-9]{1,4})?e[0-9]{1,7}$"


class _BrowserInput(_ToolInput):
    action: Literal["navigate", "snapshot", "click", "type", "close"]
    url: str | None = Field(default=None, min_length=1, max_length=2048)
    ref: str | None = Field(default=None, pattern=_BROWSER_REF)
    text: str | None = Field(default=None, max_length=2000)
    submit: bool = False


class _BrowserFillSecretInput(_ToolInput):
    ref: str = Field(pattern=_BROWSER_REF)
    secret: str = Field(min_length=10, max_length=80)
    origin: str = Field(min_length=9, max_length=300)
    submit: bool = False


#: 행동마다 받는 필드. 그 밖의 필드가 값을 가지면 스키마 거절이다.
_BROWSER_ACTION_FIELDS = {
    "navigate": frozenset({"url"}),
    "snapshot": frozenset(),
    "click": frozenset({"ref"}),
    "type": frozenset({"ref", "text", "submit"}),
    "close": frozenset(),
}


def browser_origin(value: object) -> str | None:
    """`https://Example.com:443/` -> `https://example.com`. 경로·질의·사용자 정보가 있으면 None."""
    if not isinstance(value, str):
        return None
    from urllib.parse import urlsplit

    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError:
        return None
    host = (parts.hostname or "").rstrip(".")
    if (
        parts.scheme != "https"
        or not host
        or parts.username is not None
        or parts.password is not None
        or parts.path not in {"", "/"}
        or parts.query
        or parts.fragment
    ):
        return None
    return f"https://{host}" if port in {None, 443} else f"https://{host}:{port}"


class _ReadImageInput(_PathInput):
    pass


class _ReadPdfInput(_PathInput):
    pages: str | None = None


class _NotebookEditInput(_PathInput):
    new_source: str = ""
    cell_id: str | None = None
    cell_type: Literal["code", "markdown"] | None = None
    edit_mode: Literal["replace", "insert", "delete"] = "replace"


class _SearchToolsInput(_ToolInput):
    query: str = Field(min_length=1)


class _SpawnAgentInput(_ToolInput):
    prompt: str = Field(min_length=1)
    max_turns: int = Field(default=4, ge=1, le=8)
    spec: str = Field(default="explore")
    why: str = Field(default="", max_length=2000)
    already_tried: list[str] = Field(default_factory=list)
    scope: str = Field(default="", max_length=2000)
    success: str = Field(default="", max_length=2000)
    report_budget: int = Field(default=4000, ge=256, le=16384)


class _SubagentListInput(_ToolInput):
    pass


class _SubagentSteerInput(_ToolInput):
    run_id: str = Field(min_length=1)
    text: str = Field(min_length=1, max_length=_STEER_TEXT_MAX)


class _AwaitSubagentInput(_ToolInput):
    run_id: str = Field(min_length=1)


class _EmptyInput(_ToolInput):
    pass


class _GitDiffInput(_ToolInput):
    staged: bool = False


class _GitLogInput(_ToolInput):
    limit: int = Field(default=20, ge=1, le=100)


class _ReadFileInput(_PathInput):
    offset: int = Field(default=1, ge=1)
    limit: int | None = Field(default=None, ge=1, le=5000)


class _EditFileInput(_PathInput):
    old_string: str
    new_string: str
    replace_all: bool = False


class _WriteFileInput(_PathInput):
    content: str
    parents: bool = False


class _MkdirInput(_PathInput):
    parents: bool = False


class _RmInput(_PathInput):
    recursive: bool = False


class _MvInput(_ToolInput):
    src: str
    dest: str
    overwrite: bool = False


class _ChmodInput(_PathInput):
    mode: int | str


class _TodoItem(_ToolInput):
    id: str | None = None
    content: str = Field(min_length=1)
    status: Literal["pending", "in_progress", "completed"]


class _TodoWriteInput(_ToolInput):
    todos: list[_TodoItem] = Field(min_length=1)


class _ExecuteInput(_ToolInput):
    argv: list[str] = Field(min_length=1, max_length=256)
    cwd: str = "."
    env: dict[str, str] = Field(default_factory=dict)
    stdin: str = ""
    timeout_sec: float = Field(default=30, gt=0)
    max_output_bytes: int = Field(default=1024 * 1024, gt=0)


class _SetPhaseInput(_ToolInput):
    phase: Literal["explore", "plan", "implement", "verify"]


class _AskUserOption(_ToolInput):
    label: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=240)


class _AskUserQuestion(_ToolInput):
    prompt: str = Field(min_length=1, max_length=500)
    options: list[_AskUserOption] = Field(min_length=2, max_length=4)
    multi_select: bool = False


class _AskUserInput(_ToolInput):
    questions: list[str | _AskUserQuestion] = Field(min_length=1, max_length=4)


class _LoadSkillInput(_ToolInput):
    name: str = Field(min_length=1, max_length=64)
    reference: str | None = None
    path: str | None = None


@dataclass(frozen=True, slots=True)
class _RegisteredTool:
    name: str
    description: str
    risk: ToolRisk
    schema: type[_ToolInput]

    def definition(self, *, deferred: bool = False) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            input_schema=self.schema.model_json_schema(),
            deferred=deferred,
        )


class CodingToolRegistry:
    _TOOL_SPECS: ClassVar[tuple[_RegisteredTool, ...]] = (
        _RegisteredTool(
            "list_tree.v1",
            (
                "List a workspace directory. Use this to inspect entries before choosing a path. "
                "Do not use this to read file contents (`read_file.v1`). "
                "On policy_* denial, do not retry the same path."
            ),
            ToolRisk.READ_ONLY,
            _ListTreeInput,
        ),
        _RegisteredTool(
            "stat.v1",
            (
                "Inspect workspace path metadata only. "
                "Prefer this over reading a whole file just to see size. "
                "Do not use this to read file contents. "
                "On policy_* denial, do not retry the same path."
            ),
            ToolRisk.READ_ONLY,
            _PathInput,
        ),
        _RegisteredTool(
            "read_file.v1",
            (
                "Read a workspace file. Use offset/limit for large files. "
                "Existing files must be read before edit_file.v1 or write_file.v1. "
                "Do not use execute.v1 to print file contents. "
                "On policy_* denial, do not retry the same path."
            ),
            ToolRisk.READ_ONLY,
            _ReadFileInput,
        ),
        _RegisteredTool(
            "search_text.v1",
            (
                "Search workspace text. Use this instead of a shell search. "
                "output_mode files returns unique paths; count returns path + match count. "
                "max_columns caps each match line in bytes (0 = no cap). "
                "head_limit caps returned entries and sets truncated when more remain. "
                "exclude skips matching globs. "
                "Do not use execute.v1 with rg/grep/find. "
                "On policy_* denial, do not retry the same query."
            ),
            ToolRisk.READ_ONLY,
            _SearchTextInput,
        ),
        _RegisteredTool(
            "glob_files.v1",
            (
                "Find workspace paths by glob pattern. Use this instead of find. "
                "Do not use execute.v1 with find. "
                "On policy_* denial, do not retry the same pattern."
            ),
            ToolRisk.READ_ONLY,
            _GlobFilesInput,
        ),
        _RegisteredTool(
            "git_status.v1",
            (
                "Read Git status. Prefer this over execute.v1 git. "
                "Do not use execute.v1 for status. "
                "On policy_* denial, do not retry the same call."
            ),
            ToolRisk.READ_ONLY,
            _EmptyInput,
        ),
        _RegisteredTool(
            "git_diff.v1",
            (
                "Read Git diff. Prefer this over execute.v1 git. "
                "Do not use execute.v1 for diff. "
                "On policy_* denial, do not retry the same call."
            ),
            ToolRisk.READ_ONLY,
            _GitDiffInput,
        ),
        _RegisteredTool(
            "git_log.v1",
            (
                "Read Git history. Prefer this over execute.v1 git. "
                "Do not use execute.v1 for log. "
                "On policy_* denial, do not retry the same call."
            ),
            ToolRisk.READ_ONLY,
            _GitLogInput,
        ),
        _RegisteredTool(
            "web_fetch.v1",
            (
                "Fetch an allowlisted http(s) URL as text. "
                "Only allowlisted hosts; do not use execute.v1 curl. "
                "On policy_* denial, do not retry the same url."
            ),
            ToolRisk.READ_ONLY,
            _WebFetchInput,
        ),
        _RegisteredTool(
            "web_search.v1",
            (
                "Search the public web for current pages. "
                "Returns titles, URLs, and untrusted snippets. "
                "Do not use execute.v1 curl. Prefer web_fetch.v1 to read one URL. "
                "On policy_* denial, do not retry the same query."
            ),
            ToolRisk.READ_ONLY,
            _WebSearchInput,
        ),
        _RegisteredTool(
            BROWSER_TOOL,
            (
                "Drive a private headless browser on allowlisted https hosts "
                "(one session per task, gone when the task ends). "
                "action: navigate(url) | snapshot | click(ref) | "
                "type(ref, text, submit) | close. Returns an untrusted page "
                "snapshot; its [ref=eN] marks are the refs for click/type. "
                "Never type passwords or tokens: use browser_fill_secret.v1. "
                "Prefer web_fetch.v1 to read one page. "
                "On policy_* denial, do not retry the same url."
            ),
            ToolRisk.COMMAND,
            _BrowserInput,
        ),
        _RegisteredTool(
            BROWSER_SECRET_TOOL,
            (
                "Type a stored secret (secret://<name>) into a field on the "
                "current browser page without seeing it. origin must equal the "
                "page's origin, e.g. https://github.com. Needs the user's "
                "approval or their allow rule. On denial, do not retry."
            ),
            ToolRisk.COMMAND,
            _BrowserFillSecretInput,
        ),
        _RegisteredTool(
            "read_image.v1",
            (
                "Read a workspace jpeg/png/gif/webp image. "
                "Do not use read_file.v1 or execute.v1 for images. "
                "On policy_* denial, do not retry the same path."
            ),
            ToolRisk.READ_ONLY,
            _ReadImageInput,
        ),
        _RegisteredTool(
            "read_pdf.v1",
            (
                "Extract text from a workspace PDF. "
                "pages is 1-based, e.g. 1-5. At most 20 pages per call. "
                "Do not use read_file.v1 or execute.v1 for PDFs. "
                "On policy_* denial, do not retry the same path."
            ),
            ToolRisk.READ_ONLY,
            _ReadPdfInput,
        ),
        _RegisteredTool(
            "notebook_edit.v1",
            (
                "Edit one Jupyter notebook cell (replace, insert, or delete). "
                "Path must be .ipynb. Do not use edit_file.v1 on notebooks. "
                "Does not execute cells. "
                "On policy_* denial, do not retry the same cell."
            ),
            ToolRisk.WORKSPACE_WRITE,
            _NotebookEditInput,
        ),
        _RegisteredTool(
            "edit_file.v1",
            (
                "Exact string replace in a workspace file. "
                "old_string must be unique unless replace_all. Read first. "
                "Prefer edit over write for existing files. "
                "On policy_* denial, do not retry the same old_string."
            ),
            ToolRisk.WORKSPACE_WRITE,
            _EditFileInput,
        ),
        _RegisteredTool(
            "write_file.v1",
            (
                "Create or replace an entire workspace file. "
                "Existing files require a prior read_file.v1 in this sandbox. "
                "Prefer edit_file.v1 for partial edits. "
                "Do not add unrequested README/docs. "
                "On policy_* denial, do not retry the same path."
            ),
            ToolRisk.WORKSPACE_WRITE,
            _WriteFileInput,
        ),
        _RegisteredTool(
            "mkdir.v1",
            (
                "Create a workspace directory. parents defaults to false. "
                "Do not use execute.v1 mkdir. "
                "On policy_* denial, do not retry the same path."
            ),
            ToolRisk.WORKSPACE_WRITE,
            _MkdirInput,
        ),
        _RegisteredTool(
            "rm.v1",
            (
                "Remove a workspace file or empty directory. "
                "recursive defaults to false and is required for a non-empty directory. "
                "Do not use execute.v1 rm. "
                "On policy_* denial, do not retry the same path."
            ),
            ToolRisk.WORKSPACE_WRITE,
            _RmInput,
        ),
        _RegisteredTool(
            "mv.v1",
            (
                "Move or rename a workspace path. overwrite defaults to false. "
                "Do not use execute.v1 mv. "
                "On policy_* denial, do not retry the same src."
            ),
            ToolRisk.WORKSPACE_WRITE,
            _MvInput,
        ),
        _RegisteredTool(
            "chmod.v1",
            (
                "Change a workspace path mode. Numeric mode only. "
                "Do not use execute.v1 chmod. "
                "On policy_* denial, do not retry the same path."
            ),
            ToolRisk.WORKSPACE_WRITE,
            _ChmodInput,
        ),
        _RegisteredTool(
            "todo_write.v1",
            (
                "Replace the coding-task checklist. "
                "Use this for 3+ step work. "
                "Do not use this for a one-line edit. "
                "On policy_* denial, do not retry the same todos."
            ),
            ToolRisk.READ_ONLY,
            _TodoWriteInput,
        ),
        _RegisteredTool(
            "execute.v1",
            (
                "Run an allowlisted argv command. argv only. "
                "No sh|bash|zsh -c. No network clients. No package install. "
                "git via execute is status/diff/log only. Prefer dedicated tools. "
                "On policy_* denial, do not retry the same argv."
            ),
            ToolRisk.COMMAND,
            _ExecuteInput,
        ),
        _RegisteredTool(
            "set_phase.v1",
            (
                "Set the coding-agent phase to explore, plan, implement, or verify. "
                "explore and plan hide write and execute tools. verify hides writes. "
                "Moving to implement from explore, plan, or verify needs approval. "
                "Do not use this to bypass a policy_* denial. "
                "On policy_* denial, do not retry the same phase."
            ),
            ToolRisk.READ_ONLY,
            _SetPhaseInput,
        ),
        _RegisteredTool(
            "ask_user.v1",
            (
                "Ask the user 1-4 preference questions and wait for answers. "
                "Each question may be a string or {prompt, options[2-4], multi_select}. "
                "Requires approval. Do not assume the answer. "
                "Do not use execute.v1 to pose questions. "
                "On policy_* denial, do not retry the same questions."
            ),
            ToolRisk.USER_QUESTION,
            _AskUserInput,
        ),
        _RegisteredTool(
            "load_skill.v1",
            (
                "Load a catalog skill by name (verify, commit, or any indexed "
                "markdown skill). Returns the skill markdown. Do not skip hooks. "
                "Do not invent skill names. "
                "On policy_* denial, do not retry the same name."
            ),
            ToolRisk.READ_ONLY,
            _LoadSkillInput,
        ),
        _RegisteredTool(
            "search_tools.v1",
            (
                "Search registered coding tools by name or description. "
                "Use this to discover deferred tools before calling them. "
                "On policy_* denial, do not retry the same query."
            ),
            ToolRisk.READ_ONLY,
            _SearchToolsInput,
        ),
        _RegisteredTool(
            "spawn_agent.v1",
            (
                "Spawn an explore child, or spec=implement for an isolated "
                "worktree write worker. Parent merges. "
                "On policy_* denial, do not retry the same prompt."
            ),
            ToolRisk.READ_ONLY,
            _SpawnAgentInput,
        ),
        _RegisteredTool(
            "subagent_list.v1",
            (
                "List live explore children of this parent. "
                "Returns run_id, spec, status, and turn_count only. "
                "On policy_* denial, do not retry."
            ),
            ToolRisk.READ_ONLY,
            _SubagentListInput,
        ),
        _RegisteredTool(
            "subagent_steer.v1",
            (
                "Append text to the next user message of a parent-owned child. "
                "Does not interrupt the current child step. "
                "On policy_* denial, do not retry the same run."
            ),
            ToolRisk.READ_ONLY,
            _SubagentSteerInput,
        ),
        _RegisteredTool(
            "await_subagent.v1",
            (
                "Block on a parent-owned child until it finishes and return "
                "its report here. Without this the report arrives on its own "
                "as a message. On policy_* denial, do not retry the same run."
            ),
            ToolRisk.READ_ONLY,
            _AwaitSubagentInput,
        ),
    )

    _CORE_TOOL_NAMES: ClassVar[frozenset[str]] = frozenset(
        {
            "read_file.v1",
            "search_text.v1",
            "glob_files.v1",
            "list_tree.v1",
            "stat.v1",
            "edit_file.v1",
            "write_file.v1",
            "mkdir.v1",
            "rm.v1",
            "mv.v1",
            "chmod.v1",
            "execute.v1",
            "todo_write.v1",
            "set_phase.v1",
            "ask_user.v1",
            "load_skill.v1",
            "search_tools.v1",
        }
    )

    def __init__(
        self,
        *,
        command_allowlist: frozenset[str],
        max_command_timeout_sec: float,
        max_command_output_bytes: int,
        max_command_stdin_bytes: int,
        allowed_env_names: frozenset[str],
        secret_env_refs: bool = False,
        connectors: Any = None,
    ) -> None:
        if (
            max_command_timeout_sec <= 0
            or max_command_output_bytes < 1
            or max_command_stdin_bytes < 1
        ):
            raise ValueError("command policy limits must be positive")
        # 브라우저(트랙 Q14a)가 꺼져 있으면 이름 자체를 모른다 -- 오늘과 같은 레지스트리다.
        self._tools = {
            tool.name: tool
            for tool in self._TOOL_SPECS
            if tool.name not in BROWSER_TOOL_NAMES or optional_tool_enabled(tool.name)
        }
        self._command_allowlist = command_allowlist
        self._max_command_timeout_sec = max_command_timeout_sec
        self._max_command_output_bytes = max_command_output_bytes
        self._max_command_stdin_bytes = max_command_stdin_bytes
        self._allowed_env_names = allowed_env_names
        # 트랙 Q6: 켜져 있으면 `secret://<name>` 값을 실은 변수는 허용 목록 밖이어도
        # 받는다 -- 이름은 `secret_env_name_allowed` 가, 비밀과의 묶임은 실행기가 본다.
        self._secret_env_refs = secret_env_refs
        # 트랙 Q11a: 위험을 선언한 MCP 도구(`ConnectorCatalog`). `None` 이 off 다 --
        # 그러면 도구 목록·검증이 오늘과 같다(M10).
        self._connectors = connectors

    @classmethod
    def default(
        cls,
        *,
        command_allowlist: frozenset[str],
        max_command_timeout_sec: float = 30,
        max_command_output_bytes: int = 1024 * 1024,
        max_command_stdin_bytes: int = 1024 * 1024,
        allowed_env_names: frozenset[str] = frozenset(),
        secret_env_refs: bool = False,
        connectors: Any = None,
    ) -> CodingToolRegistry:
        return cls(
            command_allowlist=command_allowlist,
            max_command_timeout_sec=max_command_timeout_sec,
            max_command_output_bytes=max_command_output_bytes,
            max_command_stdin_bytes=max_command_stdin_bytes,
            allowed_env_names=allowed_env_names,
            secret_env_refs=secret_env_refs,
            connectors=connectors,
        )

    def _connector_definitions(self) -> tuple[ToolDefinition, ...]:
        """커넥터 도구는 내장 도구 **뒤에** 붙는다. 단계로 숨기지 않는다(M12)."""
        if self._connectors is None:
            return ()
        return tuple(
            ToolDefinition(
                name=tool.name,
                description=tool.description,
                input_schema=tool.input_schema,
            )
            for tool in self._connectors.tools
        )

    def definitions(
        self,
        *,
        phase: str = "implement",
        revealed: frozenset[str] | None = None,
        declare_deferred: bool = False,
    ) -> tuple[ToolDefinition, ...]:
        from neos.coding.phases import hidden_tools_for_phase

        hidden = hidden_tools_for_phase(phase)
        revealed_names = revealed or frozenset()
        deferred = frozenset(self.deferred_tool_names(phase=phase))
        if declare_deferred:
            # Every tool is declared once, so the array stops changing. A
            # deferred tool is hidden by `defer_loading` rather than by
            # absence, and revealing it appends a message instead of
            # rewriting `tools[]` -- which is what keeps replayed thinking
            # valid (K2b). `revealed` deliberately does not appear here:
            # if it did, the array would churn again on the first reveal.
            return tuple(
                tool.definition(deferred=tool.name in deferred)
                for tool in self._TOOL_SPECS
                if tool.name not in hidden
                and (
                    tool.name not in _OPTIONAL_TOOL_FLAGS
                    or optional_tool_enabled(tool.name)
                )
                and (
                    tool.name in self._CORE_TOOL_NAMES
                    or optional_tool_enabled(tool.name)
                    or tool.name in deferred
                )
            ) + self._connector_definitions()
        return tuple(
            tool.definition()
            for tool in self._TOOL_SPECS
            if tool.name not in hidden
            and (
                tool.name not in _OPTIONAL_TOOL_FLAGS
                or optional_tool_enabled(tool.name)
            )
            and (
                tool.name in self._CORE_TOOL_NAMES
                or optional_tool_enabled(tool.name)
                or tool.name in revealed_names
            )
            and (
                tool.name in self._CORE_TOOL_NAMES
                or optional_tool_enabled(tool.name)
                or tool.name in deferred
                or tool.name in revealed_names
            )
        ) + self._connector_definitions()

    @classmethod
    def deferred_tool_names(
        cls,
        *,
        phase: str | None = None,
        subagent_enabled: bool | None = None,
    ) -> tuple[str, ...]:
        from neos.coding.phases import hidden_tools_for_phase

        hidden = hidden_tools_for_phase(phase) if phase is not None else frozenset()
        advertised = (
            _subagent_tools_enabled()
            if subagent_enabled is None
            else bool(subagent_enabled)
        )
        names: list[str] = []
        for tool in cls._TOOL_SPECS:
            if tool.name in cls._CORE_TOOL_NAMES or tool.name in hidden:
                continue
            if tool.name in _OPTIONAL_TOOL_FLAGS:
                continue
            if tool.name in _CONTROL_PLANE_TOOLS and not advertised:
                continue
            names.append(tool.name)
        return tuple(names)

    @classmethod
    def search_definitions(
        cls,
        query: str,
        *,
        limit: int = 8,
        phase: str = "implement",
        subagent_enabled: bool | None = None,
    ) -> tuple[Mapping[str, object], ...]:
        candidates = cls._deferred_tools(
            phase=phase, subagent_enabled=subagent_enabled
        )
        selected = _select_query_names(query)
        matches: list[Mapping[str, object]] = []
        if selected is not None:
            wanted = {name.casefold() for name in selected}
            for tool in candidates:
                if tool.name.casefold() not in wanted:
                    continue
                matches.append(_definition_match(tool))
                if len(matches) >= limit:
                    break
            return tuple(matches)

        required, optional = _search_query_terms(query)
        for tool in candidates:
            haystack = f"{tool.name}\n{tool.description}".casefold()
            if any(term not in haystack for term in required):
                continue
            if optional and any(term not in haystack for term in optional):
                continue
            if not required and not optional:
                continue
            matches.append(_definition_match(tool))
            if len(matches) >= limit:
                break
        return tuple(matches)

    @classmethod
    def _deferred_tools(
        cls, *, phase: str, subagent_enabled: bool | None = None
    ) -> tuple[_RegisteredTool, ...]:
        allowed = frozenset(
            cls.deferred_tool_names(phase=phase, subagent_enabled=subagent_enabled)
        )
        return tuple(tool for tool in cls._TOOL_SPECS if tool.name in allowed)

    def decide(
        self, name: str, input: Mapping[str, object]
    ) -> PolicyDecision:
        try:
            self.validate(name, input)
        except ToolValidationError as error:
            return PolicyDecision(
                False,
                error.reason_code,
                fix_note=error.fix_note or _policy_fix_note(error.reason_code),
            )
        return PolicyDecision(True, "policy_allowed")

    def validate(
        self, name: str, input: Mapping[str, object]
    ) -> ValidatedToolCall:
        tool = self._tools.get(name)
        if tool is None and self._connectors is not None:
            connector = self._connectors.get(name)
            if connector is not None:
                return self._validate_connector(connector, input)
        if tool is None or (
            name in BROWSER_TOOL_NAMES and not optional_tool_enabled(name)
        ):
            raise ToolValidationError("policy_unknown_tool")
        if name in _OPTIONAL_TOOL_FLAGS and not optional_tool_enabled(name):
            raise ToolValidationError("policy_media_tool_disabled")
        candidate = dict(input)
        if name == "execute.v1":
            candidate.setdefault(
                "timeout_sec", self._max_command_timeout_sec
            )
            candidate.setdefault(
                "max_output_bytes", self._max_command_output_bytes
            )
        try:
            parsed = tool.schema.model_validate(candidate)
        except ValidationError as error:
            raise ToolValidationError("policy_schema_invalid") from error
        data: dict[str, Any] = parsed.model_dump()
        if name == "spawn_agent.v1":
            provided = set(candidate)
            for key in (
                "spec",
                "why",
                "already_tried",
                "scope",
                "success",
                "report_budget",
            ):
                if key not in provided:
                    data.pop(key, None)
        self._normalize_paths(name, data)
        if name == "chmod.v1":
            data["mode"] = _parse_numeric_mode(data["mode"])
            self._deny_secret_world_writable(data)
        if name == "search_text.v1" and data["regex"]:
            try:
                re.compile(data["query"])
            except re.error as error:
                raise ToolValidationError("policy_schema_invalid") from error
        if name == "execute.v1":
            self._validate_command(data)
        if name in BROWSER_TOOL_NAMES:
            self._validate_browser(name, candidate, data)
        risk = tool.risk
        if name == "spawn_agent.v1" and str(data.get("spec") or "explore") == "implement":
            risk = ToolRisk.WORKSPACE_WRITE
        return ValidatedToolCall(name=name, input=data, risk=risk)

    @staticmethod
    def _validate_connector(connector: Any, input: Mapping[str, object]) -> ValidatedToolCall:
        """위험은 운영자가 선언한 것 그대로다(M4). 서버의 스키마로 인자를 검사한다."""
        try:
            data = connector.validate_arguments(input)
        except ValueError as error:
            raise ToolValidationError("policy_schema_invalid") from error
        return ValidatedToolCall(
            name=connector.name,
            input=data,
            risk=connector.risk,
            secret_refs=tuple(connector.secret_refs),
        )

    def _normalize_paths(self, name: str, data: dict[str, Any]) -> None:
        try:
            raw_path = data.get("path")
            if isinstance(raw_path, str):
                normalizer = (
                    ensure_mutable_workspace_path
                    if name
                    in {
                        "write_file.v1",
                        "edit_file.v1",
                        "notebook_edit.v1",
                        "mkdir.v1",
                        "rm.v1",
                        "chmod.v1",
                    }
                    else normalize_workspace_path
                )
                data["path"] = str(normalizer(raw_path))
            for key in ("src", "dest"):
                raw = data.get(key)
                if isinstance(raw, str):
                    data[key] = str(ensure_mutable_workspace_path(raw))
            self._deny_secret_write_paths(name, data)
            if "pattern" in data:
                data["pattern"] = str(normalize_workspace_path(data["pattern"]))
            if "paths" in data:
                data["paths"] = [
                    str(normalize_workspace_path(path)) for path in data["paths"]
                ]
            if "exclude" in data:
                data["exclude"] = [
                    str(normalize_workspace_path(path)) for path in data["exclude"]
                ]
            if "cwd" in data:
                data["cwd"] = str(normalize_workspace_path(data["cwd"]))
        except SandboxPolicyViolation as error:
            code = str(error)
            if code == "protected_git_path":
                raise ToolValidationError("policy_protected_git_path") from error
            raise ToolValidationError(f"policy_{code}") from error

    def _deny_secret_write_paths(self, name: str, data: dict[str, Any]) -> None:
        from neos.coding.domain.approvals import is_denied_secret_path

        if name not in {"mkdir.v1", "rm.v1", "mv.v1"}:
            return
        candidates = [data.get("path"), data.get("src"), data.get("dest")]
        if any(
            isinstance(path, str) and is_denied_secret_path(path)
            for path in candidates
        ):
            raise ToolValidationError("policy_secret_path_denied")

    def _deny_secret_world_writable(self, data: dict[str, Any]) -> None:
        from neos.coding.domain.approvals import is_denied_secret_path

        path = data.get("path")
        mode = data.get("mode")
        if (
            isinstance(path, str)
            and isinstance(mode, int)
            and is_denied_secret_path(path)
            and mode & 0o002
        ):
            raise ToolValidationError("policy_secret_path_denied")

    def _validate_browser(
        self, name: str, provided: Mapping[str, object], data: dict[str, Any]
    ) -> None:
        """트랙 Q14a. 행동마다 받는 필드만 받는다 -- 남는 필드는 조용히 버리지 않는다."""
        from neos.coding.secrets import secret_ref_name

        if name == BROWSER_SECRET_TOOL:
            # 비밀은 금고(Q6)에서만 온다. 브로커가 꺼져 있으면 풀 금고가 없다.
            if not self._secret_env_refs:
                raise ToolValidationError("policy_browser_secret_disabled")
            if secret_ref_name(data["secret"]) is None:
                raise ToolValidationError("policy_schema_invalid")
            origin = browser_origin(data["origin"])
            if origin is None:
                raise ToolValidationError("policy_schema_invalid")
            data["origin"] = origin
            return
        action = str(data["action"])
        wanted = _BROWSER_ACTION_FIELDS[action]
        given = {
            key
            for key in ("url", "ref", "text", "submit")
            if key in provided and provided[key] not in (None, False)
        }
        required = wanted - {"submit"}
        if given - wanted or required - given:
            raise ToolValidationError("policy_schema_invalid")
        if action == "type" and secret_ref_name(data["text"]) is not None:
            raise ToolValidationError("policy_browser_use_fill_secret")

    def _env_entry_allowed(self, key: str, value: str) -> bool:
        if key in self._allowed_env_names:
            return True
        if not self._secret_env_refs:
            return False
        from neos.coding.secrets import secret_env_name_allowed, secret_ref_name

        return secret_ref_name(value) is not None and secret_env_name_allowed(key)

    def _validate_command(self, data: dict[str, Any]) -> None:
        from neos.coding.domain.approvals import is_denied_secret_path

        argv = tuple(data["argv"])
        if any("\0" in value for value in argv):
            raise ToolValidationError("policy_schema_invalid")
        if PurePosixPath(argv[0]).name != argv[0]:
            raise ToolValidationError("policy_executable_path_denied")
        executable = PurePosixPath(argv[0]).name
        names = _unwrapped_command_names(argv)
        if "git" in names and any(_is_git_dangerous_flag(part) for part in argv):
            raise ToolValidationError("policy_git_operation_denied")
        if any(name in _REMOVAL_EXECUTABLES for name in names):
            for operand in _command_operands(argv):
                if (
                    operand in _DANGEROUS_REMOVAL_OPERANDS
                    or _operand_escapes_workspace(operand)
                ):
                    raise ToolValidationError("policy_dangerous_removal")
        denied = next((name for name in names if name in _DEDICATED_EXECUTE_DENY), None)
        if denied is not None:
            raise ToolValidationError(
                "policy_dedicated_tool_required",
                fix_note=_dedicated_tool_fix_note(denied),
            )
        if any(name in {"sh", "bash", "zsh"} for name in names) and "-c" in argv[1:]:
            raise ToolValidationError("policy_shell_command_denied")
        if any(name in _INLINE_INTERPRETERS for name in names):
            later = argv[1:]
            if any(_is_inline_interpreter_flag(part) for part in later):
                raise ToolValidationError("policy_inline_interpreter_denied")
            if "php" in names and any(
                part == "-r"
                or part.startswith("-r=")
                or (part.startswith("-r") and not part.startswith("--"))
                for part in later
            ):
                raise ToolValidationError("policy_inline_interpreter_denied")
        if any(
            name
            in {
                "curl",
                "ftp",
                "nc",
                "ncat",
                "rsync",
                "scp",
                "sftp",
                "ssh",
                "telnet",
                "wget",
            }
            for name in names
        ):
            raise ToolValidationError("policy_network_client_denied")
        if any(name in {"npm", "pnpm", "yarn", "pip", "pip3"} for name in names) and any(
            value
            in {
                "add",
                "dlx",
                "fetch",
                "install",
                "update",
                "upgrade",
            }
            for value in argv[1:]
        ):
            raise ToolValidationError("policy_network_operation_denied")
        for operand in _command_operands(argv):
            if is_denied_secret_path(operand):
                raise ToolValidationError("policy_secret_path_denied")
            if _operand_escapes_workspace(operand):
                raise ToolValidationError("policy_command_path_denied")
        if executable not in self._command_allowlist:
            raise ToolValidationError("policy_executable_not_allowed")
        if "git" in names:
            subcommand = _subcommand_after(argv, "git")
            if subcommand not in {"status", "diff", "log"}:
                raise ToolValidationError("policy_git_operation_denied")
        if any(name in {"npm", "pnpm", "yarn"} for name in names) and any(
            value in {"publish", "release"} for value in argv[1:]
        ):
            raise ToolValidationError("policy_publish_denied")
        if data["timeout_sec"] > self._max_command_timeout_sec:
            raise ToolValidationError("policy_command_timeout_exceeded")
        if data["max_output_bytes"] > self._max_command_output_bytes:
            raise ToolValidationError("policy_command_output_exceeded")
        if len(data["stdin"].encode("utf-8")) > self._max_command_stdin_bytes:
            raise ToolValidationError("policy_command_stdin_exceeded")
        if not all(
            self._env_entry_allowed(key, value) for key, value in data["env"].items()
        ):
            raise ToolValidationError("policy_environment_name_denied")
        if any("\0" in key or "\0" in value for key, value in data["env"].items()):
            raise ToolValidationError("policy_schema_invalid")
