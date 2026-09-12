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

_DEFAULT_DEFERRED_TOOLS_THRESHOLD = 20
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
    }
)
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


def _deferred_tools_threshold() -> int:
    try:
        from neos.config.settings import settings

        return int(settings.config.coding_model.deferred_tools_threshold)
    except Exception:
        return _DEFAULT_DEFERRED_TOOLS_THRESHOLD


class ToolRisk(StrEnum):
    READ_ONLY = "read_only"
    WORKSPACE_WRITE = "workspace_write"
    COMMAND = "command"
    USER_QUESTION = "user_question"


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    allowed: bool
    reason_code: str


@dataclass(frozen=True, slots=True)
class ValidatedToolCall:
    name: str
    input: Mapping[str, object]
    risk: ToolRisk


class ToolValidationError(ValueError):
    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


class _ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _PathInput(_ToolInput):
    path: str


class _ListTreeInput(_ToolInput):
    path: str = "."


class _SearchTextInput(_ToolInput):
    query: str = Field(min_length=1)
    paths: list[str] = Field(default_factory=lambda: ["**/*"], min_length=1)
    regex: bool = False
    limit: int = Field(default=100, ge=1, le=250)
    before: int = Field(default=0, ge=0, le=20)
    after: int = Field(default=0, ge=0, le=20)
    ignore_case: bool = False
    multiline: bool = False
    context: int = Field(default=0, ge=0, le=20)
    path: str | None = None
    output_mode: Literal["files", "content", "count"] = "content"


class _GlobFilesInput(_ToolInput):
    pattern: str = Field(min_length=1)
    limit: int = Field(default=100, ge=1, le=500)


class _WebFetchInput(_ToolInput):
    url: str = Field(min_length=1)


class _SearchToolsInput(_ToolInput):
    query: str = Field(min_length=1)


class _SpawnAgentInput(_ToolInput):
    prompt: str = Field(min_length=1)
    max_turns: int = Field(default=4, ge=1, le=8)


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

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            input_schema=self.schema.model_json_schema(),
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
                "Spawn a nested explore-only coding agent. "
                "The parent loop intercepts this call. Do not use this to write files. "
                "On policy_* denial, do not retry the same prompt."
            ),
            ToolRisk.READ_ONLY,
            _SpawnAgentInput,
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
    ) -> None:
        if (
            max_command_timeout_sec <= 0
            or max_command_output_bytes < 1
            or max_command_stdin_bytes < 1
        ):
            raise ValueError("command policy limits must be positive")
        self._tools = {tool.name: tool for tool in self._TOOL_SPECS}
        self._command_allowlist = command_allowlist
        self._max_command_timeout_sec = max_command_timeout_sec
        self._max_command_output_bytes = max_command_output_bytes
        self._max_command_stdin_bytes = max_command_stdin_bytes
        self._allowed_env_names = allowed_env_names

    @classmethod
    def default(
        cls,
        *,
        command_allowlist: frozenset[str],
        max_command_timeout_sec: float = 30,
        max_command_output_bytes: int = 1024 * 1024,
        max_command_stdin_bytes: int = 1024 * 1024,
        allowed_env_names: frozenset[str] = frozenset(),
    ) -> CodingToolRegistry:
        return cls(
            command_allowlist=command_allowlist,
            max_command_timeout_sec=max_command_timeout_sec,
            max_command_output_bytes=max_command_output_bytes,
            max_command_stdin_bytes=max_command_stdin_bytes,
            allowed_env_names=allowed_env_names,
        )

    def definitions(
        self,
        *,
        phase: str = "implement",
        revealed: frozenset[str] | None = None,
    ) -> tuple[ToolDefinition, ...]:
        from neos.coding.phases import hidden_tools_for_phase

        hidden = hidden_tools_for_phase(phase)
        revealed_names = revealed or frozenset()
        deferred = frozenset(self.deferred_tool_names(phase=phase))
        return tuple(
            tool.definition()
            for tool in self._TOOL_SPECS
            if tool.name not in hidden
            and (
                tool.name in self._CORE_TOOL_NAMES
                or tool.name in revealed_names
            )
            and (
                tool.name in self._CORE_TOOL_NAMES
                or tool.name in deferred
                or tool.name in revealed_names
            )
        )

    @classmethod
    def deferred_tool_names(cls, *, phase: str | None = None) -> tuple[str, ...]:
        from neos.coding.phases import hidden_tools_for_phase

        hidden = hidden_tools_for_phase(phase) if phase is not None else frozenset()
        return tuple(
            tool.name
            for tool in cls._TOOL_SPECS
            if tool.name not in cls._CORE_TOOL_NAMES and tool.name not in hidden
        )

    @classmethod
    def search_definitions(
        cls, query: str, *, limit: int = 8, phase: str = "implement"
    ) -> tuple[Mapping[str, object], ...]:
        candidates = cls._deferred_tools(phase=phase)
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
    def _deferred_tools(cls, *, phase: str) -> tuple[_RegisteredTool, ...]:
        allowed = frozenset(cls.deferred_tool_names(phase=phase))
        return tuple(tool for tool in cls._TOOL_SPECS if tool.name in allowed)

    def decide(
        self, name: str, input: Mapping[str, object]
    ) -> PolicyDecision:
        try:
            self.validate(name, input)
        except ToolValidationError as error:
            return PolicyDecision(False, error.reason_code)
        return PolicyDecision(True, "policy_allowed")

    def validate(
        self, name: str, input: Mapping[str, object]
    ) -> ValidatedToolCall:
        tool = self._tools.get(name)
        if tool is None:
            raise ToolValidationError("policy_unknown_tool")
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
        self._normalize_paths(name, data)
        if name == "search_text.v1" and data["regex"]:
            try:
                re.compile(data["query"])
            except re.error as error:
                raise ToolValidationError("policy_schema_invalid") from error
        if name == "execute.v1":
            self._validate_command(data)
        return ValidatedToolCall(name=name, input=data, risk=tool.risk)

    def _normalize_paths(self, name: str, data: dict[str, Any]) -> None:
        try:
            raw_path = data.get("path")
            if isinstance(raw_path, str):
                normalizer = (
                    ensure_mutable_workspace_path
                    if name in {"write_file.v1", "edit_file.v1"}
                    else normalize_workspace_path
                )
                data["path"] = str(normalizer(raw_path))
            if "pattern" in data:
                data["pattern"] = str(normalize_workspace_path(data["pattern"]))
            if "paths" in data:
                data["paths"] = [
                    str(normalize_workspace_path(path)) for path in data["paths"]
                ]
            if "cwd" in data:
                data["cwd"] = str(normalize_workspace_path(data["cwd"]))
        except SandboxPolicyViolation as error:
            code = str(error)
            if code == "protected_git_path":
                raise ToolValidationError("policy_protected_git_path") from error
            raise ToolValidationError(f"policy_{code}") from error

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
        if any(name in _DEDICATED_EXECUTE_DENY for name in names):
            raise ToolValidationError("policy_dedicated_tool_required")
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
        if any(name in _REMOVAL_EXECUTABLES for name in names):
            for operand in _command_operands(argv):
                if (
                    operand in _DANGEROUS_REMOVAL_OPERANDS
                    or _operand_escapes_workspace(operand)
                ):
                    raise ToolValidationError("policy_dangerous_removal")
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
        if not set(data["env"]).issubset(self._allowed_env_names):
            raise ToolValidationError("policy_environment_name_denied")
        if any("\0" in key or "\0" in value for key, value in data["env"].items()):
            raise ToolValidationError("policy_schema_invalid")
