"""Same-process coding phases. Hidden tools are not offered to the model."""

from __future__ import annotations

from enum import StrEnum

from neos.coding.tools.registry import ToolRisk


class CodingAgentPhase(StrEnum):
    EXPLORE = "explore"
    IMPLEMENT = "implement"
    VERIFY = "verify"


_HIDDEN: dict[CodingAgentPhase, frozenset[str]] = {
    CodingAgentPhase.EXPLORE: frozenset(
        {"edit_file.v1", "write_file.v1", "execute.v1"}
    ),
    CodingAgentPhase.VERIFY: frozenset({"edit_file.v1", "write_file.v1"}),
    CodingAgentPhase.IMPLEMENT: frozenset(),
}


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
