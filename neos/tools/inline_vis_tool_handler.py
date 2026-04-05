"""
Inline Visualization Tool Handler

renderDiagram / renderChart 도구 입력을 inline_viz 이벤트로 변환.
아티팩트 핸들러와 달리 추가 LLM 호출 없이 즉시 이벤트를 emit한다.
"""
import uuid
from typing import Dict, Any, AsyncGenerator

from neos.utils.logger import get_logger

logger = get_logger(__name__)


async def handle_render_diagram(
    tool_input: Dict[str, Any]
) -> AsyncGenerator[Dict[str, Any], None]:
    title = tool_input.get("title", "")
    mermaid_code = tool_input.get("mermaidCode", "")
    description = tool_input.get("description", "")

    if not mermaid_code:
        yield {"type": "error", "error": "mermaidCode is required for renderDiagram"}
        return

    viz_id = str(uuid.uuid4())
    logger.info(f"[InlineVis] renderDiagram: {title} (id={viz_id})")

    yield {
        "type": "inline_viz",
        "viz_id": viz_id,
        "viz_type": "mermaid",
        "data": {
            "title": title,
            "mermaidCode": mermaid_code,
            "description": description,
        }
    }


async def handle_render_chart(
    tool_input: Dict[str, Any]
) -> AsyncGenerator[Dict[str, Any], None]:
    title = tool_input.get("title", "")
    chart_type = tool_input.get("type", "bar")
    data = tool_input.get("data", [])

    if not data:
        yield {"type": "error", "error": "data is required for renderChart"}
        return

    viz_id = str(uuid.uuid4())
    logger.info(f"[InlineVis] renderChart: {title} type={chart_type} (id={viz_id})")

    yield {
        "type": "inline_viz",
        "viz_id": viz_id,
        "viz_type": "chart",
        "data": {
            "title": title,
            "type": chart_type,
            "data": data,
        }
    }


async def execute_inline_vis_tool(
    tool_name: str,
    tool_input: Dict[str, Any],
) -> AsyncGenerator[Dict[str, Any], None]:
    if tool_name == "renderDiagram":
        async for event in handle_render_diagram(tool_input):
            yield event
    elif tool_name == "renderChart":
        async for event in handle_render_chart(tool_input):
            yield event
    else:
        yield {"type": "error", "error": f"Unknown inline vis tool: {tool_name}"}
