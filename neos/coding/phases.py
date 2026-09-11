"""Same-process coding phases. Hidden tools are not offered to the model."""

from __future__ import annotations

from enum import StrEnum

from neos.coding.tools.registry import ToolRisk


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
    }
)

_HIDDEN: dict[CodingAgentPhase, frozenset[str]] = {
    CodingAgentPhase.EXPLORE: _HIDDEN_WRITES,
    CodingAgentPhase.PLAN: _HIDDEN_WRITES,
    CodingAgentPhase.VERIFY: frozenset(
        {"edit_file.v1", "write_file.v1", "spawn_agent.v1"}
    ),
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
