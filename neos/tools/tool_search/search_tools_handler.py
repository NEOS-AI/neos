"""
search_tools 도구 정의 및 핸들러

Anthropic Advanced Tool Use 패턴의 핵심 메타 도구.
Claude에게 search_tools 도구를 제공하여 필요한 도구를 동적으로 검색할 수 있게 한다.
"""

import logging
from typing import Dict, Any

from .tool_registry_store import ToolRegistryStore

logger = logging.getLogger(__name__)


# Claude에게 제공되는 search_tools 도구 스키마
SEARCH_TOOLS_TOOL: Dict[str, Any] = {
    "name": "search_tools",
    "description": (
        "Search for available tools and skills by describing what capability you need. "
        "Use this when you don't have a suitable tool loaded for the user's request. "
        "Returns matching tool definitions that you can then invoke. "
        "You can search multiple times with different queries if the first results "
        "aren't satisfactory."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "Natural language description of the capability needed. "
                    "Be specific about what you want to accomplish. "
                    "Examples: 'search academic papers on arxiv', "
                    "'extract text from PDF documents', "
                    "'query BigQuery database'"
                )
            },
            "category": {
                "type": "string",
                "enum": ["search", "analysis", "document", "data", "general"],
                "description": "Optional category filter to narrow results"
            }
        },
        "required": ["query"]
    }
}


class SearchToolsHandler:
    """search_tools 호출 처리"""

    def __init__(self, registry_store: ToolRegistryStore, top_k: int = 5):
        self.registry_store = registry_store
        self.top_k = top_k

    async def handle(self, tool_input: Dict[str, Any]) -> Dict[str, Any]:
        """
        search_tools 호출 처리

        Args:
            tool_input: {"query": "...", "category": "..." (optional)}

        Returns:
            검색 결과. found_tools에 도구 스키마를 포함하여
            Claude가 후속 호출에 사용할 수 있게 한다.
        """
        query = tool_input["query"]
        category = tool_input.get("category")

        logger.info(f"search_tools called: query='{query}', category={category}")

        results = await self.registry_store.search(
            query=query,
            top_k=self.top_k,
            category=category,
        )

        if not results:
            logger.info(f"No matching tools found for query: '{query}'")
            return {
                "type": "tool_result",
                "content": "No matching tools found. Try a different search query.",
                "found_tools": []
            }

        found_tools = []
        for result in results:
            found_tools.append({
                "name": result.tool.name,
                "description": result.tool.description,
                "input_schema": result.tool.input_schema,
                "relevance_score": round(result.score, 3),
                "category": result.tool.category,
            })

        logger.info(
            f"search_tools found {len(found_tools)} tools: "
            f"{[t['name'] for t in found_tools]}"
        )

        return {
            "type": "tool_result",
            "content": (
                f"Found {len(found_tools)} matching tools. "
                "You can now use any of these tools by calling them directly."
            ),
            "found_tools": found_tools
        }
