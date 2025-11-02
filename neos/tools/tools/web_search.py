"""Web search MCP tool implementation"""

from datetime import datetime
from typing import Any, Dict

import aiohttp
import logging

from neos.config.settings import settings
from neos.tools.base import MCPTool, MCPToolResult, MCPToolType


logger = logging.getLogger(__name__)


class WebSearchMCPTool(MCPTool):
    """웹 검색 MCP 도구

    Tavily API를 사용한 실시간 웹 검색 기능을 제공합니다.

    Capabilities:
        - real_time_search: 실시간 웹 검색
        - multi_source_search: 다중 소스 검색
        - structured_results: 구조화된 결과 반환
    """

    def __init__(self):
        super().__init__(
            name="web_search_mcp",
            tool_type=MCPToolType.WEB_SEARCH,
            description="MCP를 통한 웹 검색 도구 (Tavily API)",
            capabilities=[
                "real_time_search",
                "multi_source_search",
                "structured_results",
            ],
        )
        self.client = None

    async def initialize(self) -> bool:
        """웹 검색 클라이언트 초기화

        Returns:
            초기화 성공 여부
        """
        try:
            # Tavily API 키 확인
            if not settings.TAVILY_API_KEY:
                logger.warning(
                    "TAVILY_API_KEY not configured, WebSearch MCP tool will not be available"
                )
                return False

            # HTTP 클라이언트 초기화
            self.client = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=settings.MCP_TIMEOUT)
            )

            logger.info("WebSearch MCP tool initialized with Tavily API")
            self.is_available = True
            return True

        except Exception as e:
            logger.error(f"Failed to initialize WebSearch MCP tool: {e}")
            return False

    async def execute(self, params: Dict[str, Any]) -> MCPToolResult:
        """웹 검색 실행

        Args:
            params: 검색 파라미터
                - query (str, required): 검색 쿼리
                - max_results (int, optional): 최대 결과 개수 (기본값: 5)
                - search_depth (str, optional): 검색 깊이 (basic/advanced, 기본값: basic)

        Returns:
            MCPToolResult: 검색 결과
        """
        start_time = datetime.now()

        try:
            # 파라미터 검증
            query = params.get("query", "")
            if not query:
                return MCPToolResult.from_error(
                    error="Query parameter is required",
                    tool_name=self.name,
                )

            if not self.client:
                return MCPToolResult.from_error(
                    error="WebSearch client not initialized",
                    tool_name=self.name,
                )

            # Tavily API 호출
            max_results = params.get("max_results", 5)
            search_depth = params.get("search_depth", "basic")

            search_payload = {
                "api_key": settings.TAVILY_API_KEY,
                "query": query,
                "search_depth": search_depth,
                "max_results": max_results,
                "include_answer": True,
                "include_raw_content": False,
            }

            async with self.client.post(
                "https://api.tavily.com/search", json=search_payload
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    return MCPToolResult.from_error(
                        error=f"Tavily API error {response.status}: {error_text}",
                        tool_name=self.name,
                    )

                search_data = await response.json()

            # 결과 포맷팅
            results = []
            for item in search_data.get("results", []):
                results.append(
                    {
                        "title": item.get("title", ""),
                        "content": item.get("content", ""),
                        "url": item.get("url", ""),
                        "score": item.get("score", 0.0),
                        "source": "tavily_mcp_search",
                    }
                )

            execution_time = int(
                (datetime.now() - start_time).total_seconds() * 1000
            )

            return MCPToolResult.from_success(
                data=results,
                tool_name=self.name,
                execution_time_ms=execution_time,
                metadata={
                    "source": "mcp_tavily",
                    "result_count": len(results),
                    "query": query,
                    "search_depth": search_depth,
                    "answer": search_data.get("answer"),
                },
            )

        except Exception as e:
            execution_time = int(
                (datetime.now() - start_time).total_seconds() * 1000
            )
            return MCPToolResult.from_error(
                error=str(e),
                tool_name=self.name,
                execution_time_ms=execution_time,
            )

    async def cleanup(self) -> None:
        """클라이언트 정리"""
        if self.client:
            try:
                await self.client.close()
                logger.info("WebSearch MCP tool client cleaned up")
            except Exception as e:
                logger.error(f"Error cleaning up WebSearch MCP tool: {e}")
