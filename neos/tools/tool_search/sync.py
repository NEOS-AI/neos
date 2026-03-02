"""
Tool Registry 동기화 스크립트

기존 스킬, MCP 도구, 아티팩트 도구를 Tool Registry에 동기화한다.
앱 시작 시 또는 CLI 명령으로 실행 가능.
"""

import asyncio
import logging

from neos.utils.embeddings import EmbeddingManager
from neos.tools.artifact_tools import ARTIFACT_TOOLS
from .tool_registry_store import ToolRegistryStore
from .search_tools_handler import SEARCH_TOOLS_TOOL

logger = logging.getLogger(__name__)


async def sync_tool_registry(
    store: ToolRegistryStore | None = None,
) -> dict:
    """
    기존 스킬/도구를 Tool Registry에 동기화

    Args:
        store: ToolRegistryStore 인스턴스 (없으면 새로 생성)

    Returns:
        동기화 결과 {"artifact_tools": int, "skills": int, "mcp_tools": int}
    """
    if store is None:
        embedding_manager = EmbeddingManager()
        store = ToolRegistryStore(embedding_manager=embedding_manager)

    result = {"artifact_tools": 0, "skills": 0, "mcp_tools": 0}

    # 1. 아티팩트 도구 등록 (코어 도구 - defer_loading=False)
    for tool in ARTIFACT_TOOLS:
        tool_id = await store.register_tool(
            name=tool["name"],
            description=tool["description"],
            schema=tool["input_schema"],
            source_type="artifact_tool",
            category="document",
            tags=["document", "artifact", "creation"],
            defer_loading=False,  # 코어 도구
        )
        if tool_id:
            result["artifact_tools"] += 1

    logger.info(f"Synced {result['artifact_tools']} artifact tools (core)")

    # 2. 빌트인 스킬 등록 (검색 대상 - defer_loading=True)
    try:
        result["skills"] = await store.register_from_skill_registry()
    except Exception as e:
        logger.warning(f"Failed to sync skills: {e}")

    # 3. MCP 도구 등록 (검색 대상 - defer_loading=True)
    try:
        result["mcp_tools"] = await store.register_from_mcp_manager()
    except Exception as e:
        logger.warning(f"Failed to sync MCP tools: {e}")

    # 4. 임베딩 인덱스 재구축 (누락분)
    await store.rebuild_index()

    total = sum(result.values())
    logger.info(
        f"Tool registry sync complete: {total} tools "
        f"(artifact={result['artifact_tools']}, "
        f"skills={result['skills']}, "
        f"mcp={result['mcp_tools']})"
    )

    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(sync_tool_registry())
