"""Helpers for reading autonomy policy from workflow state."""

from __future__ import annotations

from typing import TYPE_CHECKING

from neos.config.settings import settings
from neos.workflow.enums import AutonomyLevel

from .policy import AutonomyPolicy

if TYPE_CHECKING:
    from neos.workflow.state import AgentState


class AutonomyMiddleware:
    """Compatibility wrapper for autonomy policy extraction."""

    @staticmethod
    def get_policy_from_state(state: "AgentState") -> AutonomyPolicy:
        return get_policy_from_state(state)


def get_policy_from_state(state: "AgentState") -> AutonomyPolicy:
    raw_level = state.get("autonomy_level")
    if raw_level is None:
        raw_level = settings.DEFAULT_AUTONOMY_LEVEL

    try:
        level = AutonomyLevel(int(raw_level))
    except (TypeError, ValueError):
        level = AutonomyLevel.ASSISTED

    return AutonomyPolicy(level)
