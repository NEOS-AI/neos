"""Type definitions for MCP tools"""

from enum import Enum


class MCPToolType(Enum):
    """MCP 도구 타입"""

    WEB_SEARCH = "web_search"
    FILE_PROCESSING = "file_processing"
    DATA_ANALYSIS = "data_analysis"
    API_INTEGRATION = "api_integration"
    CODE_EXECUTION = "code_execution"
    IMAGE_PROCESSING = "image_processing"


class ToolCondition(Enum):
    """도구 실행 조건"""

    ALWAYS = "always"  # 항상 실행
    MCP_AVAILABLE = "mcp_available"  # MCP 사용 가능할 때만
    MCP_FALLBACK = "mcp_fallback"  # 기본 도구 실패 시 MCP 사용
    PREFERENCE_BASED = "preference_based"  # 설정에 따라
    CONTEXT_DEPENDENT = "context_dependent"  # 컨텍스트에 따라
