"""Tool Selector - Improved version with better strategy patterns"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional, Tuple
import logging

from neos.tools.base import MCPToolResult
from neos.tools.tool_selector import ToolCondition
from neos.tools.manager.mcp_manager import MCPManager, mcp_manager


logger = logging.getLogger(__name__)


@dataclass
class ToolContext:
    """도구 실행 컨텍스트

    도구 선택 및 실행에 필요한 컨텍스트 정보를 담습니다.

    Attributes:
        query: 사용자 쿼리
        user_id: 사용자 ID
        session_id: 세션 ID
        intent: 쿼리 의도
        urgency: 긴급도 (low/normal/high)
        quality_requirement: 품질 요구사항 (basic/standard/high)
        resource_constraints: 리소스 제약 사항
        mcp_preference: MCP 사용 선호 여부
        fallback_allowed: 대체 도구 사용 허용 여부
    """

    query: str
    user_id: str
    session_id: str
    intent: Optional[str] = None
    urgency: str = "normal"
    quality_requirement: str = "standard"
    resource_constraints: Dict[str, Any] = field(default_factory=dict)
    mcp_preference: bool = True
    fallback_allowed: bool = True


class ToolSelector:
    """도구 선택 및 실행 관리자

    상황에 따라 최적의 도구를 선택하고 실행합니다.

    Attributes:
        mcp_manager: MCP 매니저
        tool_strategies: 도구 실행 전략
        initialized: 초기화 완료 여부
    """

    def __init__(self, mcp_manager: MCPManager):
        self.mcp_manager = mcp_manager
        self.tool_strategies = self._define_tool_strategies()
        self.initialized = False

    def _define_tool_strategies(self) -> Dict[str, Dict[str, Any]]:
        """도구 실행 전략 정의

        Returns:
            전략 딕셔너리
        """
        return {
            "web_search": {
                "primary_tool": "web_search_mcp",
                "fallback_tools": ["tavily_search", "basic_web_search"],
                "condition": ToolCondition.MCP_FALLBACK,
                "timeout_seconds": 30,
            },
            "file_processing": {
                "primary_tool": "file_processing_mcp",
                "fallback_tools": ["basic_file_processor"],
                "condition": ToolCondition.MCP_AVAILABLE,
                "timeout_seconds": 60,
            },
            "data_analysis": {
                "primary_tool": "database_mcp",
                "fallback_tools": ["pandas_analyzer", "basic_analyzer"],
                "condition": ToolCondition.PREFERENCE_BASED,
                "timeout_seconds": 120,
            },
            "git_operations": {
                "primary_tool": "git_mcp",
                "fallback_tools": ["basic_git"],
                "condition": ToolCondition.MCP_AVAILABLE,
                "timeout_seconds": 30,
            },
        }

    async def initialize(self) -> bool:
        """도구 선택기 초기화

        Returns:
            초기화 성공 여부
        """
        try:
            if not self.mcp_manager.initialization_complete:
                await self.mcp_manager.initialize()

            self.initialized = True
            logger.info("ToolSelector initialized successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize ToolSelector: {e}")
            return False

    async def select_and_execute_tool(
        self,
        tool_category: str,
        params: Dict[str, Any],
        context: ToolContext,
    ) -> Tuple[MCPToolResult, str]:
        """상황에 따라 최적의 도구 선택 및 실행

        Args:
            tool_category: 도구 카테고리
            params: 실행 파라미터
            context: 실행 컨텍스트

        Returns:
            (실행 결과, 선택된 도구 이름) 튜플
        """
        # 초기화 확인
        if not self.initialized:
            await self.initialize()

        # 전략 조회
        strategy = self.tool_strategies.get(tool_category)
        if not strategy:
            return (
                MCPToolResult.from_error(
                    error=f"Unknown tool category: {tool_category}",
                    tool_name="tool_selector",
                ),
                "error",
            )

        # 실행 계획 결정
        execution_plan = self._determine_execution_plan(strategy, context)

        # 도구 실행
        result, selected_tool = await self._execute_with_strategy(
            execution_plan, params, context
        )

        return result, selected_tool

    def _determine_execution_plan(
        self, strategy: Dict[str, Any], context: ToolContext
    ) -> Dict[str, Any]:
        """실행 계획 결정

        Args:
            strategy: 도구 전략
            context: 실행 컨텍스트

        Returns:
            실행 계획
        """
        condition = strategy["condition"]
        primary_tool = strategy["primary_tool"]
        fallback_tools = strategy["fallback_tools"]

        execution_plan = {
            "primary_tool": primary_tool,
            "fallback_tools": fallback_tools,
            "use_mcp": False,
            "execution_order": [],
        }

        # 조건에 따른 실행 계획
        if condition == ToolCondition.ALWAYS:
            execution_plan["execution_order"] = [primary_tool] + fallback_tools
            execution_plan["use_mcp"] = self.mcp_manager.is_tool_available(
                primary_tool
            )

        elif condition == ToolCondition.MCP_AVAILABLE:
            if self.mcp_manager.is_tool_available(primary_tool):
                execution_plan["execution_order"] = [primary_tool]
                execution_plan["use_mcp"] = True
            else:
                execution_plan["execution_order"] = fallback_tools

        elif condition == ToolCondition.MCP_FALLBACK:
            if context.mcp_preference and self.mcp_manager.is_tool_available(
                primary_tool
            ):
                execution_plan["execution_order"] = [primary_tool] + fallback_tools
                execution_plan["use_mcp"] = True
            else:
                execution_plan["execution_order"] = fallback_tools + [primary_tool]

        elif condition == ToolCondition.PREFERENCE_BASED:
            if context.mcp_preference and self.mcp_manager.is_tool_available(
                primary_tool
            ):
                execution_plan["execution_order"] = [primary_tool] + fallback_tools
                execution_plan["use_mcp"] = True
            else:
                execution_plan["execution_order"] = fallback_tools

        elif condition == ToolCondition.CONTEXT_DEPENDENT:
            if self._should_use_mcp_for_context(context):
                execution_plan["execution_order"] = [primary_tool] + fallback_tools
                execution_plan["use_mcp"] = True
            else:
                execution_plan["execution_order"] = fallback_tools

        return execution_plan

    def _should_use_mcp_for_context(self, context: ToolContext) -> bool:
        """컨텍스트에 따른 MCP 사용 여부 결정

        Args:
            context: 실행 컨텍스트

        Returns:
            MCP 사용 여부
        """
        # 긴급도가 높으면 안정적인 기본 도구 사용
        if context.urgency == "high":
            return False

        # 품질 요구사항이 높으면 MCP 사용
        if context.quality_requirement == "high":
            return True

        # 리소스 제약이 있으면 기본 도구 사용
        if context.resource_constraints.get("limited_resources", False):
            return False

        # 기본적으로 사용자 선호도 따름
        return context.mcp_preference

    async def _execute_with_strategy(
        self,
        execution_plan: Dict[str, Any],
        params: Dict[str, Any],
        context: ToolContext,
    ) -> Tuple[MCPToolResult, str]:
        """실행 계획에 따른 도구 실행

        Args:
            execution_plan: 실행 계획
            params: 실행 파라미터
            context: 실행 컨텍스트

        Returns:
            (실행 결과, 선택된 도구 이름) 튜플
        """
        execution_order = execution_plan["execution_order"]
        last_error = None

        for tool_name in execution_order:
            try:
                # MCP 도구 확인
                if self.mcp_manager.is_tool_available(tool_name):
                    logger.info(f"Executing MCP tool: {tool_name}")
                    result = await self.mcp_manager.execute_tool(tool_name, params)

                    if result.success:
                        return result, tool_name
                    else:
                        last_error = result.error
                        logger.warning(f"MCP tool '{tool_name}' failed: {result.error}")

                        if not context.fallback_allowed:
                            return result, tool_name

                else:
                    # 기본 도구 실행 (시뮬레이션)
                    logger.info(f"Executing fallback tool: {tool_name}")
                    result = self._simulate_fallback_tool(tool_name, params)

                    if result.success:
                        return result, tool_name
                    else:
                        last_error = result.error
                        logger.warning(
                            f"Fallback tool '{tool_name}' failed: {result.error}"
                        )

            except Exception as e:
                last_error = str(e)
                logger.error(f"Error executing tool '{tool_name}': {e}")
                continue

        # 모든 도구 실행 실패
        return (
            MCPToolResult.from_error(
                error=f"All tools failed. Last error: {last_error}",
                tool_name="tool_selector",
            ),
            "none",
        )

    def _simulate_fallback_tool(
        self, tool_name: str, params: Dict[str, Any]
    ) -> MCPToolResult:
        """대체 도구 시뮬레이션

        Args:
            tool_name: 도구 이름
            params: 실행 파라미터

        Returns:
            실행 결과
        """
        # 실제 구현에서는 적절한 fallback 도구를 실행
        logger.warning(f"Fallback tool '{tool_name}' not implemented (simulated)")

        return MCPToolResult.from_success(
            data={
                "message": f"Simulated result from {tool_name}",
                "params": params,
                "simulated": True,
            },
            tool_name=tool_name,
            metadata={"source": "fallback_simulation"},
        )

    def get_available_tools_summary(self) -> Dict[str, Any]:
        """사용 가능한 도구 요약 정보

        Returns:
            요약 정보
        """
        mcp_tools = [
            {
                "name": tool.name,
                "type": tool.tool_type.value,
                "description": tool.description,
                "capabilities": tool.capabilities,
            }
            for tool in self.mcp_manager.get_available_tools()
        ]

        return {
            "mcp_tools_available": len(mcp_tools),
            "mcp_tools": mcp_tools,
            "strategies": list(self.tool_strategies.keys()),
            "initialization_complete": self.initialized,
        }

    async def health_check(self) -> Dict[str, Any]:
        """도구 상태 확인

        Returns:
            상태 정보
        """
        health_status = {
            "tool_selector": "healthy",
            "mcp_manager": "unknown",
            "available_mcp_tools": 0,
            "tool_strategies": len(self.tool_strategies),
            "timestamp": datetime.utcnow().isoformat(),
        }

        try:
            if self.mcp_manager.initialization_complete:
                health_status["mcp_manager"] = "healthy"
                health_status["available_mcp_tools"] = len(
                    self.mcp_manager.available_tools
                )
            else:
                await self.mcp_manager.initialize()
                health_status["mcp_manager"] = "initialized"
                health_status["available_mcp_tools"] = len(
                    self.mcp_manager.available_tools
                )

        except Exception as e:
            health_status["mcp_manager"] = f"error: {str(e)}"

        return health_status


tool_selector = ToolSelector(mcp_manager)
