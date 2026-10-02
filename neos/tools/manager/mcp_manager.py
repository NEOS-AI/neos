"""MCP Manager - Central coordinator for MCP tools

⚠️ 이름만 MCP 다 -- Model Context Protocol(JSON-RPC)을 말하지 않는다. 실제 MCP
클라이언트는 `neos/coding/connectors/` 다(트랙 Q11a, docs/Q11_MCP_CLIENT_DESIGN_261001.md M1).
"""

import asyncio
from typing import Any, Dict, List, Optional
import logging

from neos.tools.base import MCPTool, MCPToolResult, MCPToolType
from neos.tools.tools import (
    DatabaseMCPTool,
    FileProcessingMCPTool,
    GitMCPTool,
    WebSearchMCPTool,
    LinkFollowerMCPTool,
    YouTubeMCPTool,
)


logger = logging.getLogger(__name__)


class MCPManager:
    """MCP 도구 관리자

    모든 MCP 도구의 생명주기를 관리하고 실행을 조율합니다.

    Attributes:
        tools: 등록된 모든 도구
        available_tools: 사용 가능한 도구
        initialization_complete: 초기화 완료 여부
    """

    def __init__(self):
        self.tools: Dict[str, MCPTool] = {}
        self.available_tools: Dict[str, MCPTool] = {}
        self.initialization_complete = False
        self._register_default_tools()

    def _register_default_tools(self) -> None:
        """기본 MCP 도구들 등록"""
        default_tools = [
            WebSearchMCPTool(),
            FileProcessingMCPTool(),
            DatabaseMCPTool(),
            GitMCPTool(),
            LinkFollowerMCPTool(),
            YouTubeMCPTool(),
        ]

        for tool in default_tools:
            self.tools[tool.name] = tool

        logger.info(f"Registered {len(default_tools)} default MCP tools")

    async def initialize(self) -> Dict[str, bool]:
        """모든 등록된 MCP 도구 초기화

        Returns:
            각 도구의 초기화 결과 (도구명: 성공여부)
        """
        logger.info("Initializing MCP tools...")
        initialization_results = {}

        for tool_name, tool in self.tools.items():
            try:
                is_available = await tool.check_availability()
                initialization_results[tool_name] = is_available

                if is_available:
                    self.available_tools[tool_name] = tool
                    logger.info(f"✓ MCP tool '{tool_name}' is available")
                else:
                    logger.warning(f"✗ MCP tool '{tool_name}' is not available")

            except Exception as e:
                logger.error(f"Error initializing MCP tool '{tool_name}': {e}")
                initialization_results[tool_name] = False

        self.initialization_complete = True

        available_count = len(self.available_tools)
        total_count = len(self.tools)
        logger.info(
            f"MCP initialization complete: {available_count}/{total_count} tools available"
        )

        return initialization_results

    def get_available_tools(
        self, tool_type: Optional[MCPToolType] = None
    ) -> List[MCPTool]:
        """사용 가능한 도구 목록 반환

        Args:
            tool_type: 특정 타입의 도구만 조회 (None이면 전체)

        Returns:
            도구 목록
        """
        if not tool_type:
            return list(self.available_tools.values())

        return [
            tool
            for tool in self.available_tools.values()
            if tool.tool_type == tool_type
        ]

    def is_tool_available(self, tool_name: str) -> bool:
        """특정 도구 사용 가능성 확인

        Args:
            tool_name: 도구 이름

        Returns:
            사용 가능 여부
        """
        return tool_name in self.available_tools

    def get_tool(self, tool_name: str) -> Optional[MCPTool]:
        """특정 도구 반환

        Args:
            tool_name: 도구 이름

        Returns:
            도구 객체 (없으면 None)
        """
        return self.available_tools.get(tool_name)

    async def execute_tool(
        self, tool_name: str, params: Dict[str, Any]
    ) -> MCPToolResult:
        """MCP 도구 실행

        Args:
            tool_name: 도구 이름
            params: 실행 파라미터

        Returns:
            실행 결과
        """
        # 초기화 확인
        if not self.initialization_complete:
            await self.initialize()

        # 도구 사용 가능 확인
        if tool_name not in self.available_tools:
            return MCPToolResult.from_error(
                error=f"MCP tool '{tool_name}' is not available",
                tool_name=tool_name,
            )

        # 도구 실행
        tool = self.available_tools[tool_name]
        try:
            result = await tool.execute(params)
            logger.info(
                f"Executed MCP tool '{tool_name}': success={result.success}, time={result.execution_time_ms}ms"
            )
            return result

        except Exception as e:
            logger.error(f"Error executing MCP tool '{tool_name}': {e}")
            return MCPToolResult.from_error(
                error=f"Execution failed: {str(e)}",
                tool_name=tool_name,
            )

    async def execute_by_type(
        self, tool_type: MCPToolType, params: Dict[str, Any]
    ) -> List[MCPToolResult]:
        """특정 타입의 모든 도구 실행

        Args:
            tool_type: 도구 타입
            params: 실행 파라미터

        Returns:
            실행 결과 리스트
        """
        available_tools = self.get_available_tools(tool_type)

        if not available_tools:
            return [
                MCPToolResult.from_error(
                    error=f"No MCP tools available for type '{tool_type.value}'",
                    tool_name=f"type_{tool_type.value}",
                )
            ]

        # 병렬 실행
        tasks = [tool.execute(params) for tool in available_tools]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 결과 처리
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                processed_results.append(
                    MCPToolResult.from_error(
                        error=str(result),
                        tool_name=available_tools[i].name,
                    )
                )
            else:
                processed_results.append(result)

        return processed_results

    def register_tool(self, tool: MCPTool) -> None:
        """새로운 MCP 도구 등록

        Args:
            tool: 등록할 도구
        """
        self.tools[tool.name] = tool
        logger.info(f"Registered MCP tool: {tool.name}")

    def unregister_tool(self, tool_name: str) -> bool:
        """MCP 도구 등록 해제

        Args:
            tool_name: 도구 이름

        Returns:
            해제 성공 여부
        """
        if tool_name in self.tools:
            del self.tools[tool_name]
            if tool_name in self.available_tools:
                del self.available_tools[tool_name]
            logger.info(f"Unregistered MCP tool: {tool_name}")
            return True

        return False

    def get_tool_summary(self) -> Dict[str, Any]:
        """도구 요약 정보 반환

        Returns:
            요약 정보
        """
        return {
            "total_tools": len(self.tools),
            "available_tools": len(self.available_tools),
            "initialized": self.initialization_complete,
            "tools": [tool.get_info() for tool in self.available_tools.values()],
        }

    async def cleanup(self) -> None:
        """모든 MCP 도구 정리"""
        logger.info("Cleaning up MCP tools...")

        cleanup_tasks = [
            tool.cleanup() for tool in self.available_tools.values()
        ]

        results = await asyncio.gather(*cleanup_tasks, return_exceptions=True)

        for i, result in enumerate(results):
            if isinstance(result, Exception):
                tool_name = list(self.available_tools.keys())[i]
                logger.error(f"Error cleaning up MCP tool '{tool_name}': {result}")

        self.available_tools.clear()
        logger.info("MCP tools cleanup complete")


# 전역 MCP 매니저 인스턴스
mcp_manager = MCPManager()
