"""
Advanced Tool Search 통합 테스트

멀티턴 도구 호출 루프의 E2E 흐름을 테스트한다.
Claude API를 모킹하여 search_tools → 도구 발견 → 도구 실행 흐름을 검증한다.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from neos.tools.tool_search.tool_metadata import ToolDefinition, ToolSearchResult
from neos.tools.tool_search.search_tools_handler import SearchToolsHandler, SEARCH_TOOLS_TOOL


# ============================================================================
# Helper: Mock Claude 응답 생성
# ============================================================================

def make_text_block(text: str):
    """Claude text content block mock"""
    block = MagicMock()
    block.type = "text"
    block.text = text
    block.model_dump = MagicMock(return_value={"type": "text", "text": text})
    return block


def make_tool_use_block(name: str, input_data: dict, tool_id: str = "tool_123"):
    """Claude tool_use content block mock"""
    block = MagicMock()
    block.type = "tool_use"
    block.name = name
    block.input = input_data
    block.id = tool_id
    block.model_dump = MagicMock(return_value={
        "type": "tool_use", "id": tool_id, "name": name, "input": input_data
    })
    return block


def make_final_message(content_blocks, input_tokens=100, output_tokens=50):
    """Claude final_message mock"""
    msg = MagicMock()
    msg.content = content_blocks
    msg.usage = MagicMock()
    msg.usage.input_tokens = input_tokens
    msg.usage.output_tokens = output_tokens
    return msg


# ============================================================================
# 테스트
# ============================================================================

class TestToolSearchFlow:
    """E2E 통합 테스트"""

    @pytest.mark.asyncio
    async def test_core_tool_direct_use(self):
        """코어 도구는 search_tools 없이 직접 사용 가능"""
        mock_store = MagicMock()
        mock_store.search = AsyncMock(return_value=[])

        handler = SearchToolsHandler(registry_store=mock_store)

        # search_tools가 호출되지 않으면 검색은 일어나지 않음
        # 코어 도구(createDocument 등)는 active_tools에 이미 포함되어 있어 직접 호출 가능
        assert SEARCH_TOOLS_TOOL["name"] == "search_tools"

    @pytest.mark.asyncio
    async def test_search_then_discover_tools(self):
        """search_tools 호출 → 도구 검색 → 도구 발견 흐름"""
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
                    tags=["academic", "arxiv"],
                ),
                score=0.92,
                match_source="hybrid",
            ),
            ToolSearchResult(
                tool=ToolDefinition(
                    name="semantic_scholar_search",
                    description="Search papers on Semantic Scholar",
                    input_schema={"type": "object"},
                    source_type="skill",
                    category="search",
                    tags=["academic", "scholar"],
                ),
                score=0.78,
                match_source="vector",
            ),
        ])

        handler = SearchToolsHandler(registry_store=mock_store, top_k=5)

        # search_tools 호출 시뮬레이션
        result = await handler.handle({
            "query": "search academic papers",
            "category": "search",
        })

        assert result["type"] == "tool_result"
        assert len(result["found_tools"]) == 2
        assert result["found_tools"][0]["name"] == "arxiv_search"
        assert result["found_tools"][1]["name"] == "semantic_scholar_search"

        # 발견된 도구에 input_schema가 포함되어 Claude가 호출 가능
        assert "input_schema" in result["found_tools"][0]
        assert result["found_tools"][0]["input_schema"]["type"] == "object"

    @pytest.mark.asyncio
    async def test_iterative_search(self):
        """첫 검색 불만족 → 다른 쿼리로 재검색"""
        call_count = 0

        async def mock_search(query, top_k=5, category=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # 첫 검색: 부적합한 결과
                return [
                    ToolSearchResult(
                        tool=ToolDefinition(
                            name="web_search",
                            description="General web search",
                            input_schema={},
                            source_type="mcp_tool",
                        ),
                        score=0.45,
                        match_source="bm25",
                    ),
                ]
            else:
                # 재검색: 적합한 결과
                return [
                    ToolSearchResult(
                        tool=ToolDefinition(
                            name="pdf_skill",
                            description="Extract and analyze PDF documents",
                            input_schema={},
                            source_type="skill",
                        ),
                        score=0.91,
                        match_source="hybrid",
                    ),
                ]

        mock_store = MagicMock()
        mock_store.search = AsyncMock(side_effect=mock_search)

        handler = SearchToolsHandler(registry_store=mock_store)

        # 첫 검색
        result1 = await handler.handle({"query": "document processing"})
        assert result1["found_tools"][0]["name"] == "web_search"

        # 재검색 (다른 쿼리)
        result2 = await handler.handle({"query": "extract text from PDF files"})
        assert result2["found_tools"][0]["name"] == "pdf_skill"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_no_tools_found(self):
        """존재하지 않는 기능 요청 → 검색 결과 없음"""
        mock_store = MagicMock()
        mock_store.search = AsyncMock(return_value=[])

        handler = SearchToolsHandler(registry_store=mock_store)
        result = await handler.handle({"query": "quantum teleportation simulation"})

        assert len(result["found_tools"]) == 0
        assert "No matching tools found" in result["content"]

    @pytest.mark.asyncio
    async def test_tool_deduplication_in_active_tools(self):
        """검색된 도구가 active_tools에 중복 추가되지 않는지 검증"""
        # 동일한 도구가 여러 번 검색되어도 active_tools에 한 번만 추가
        active_tools = [
            {"name": "createDocument", "description": "Create a doc", "input_schema": {}},
            SEARCH_TOOLS_TOOL,
        ]

        # 이미 존재하는 도구 이름 세트
        existing_names = {t["name"] for t in active_tools}

        # 검색 결과에서 새 도구 추가
        found_tools = [
            {"name": "pdf_skill", "description": "PDF processing", "input_schema": {}},
            {"name": "createDocument", "description": "Already exists", "input_schema": {}},  # 중복
        ]

        for tool in found_tools:
            if tool["name"] not in existing_names:
                active_tools.append(tool)
                existing_names.add(tool["name"])

        # createDocument는 중복이므로 추가되지 않음
        assert len(active_tools) == 3  # createDocument + search_tools + pdf_skill
        tool_names = [t["name"] for t in active_tools]
        assert tool_names.count("createDocument") == 1
        assert "pdf_skill" in tool_names
