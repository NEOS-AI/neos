"""Agent autonomy policy mapping levels to approval behavior."""

from __future__ import annotations

from typing import Iterable, List

from neos.config.settings import settings
from neos.workflow.enums import AutonomyLevel


def _dedupe(items: Iterable[str]) -> List[str]:
    seen: set[str] = set()
    result: List[str] = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


class AutonomyPolicy:
    """Convert an autonomy level into workflow approval decisions."""

    def __init__(self, autonomy_level: int | AutonomyLevel = AutonomyLevel.ASSISTED):
        self._level = AutonomyLevel(int(autonomy_level))

    @property
    def level(self) -> AutonomyLevel:
        return self._level

    def get_approval_required_skills(self) -> List[str]:
        if self._level == AutonomyLevel.AUTONOMOUS:
            return []

        configured = list(settings.APPROVAL_REQUIRED_SKILLS)
        if self._level == AutonomyLevel.ASSISTED:
            return configured

        from neos.workflow.state import WorkflowConfig

        manual_skills = (
            WorkflowConfig.SEARCH_AGENTS
            + WorkflowConfig.ANALYSIS_AGENTS
            + WorkflowConfig.GENERATION_AGENTS
        )
        extra = [skill for skill in manual_skills if skill not in configured]
        return configured + extra

    def requires_approval(self, skill_name: str) -> bool:
        return skill_name in self.get_approval_required_skills()

    def get_approval_required_actions(
        self,
        *,
        required_agents: Iterable[str] | None = None,
        selected_skills: Iterable[str] | None = None,
        selected_tools: Iterable[str] | None = None,
    ) -> List[str]:
        """Return planned workflow actions that require approval."""
        if self._level == AutonomyLevel.AUTONOMOUS:
            return []

        planned_actions = _dedupe(
            [
                *(required_agents or []),
                *(selected_skills or []),
                *(selected_tools or []),
            ]
        )
        if self._level == AutonomyLevel.MANUAL:
            return planned_actions

        approval_required = set(self.get_approval_required_skills())
        return [
            action
            for action in planned_actions
            if action in approval_required
        ]

    def allows_recursive_research(self) -> bool:
        return self._level != AutonomyLevel.MANUAL

    def allows_autonomous_replan(self) -> bool:
        return self._level != AutonomyLevel.MANUAL

    def description(self) -> str:
        return {
            AutonomyLevel.MANUAL: "수동 - 모든 에이전트 액션 승인 필요",
            AutonomyLevel.ASSISTED: "요청 - 위험 작업만 승인 필요",
            AutonomyLevel.AUTONOMOUS: "완전 자율 - 모든 액션 자동 처리",
        }[self._level]
