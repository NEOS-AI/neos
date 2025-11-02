"""Abstract base class for MCP tools"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List
import logging

from .result import MCPToolResult
from .types import MCPToolType


logger = logging.getLogger(__name__)


class MCPTool(ABC):
    """MCP 도구 추상 기본 클래스

    모든 MCP 도구는 이 클래스를 상속받아 구현해야 합니다.

    Attributes:
        name: 도구 이름
        tool_type: 도구 타입 (MCPToolType enum)
        description: 도구 설명
        capabilities: 도구 기능 목록
        is_available: 도구 사용 가능 여부
    """

    def __init__(
        self,
        name: str,
        tool_type: MCPToolType,
        description: str = "",
        capabilities: List[str] = None,
    ):
        """
        Args:
            name: 도구 이름
            tool_type: 도구 타입
            description: 도구 설명
            capabilities: 도구 기능 목록
        """
        self.name = name
        self.tool_type = tool_type
        self.description = description
        self.capabilities = capabilities or []
        self.is_available = False

    @abstractmethod
    async def initialize(self) -> bool:
        """도구 초기화

        Returns:
            초기화 성공 여부
        """
        pass

    @abstractmethod
    async def execute(self, params: Dict[str, Any]) -> MCPToolResult:
        """도구 실행

        Args:
            params: 실행 파라미터

        Returns:
            실행 결과
        """
        pass

    @abstractmethod
    async def cleanup(self) -> None:
        """도구 정리 (리소스 해제 등)"""
        pass

    async def check_availability(self) -> bool:
        """도구 사용 가능성 확인

        Returns:
            사용 가능 여부
        """
        try:
            return await self.initialize()
        except Exception as e:
            logger.warning(f"MCP tool {self.name} not available: {e}")
            return False

    def get_info(self) -> Dict[str, Any]:
        """도구 정보 반환

        Returns:
            도구 정보 딕셔너리
        """
        return {
            "name": self.name,
            "type": self.tool_type.value,
            "description": self.description,
            "capabilities": self.capabilities,
            "is_available": self.is_available,
        }

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name}, type={self.tool_type.value}, available={self.is_available})"
