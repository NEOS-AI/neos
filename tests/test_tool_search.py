"""
Advanced Tool Search 단위 테스트

ToolRegistryStore, HybridSearchEngine, SearchToolsHandler의 핵심 기능을 테스트한다.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from typing import List, Optional

from neos.tools.tool_search.tool_metadata import ToolDefinition, ToolSearchResult
from neos.tools.tool_search.search_tools_handler import SearchToolsHandler, SEARCH_TOOLS_TOOL


# ============================================================================
# Fixtures
# ============================================================================

class MockEmbeddingManager:
    """결정적 벡터를 반환하는 모킹 EmbeddingManager"""

    def __init__(self):
        # 도구 이름/설명에 따라 다른 벡터를 반환
        self._vectors = {}
        self.dimension = 1536

    def set_vector(self, text_contains: str, vector: List[float]):
        """특정 텍스트에 대한 벡터 미리 설정"""
        self._vectors[text_contains] = vector

    async def get_embedding(self, text: str, use_cache: bool = True) -> Optional[List[float]]:
        """설정된 벡터 반환, 없으면 기본 벡터 생성"""
        for key, vector in self._vectors.items():
            if key.lower() in text.lower():
                return vector
        # 기본: 텍스트 해시 기반 결정적 벡터
        import hashlib
        h = hashlib.sha256(text.encode()).hexdigest()
        return [float(int(h[i:i+2], 16)) / 255.0 for i in range(0, min(len(h), 3072), 2)][:1536]


@pytest.fixture
def mock_embedding_manager():
    return MockEmbeddingManager()


# ============================================================================
# ToolDefinition 테스트
# ============================================================================

class TestToolDefinition:
    def test_to_anthropic_tool(self):
        """Anthropic API 형식 변환 테스트"""
        tool = ToolDefinition(
            name="test_tool",
            description="A test tool",
            input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
            source_type="skill",
            category="search",
            tags=["test", "search"],
        )

        result = tool.to_anthropic_tool()

        assert result["name"] == "test_tool"
        assert result["description"] == "A test tool"
        assert "properties" in result["input_schema"]
        # source_type, category, tags는 Anthropic 형식에 포함되지 않음
        assert "source_type" not in result
        assert "category" not in result


class TestToolSearchResult:
    def test_creation(self):
        """ToolSearchResult 생성 테스트"""
        tool = ToolDefinition(
            name="pdf_skill",
            description="Extract text from PDF",
            input_schema={},
            source_type="skill",
        )
        result = ToolSearchResult(tool=tool, score=0.89, match_source="hybrid")

        assert result.tool.name == "pdf_skill"
        assert result.score == 0.89
        assert result.match_source == "hybrid"


# ============================================================================
# SearchToolsHandler 테스트
# ============================================================================

class TestSearchToolsHandler:
    def test_search_tools_tool_schema(self):
        """SEARCH_TOOLS_TOOL 스키마 유효성 검증"""
        assert SEARCH_TOOLS_TOOL["name"] == "search_tools"
        assert "input_schema" in SEARCH_TOOLS_TOOL
        assert "query" in SEARCH_TOOLS_TOOL["input_schema"]["properties"]
        assert "query" in SEARCH_TOOLS_TOOL["input_schema"]["required"]
        assert "category" in SEARCH_TOOLS_TOOL["input_schema"]["properties"]

    @pytest.mark.asyncio
    async def test_handle_basic_query(self):
        """기본 검색 쿼리 처리 테스트"""
        # Mock ToolRegistryStore
        mock_store = MagicMock()
        mock_store.search = AsyncMock(return_value=[
            ToolSearchResult(
                tool=ToolDefinition(
                    name="pdf_skill",
                    description="Extract text from PDF documents",
                    input_schema={"type": "object"},
                    source_type="skill",
                    category="document",
                    tags=["pdf", "extract"],
                ),
                score=0.89,
                match_source="hybrid",
            ),
        ])

        handler = SearchToolsHandler(registry_store=mock_store)
        result = await handler.handle({"query": "extract text from PDF"})

        assert result["type"] == "tool_result"
        assert len(result["found_tools"]) == 1
        assert result["found_tools"][0]["name"] == "pdf_skill"
        assert result["found_tools"][0]["relevance_score"] == 0.89
        assert "Found 1 matching tools" in result["content"]

    @pytest.mark.asyncio
    async def test_handle_no_results(self):
        """결과 없는 경우 처리 테스트"""
        mock_store = MagicMock()
        mock_store.search = AsyncMock(return_value=[])

        handler = SearchToolsHandler(registry_store=mock_store)
        result = await handler.handle({"query": "nonexistent tool"})

        assert result["type"] == "tool_result"
        assert len(result["found_tools"]) == 0
        assert "No matching tools found" in result["content"]

    @pytest.mark.asyncio
    async def test_handle_category_filter(self):
        """카테고리 필터 적용 테스트"""
        mock_store = MagicMock()
        mock_store.search = AsyncMock(return_value=[])

        handler = SearchToolsHandler(registry_store=mock_store)
        await handler.handle({"query": "search papers", "category": "search"})

        # search가 category 파라미터로 호출되었는지 확인
        mock_store.search.assert_called_once_with(
            query="search papers",
            top_k=5,
            category="search",
        )

    @pytest.mark.asyncio
    async def test_result_format(self):
        """검색 결과 포맷 검증"""
        mock_store = MagicMock()
        mock_store.search = AsyncMock(return_value=[
            ToolSearchResult(
                tool=ToolDefinition(
                    name="arxiv_search",
                    description="Search academic papers on arXiv",
                    input_schema={
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"],
                    },
                    source_type="skill",
                    category="search",
                    tags=["academic", "paper"],
                ),
                score=0.923,
                match_source="vector",
            ),
        ])

        handler = SearchToolsHandler(registry_store=mock_store)
        result = await handler.handle({"query": "academic papers"})

        found = result["found_tools"][0]
        assert "name" in found
        assert "description" in found
        assert "input_schema" in found
        assert "relevance_score" in found
        assert "category" in found
        assert found["relevance_score"] == 0.923
        assert found["input_schema"]["type"] == "object"


# ============================================================================
# HybridSearchEngine 테스트 (DB 의존, mock으로 대체)
# ============================================================================

class TestHybridSearchEngine:
    @pytest.mark.asyncio
    async def test_row_to_result(self):
        """DB row → ToolSearchResult 변환 테스트"""
        from neos.tools.tool_search.hybrid_search_engine import HybridSearchEngine

        # Mock row object
        row = MagicMock()
        row.name = "test_tool"
        row.description = "A test tool"
        row.schema = {"type": "object"}
        row.source_type = "skill"
        row.category = "search"
        row.tags = ["test"]
        row.combined_score = 0.75
        row.match_source = "hybrid"

        result = HybridSearchEngine._row_to_result(row)

        assert isinstance(result, ToolSearchResult)
        assert result.tool.name == "test_tool"
        assert result.score == 0.75
        assert result.match_source == "hybrid"
        assert result.tool.input_schema == {"type": "object"}

    @pytest.mark.asyncio
    async def test_search_fallback_to_bm25(self, mock_embedding_manager):
        """임베딩 실패 시 BM25 폴백 테스트"""
        from neos.tools.tool_search.hybrid_search_engine import HybridSearchEngine

        # 임베딩 실패 시뮬레이션
        mock_embedding_manager.get_embedding = AsyncMock(return_value=None)

        engine = HybridSearchEngine(embedding_manager=mock_embedding_manager)

        # BM25 검색도 mock
        engine._search_bm25_only = AsyncMock(return_value=[])

        results = await engine.search(query="test query", top_k=5)

        # BM25 폴백이 호출되었는지 확인
        engine._search_bm25_only.assert_called_once_with("test query", 5, None)
        assert results == []


# ============================================================================
# ToolRegistryStore 테스트 (DB 의존, mock으로 대체)
# ============================================================================

class TestToolRegistryStore:
    @pytest.mark.asyncio
    async def test_category_inference_skill(self):
        """스킬 타입에서 카테고리 추론 테스트"""
        from neos.tools.tool_search.tool_registry_store import ToolRegistryStore

        assert ToolRegistryStore._infer_category_from_skill_type("search") == "search"
        assert ToolRegistryStore._infer_category_from_skill_type("analysis") == "analysis"
        assert ToolRegistryStore._infer_category_from_skill_type("generation") == "general"
        assert ToolRegistryStore._infer_category_from_skill_type("unknown") == "general"

    @pytest.mark.asyncio
    async def test_category_inference_tool(self):
        """MCP 도구 타입에서 카테고리 추론 테스트"""
        from neos.tools.tool_search.tool_registry_store import ToolRegistryStore

        assert ToolRegistryStore._infer_category_from_tool_type("search") == "search"
        assert ToolRegistryStore._infer_category_from_tool_type("file_processing") == "document"
        assert ToolRegistryStore._infer_category_from_tool_type("data_analysis") == "data"
        assert ToolRegistryStore._infer_category_from_tool_type("api_integration") == "general"
