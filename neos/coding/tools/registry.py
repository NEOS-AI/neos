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


class ToolRisk(StrEnum):
    READ_ONLY = "read_only"
    WORKSPACE_WRITE = "workspace_write"
    COMMAND = "command"


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
    limit: int = Field(default=100, ge=1, le=100)


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
                "Do not use execute.v1 with rg/grep/find. "
                "On policy_* denial, do not retry the same query."
            ),
            ToolRisk.READ_ONLY,
            _SearchTextInput,
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

    def definitions(self) -> tuple[ToolDefinition, ...]:
        return tuple(tool.definition() for tool in self._TOOL_SPECS)

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
            if "path" in data:
                normalizer = (
                    ensure_mutable_workspace_path
                    if name in {"write_file.v1", "edit_file.v1"}
                    else normalize_workspace_path
                )
                data["path"] = str(normalizer(data["path"]))
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
        argv = tuple(data["argv"])
        if any("\0" in value for value in argv):
            raise ToolValidationError("policy_schema_invalid")
        if PurePosixPath(argv[0]).name != argv[0]:
            raise ToolValidationError("policy_executable_path_denied")
        executable = PurePosixPath(argv[0]).name
        if executable in {"sh", "bash", "zsh"} and len(argv) > 1 and argv[1] == "-c":
            raise ToolValidationError("policy_shell_command_denied")
        if executable in {
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
        }:
            raise ToolValidationError("policy_network_client_denied")
        if executable in {"npm", "pnpm", "yarn", "pip", "pip3"} and any(
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
        if executable not in self._command_allowlist:
            raise ToolValidationError("policy_executable_not_allowed")
        if executable == "git" and (
            len(argv) < 2 or argv[1] not in {"status", "diff", "log"}
        ):
            raise ToolValidationError("policy_git_operation_denied")
        if executable in {"npm", "pnpm", "yarn"} and any(
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
