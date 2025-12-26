"""Abstract base class for Skills"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from pathlib import Path
import logging

from .result import SkillResult
from .types import SkillType


logger = logging.getLogger(__name__)


class BaseSkill(ABC):
    """스킬 추상 기본 클래스

    모든 스킬은 이 클래스를 상속받아 구현해야 합니다.

    Attributes:
        name: 스킬 이름
        skill_type: 스킬 타입 (SkillType enum)
        description: 스킬 설명
        capabilities: 스킬 기능 목록
        is_available: 스킬 사용 가능 여부
        skill_dir: 스킬 디렉토리 경로
        version: 스킬 버전
    """

    def __init__(
        self,
        name: str,
        skill_type: SkillType,
        description: str = "",
        capabilities: Optional[List[str]] = None,
        skill_dir: Optional[Path] = None,
        version: str = "1.0.0",
        allowed_tools: Optional[str] = None,
    ):
        """
        Args:
            name: 스킬 이름
            skill_type: 스킬 타입
            description: 스킬 설명
            capabilities: 스킬 기능 목록
            skill_dir: 스킬 디렉토리 경로
            version: 스킬 버전
            allowed_tools: 스킬이 필요로 하는 도구 목록
        """
        self.name = name
        self.skill_type = skill_type
        self.description = description
        self.capabilities = capabilities or []
        self.is_available = False
        self.skill_dir = skill_dir
        self.version = version
        self.allowed_tools = allowed_tools

    @abstractmethod
    async def initialize(self) -> bool:
        """스킬 초기화

        스킬에 필요한 리소스를 초기화합니다.
        예: API 클라이언트 연결, 설정 파일 로드 등

        Returns:
            초기화 성공 여부
        """
        pass

    @abstractmethod
    async def execute(self, params: Dict[str, Any]) -> SkillResult:
        """스킬 실행

        스킬의 주요 기능을 실행합니다.

        Args:
            params: 실행 파라미터

        Returns:
            실행 결과
        """
        pass

    @abstractmethod
    async def cleanup(self) -> None:
        """스킬 정리

        스킬이 사용한 리소스를 정리합니다.
        예: API 연결 종료, 임시 파일 삭제 등
        """
        pass

    async def check_availability(self) -> bool:
        """스킬 사용 가능성 확인

        Returns:
            사용 가능 여부
        """
        try:
            return await self.initialize()
        except Exception as e:
            logger.warning(f"Skill {self.name} not available: {e}")
            return False

    def get_info(self) -> Dict[str, Any]:
        """스킬 정보 반환

        Returns:
            스킬 정보 딕셔너리
        """
        return {
            "name": self.name,
            "type": self.skill_type.value,
            "description": self.description,
            "capabilities": self.capabilities,
            "is_available": self.is_available,
            "version": self.version,
            "skill_dir": str(self.skill_dir) if self.skill_dir else None,
            "allowed_tools": self.allowed_tools,
        }

    def load_skill_file(self, filename: str) -> Optional[str]:
        """스킬 디렉토리에서 파일 로드

        Args:
            filename: 파일명 (예: "SKILL.md", "datasources.md")

        Returns:
            파일 내용 (파일이 없으면 None)
        """
        if not self.skill_dir:
            return None

        file_path = self.skill_dir / filename
        if not file_path.exists():
            logger.warning(f"Skill file not found: {file_path}")
            return None

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            logger.error(f"Failed to load skill file {file_path}: {e}")
            return None

    def get_skill_description(self) -> Optional[str]:
        """SKILL.md 파일 내용 가져오기

        Returns:
            SKILL.md 파일 내용
        """
        return self.load_skill_file("SKILL.md")

    def get_skill_body(self) -> Optional[str]:
        """Get SKILL.md body (markdown content after frontmatter)

        Returns:
            SKILL.md body content
        """
        if not self.skill_dir:
            return None

        skill_md = self.skill_dir / "SKILL.md"
        if not skill_md.exists():
            return None

        try:
            content = skill_md.read_text(encoding='utf-8')
            # Import here to avoid circular dependency
            from .metadata_parser import extract_frontmatter
            _, body = extract_frontmatter(content)
            return body
        except Exception as e:
            logger.error(f"Failed to extract skill body from {skill_md}: {e}")
            return None

    def to_context(
        self,
        include_body: bool = True,
        max_tokens: int = 2000
    ) -> str:
        """Convert skill to LLM context (XML format)

        Args:
            include_body: Include SKILL.md documentation body
            max_tokens: Maximum tokens for body (approximate)

        Returns:
            XML formatted skill context
        """
        try:
            from .prompt_generator import generate_skill_context

            return generate_skill_context(
                skill_name=self.name,
                description=self.description,
                skill_body=self.get_skill_body() if include_body else None,
                allowed_tools=self.allowed_tools,
                capabilities=self.capabilities,
                include_body=include_body,
                max_tokens=max_tokens,
            )
        except ImportError:
            # Fallback if prompt_generator not available yet
            logger.warning("prompt_generator not available, returning basic context")
            return f"<skill><name>{self.name}</name><description>{self.description}</description></skill>"

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"name={self.name}, "
            f"type={self.skill_type.value}, "
            f"version={self.version}, "
            f"available={self.is_available})"
        )
