"""검색 오케스트레이터 모듈"""

from typing import Dict, Any, List
from datetime import datetime
import logging

from neos.config.settings import settings
from neos.workflow.orchestrators.search_strategies import (
    SearchStrategy,
    IterativeSearchStrategy,
    StandardSearchStrategy
)

from ..state import AgentState

logger = logging.getLogger(__name__)


class SearchOrchestrator:
    """검색 오케스트레이터 (Strategy 패턴)

    다양한 검색 전략을 관리하고 적절한 전략을 선택하여 실행
    """

    def __init__(self, agents: Dict[str, Any], config, tool_selector):
        self.agents = agents
        self.config = config
        self.tool_selector = tool_selector

        # 사용 가능한 전략들 등록
        self.strategies: List[SearchStrategy] = [
            IterativeSearchStrategy(),
            StandardSearchStrategy()  # 항상 마지막 (폴백)
        ]

        logger.info(f"SearchOrchestrator initialized with {len(self.strategies)} strategies")

    async def orchestrate(self, state: AgentState) -> Dict[str, Any]:
        """검색 오케스트레이션

        적절한 전략을 선택하여 실행하고, 실패 시 다음 전략으로 폴백
        """
        logger.info("검색 오케스트레이션 시작")

        required_agents = state["required_agents"]
        search_agents = [agent for agent in required_agents if agent in self.config.SEARCH_AGENTS]
        logger.info(f"실행할 검색 에이전트: {search_agents}")

        if not search_agents:
            logger.warning("실행할 검색 에이전트가 없습니다")
            state["execution_steps"].append({
                "step": "search_orchestration",
                "result": "skipped - no search agents required",
                "timestamp": datetime.utcnow().isoformat()
            })
            return state

        # 도구 선택기 초기화
        if not self.tool_selector.is_initialized:
            logger.debug("도구 선택기 초기화 중...")
            await self.tool_selector.initialize()

        # 적용 가능한 전략 선택
        selected_strategy = None
        for strategy in self.strategies:
            if strategy.is_applicable(state):
                selected_strategy = strategy
                logger.info(f"🎯 Selected strategy: {strategy.name}")
                break

        if not selected_strategy:
            logger.error("No applicable strategy found!")
            return state

        # 전략 실행 (자동 폴백)
        return await self._execute_with_fallback(
            selected_strategy,
            state,
            search_agents
        )

    async def _execute_with_fallback(
        self,
        strategy: SearchStrategy,
        state: AgentState,
        search_agents: List[str]
    ) -> AgentState:
        """전략 실행 with 자동 폴백

        선택된 전략 실행 실패 시 StandardSearchStrategy로 폴백
        """
        try:
            # 선택된 전략 실행
            state = await strategy.execute(state, search_agents, self.agents, self.tool_selector)
            return state

        except Exception as e:
            logger.error(f"Strategy '{strategy.name}' failed: {e}")

            # Standard strategy가 아닌 경우만 폴백
            if not isinstance(strategy, StandardSearchStrategy):
                logger.info("Falling back to StandardSearchStrategy")

                # Standard strategy 찾기
                standard_strategy = next(
                    (s for s in self.strategies if isinstance(s, StandardSearchStrategy)),
                    None
                )

                if standard_strategy:
                    try:
                        state = await standard_strategy.execute(state, search_agents, self.agents, self.tool_selector)
                        return state
                    except Exception as fallback_error:
                        logger.error(f"Fallback strategy also failed: {fallback_error}")
                        state["errors"].append(f"All strategies failed: {str(fallback_error)}")
            else:
                state["errors"].append(f"Standard strategy failed: {str(e)}")

            return state
