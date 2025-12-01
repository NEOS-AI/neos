"""Skills Module for NEOS

Skills는 AI 에이전트에게 특정 도메인의 전문성을 부여하는 확장 모듈입니다.
"""

from .base import BaseSkill, SkillResult, SkillType
from .manager import (
    SkillManager,
    SkillRegistry,
    SkillInfo,
    skill_manager,
)

# Version
__version__ = "1.0.0"

__all__ = [
    # Base classes
    "BaseSkill",
    "SkillResult",
    "SkillType",
    # Manager classes
    "SkillManager",
    "SkillRegistry",
    "SkillInfo",
    # Global instance
    "skill_manager",
]
