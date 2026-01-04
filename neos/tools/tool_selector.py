"""도구 선택 및 조건부 실행 관리자"""

from typing import Dict, Any, List, Optional, Tuple, Union
from dataclasses import dataclass
from enum import Enum
import logging
from datetime import datetime

from .mcp_integration import MCPManager, MCPToolType, MCPToolResult, mcp_manager
from neos.config.settings import settings

logger = logging.getLogger(__name__)


class ToolCondition(Enum):
    """도구 실행 조건"""
    ALWAYS = "always"  # 항상 실행
    MCP_AVAILABLE = "mcp_available"  # MCP 사용 가능할 때만
    MCP_FALLBACK = "mcp_fallback"  # 기본 도구 실패 시 MCP 사용
    PREFERENCE_BASED = "preference_based"  # 설정에 따라
    CONTEXT_DEPENDENT = "context_dependent"  # 컨텍스트에 따라


@dataclass
class ToolContext:
    """도구 실행 컨텍스트"""
    query: str
    user_id: str
    session_id: str
    intent: Optional[str] = None
    urgency: str = "normal"  # low, normal, high
    quality_requirement: str = "standard"  # basic, standard, high
    resource_constraints: Dict[str, Any] = None
    mcp_preference: bool = True  # MCP 사용 선호 여부
    fallback_allowed: bool = True  # 대체 도구 사용 허용 여부

    def __post_init__(self):
        if self.resource_constraints is None:
            self.resource_constraints = {}


class ToolSelector:
    """상황에 따른 도구 선택 및 실행 관리자"""

    def __init__(self, mcp_manager: MCPManager):
        self.mcp_manager = mcp_manager
        self.tool_strategies = self._define_tool_strategies()
        self.initialized = False

    def _define_tool_strategies(self) -> Dict[str, Dict[str, Any]]:
        """도구 실행 전략 정의"""
        return {
            "web_search": {
                "primary_tool": "web_search_mcp",
                "fallback_tools": ["tavily_search", "basic_web_search"],
                "condition": ToolCondition.MCP_FALLBACK,
                "timeout_seconds": 30
            },
            "file_processing": {
                "primary_tool": "file_processing_mcp",
                "fallback_tools": ["basic_file_processor"],
                "condition": ToolCondition.MCP_AVAILABLE,
                "timeout_seconds": 60
            },
            "data_analysis": {
                "primary_tool": "data_analysis_mcp",
                "fallback_tools": ["pandas_analyzer", "basic_analyzer"],
                "condition": ToolCondition.PREFERENCE_BASED,
                "timeout_seconds": 120
            },
            "api_integration": {
                "primary_tool": "api_integration_mcp",
                "fallback_tools": ["direct_api_call"],
                "condition": ToolCondition.CONTEXT_DEPENDENT,
                "timeout_seconds": 45
            }
        }

    async def initialize(self) -> bool:
        """도구 선택기 초기화"""
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
        context: ToolContext
    ) -> Tuple[MCPToolResult, str]:
        """상황에 따라 최적의 도구 선택 및 실행"""

        if not self.initialized:
            await self.initialize()

        strategy = self.tool_strategies.get(tool_category)
        if not strategy:
            return MCPToolResult(
                success=False,
                data=None,
                error=f"Unknown tool category: {tool_category}",
                tool_name="tool_selector"
            ), "error"

        # 실행 전략 결정
        execution_plan = await self._determine_execution_plan(strategy, context)

        # 도구 실행
        result, selected_tool = await self._execute_with_strategy(
            execution_plan, params, context
        )

        return result, selected_tool

    async def _determine_execution_plan(
        self,
        strategy: Dict[str, Any],
        context: ToolContext
    ) -> Dict[str, Any]:
        """실행 계획 결정"""

        condition = strategy["condition"]
        primary_tool = strategy["primary_tool"]
        fallback_tools = strategy["fallback_tools"]

        execution_plan = {
            "primary_tool": primary_tool,
            "fallback_tools": fallback_tools,
            "use_mcp": False,
            "execution_order": []
        }

        # 조건에 따른 실행 계획 수립
        if condition == ToolCondition.ALWAYS:
            execution_plan["execution_order"] = [primary_tool] + fallback_tools
            execution_plan["use_mcp"] = self.mcp_manager.is_tool_available(primary_tool)

        elif condition == ToolCondition.MCP_AVAILABLE:
            if self.mcp_manager.is_tool_available(primary_tool):
                execution_plan["execution_order"] = [primary_tool]
                execution_plan["use_mcp"] = True
            else:
                execution_plan["execution_order"] = fallback_tools

        elif condition == ToolCondition.MCP_FALLBACK:
            # 기본 도구 먼저, 실패 시 MCP 사용
            if context.mcp_preference and self.mcp_manager.is_tool_available(primary_tool):
                execution_plan["execution_order"] = [primary_tool] + fallback_tools
                execution_plan["use_mcp"] = True
            else:
                execution_plan["execution_order"] = fallback_tools + [primary_tool]

        elif condition == ToolCondition.PREFERENCE_BASED:
            if context.mcp_preference and self.mcp_manager.is_tool_available(primary_tool):
                execution_plan["execution_order"] = [primary_tool] + fallback_tools
                execution_plan["use_mcp"] = True
            else:
                execution_plan["execution_order"] = fallback_tools

        elif condition == ToolCondition.CONTEXT_DEPENDENT:
            # 컨텍스트에 따른 동적 결정
            if self._should_use_mcp_for_context(context):
                execution_plan["execution_order"] = [primary_tool] + fallback_tools
                execution_plan["use_mcp"] = True
            else:
                execution_plan["execution_order"] = fallback_tools

        return execution_plan

    def _should_use_mcp_for_context(self, context: ToolContext) -> bool:
        """컨텍스트에 따른 MCP 사용 여부 결정"""

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
        context: ToolContext
    ) -> Tuple[MCPToolResult, str]:
        """실행 계획에 따른 도구 실행"""

        execution_order = execution_plan["execution_order"]
        last_error = None

        for tool_name in execution_order:
            try:
                # MCP 도구인지 확인
                if self.mcp_manager.is_tool_available(tool_name):
                    logger.info(f"Executing MCP tool: {tool_name}")
                    result = await self.mcp_manager.execute_tool(tool_name, params)

                    if result.success:
                        return result, tool_name
                    else:
                        last_error = result.error
                        logger.warning(f"MCP tool {tool_name} failed: {result.error}")

                        # 대체 도구 사용 허용하지 않으면 즉시 반환
                        if not context.fallback_allowed:
                            return result, tool_name

                else:
                    # 기본 도구 실행 (여기서는 시뮬레이션)
                    logger.info(f"Executing fallback tool: {tool_name}")
                    result = await self._execute_fallback_tool(tool_name, params, context)

                    if result.success:
                        return result, tool_name
                    else:
                        last_error = result.error
                        logger.warning(f"Fallback tool {tool_name} failed: {result.error}")

            except Exception as e:
                last_error = str(e)
                logger.error(f"Error executing tool {tool_name}: {e}")
                continue

        # 모든 도구 실행 실패
        return MCPToolResult(
            success=False,
            data=None,
            error=f"All tools failed. Last error: {last_error}",
            tool_name="tool_selector"
        ), "none"

    async def _execute_fallback_tool(
        self,
        tool_name: str,
        params: Dict[str, Any],
        context: ToolContext
    ) -> MCPToolResult:
        """대체 도구 실행 (시뮬레이션)"""

        start_time = datetime.now()

        try:
            # 실제 구현에서는 해당하는 기본 도구를 실행
            # 여기서는 시뮬레이션으로 처리

            if "search" in tool_name:
                result_data = {
                    "results": [
                        {
                            "title": f"Fallback search result for: {params.get('query', '')}",
                            "content": f"Basic search content via {tool_name}",
                            "url": "https://example.com/fallback",
                            "score": 0.7,
                            "source": tool_name
                        }
                    ]
                }
            elif "file" in tool_name:
                result_data = {
                    "processed": True,
                    "file_path": params.get("file_path", ""),
                    "operation": params.get("operation", ""),
                    "result": f"File processed via {tool_name}"
                }
            else:
                result_data = {
                    "tool": tool_name,
                    "params": params,
                    "processed": True
                }

            execution_time = int((datetime.now() - start_time).total_seconds() * 1000)

            return MCPToolResult(
                success=True,
                data=result_data,
                tool_name=tool_name,
                execution_time_ms=execution_time,
                metadata={"source": "fallback", "tool_type": "basic"}
            )

        except Exception as e:
            execution_time = int((datetime.now() - start_time).total_seconds() * 1000)
            return MCPToolResult(
                success=False,
                data=None,
                error=str(e),
                tool_name=tool_name,
                execution_time_ms=execution_time
            )

    def get_available_tools_summary(self) -> Dict[str, Any]:
        """사용 가능한 도구 요약 정보 반환"""

        mcp_tools = []
        for tool in self.mcp_manager.get_available_tools():
            mcp_tools.append({
                "name": tool.name,
                "type": tool.tool_type.value,
                "description": tool.description,
                "capabilities": tool.capabilities
            })

        return {
            "mcp_tools_available": len(mcp_tools),
            "mcp_tools": mcp_tools,
            "strategies": list(self.tool_strategies.keys()),
            "initialization_complete": self.initialized
        }

    async def health_check(self) -> Dict[str, Any]:
        """도구 상태 확인"""

        health_status = {
            "tool_selector": "healthy",
            "mcp_manager": "unknown",
            "available_mcp_tools": 0,
            "tool_strategies": len(self.tool_strategies),
            "timestamp": datetime.now().isoformat()
        }

        try:
            if self.mcp_manager.initialization_complete:
                health_status["mcp_manager"] = "healthy"
                health_status["available_mcp_tools"] = len(self.mcp_manager.available_tools)
            else:
                await self.mcp_manager.initialize()
                health_status["mcp_manager"] = "initialized"
                health_status["available_mcp_tools"] = len(self.mcp_manager.available_tools)

        except Exception as e:
            health_status["mcp_manager"] = f"error: {str(e)}"

        return health_status


# 전역 도구 선택기 인스턴스
tool_selector = ToolSelector(mcp_manager)