"""Agent autonomy policy mapping levels to approval behavior."""

from __future__ import annotations

from typing import List

from neos.config.settings import settings
from neos.workflow.enums import AutonomyLevel

_MANUAL_EXTRA_SKILLS: List[str] = [
    "knowledge_search",
    "realtime_info_search",
    "realtime_data_search",
    "multi_query_search",
    "web_lookup",
    "youtube_search",
    "deep_research",
]


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

        extra = [skill for skill in _MANUAL_EXTRA_SKILLS if skill not in configured]
        return configured + extra

    def requires_approval(self, skill_name: str) -> bool:
        return skill_name in self.get_approval_required_skills()

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
