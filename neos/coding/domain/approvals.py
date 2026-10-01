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


class UserRuleEffect(StrEnum):
    """사용자 규칙의 효과 (트랙 Q2). 기본 정책 **뒤에서** 평가된다:

    `USER_ONLY > 기본 DENY > 사용자 block > 기본 REQUIRE(보호 파일) > 사용자 require
    > 운영자 allow > 사용자 allow > 기본값`. 사용자 allow 는 위험 등급이 정하는
    기본 REQUIRE_APPROVAL 만 ALLOW 로 바꾼다 -- 기본 정책의 DENY 도, 보호 파일의
    REQUIRE 도, 단계 전환 승인도 넘지 못한다.
    """

    ALLOW = "allow"
    REQUIRE = "require"
    BLOCK = "block"


@dataclass(frozen=True, slots=True)
class UserApprovalRule:
    """사용자 한 명의 규칙 하나. 도구 이름 + (execute.v1 이면) argv 접두.

    argv 접두는 USER_ONLY 와 **같은 규칙**으로 맞춘다(래퍼를 벗기고, 플래그 값
    읽기 둘 다 시도) -- 사본을 만들면 한쪽만 고쳐진다.
    """

    rule_id: str
    effect: UserRuleEffect
    tool: str
    argv_prefix: tuple[str, ...] = ()


#: 승인으로도 위임할 수 없는 명령 -- 사람이 직접 한다 (로드맵 트랙 Q2, 결정 2).
#:
#: **코드에 고정한다.** 설정(`approval_user_only_extra`)은 여기에 **더하기만**
#: 하고 빼는 표현은 없다 -- 설정으로 끌 수 있는 안전 요건은 "항상 적용"이
#: 아니다. 항목은 argv 접두(실행 파일 + 하위 명령)다.
#:
#: 오늘 샌드박스의 검증은 이것들 대부분을 이미 막는다(실행 파일 allowlist
#: 기본값이 pytest/ruff/mypy/pnpm/git). 이 바닥은 운영자가 allowlist 를
#: 넓히는 날을 위한 것이다 -- `gh` 가 돌 수 있게 돼도 `gh auth login` 은
#: 여전히 사람의 몫이어야 한다.
USER_ONLY_COMMANDS: frozenset[tuple[str, ...]] = frozenset(
    {
        # 자격증명 -- 로그인·토큰·비밀번호
        ("gh", "auth"),
        ("gh", "secret"),
        ("docker", "login"),
        ("npm", "login"),
        ("npm", "adduser"),
        ("npm", "token"),
        ("git", "credential"),
        ("passwd",),
        # 공유 범위·권한 변경
        ("gh", "repo", "edit"),
        # 계정·저장소 삭제
        ("gh", "repo", "delete"),
    }
)


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
    #: `USER_ONLY_COMMANDS` 에 **더하는** 항목. 합집합으로만 쓰인다.
    user_only_extra: frozenset[tuple[str, ...]] = frozenset()
    #: background 모드(트랙 Q1) -- 아무것도 바꿀 수 없는 호출만 통과한다.
    read_only_ceiling: bool = False
    #: 태스크 소유자의 규칙(트랙 Q2). 에이전트 태스크도 소유자의 규칙을 쓴다.
    user_rules: tuple[UserApprovalRule, ...] = ()



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


def fold_for_unattended(
    outcome: ApprovalPolicyOutcome, gate: ApprovalGate
) -> ApprovalPolicyOutcome:
    """승인할 사람이 없는 런에서 "사람에게 묻는다"는 답이 아니다.

    이 규칙은 **접기다** -- 결과를 좁히기만 하고 넓히지 않는다. 확률 판정
    층(로드맵 트랙 L)이 이 함수를 재사용하는 이유가 그것이고, 재사용해야
    하는 이유는 규칙 사본이 둘이 되면 고침이 한쪽에만 도착하기 때문이다.

    호출 순서가 계약이다: **밴딩이 먼저, 접기가 나중.** 뒤집으면 Jev 가
    올린 중간대 REQUIRE_APPROVAL 이 접히지 않고 남아, 승인할 사람이 없는
    런에서 매달린다(D-L1).
    """
    if gate.unattended and outcome is ApprovalPolicyOutcome.REQUIRE_APPROVAL:
        return ApprovalPolicyOutcome.DENY
    return outcome


def evaluate_static_approval(
    call: ValidatedToolCall, gate: ApprovalGate
) -> ApprovalPolicyOutcome:
    """접기 **전**의 정적 정책 결과 R₀.

    트랙 L 이 밴딩을 끼워 넣을 수 있도록 노출한다. 평소 경로는
    `evaluate_approval` 이고, 그쪽이 이것과 접기를 이어 붙인 것이다.
    """
    return _evaluate_approval(call, gate)


def evaluate_approval(
    call: ValidatedToolCall,
    gate: ApprovalGate | None = None,
) -> ApprovalPolicyOutcome:
    try:
        resolved = gate or ApprovalGate()
        return fold_for_unattended(
            evaluate_static_approval(call, resolved), resolved
        )
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


def is_user_only(call: ValidatedToolCall, gate: ApprovalGate) -> bool:
    """이 호출이 승인으로도 위임할 수 없는 행동인가 (트랙 Q2).

    결과는 DENY 계열이다 -- 넷째 enum 값이 **아니다.** `_approval_gate_step`
    은 DENY 도 REQUIRE_APPROVAL 도 아닌 결과를 실행하므로, 새 값은 열린 채로
    실패한다(fail-open).
    """
    if call.name != "execute.v1":
        return False
    argv = call.input.get("argv")
    if not isinstance(argv, (list, tuple)) or not argv:
        return False
    command = _innermost_command(tuple(str(part) for part in argv))
    floor = USER_ONLY_COMMANDS | gate.user_only_extra
    return any(_argv_has_prefix(command, prefix) for prefix in floor)


def _innermost_command(argv: tuple[str, ...]) -> tuple[str, ...]:
    """`env X=1 timeout 30 gh auth login` -> `gh auth login`.

    래퍼를 벗기는 규칙은 검증기(`registry`)의 것을 그대로 쓴다 -- 사본을
    만들면 한쪽이 새 래퍼를 알게 될 때 다른 쪽이 모른다.
    """
    from neos.coding.tools.registry import (
        _command_name,
        _next_wrapped_command_index,
    )

    index = 0
    while index < len(argv):
        rest = argv[index + 1 :]
        step = _next_wrapped_command_index(_command_name(argv[index]), rest)
        if step is None:
            break
        index = index + 1 + step
    return (_command_name(argv[index]),) + argv[index + 1 :] if index < len(argv) else ()


def _argv_has_prefix(command: tuple[str, ...], prefix: tuple[str, ...]) -> bool:
    """`command`(래퍼를 벗긴 argv)가 `prefix` 로 시작하는가.

    플래그 뒤의 토큰이 그 플래그의 **값인지 아닌지** argv 만으로는 모른다
    (`gh --hostname example.com auth` 대 `gh --verbose auth`). 한쪽으로 정하면
    다른 쪽에서 열린 채로 실패하므로 **두 읽기를 다 해 보고 하나라도 맞으면**
    맞다고 한다. 하위 명령 토큰은 실행 파일 바로 뒤에 순서대로 붙어야 한다 --
    아무 데서나 찾으면 `gh pr view auth` 같은 무해한 호출까지 막는다.
    """
    if not command or not prefix or command[0] != prefix[0]:
        return False
    wanted = list(prefix[1:])
    for flag_takes_value in (False, True):
        words: list[str] = []
        skip_next = False
        for token in command[1:]:
            if skip_next:
                skip_next = False
                continue
            if token.startswith("-"):
                skip_next = flag_takes_value and "=" not in token
                continue
            words.append(token)
        if words[: len(wanted)] == wanted:
            return True
    return False


def user_rule_matches(rule: UserApprovalRule, call: ValidatedToolCall) -> bool:
    if call.name != rule.tool:
        return False
    if not rule.argv_prefix:
        return True
    if call.name != "execute.v1":
        return False
    argv = call.input.get("argv")
    if not isinstance(argv, (list, tuple)) or not argv:
        return False
    command = _innermost_command(tuple(str(part) for part in argv))
    return _argv_has_prefix(command, rule.argv_prefix)


def has_user_rule(call: ValidatedToolCall, gate: ApprovalGate, effect: UserRuleEffect) -> bool:
    return any(
        rule.effect is effect and user_rule_matches(rule, call) for rule in gate.user_rules
    )


def exceeds_mode_ceiling(call: ValidatedToolCall, gate: ApprovalGate) -> bool:
    """background 모드에서 이 호출이 천장을 넘는가 (트랙 Q1).

    검증된 위험(`call.risk`)만 본다. 자식을 여는 호출도 따로 셀 필요가 없다 --
    검증기가 `spawn_agent.v1 spec=implement` 를 WORKSPACE_WRITE 로 올리고,
    explore 자식은 포트가 쓰기를 막는다.
    """
    if not gate.read_only_ceiling:
        return False
    from neos.coding.tools.registry import ToolRisk

    return call.risk is not ToolRisk.READ_ONLY


def policy_denial_reason(call: ValidatedToolCall, gate: ApprovalGate) -> str:
    """정책 DENY 의 사유 코드. 두 호출부(부모 게이트 · 자식 게이트)가 같이 쓴다.

    원장에서 Q5 폴백 규칙이 읽는 이름이다 -- `policy_user_only` 는 FB1,
    `policy_mode_ceiling` 은 FB2. 둘 다 맞으면 더 엄한 FB1 의 이름을 단다.
    """
    try:
        if is_user_only(call, gate):
            return "policy_user_only"
    except Exception:
        pass
    if exceeds_mode_ceiling(call, gate):
        return "policy_mode_ceiling"
    try:
        if has_user_rule(call, gate, UserRuleEffect.BLOCK):
            return "policy_user_rule_blocked"
    except Exception:
        pass
    return "policy_approval_denied"


def _evaluate_approval(
    call: ValidatedToolCall, gate: ApprovalGate
) -> ApprovalPolicyOutcome:
    # 맨 앞이다 -- auto 모드·allow 목록·"항상 허용" 기억 어느 것도 이것을 넘지 못한다.
    if is_user_only(call, gate):
        return ApprovalPolicyOutcome.DENY
    # 모드의 천장도 운영자의 allow 목록보다 앞이다.
    if exceeds_mode_ceiling(call, gate):
        return ApprovalPolicyOutcome.DENY
    if any(is_denied_secret_path(path) for path in _call_paths(call)):
        return ApprovalPolicyOutcome.DENY
    if call.name in gate.deny_tools:
        return ApprovalPolicyOutcome.DENY
    # 사용자 block(트랙 Q2) -- 기본 DENY 뒤, 그 밖의 모든 것 앞.
    if has_user_rule(call, gate, UserRuleEffect.BLOCK):
        return ApprovalPolicyOutcome.DENY
    # Instruction files persist agent behavior; never auto-approve writes.
    if _is_protected_instruction_write(call, gate.workspace_root):
        return ApprovalPolicyOutcome.REQUIRE_APPROVAL
    if _is_sensitive_config_write(call):
        return ApprovalPolicyOutcome.REQUIRE_APPROVAL
    # 사용자 require -- 운영자 allow 와 "항상 허용" 기억보다 앞이다(좁히기만).
    if has_user_rule(call, gate, UserRuleEffect.REQUIRE):
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
    # 사용자 allow -- 위험 등급이 정하는 기본 REQUIRE 만 바꾼다. 위의 어떤 판정도 넘지 못한다.
    if has_user_rule(call, gate, UserRuleEffect.ALLOW):
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
    "policy_mode_ceiling": (
        "this is a background task: read only, no writes, commands or "
        "questions; do not retry -- note what should be done instead"
    ),
    "policy_user_rule_blocked": (
        "the user has a rule blocking this action; do not retry -- "
        "choose another way or tell the user why it is needed"
    ),
    "policy_user_only": (
        "only the user can do this, even with approval; do not retry -- "
        "tell the user what to run and why"
    ),
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
    "policy_use_read_image": "use read_image.v1 for images; do not read them as text",
    "policy_use_read_pdf": "use read_pdf.v1 for PDFs; do not read them as text",
    "policy_notebook_required": "use notebook_edit.v1 for Jupyter notebooks",
    "policy_media_tool_disabled": "this optional tool is not enabled",
    "policy_image_unsupported": "only jpeg, png, gif, or webp images are readable",
    "policy_image_too_large": "the image is larger than the configured cap",
    "policy_pdf_invalid": "that PDF could not be parsed",
    "policy_pdf_encrypted": "encrypted PDFs cannot be read",
    "policy_pdf_too_large": "request a smaller page range",
    "policy_notebook_invalid": "that path is not a valid Jupyter notebook",
    "policy_notebook_cell_missing": "that notebook cell was not found",
    "policy_web_search_unconfigured": "web search is not configured",
    "web_search_failed": "the search provider failed; change the query",
    "policy_dedicated_tool_required": "use a dedicated tool instead of this executable",
    "policy_publish_denied": "publish/release is not allowed",
    "policy_command_timeout_exceeded": "timeout is too large; lower timeout_sec",
    "policy_command_output_exceeded": "output cap is too large; lower max_output_bytes",
    "policy_command_stdin_exceeded": "stdin is too large",
    "policy_environment_name_denied": "that environment variable is not allowed",
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
    base = _DENIAL_REASONS.get(reason_code)
    if base is None:
        from neos.coding.tools.registry import _policy_fix_note

        base = _policy_fix_note(reason_code) or _DEFAULT_DENIAL_REASON
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
    raw_warnings = excerpt.pop("warnings", None)
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
    flags: list[str] = []
    for part in parts[1:]:
        if part == "--":
            break
        flags.append(part)
    warnings: list[str] = []
    if executable == "rm" and any(_is_recursive_rm_flag(flag) for flag in flags):
        warnings.append("destructive_recursive_delete")
    if executable == "git" and "reset" in flags and "--hard" in flags:
        warnings.append("destructive_git_reset")
    if executable == "git" and "push" in flags and _has_force_push_flag(flags):
        warnings.append("destructive_force_push")
    return warnings


_RM_SHORT_OPTS = frozenset("fiIrRdv")


def _is_recursive_rm_flag(flag: str) -> bool:
    if flag in {"-r", "-R", "-rf", "-fr", "-Rf", "-fR"}:
        return True
    if flag == "--recursive" or flag.startswith("--recursive="):
        return True
    if not flag.startswith("-") or flag.startswith("--"):
        return False
    body = flag[1:]
    return bool(body) and set(body) <= _RM_SHORT_OPTS and "r" in body.lower()


def _has_force_push_flag(flags: list[str]) -> bool:
    return any(
        flag in {"--force", "-f", "--force-with-lease"}
        or flag.startswith("--force-with-lease=")
        for flag in flags
    )
