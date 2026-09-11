"""Skills Manager for initializing and managing skills"""

from typing import Dict, Any, List, Optional
from pathlib import Path
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
        self._markdown_catalog = None

    def register_builtin_skills(self, use_auto_discovery: bool = False) -> None:
        """내장 스킬 등록

        Args:
            use_auto_discovery: True이면 자동 발견 사용, False이면 기존 방식 (하위 호환성)
        """
        if use_auto_discovery:
            # 새로운 자동 발견 방식
            self.auto_discover_builtin_skills()
        else:
            # 기존 수동 등록 방식 (하위 호환성)
            try:
                from neos.skills.builtin import get_builtin_skills

                builtin_skills = get_builtin_skills()
                for skill_info in builtin_skills:
                    self.registry.register_skill(skill_info)

                logger.info(
                    f"Registered {len(builtin_skills)} builtin skills (manual mode)"
                )
            except ImportError as e:
                logger.warning(f"Failed to import builtin skills: {e}")
            except Exception as e:
                logger.error(f"Error registering builtin skills: {e}")
        self._log_markdown_catalog()

    def auto_discover_builtin_skills(self, check_deps: bool = True) -> None:
        """내장 스킬 자동 발견 및 등록

        Args:
            check_deps: 의존성 체크 수행 여부
        """
        from neos.skills.manager.auto_discovery import discover_skills

        builtin_dir = Path(__file__).parent.parent / "builtin"

        logger.info(f"Auto-discovering builtin skills from: {builtin_dir}")
        discovered_skills = discover_skills(builtin_dir, check_deps=check_deps)

        for skill_info in discovered_skills:
            self.registry.register_skill(skill_info)

        logger.info(
            f"Auto-discovered and registered {len(discovered_skills)} builtin skills"
        )

    def auto_discover_custom_skills(
        self,
        custom_dir: Path,
        check_deps: bool = True
    ) -> None:
        """커스텀 스킬 자동 발견 및 등록

        Args:
            custom_dir: 커스텀 스킬 디렉토리 경로
            check_deps: 의존성 체크 수행 여부
        """
        from neos.skills.manager.auto_discovery import discover_skills

        if not custom_dir.exists():
            logger.warning(f"Custom skills directory not found: {custom_dir}")
            return

        logger.info(f"Auto-discovering custom skills from: {custom_dir}")
        discovered_skills = discover_skills(custom_dir, check_deps=check_deps)

        for skill_info in discovered_skills:
            self.registry.register_skill(skill_info)

        logger.info(
            f"Auto-discovered and registered {len(discovered_skills)} custom skills"
        )

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
                "allowed_tools": info.allowed_tools,
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

    def generate_skills_prompt(
        self,
        skill_names: Optional[List[str]] = None,
        include_body: bool = True,
        skill_type: Optional[SkillType] = None,
    ) -> str:
        """Generate XML prompt for skills.

        Args:
            skill_names: Specific skills to include (None = all available)
            include_body: Include SKILL.md documentation body
            skill_type: Filter by skill type

        Returns:
            XML formatted skills prompt (<available_skills>...</available_skills>)
        """
        from neos.skills.base.prompt_generator import generate_skills_prompt

        # Get skill list
        if skill_names:
            skills = [self.registry.get_skill(n) for n in skill_names]
            skills = [s for s in skills if s is not None]
        else:
            skill_infos = self.registry.list_skills(skill_type)
            skills = [self.registry.get_skill(info.name) for info in skill_infos]

        # Convert to context
        skills_data = []
        for skill in skills:
            if not skill:
                continue

            # Include all skills (even if not initialized) for prompt generation
            # Prompt generation is informational and doesn't require initialization
            skills_data.append({
                "name": skill.name,
                "description": skill.description,
                "skill_body": skill.get_skill_body() if include_body else None,
                "allowed_tools": skill.allowed_tools,
                "capabilities": skill.capabilities,
            })

        return generate_skills_prompt(skills_data, include_body=include_body)

    def get_available_skills_context(self) -> str:
        """Convenience method: all available skills with body.

        Returns:
            XML formatted prompt with all available skills
        """
        return self.generate_skills_prompt(include_body=True)

    def markdown_catalog(self):
        """Return the markdown skill catalog (names/descriptions only)."""
        if self._markdown_catalog is None:
            from neos.skills.markdown_catalog import default_catalog

            self._markdown_catalog = default_catalog()
        return self._markdown_catalog

    def markdown_skills(self):
        """Indexed markdown skills. Not registered as BaseSkill."""
        return list(self.markdown_catalog().list_skills())

    def _log_markdown_catalog(self) -> None:
        try:
            visible = self.markdown_skills()
        except Exception as exc:
            logger.warning("Failed to index markdown skill catalog: %s", exc)
            return
        logger.info(
            "Markdown skill catalog visible: %s skills (not registered as BaseSkill)",
            len(visible),
        )


# 전역 스킬 매니저 인스턴스
skill_manager = SkillManager()
