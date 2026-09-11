from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from neos.coding.tools.registry import ToolRisk, ValidatedToolCall
from neos.coding.domain.events import CodingEvent
from neos.coding.domain.phases import CodingCheckpoint
from neos.coding.phases import phase_change_requires_approval
from neos.coding.redact import redact_sensitive


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


def evaluate_approval(
    call: ValidatedToolCall,
    gate: ApprovalGate | None = None,
) -> ApprovalPolicyOutcome:
    try:
        return _evaluate_approval(call, gate or ApprovalGate())
    except Exception:
        return ApprovalPolicyOutcome.DENY


def _call_paths(call: ValidatedToolCall) -> tuple[str, ...]:
    found: list[str] = []
    raw_path = call.input.get("path")
    if isinstance(raw_path, str) and raw_path:
        found.append(raw_path)
    raw_paths = call.input.get("paths")
    if isinstance(raw_paths, (list, tuple)):
        found.extend(str(item) for item in raw_paths if item)
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
    name = parts[-1]
    if name == ".env" or name.startswith(".env."):
        return True
    if ".git" in parts or ".ssh" in parts:
        return True
    if name == "id_rsa":
        return True
    return any(
        part == ".aws" and parts[index + 1] == "credentials"
        for index, part in enumerate(parts[:-1])
    )


def _evaluate_approval(
    call: ValidatedToolCall, gate: ApprovalGate
) -> ApprovalPolicyOutcome:
    if any(is_denied_secret_path(path) for path in _call_paths(call)):
        return ApprovalPolicyOutcome.DENY
    if call.name in gate.deny_tools:
        return ApprovalPolicyOutcome.DENY
    if call.name in gate.allow_tools:
        return ApprovalPolicyOutcome.ALLOW
    if call.name in gate.approved_always:
        return ApprovalPolicyOutcome.ALLOW
    if call.name in gate.always_allow and gate.mode is ApprovalMode.AUTO:
        return ApprovalPolicyOutcome.ALLOW
    if call.name == "set_phase.v1" and gate.current_phase is not None:
        target = str(call.input.get("phase") or "")
        if phase_change_requires_approval(gate.current_phase, target):
            return ApprovalPolicyOutcome.REQUIRE_APPROVAL
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
        return redact_sensitive(summary)
    path = call.input.get("path")
    if isinstance(path, str):
        return redact_sensitive({"path": path})
    return redact_sensitive({"operation": call.name})


def denial_envelope(call, reason_code: str) -> dict[str, object]:
    if reason_code.startswith("policy_hook_"):
        denied_by = "hook"
    elif reason_code in {"approval_denied", "policy_approval_denied"}:
        denied_by = "user"
    else:
        denied_by = "policy"
    summary_call = (
        call
        if isinstance(call, ValidatedToolCall)
        else ValidatedToolCall(call.name, dict(call.input), ToolRisk.READ_ONLY)
    )
    return {
        "reason_code": reason_code,
        "status": "denied",
        "denied_by": denied_by,
        "function_id": call.name,
        "reason": reason_code,
        "args_excerpt": redact_sensitive(dict(approval_display_summary(summary_call))),
    }


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
