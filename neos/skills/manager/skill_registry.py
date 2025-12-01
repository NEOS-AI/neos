"""Skills Registry for managing available skills"""

from typing import Dict, Any, List, Optional, Type
from dataclasses import dataclass
from pathlib import Path
import logging

from neos.skills.base import BaseSkill, SkillType


logger = logging.getLogger(__name__)


@dataclass
class SkillInfo:
    """스킬 정보

    Attributes:
        name: 스킬 이름
        skill_class: 스킬 클래스
        skill_type: 스킬 타입
        description: 스킬 설명
        capabilities: 스킬 기능 목록
        version: 스킬 버전
        skill_dir: 스킬 디렉토리 경로
    """

    name: str
    skill_class: Type[BaseSkill]
    skill_type: SkillType
    description: str
    capabilities: List[str]
    version: str = "1.0.0"
    skill_dir: Optional[Path] = None


class SkillRegistry:
    """스킬 레지스트리 - 사용 가능한 모든 스킬 관리

    AgentRegistry 패턴을 따라 스킬을 등록하고 관리합니다.
    """

    def __init__(self):
        self._skills: Dict[str, SkillInfo] = {}
        self._instances: Dict[str, BaseSkill] = {}

    def register_skill(self, skill_info: SkillInfo) -> None:
        """스킬 등록

        Args:
            skill_info: 등록할 스킬 정보
        """
        self._skills[skill_info.name] = skill_info
        logger.info(
            f"Registered skill: {skill_info.name} "
            f"(type: {skill_info.skill_type.value}, version: {skill_info.version})"
        )

    def unregister_skill(self, skill_name: str) -> bool:
        """스킬 등록 해제

        Args:
            skill_name: 스킬 이름

        Returns:
            등록 해제 성공 여부
        """
        if skill_name in self._skills:
            del self._skills[skill_name]
            if skill_name in self._instances:
                del self._instances[skill_name]
            logger.info(f"Unregistered skill: {skill_name}")
            return True
        return False

    def get_skill(self, skill_name: str) -> Optional[BaseSkill]:
        """스킬 인스턴스 가져오기 (싱글톤)

        Args:
            skill_name: 스킬 이름

        Returns:
            스킬 인스턴스 (없으면 None)
        """
        if skill_name not in self._skills:
            logger.error(f"Skill '{skill_name}' not found in registry")
            return None

        # 이미 인스턴스가 있으면 재사용
        if skill_name in self._instances:
            return self._instances[skill_name]

        # 새 인스턴스 생성
        skill_info = self._skills[skill_name]
        try:
            instance = skill_info.skill_class(
                name=skill_info.name,
                skill_type=skill_info.skill_type,
                description=skill_info.description,
                capabilities=skill_info.capabilities,
                skill_dir=skill_info.skill_dir,
                version=skill_info.version,
            )
            self._instances[skill_name] = instance
            logger.info(f"Created skill instance: {skill_name}")
            return instance
        except Exception as e:
            logger.error(f"Failed to create skill instance '{skill_name}': {e}")
            return None

    def get_skill_info(self, skill_name: str) -> Optional[SkillInfo]:
        """스킬 정보 가져오기

        Args:
            skill_name: 스킬 이름

        Returns:
            스킬 정보 (없으면 None)
        """
        return self._skills.get(skill_name)

    def list_skills(
        self, skill_type: Optional[SkillType] = None
    ) -> List[SkillInfo]:
        """스킬 목록 조회

        Args:
            skill_type: 스킬 타입 (None이면 전체)

        Returns:
            스킬 정보 목록
        """
        skills = list(self._skills.values())

        if skill_type:
            skills = [s for s in skills if s.skill_type == skill_type]

        return skills

    def get_skill_types(self) -> List[SkillType]:
        """사용 가능한 스킬 타입 목록

        Returns:
            스킬 타입 목록
        """
        types = set(skill.skill_type for skill in self._skills.values())
        return sorted(types, key=lambda t: t.value)

    def skill_exists(self, skill_name: str) -> bool:
        """스킬 존재 여부 확인

        Args:
            skill_name: 스킬 이름

        Returns:
            존재 여부
        """
        return skill_name in self._skills

    def get_skills_by_capability(self, capability: str) -> List[SkillInfo]:
        """특정 capability를 가진 스킬 목록

        Args:
            capability: 찾을 기능

        Returns:
            해당 기능을 가진 스킬 목록
        """
        return [
            skill
            for skill in self._skills.values()
            if capability in skill.capabilities
        ]

    def get_skills_by_type(self, skill_type: SkillType) -> List[SkillInfo]:
        """특정 타입의 스킬 목록

        Args:
            skill_type: 스킬 타입

        Returns:
            해당 타입의 스킬 목록
        """
        return [
            skill
            for skill in self._skills.values()
            if skill.skill_type == skill_type
        ]

    def clear(self) -> None:
        """모든 스킬 등록 해제"""
        self._skills.clear()
        self._instances.clear()
        logger.info("Cleared all skills from registry")

    def __len__(self) -> int:
        """등록된 스킬 수"""
        return len(self._skills)

    def __contains__(self, skill_name: str) -> bool:
        """스킬 존재 여부 확인 (in 연산자)"""
        return skill_name in self._skills
