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


def evaluate_approval(call: ValidatedToolCall) -> ApprovalPolicyOutcome:
    if call.risk is ToolRisk.READ_ONLY:
        return ApprovalPolicyOutcome.ALLOW
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
            return {"executable": "unknown", "argument_count": 0}
        summary: dict[str, object] = {
            "executable": str(argv[0]),
            "argument_count": max(len(argv) - 1, 0),
        }
        warnings = _execute_warning_codes(argv)
        if warnings:
            summary["warnings"] = warnings
        return summary
    path = call.input.get("path")
    if isinstance(path, str):
        return {"path": path}
    return {"operation": call.name}


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
