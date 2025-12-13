"""Skills Manager for initializing and managing skills"""

from typing import Dict, Any, List, Optional
import logging

from neos.skills.base import SkillResult, SkillType
from neos.skills.manager.skill_registry import SkillRegistry, SkillInfo


logger = logging.getLogger(__name__)


class SkillManager:
    """스킬 매니저 - 스킬의 라이프사이클 관리

    MCPManager 패턴을 따라 스킬을 초기화하고 실행합니다.
    """

    def __init__(self, skill_registry: Optional[SkillRegistry] = None):
        """
        Args:
            skill_registry: 스킬 레지스트리 (None이면 새로 생성)
        """
        self.registry = skill_registry or SkillRegistry()
        self._initialized_skills: Dict[str, bool] = {}

    def register_builtin_skills(self) -> None:
        """내장 스킬 등록

        builtin/ 디렉토리의 스킬들을 자동으로 등록합니다.
        """
        try:
            # 동적으로 builtin 스킬들을 import하고 등록
            from neos.skills.builtin import get_builtin_skills

            builtin_skills = get_builtin_skills()
            for skill_info in builtin_skills:
                self.registry.register_skill(skill_info)

            logger.info(
                f"Registered {len(builtin_skills)} builtin skills"
            )
        except ImportError as e:
            logger.warning(f"Failed to import builtin skills: {e}")
        except Exception as e:
            logger.error(f"Error registering builtin skills: {e}")

    async def initialize_all(self) -> Dict[str, bool]:
        """모든 스킬 초기화

        Returns:
            스킬별 초기화 성공 여부 딕셔너리
        """
        results = {}
        for skill_name in self.registry._skills.keys():
            success = await self.initialize_skill(skill_name)
            results[skill_name] = success

        logger.info(
            f"Initialized {sum(results.values())}/{len(results)} skills"
        )
        return results

    async def initialize_skill(self, skill_name: str) -> bool:
        """특정 스킬 초기화

        Args:
            skill_name: 스킬 이름

        Returns:
            초기화 성공 여부
        """
        if skill_name in self._initialized_skills:
            return self._initialized_skills[skill_name]

        skill = self.registry.get_skill(skill_name)
        if not skill:
            logger.error(f"Skill '{skill_name}' not found")
            return False

        try:
            success = await skill.initialize()
            skill.is_available = success
            self._initialized_skills[skill_name] = success

            if success:
                logger.info(f"Successfully initialized skill: {skill_name}")
            else:
                logger.warning(f"Failed to initialize skill: {skill_name}")

            return success
        except Exception as e:
            logger.error(f"Error initializing skill '{skill_name}': {e}")
            self._initialized_skills[skill_name] = False
            return False

    async def execute_skill(
        self, skill_name: str, params: Dict[str, Any]
    ) -> SkillResult:
        """스킬 실행

        Args:
            skill_name: 스킬 이름
            params: 실행 파라미터

        Returns:
            실행 결과
        """
        # 스킬이 초기화되지 않았으면 초기화
        if skill_name not in self._initialized_skills:
            success = await self.initialize_skill(skill_name)
            if not success:
                return SkillResult.error_result(
                    error=f"Failed to initialize skill '{skill_name}'",
                    skill_name=skill_name,
                )

        skill = self.registry.get_skill(skill_name)
        if not skill:
            return SkillResult.error_result(
                error=f"Skill '{skill_name}' not found",
                skill_name=skill_name,
            )

        if not skill.is_available:
            return SkillResult.error_result(
                error=f"Skill '{skill_name}' is not available",
                skill_name=skill_name,
            )

        try:
            logger.info(f"Executing skill: {skill_name} with params: {params}")
            result = await skill.execute(params)
            logger.info(f"Skill execution completed: {skill_name}")
            return result
        except Exception as e:
            logger.error(f"Error executing skill '{skill_name}': {e}")
            return SkillResult.error_result(
                error=str(e),
                skill_name=skill_name,
            )

    async def cleanup_skill(self, skill_name: str) -> bool:
        """특정 스킬 정리

        Args:
            skill_name: 스킬 이름

        Returns:
            정리 성공 여부
        """
        skill = self.registry.get_skill(skill_name)
        if not skill:
            logger.error(f"Skill '{skill_name}' not found")
            return False

        try:
            await skill.cleanup()
            skill.is_available = False
            if skill_name in self._initialized_skills:
                del self._initialized_skills[skill_name]
            logger.info(f"Successfully cleaned up skill: {skill_name}")
            return True
        except Exception as e:
            logger.error(f"Error cleaning up skill '{skill_name}': {e}")
            return False

    async def cleanup_all(self) -> None:
        """모든 스킬 정리"""
        for skill_name in list(self._initialized_skills.keys()):
            await self.cleanup_skill(skill_name)
        logger.info("Cleaned up all skills")

    def get_available_skills(
        self, skill_type: Optional[SkillType] = None
    ) -> List[Dict[str, Any]]:
        """사용 가능한 스킬 목록 조회

        Args:
            skill_type: 스킬 타입 (None이면 전체)

        Returns:
            스킬 정보 목록
        """
        skill_infos = self.registry.list_skills(skill_type)
        return [
            {
                "name": info.name,
                "type": info.skill_type.value,
                "description": info.description,
                "capabilities": info.capabilities,
                "version": info.version,
                "is_available": self._initialized_skills.get(info.name, False),
            }
            for info in skill_infos
        ]

    def get_skill_info(self, skill_name: str) -> Optional[Dict[str, Any]]:
        """스킬 정보 조회

        Args:
            skill_name: 스킬 이름

        Returns:
            스킬 정보 (없으면 None)
        """
        skill = self.registry.get_skill(skill_name)
        if not skill:
            return None

        return skill.get_info()

    def register_custom_skill(
        self,
        skill_info: SkillInfo,
        auto_initialize: bool = True
    ) -> bool:
        """커스텀 스킬 등록

        Args:
            skill_info: 스킬 정보
            auto_initialize: 자동 초기화 여부

        Returns:
            등록 성공 여부
        """
        try:
            self.registry.register_skill(skill_info)
            logger.info(f"Registered custom skill: {skill_info.name}")

            if auto_initialize:
                # 비동기 초기화는 별도로 호출해야 함
                logger.info(
                    f"Auto-initialize enabled for {skill_info.name}, "
                    "call initialize_skill() to initialize"
                )

            return True
        except Exception as e:
            logger.error(f"Error registering custom skill: {e}")
            return False


# 전역 스킬 매니저 인스턴스
skill_manager = SkillManager()
