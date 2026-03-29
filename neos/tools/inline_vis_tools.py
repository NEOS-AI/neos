"""
Inline Visualization Tools for Anthropic Tool Use API

renderDiagram(Mermaid) 및 renderChart(Recharts) 도구를 Anthropic tool use API 형식으로 정의.
"""
from typing import Dict, Any


RENDER_DIAGRAM_TOOL: Dict[str, Any] = {
    "name": "renderDiagram",
    "description": (
        "Render a Mermaid diagram inline in the chat message to visualize processes, "
        "system structures, sequences, entity relationships, or causal graphs. "
        "Use this when a visual diagram would clarify a complex concept better than text alone."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Short descriptive title for the diagram."
            },
            "mermaidCode": {
                "type": "string",
                "description": (
                    "Valid Mermaid diagram code. Supported types: flowchart, sequenceDiagram, "
                    "classDiagram, stateDiagram, erDiagram. "
                    "Wrap node labels containing special characters in double quotes."
                )
            },
            "description": {
                "type": "string",
                "description": "One-sentence description of what the diagram shows."
            }
        },
        "required": ["title", "mermaidCode", "description"]
    }
}


RENDER_CHART_TOOL: Dict[str, Any] = {
    "name": "renderChart",
    "description": (
        "Render a bar, line, or pie chart inline in the chat message to visualize quantitative data. "
        "Use bar for comparisons, line for trends over time, pie for proportional composition."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Chart title."
            },
            "type": {
                "type": "string",
                "enum": ["bar", "line", "pie"],
                "description": "Chart type: 'bar' for comparisons, 'line' for trends, 'pie' for proportions."
            },
            "data": {
                "type": "array",
                "description": "Array of data points.",
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string"},
                        "value": {"type": "number"}
                    },
                    "required": ["label", "value"]
                }
            }
        },
        "required": ["title", "type", "data"]
    }
}


INLINE_VIS_TOOLS = [RENDER_DIAGRAM_TOOL, RENDER_CHART_TOOL]
_INLINE_VIS_TOOL_NAMES = {"renderDiagram", "renderChart"}


def get_inline_vis_tools() -> list[Dict[str, Any]]:
    """인라인 시각화 도구 목록 반환"""
    return INLINE_VIS_TOOLS


def is_inline_vis_tool(name: str) -> bool:
    """시각화 도구 여부 판별"""
    return name in _INLINE_VIS_TOOL_NAMES
