"""
Tool Registry Store - 도구 레지스트리 저장소

도구 메타데이터의 등록, 조회, 검색, 사용 통계를 관리한다.
기존 SkillRegistry와 MCPManager에서 도구 메타데이터를 가져와 등록할 수 있다.
"""

import json
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional

from sqlalchemy import text

from neos.database.connection import get_session_ctx
from neos.utils.embeddings import EmbeddingManager
from .hybrid_search_engine import HybridSearchEngine
from .tool_metadata import ToolDefinition, ToolSearchResult

logger = logging.getLogger(__name__)

# 도구 등록 upsert SQL
UPSERT_TOOL_SQL = """
INSERT INTO tool_registry (name, display_name, description, schema, category, tags, source_type, defer_loading, embedding)
VALUES (:name, :display_name, :description, :schema::jsonb, :category, :tags, :source_type, :defer_loading, :embedding::vector)
ON CONFLICT (name) DO UPDATE SET
    display_name = EXCLUDED.display_name,
    description = EXCLUDED.description,
    schema = EXCLUDED.schema,
    category = EXCLUDED.category,
    tags = EXCLUDED.tags,
    source_type = EXCLUDED.source_type,
    defer_loading = EXCLUDED.defer_loading,
    embedding = EXCLUDED.embedding,
    updated_at = NOW()
RETURNING id::text;
"""

# 코어 도구 조회 SQL
CORE_TOOLS_SQL = """
SELECT name, display_name, description, schema, category, tags, source_type
FROM tool_registry
WHERE defer_loading = FALSE AND is_active = TRUE
ORDER BY name;
"""

# 사용 횟수 업데이트 SQL
UPDATE_USAGE_SQL = """
UPDATE tool_registry
SET usage_count = usage_count + 1,
    last_used_at = NOW(),
    updated_at = NOW()
WHERE name = :tool_name;
"""

# 임베딩 없는 도구 조회 SQL
NULL_EMBEDDING_SQL = """
SELECT name, description, tags
FROM tool_registry
WHERE embedding IS NULL AND is_active = TRUE;
"""

# 임베딩 업데이트 SQL
UPDATE_EMBEDDING_SQL = """
UPDATE tool_registry
SET embedding = :embedding::vector,
    updated_at = NOW()
WHERE name = :name;
"""


class ToolRegistryStore:
    """도구 레지스트리 저장소 - 등록, 조회, 하이브리드 검색"""

    def __init__(
        self,
        embedding_manager: EmbeddingManager,
        search_engine: Optional[HybridSearchEngine] = None,
        rrf_k: int = 60,
    ):
        self.embedding_manager = embedding_manager
        self.search_engine = search_engine or HybridSearchEngine(
            embedding_manager=embedding_manager,
            rrf_k=rrf_k,
        )

    async def register_tool(
        self,
        name: str,
        description: str,
        schema: Dict[str, Any],
        source_type: str,
        category: str = "general",
        tags: Optional[List[str]] = None,
        defer_loading: bool = True,
        display_name: Optional[str] = None,
    ) -> Optional[str]:
        """
        도구 등록 및 임베딩 생성 (upsert)

        Returns:
            등록된 도구의 ID (문자열) 또는 실패 시 None
        """
        # 임베딩 생성
        embedding_text = f"{name} {description}"
        if tags:
            embedding_text += " " + " ".join(tags)
        embedding = await self.embedding_manager.get_embedding(embedding_text)

        embedding_str = None
        if embedding:
            embedding_str = "[" + ",".join(str(v) for v in embedding) + "]"

        schema_json = json.dumps(schema, ensure_ascii=False) if schema else None

        try:
            async with get_session_ctx() as session:
                result = await session.execute(
                    text(UPSERT_TOOL_SQL),
                    {
                        "name": name,
                        "display_name": display_name or name,
                        "description": description,
                        "schema": schema_json,
                        "category": category,
                        "tags": tags or [],
                        "source_type": source_type,
                        "defer_loading": defer_loading,
                        "embedding": embedding_str,
                    }
                )
                row = result.fetchone()
                await session.commit()
                tool_id = row[0] if row else None
                logger.info(f"Registered tool: {name} (source={source_type}, defer={defer_loading})")
                return tool_id
        except Exception as e:
            logger.error(f"Failed to register tool '{name}': {e}")
            return None

    async def get_core_tools(self) -> List[ToolDefinition]:
        """defer_loading=False인 코어 도구 목록 반환"""
        async with get_session_ctx() as session:
            result = await session.execute(text(CORE_TOOLS_SQL))
            rows = result.fetchall()

        return [
            ToolDefinition(
                name=row.name,
                description=row.description,
                input_schema=row.schema or {},
                source_type=row.source_type,
                category=row.category or "general",
                tags=row.tags or [],
            )
            for row in rows
        ]

    async def search(
        self,
        query: str,
        top_k: int = 5,
        category: Optional[str] = None,
    ) -> List[ToolSearchResult]:
        """하이브리드 검색 (벡터 + BM25 + RRF)"""
        return await self.search_engine.search(
            query=query,
            top_k=top_k,
            category=category,
        )

    async def update_usage(self, tool_name: str) -> None:
        """도구 사용 횟수 증가"""
        try:
            async with get_session_ctx() as session:
                await session.execute(
                    text(UPDATE_USAGE_SQL),
                    {"tool_name": tool_name}
                )
                await session.commit()
        except Exception as e:
            logger.warning(f"Failed to update usage for '{tool_name}': {e}")

    async def register_from_skill_registry(self) -> int:
        """기존 SkillRegistry의 모든 스킬을 자동 등록. 등록된 수 반환"""
        from neos.skills.manager.skill_manager import skill_manager

        registry = skill_manager.registry
        skills = registry.list_skills()
        count = 0

        for skill_info in skills:
            # 스킬의 description과 capabilities를 결합하여 풍부한 검색 메타데이터 생성
            description = skill_info.description
            if skill_info.capabilities:
                description += " Capabilities: " + ", ".join(skill_info.capabilities)

            # 스킬의 카테고리를 skill_type에서 추론
            category = self._infer_category_from_skill_type(skill_info.skill_type.value)

            # skill_class에서 input_schema 추출 (BaseSkill.get_input_schema classmethod)
            try:
                schema = skill_info.skill_class.get_input_schema()
            except Exception:
                schema = {}

            result = await self.register_tool(
                name=skill_info.name,
                description=description,
                schema=schema,
                source_type="skill",
                category=category,
                tags=list(skill_info.capabilities) if skill_info.capabilities else [],
                defer_loading=True,
                display_name=skill_info.name,
            )
            if result:
                count += 1

        logger.info(f"Registered {count} skills from SkillRegistry")
        return count

    async def register_from_mcp_manager(self) -> int:
        """기존 MCPManager의 모든 도구를 자동 등록. 등록된 수 반환"""
        from neos.tools.manager.mcp_manager import mcp_manager

        tools = mcp_manager.get_available_tools()
        count = 0

        for tool in tools:
            description = tool.description
            if tool.capabilities:
                description += " Capabilities: " + ", ".join(tool.capabilities)

            category = self._infer_category_from_tool_type(tool.tool_type.value)

            # MCPTool 인스턴스에서 input_schema 추출 (get_input_schema 미구현 시 기본값 사용)
            try:
                schema = tool.get_input_schema()
            except Exception:
                schema = {}

            result = await self.register_tool(
                name=tool.name,
                description=description,
                schema=schema,
                source_type="mcp_tool",
                category=category,
                tags=list(tool.capabilities) if tool.capabilities else [],
                defer_loading=True,
                display_name=tool.name,
            )
            if result:
                count += 1

        logger.info(f"Registered {count} tools from MCPManager")
        return count

    async def rebuild_index(self) -> None:
        """임베딩이 없는 도구의 임베딩을 재생성"""
        async with get_session_ctx() as session:
            result = await session.execute(text(NULL_EMBEDDING_SQL))
            rows = result.fetchall()

        if not rows:
            logger.info("All tools have embeddings, nothing to rebuild")
            return

        logger.info(f"Rebuilding embeddings for {len(rows)} tools")
        updates = []
        for row in rows:
            embedding_text = f"{row.name} {row.description}"
            if row.tags:
                embedding_text += " " + " ".join(row.tags)

            embedding = await self.embedding_manager.get_embedding(embedding_text)
            if embedding:
                embedding_str = "[" + ",".join(str(v) for v in embedding) + "]"
                updates.append({"name": row.name, "embedding": embedding_str})

        if updates:
            async with get_session_ctx() as session:
                for params in updates:
                    await session.execute(text(UPDATE_EMBEDDING_SQL), params)
                await session.commit()

        logger.info(f"Embedding rebuild complete: {len(updates)} tools updated")

    async def auto_promote_core_tools(self, threshold: int = 100) -> List[str]:
        """usage_count 기준으로 코어 도구 자동 승격 후보 반환"""
        sql = """
        SELECT name, usage_count
        FROM tool_registry
        WHERE defer_loading = TRUE AND is_active = TRUE AND usage_count >= :threshold
        ORDER BY usage_count DESC;
        """
        async with get_session_ctx() as session:
            result = await session.execute(text(sql), {"threshold": threshold})
            rows = result.fetchall()

        return [row.name for row in rows]

    @staticmethod
    def _infer_category_from_skill_type(skill_type: str) -> str:
        """스킬 타입에서 카테고리 추론"""
        mapping = {
            "search": "search",
            "analysis": "analysis",
            "generation": "general",
            "document": "document",
            "data": "data",
        }
        return mapping.get(skill_type, "general")

    @staticmethod
    def _infer_category_from_tool_type(tool_type: str) -> str:
        """MCP 도구 타입에서 카테고리 추론"""
        mapping = {
            "search": "search",
            "file_processing": "document",
            "data_analysis": "data",
            "api_integration": "general",
        }
        return mapping.get(tool_type, "general")
