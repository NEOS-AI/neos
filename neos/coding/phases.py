"""Same-process coding phases. Hidden tools are not offered to the model."""

from __future__ import annotations

import re
from enum import StrEnum

from neos.coding.tools.registry import ToolRisk

_VERDICT_RE = re.compile(r"VERDICT:\s*(PASS|FAIL|PARTIAL)\b", re.IGNORECASE)
_CRITICAL_HEADING_RE = re.compile(
    r"(?im)^\s{0,3}(?:#{1,6}\s+)?(?:\*{0,2}|_{0,2})Critical Files?(?:\*{0,2}|_{0,2})\s*:?\s*$"
)
_CRITICAL_INLINE_RE = re.compile(r"(?im)Critical Files?\s*:\s*(\S.+)$")
_CRITICAL_ITEM_RE = re.compile(r"^\s*(?:[-*]|\d+[.)])\s+(.+?)\s*$")
_NEXT_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+\S")


class CodingAgentPhase(StrEnum):
    EXPLORE = "explore"
    PLAN = "plan"
    IMPLEMENT = "implement"
    VERIFY = "verify"


_HIDDEN_WRITES = frozenset(
    {
        "edit_file.v1",
        "write_file.v1",
        "execute.v1",
        "spawn_agent.v1",
        "subagent_list.v1",
        "subagent_steer.v1",
    }
)

_HIDDEN: dict[CodingAgentPhase, frozenset[str]] = {
    CodingAgentPhase.EXPLORE: _HIDDEN_WRITES,
    CodingAgentPhase.PLAN: _HIDDEN_WRITES,
    CodingAgentPhase.VERIFY: frozenset(
        {
            "edit_file.v1",
            "write_file.v1",
            "spawn_agent.v1",
            "subagent_list.v1",
            "subagent_steer.v1",
        }
    ),
    CodingAgentPhase.IMPLEMENT: frozenset(),
}


def parse_verify_verdict(text: str) -> str | None:
    match = _VERDICT_RE.search(text or "")
    return match.group(1).upper() if match else None


def persist_verify_verdict(text: str) -> str | None:
    return parse_verify_verdict(text)


def persist_plan_critical_files(text: str) -> tuple[str, ...]:
    files = parse_plan_critical_files(text)
    return tuple(files or ())


def restore_verify_verdict(value: object) -> str | None:
    if value in {"PASS", "FAIL", "PARTIAL"}:
        return str(value)
    return None


def restore_plan_critical_files(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def parse_plan_critical_files(text: str) -> list[str] | None:
    blob = text or ""
    heading = _CRITICAL_HEADING_RE.search(blob)
    if heading is not None:
        files: list[str] = []
        for line in blob[heading.end() :].splitlines():
            if _NEXT_HEADING_RE.match(line):
                break
            item = _CRITICAL_ITEM_RE.match(line)
            if item:
                files.append(item.group(1).strip().strip("`"))
            elif line.strip() and files:
                break
        return files
    inline = _CRITICAL_INLINE_RE.search(blob)
    if inline is None:
        return None
    return [part.strip().strip("`") for part in inline.group(1).split(",") if part.strip()]


def parse_phase(value: object) -> CodingAgentPhase:
    text = str(value or CodingAgentPhase.IMPLEMENT)
    try:
        return CodingAgentPhase(text)
    except ValueError:
        return CodingAgentPhase.IMPLEMENT


def hidden_tools_for_phase(phase: CodingAgentPhase | str) -> frozenset[str]:
    return _HIDDEN[parse_phase(phase)]


def tool_allowed_in_phase(name: str, phase: CodingAgentPhase | str) -> bool:
    return name not in hidden_tools_for_phase(phase)


def write_risk_blocked(risk: ToolRisk, phase: CodingAgentPhase | str) -> bool:
    parsed = parse_phase(phase)
    if parsed is CodingAgentPhase.IMPLEMENT:
        return False
    return risk is ToolRisk.WORKSPACE_WRITE


def phase_change_requires_approval(
    current: CodingAgentPhase | str, target: CodingAgentPhase | str
) -> bool:
    current_phase = parse_phase(current)
    target_phase = parse_phase(target)
    if target_phase is not CodingAgentPhase.IMPLEMENT:
        return False
    return current_phase in {
        CodingAgentPhase.EXPLORE,
        CodingAgentPhase.PLAN,
        CodingAgentPhase.VERIFY,
    }


def durable_phase_kind(phase: CodingAgentPhase | str):
    from neos.coding.domain.phases import CodingPhaseKind

    parsed = parse_phase(phase)
    return {
        CodingAgentPhase.EXPLORE: CodingPhaseKind.UNDERSTAND,
        CodingAgentPhase.PLAN: CodingPhaseKind.PLAN,
        CodingAgentPhase.IMPLEMENT: CodingPhaseKind.IMPLEMENT,
        CodingAgentPhase.VERIFY: CodingPhaseKind.VERIFY,
    }[parsed]
