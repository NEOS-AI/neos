"""Tools 모듈 - MCP 및 다양한 도구 통합

리팩토링된 구조:
    - base: 기본 클래스 및 타입
    - tools: 개별 도구 구현
    - manager: 관리자 클래스
    - utils: 유틸리티

이전 버전과의 호환성을 위해 기존 import를 유지합니다.
"""

# 새로운 구조화된 imports
from .base import MCPTool, MCPToolResult, MCPToolType
from .manager import (
    MCPManager,
    MCPServerManager,
    ToolContext,
    ToolSelector,
    mcp_manager,
    mcp_server_manager,
    tool_selector,
)
from .tools import (
    DatabaseMCPTool,
    FileProcessingMCPTool,
    GitMCPTool,
    WebSearchMCPTool,
)

# 하위 호환성을 위한 별칭
from .base.types import ToolCondition

__all__ = [
    # Base classes and types
    "MCPTool",
    "MCPToolResult",
    "MCPToolType",
    "ToolCondition",
    # Individual tools
    "WebSearchMCPTool",
    "FileProcessingMCPTool",
    "DatabaseMCPTool",
    "GitMCPTool",
    # Managers
    "MCPManager",
    "MCPServerManager",
    "ToolSelector",
    "ToolContext",
    # Singleton instances
    "mcp_manager",
    "mcp_server_manager",
    "tool_selector",
]
