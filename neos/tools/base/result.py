"""Result classes for MCP tool execution"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class MCPToolResult:
    """MCP 도구 실행 결과

    Attributes:
        success: 실행 성공 여부
        data: 실행 결과 데이터
        error: 에러 메시지 (실패 시)
        tool_name: 실행된 도구 이름
        execution_time_ms: 실행 시간 (밀리초)
        metadata: 추가 메타데이터
    """

    success: bool
    data: Any
    error: Optional[str] = None
    tool_name: str = ""
    execution_time_ms: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환"""
        return {
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "tool_name": self.tool_name,
            "execution_time_ms": self.execution_time_ms,
            "metadata": self.metadata,
        }

    @classmethod
    def from_error(
        cls,
        error: str,
        tool_name: str = "",
        execution_time_ms: int = 0,
    ) -> "MCPToolResult":
        """에러로부터 결과 생성"""
        return cls(
            success=False,
            data=None,
            error=error,
            tool_name=tool_name,
            execution_time_ms=execution_time_ms,
        )

    @classmethod
    def from_success(
        cls,
        data: Any,
        tool_name: str = "",
        execution_time_ms: int = 0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "MCPToolResult":
        """성공 결과 생성"""
        return cls(
            success=True,
            data=data,
            tool_name=tool_name,
            execution_time_ms=execution_time_ms,
            metadata=metadata or {},
        )
