from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from neos.coding.domain.events import CodingEvent
from neos.coding.domain.phases import CodingCheckpoint
from neos.coding.phases import phase_change_requires_approval
from neos.coding.redact import redact_sensitive

if TYPE_CHECKING:
    from neos.coding.tools.registry import ToolRisk, ValidatedToolCall


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"
    INVALIDATED = "invalidated"


class ApprovalDecision(StrEnum):
    APPROVE = "approve"
    DENY = "deny"


class ApprovalPolicyOutcome(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


class ApprovalMode(StrEnum):
    MANUAL = "manual"
    AUTO = "auto"


@dataclass(frozen=True, slots=True)
class ApprovalGate:
    mode: ApprovalMode = ApprovalMode.MANUAL
    deny_tools: frozenset[str] = frozenset()
    allow_tools: frozenset[str] = frozenset()
    always_allow: frozenset[str] = frozenset()
    approved_always: frozenset[str] = frozenset()
    current_phase: str | None = None
    unattended: bool = False
    workspace_root: str | None = None


@dataclass(frozen=True, slots=True)
class CodingApproval:
    approval_id: str
    task_id: str
    run_id: str
    tool_call_id: str
    checkpoint_id: str
    tool_name: str
    risk: ToolRisk
    workspace_revision: str
    request_hash: str
    display_summary: Mapping[str, object]
    status: ApprovalStatus
    requested_by: str
    requested_at: datetime
    expires_at: datetime
    decision: ApprovalDecision | None = None
    decided_by: str | None = None
    decided_at: datetime | None = None

    def __post_init__(self) -> None:
        if len(self.request_hash) != 64:
            raise ValueError("approval request hash must be sha256")
        if self.expires_at <= self.requested_at:
            raise ValueError("approval expiry must follow request time")
        if self.status is ApprovalStatus.PENDING and any(
            value is not None
            for value in (self.decision, self.decided_by, self.decided_at)
        ):
            raise ValueError("pending approval cannot have a decision")
        if self.status is ApprovalStatus.APPROVED and (
            self.decision is not ApprovalDecision.APPROVE
            or self.decided_by is None
            or self.decided_at is None
        ):
            raise ValueError("approved approval requires an approve decision")
        if self.status is ApprovalStatus.DENIED and (
            self.decision is not ApprovalDecision.DENY
            or self.decided_by is None
            or self.decided_at is None
        ):
            raise ValueError("denied approval requires a deny decision")


@dataclass(frozen=True, slots=True)
class ApprovalRequestCommit:
    approval: CodingApproval
    checkpoint: CodingCheckpoint
    events: tuple[CodingEvent, ...]
    created: bool


@dataclass(frozen=True, slots=True)
class ApprovalResolutionCommit:
    approval: CodingApproval
    events: tuple[CodingEvent, ...]
    conflict_code: str | None = None


class ApprovalConflict(RuntimeError):
    pass


class ApprovalNotFound(LookupError):
    pass


def requires_approval_answers(tool_name: str) -> bool:
    return tool_name == "ask_user.v1"


def ask_user_answers_complete(questions, answers) -> bool:
    if not isinstance(questions, (list, tuple)) or not questions:
        return False
    if not isinstance(answers, (list, tuple)):
        return False
    if len(answers) < len(questions):
        return False
    return all(
        isinstance(answers[index], str) and answers[index].strip() != ""
        for index in range(len(questions))
    )


def evaluate_approval(
    call: ValidatedToolCall,
    gate: ApprovalGate | None = None,
) -> ApprovalPolicyOutcome:
    try:
        resolved = gate or ApprovalGate()
        outcome = _evaluate_approval(call, resolved)
        if resolved.unattended and outcome is ApprovalPolicyOutcome.REQUIRE_APPROVAL:
            return ApprovalPolicyOutcome.DENY
        return outcome
    except Exception:
        return ApprovalPolicyOutcome.DENY


def approval_remember_key(call: ValidatedToolCall) -> str:
    raw_path = call.input.get("path")
    if isinstance(raw_path, str) and raw_path.strip():
        try:
            from neos.coding.sandbox.paths import normalize_workspace_path

            scoped = str(normalize_workspace_path(raw_path))
        except Exception:
            scoped = raw_path.replace("\\", "/").strip()
        if scoped:
            return f"{call.name}:{scoped}"
    if call.name == "execute.v1":
        argv = call.input.get("argv")
        if isinstance(argv, (list, tuple)) and argv:
            token = str(argv[0]).strip()
            if token:
                return f"{call.name}:{token}"
    return call.name


def _call_paths(call: ValidatedToolCall) -> tuple[str, ...]:
    found: list[str] = []
    raw_path = call.input.get("path")
    if isinstance(raw_path, str) and raw_path:
        found.append(raw_path)
    for key in ("src", "dest"):
        raw = call.input.get(key)
        if isinstance(raw, str) and raw:
            found.append(raw)
    raw_paths = call.input.get("paths")
    if isinstance(raw_paths, (list, tuple)):
        found.extend(str(item) for item in raw_paths if item)
    if call.name == "execute.v1":
        from neos.coding.tools.registry import path_operands_from_argv

        argv = call.input.get("argv")
        if isinstance(argv, (list, tuple)):
            found.extend(path_operands_from_argv(tuple(str(item) for item in argv)))
    return tuple(found)


def _posix_path_parts(path: str) -> tuple[str, ...]:
    return tuple(
        part
        for part in path.replace("\\", "/").split("/")
        if part not in {"", "."}
    )


def is_denied_secret_path(path: object) -> bool:
    if not isinstance(path, str) or not path:
        return False
    parts = _posix_path_parts(path)
    if not parts:
        return False
    from neos.coding.sandbox.paths import compare_path_key

    folded = tuple(compare_path_key(part) for part in parts)
    name = folded[-1]
    if name == ".env" or name.startswith(".env."):
        return True
    if ".git" in folded or ".ssh" in folded:
        return True
    if name in {
        "id_rsa",
        "id_ed25519",
        ".envrc",
        ".npmrc",
        ".pypirc",
        ".netrc",
        ".pgpass",
        ".git-credentials",
    }:
        return True
    if any(
        part == ".neos" and folded[index + 1] == "secrets"
        for index, part in enumerate(folded[:-1])
    ):
        return True
    return any(
        part == ".aws" and folded[index + 1] == "credentials"
        for index, part in enumerate(folded[:-1])
    )


_PROTECTED_INSTRUCTION_BASENAMES = frozenset(
    {
        "agents.md",
        "claude.md",
        "soul.md",
        ".cursorrules",
        "claude.local.md",
    }
)
_INSTRUCTION_WRITE_TOOLS = frozenset(
    {
        "write_file.v1",
        "edit_file.v1",
        "mkdir.v1",
        "rm.v1",
        "mv.v1",
        "chmod.v1",
    }
)
_SENSITIVE_CONFIG_BASENAMES = frozenset(
    {
        ".bashrc",
        ".zshrc",
        ".profile",
        ".gitconfig",
        ".gitmodules",
        ".mcp.json",
        ".claude.json",
        ".ripgreprc",
    }
)
_SENSITIVE_CONFIG_DIR_PARTS = frozenset({".vscode", ".idea", ".claude"})
_PREVIEW_MAX_LINES = 40
_PREVIEW_MAX_CHARS = 2000


def _has_protected_instruction_basename(path: str) -> bool:
    from neos.coding.sandbox.paths import compare_path_key

    parts = _posix_path_parts(path)
    return bool(parts) and compare_path_key(parts[-1]) in _PROTECTED_INSTRUCTION_BASENAMES


def _is_claude_rules_path(path: str) -> bool:
    from neos.coding.sandbox.paths import compare_path_key

    parts = _posix_path_parts(path)
    folded = tuple(compare_path_key(part) for part in parts)
    for index, part in enumerate(folded[:-1]):
        if part == ".claude" and folded[index + 1] == "rules":
            return index + 2 < len(folded)
    return False


def _looks_like_instruction_file(path: str) -> bool:
    return _has_protected_instruction_basename(path) or _is_claude_rules_path(path)


def _is_instruction_file_path(path: str, workspace_root: str | None = None) -> bool:
    if _looks_like_instruction_file(path):
        return True
    if not workspace_root:
        return False
    from neos.coding.sandbox.paths import realpath_for_compare

    resolved = realpath_for_compare(workspace_root, path)
    return resolved != path and _looks_like_instruction_file(resolved)


def _is_protected_instruction_write(
    call: ValidatedToolCall,
    workspace_root: str | None = None,
) -> bool:
    if call.name not in _INSTRUCTION_WRITE_TOOLS and call.name != "execute.v1":
        return False
    if any(
        _is_instruction_file_path(path, workspace_root) for path in _call_paths(call)
    ):
        return True
    if call.name == "execute.v1":
        argv = call.input.get("argv")
        if isinstance(argv, (list, tuple)):
            return any(
                _is_instruction_file_path(str(item), workspace_root)
                for item in argv
                if item
            )
    return False


def _is_sensitive_config_write(call: ValidatedToolCall) -> bool:
    if call.name not in _INSTRUCTION_WRITE_TOOLS:
        return False
    names = {item.casefold() for item in _SENSITIVE_CONFIG_BASENAMES}
    dirs = {item.casefold() for item in _SENSITIVE_CONFIG_DIR_PARTS}
    for path in _call_paths(call):
        parts = _posix_path_parts(path)
        if not parts:
            continue
        folded = [part.casefold() for part in parts]
        if folded[-1] in names or any(part in dirs for part in folded):
            return True
    return False


def _truncated_text(text: str) -> tuple[str, bool]:
    lines = text.splitlines(keepends=True)
    truncated = len(lines) > _PREVIEW_MAX_LINES
    if truncated:
        lines = lines[:_PREVIEW_MAX_LINES]
    preview = "".join(lines)
    if len(preview) > _PREVIEW_MAX_CHARS:
        return preview[:_PREVIEW_MAX_CHARS], True
    return preview, truncated


def _approved_always_allows(
    call: ValidatedToolCall, approved_always: frozenset[str]
) -> bool:
    if not approved_always:
        return False
    if call.name in approved_always:
        return True
    return approval_remember_key(call) in approved_always


def _evaluate_approval(
    call: ValidatedToolCall, gate: ApprovalGate
) -> ApprovalPolicyOutcome:
    if any(is_denied_secret_path(path) for path in _call_paths(call)):
        return ApprovalPolicyOutcome.DENY
    if call.name in gate.deny_tools:
        return ApprovalPolicyOutcome.DENY
    # Instruction files persist agent behavior; never auto-approve writes.
    if _is_protected_instruction_write(call, gate.workspace_root):
        return ApprovalPolicyOutcome.REQUIRE_APPROVAL
    if _is_sensitive_config_write(call):
        return ApprovalPolicyOutcome.REQUIRE_APPROVAL
    if call.name in gate.allow_tools:
        return ApprovalPolicyOutcome.ALLOW
    if _approved_always_allows(call, gate.approved_always):
        return ApprovalPolicyOutcome.ALLOW
    if call.name in gate.always_allow and gate.mode is ApprovalMode.AUTO:
        return ApprovalPolicyOutcome.ALLOW
    if call.name == "set_phase.v1" and gate.current_phase is not None:
        target = str(call.input.get("phase") or "")
        if phase_change_requires_approval(gate.current_phase, target):
            return ApprovalPolicyOutcome.REQUIRE_APPROVAL
    from neos.coding.tools.registry import ToolRisk

    if call.risk is ToolRisk.READ_ONLY:
        return ApprovalPolicyOutcome.ALLOW
    if call.risk in {
        ToolRisk.WORKSPACE_WRITE,
        ToolRisk.COMMAND,
        ToolRisk.USER_QUESTION,
    }:
        return ApprovalPolicyOutcome.REQUIRE_APPROVAL
    return ApprovalPolicyOutcome.REQUIRE_APPROVAL


def canonical_approval_hash(binding: Mapping[str, object]) -> str:
    payload = {"contract": "coding-approval-v1", **binding}
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def approval_display_summary(call: ValidatedToolCall) -> Mapping[str, object]:
    if call.name == "execute.v1":
        argv = call.input.get("argv")
        if not isinstance(argv, list) or not argv:
            return redact_sensitive({"executable": "unknown", "argument_count": 0})
        summary: dict[str, object] = {
            "executable": str(argv[0]),
            "argument_count": max(len(argv) - 1, 0),
        }
        warnings = _execute_warning_codes(argv)
        if warnings:
            summary["warnings"] = warnings
        return redact_sensitive(summary)
    if call.name == "ask_user.v1":
        questions = call.input.get("questions")
        if not isinstance(questions, list):
            return redact_sensitive({"questions": []})
        rendered: list[str] = []
        options: list[list[str]] = []
        for item in questions:
            if isinstance(item, Mapping):
                rendered.append(str(item.get("prompt") or ""))
                raw_options = item.get("options") or []
                labels = []
                if isinstance(raw_options, (list, tuple)):
                    for option in raw_options:
                        if isinstance(option, Mapping):
                            labels.append(str(option.get("label") or ""))
                        elif option:
                            labels.append(str(option))
                options.append(labels)
            else:
                rendered.append(str(item))
                options.append([])
        summary: dict[str, object] = {"questions": rendered}
        if any(options):
            summary["options"] = options
        multi_select = [
            bool(item.get("multi_select"))
            if isinstance(item, Mapping)
            else False
            for item in questions
        ]
        if any(multi_select):
            summary["multi_select"] = multi_select
        return redact_sensitive(summary)
    if call.name == "set_phase.v1":
        summary: dict[str, object] = {
            "phase": str(call.input.get("phase") or ""),
        }
        return redact_sensitive(summary)
    if call.name in {"write_file.v1", "edit_file.v1"}:
        path = call.input.get("path")
        summary: dict[str, object] = (
            {"path": path} if isinstance(path, str) else {"operation": call.name}
        )
        if call.name == "write_file.v1":
            preview, truncated = _truncated_text(str(call.input.get("content") or ""))
            summary["preview"] = preview
        else:
            old = str(call.input.get("old_string") or "")
            new = str(call.input.get("new_string") or "")
            preview, truncated = _truncated_text(f"--- old\n{old}\n+++ new\n{new}\n")
            summary["patch"] = preview
        summary["truncated"] = truncated
        return redact_sensitive(summary)
    path = call.input.get("path")
    if isinstance(path, str):
        return redact_sensitive({"path": path})
    return redact_sensitive({"operation": call.name})


def approval_event_display_summary(
    summary: Mapping[str, object],
) -> dict[str, object]:
    excerpt = dict(summary)
    excerpt.pop("preview", None)
    excerpt.pop("patch", None)
    excerpt.pop("content", None)
    excerpt.pop("truncated", None)
    return excerpt


_DENIAL_REASONS = {
    "policy_hook_denied": "a hook blocked this call; change the input and do not retry it",
    "hook_prevented": "a hook stopped further tools; do not continue this batch",
    "approval_denied": "the user denied this action; do not retry the same call",
    "policy_approval_denied": "the user denied this action; do not retry the same call",
    "approval_expired": "approval expired; ask again only with a safer call",
    "approval_invalidated": "approval is no longer valid; ask again only with a safer call",
    "policy_phase_denied": "this tool is not allowed in the current phase",
    "policy_skill_denied": "the loaded skill does not allow this tool",
    "policy_stall_denied": "the same call failed repeatedly; change the approach",
    "policy_schema_invalid": "the tool input is invalid; fix the arguments",
    "policy_unknown_tool": "this tool is not available",
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
    "policy_binary_file": "this file is binary; do not read it as text",
    "aborted": "the run was aborted; do not retry this call",
}
_WARNING_REASONS = {
    "destructive_recursive_delete": "recursive delete is blocked; do not retry rm -r",
    "destructive_git_reset": "git reset --hard is blocked; do not discard the tree via execute",
    "destructive_force_push": "force-push is blocked; do not rewrite remotes via execute",
}
_DEFAULT_DENIAL_REASON = (
    "this call was denied; change the input and do not retry the same one"
)


def adaptive_denial_reason(
    reason_code: str, warnings: Sequence[str] = ()
) -> str:
    base = _DENIAL_REASONS.get(reason_code, _DEFAULT_DENIAL_REASON)
    extras = [
        _WARNING_REASONS[code] for code in warnings if code in _WARNING_REASONS
    ]
    if not extras:
        return base
    return " ".join((base, *extras))


def denial_envelope(call, reason_code: str) -> dict[str, object]:
    if reason_code.startswith("policy_hook_"):
        denied_by = "hook"
    elif reason_code in {"approval_denied", "policy_approval_denied"}:
        denied_by = "user"
    else:
        denied_by = "policy"
    from neos.coding.tools.registry import ToolRisk, ValidatedToolCall

    summary_call = (
        call
        if isinstance(call, ValidatedToolCall)
        else ValidatedToolCall(call.name, dict(call.input), ToolRisk.READ_ONLY)
    )
    excerpt = dict(approval_display_summary(summary_call))
    excerpt.pop("preview", None)
    excerpt.pop("patch", None)
    excerpt.pop("content", None)
    excerpt.pop("truncated", None)
    raw_warnings = excerpt.get("warnings")
    warnings = (
        tuple(str(item) for item in raw_warnings)
        if isinstance(raw_warnings, list)
        else ()
    )
    envelope: dict[str, object] = {
        "reason_code": reason_code,
        "status": "denied",
        "denied_by": denied_by,
        "function_id": call.name,
        "reason": adaptive_denial_reason(reason_code, warnings),
        "args_excerpt": redact_sensitive(excerpt),
    }
    if warnings:
        envelope["warnings"] = list(warnings)
    return envelope


def _execute_warning_codes(argv: list[object]) -> list[str]:
    parts = [str(part) for part in argv]
    if not parts:
        return []
    executable = parts[0]
    flags = parts[1:]
    warnings: list[str] = []
    if executable == "rm" and any(_is_recursive_rm_flag(flag) for flag in flags):
        warnings.append("destructive_recursive_delete")
    if executable == "git" and "reset" in flags and "--hard" in flags:
        warnings.append("destructive_git_reset")
    if executable == "git" and "push" in flags and _has_force_push_flag(flags):
        warnings.append("destructive_force_push")
    return warnings


def _is_recursive_rm_flag(flag: str) -> bool:
    return flag in {"-r", "-R", "-rf", "-fr", "-Rf", "-fR"} or (
        flag.startswith("-")
        and not flag.startswith("--")
        and "r" in flag.lower()
    )


def _has_force_push_flag(flags: list[str]) -> bool:
    return any(flag == "--force" or flag == "-f" for flag in flags)
