"""
Tool Search 데이터 모델

ToolDefinition: Anthropic tool 정의 형식
ToolSearchResult: 하이브리드 검색 결과
"""

from dataclasses import dataclass, field
from typing import Dict, Any, List


@dataclass
class ToolDefinition:
    """Anthropic tool 정의 형식"""
    name: str
    description: str
    input_schema: Dict[str, Any]
    source_type: str        # 'skill' | 'mcp_tool' | 'artifact_tool' | 'custom'
    category: str = "general"
    tags: List[str] = field(default_factory=list)

    def to_anthropic_tool(self) -> Dict[str, Any]:
        """Anthropic API tools 파라미터 형식으로 변환"""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


@dataclass
class ToolSearchResult:
    """하이브리드 검색 결과"""
    tool: ToolDefinition
    score: float                    # 0.0 ~ 1.0
    match_source: str               # 'vector' | 'bm25' | 'hybrid'
