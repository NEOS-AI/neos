"""검색 오케스트레이터 모듈"""

from typing import Dict, Any, List
from datetime import datetime
import logging

from neos.config.settings import settings
from neos.workflow.orchestrators.search_strategies import (
    SearchStrategy,
    MultiHopSearchStrategy,
    IterativeSearchStrategy,
    StandardSearchStrategy
)
from neos.utils.llm_factory import create_llm

from ..state import AgentState
from ..utils.cost_router import cost_router

logger = logging.getLogger(__name__)


class SearchOrchestrator:
    """검색 오케스트레이터 (Strategy 패턴)

    다양한 검색 전략을 관리하고 적절한 전략을 선택하여 실행
    """

    def __init__(self, agents: Dict[str, Any], config, tool_selector):
        self.agents = agents
        self.config = config
        self.tool_selector = tool_selector

        # 사용 가능한 전략들 등록 (우선순위 순서)
        self.strategies: List[SearchStrategy] = [
            MultiHopSearchStrategy(),     # 1순위: 복잡한 추론 질문
            IterativeSearchStrategy(),    # 2순위: 심층 연구 질문
            StandardSearchStrategy()      # 3순위: 일반 질문 (항상 적용 가능, 폴백)
        ]

        logger.info(f"SearchOrchestrator initialized with {len(self.strategies)} strategies")

    def _get_llm(self, temperature: float = 0.2, max_tokens: int = 200):
        """
        LLM 인스턴스를 가져옵니다.

        LLMFactory의 다중 키 캐싱을 활용하여 (model, temperature, max_tokens) 조합별로
        인스턴스를 재사용합니다. 이를 통해 다양한 파라미터 조합에 대한 캐싱이 가능합니다.
        """
        # 자동 워크로드 — 모델을 지정하지 않아 everyday 역할 기본값으로 해석된다
        return create_llm(
            temperature=temperature,
            max_tokens=max_tokens,
            use_cache=True  # LLMFactory 캐시 활용
        )

    async def orchestrate(self, state: AgentState) -> Dict[str, Any]:
        """검색 오케스트레이션 (대화 컨텍스트 활용)

        적절한 전략을 선택하여 실행하고, 실패 시 다음 전략으로 폴백
        """
        logger.info("검색 오케스트레이션 시작")

        # 대화 컨텍스트가 있으면 쿼리 개선
        conversation_context = state.get("conversation_context")
        if conversation_context:
            logger.info(f"[SearchOrchestrator] Using conversation context (length: {len(conversation_context)})")
            # 컨텍스트 기반으로 쿼리 개선
            enhanced_query = await self._enhance_query_with_context(
                original_query=state["original_query"],
                context=conversation_context
            )
            if enhanced_query and enhanced_query != state["original_query"]:
                logger.info(f"[SearchOrchestrator] Query enhanced: '{state['original_query']}' → '{enhanced_query}'")
                # 원본 쿼리는 유지하되, 검색에 사용할 쿼리를 메타데이터에 저장
                # query_classification이 None일 수 있으므로 안전하게 처리
                if state.get("query_classification"):
                    state["query_classification"]["enhanced_query"] = enhanced_query
                else:
                    logger.warning("[SearchOrchestrator] query_classification not found, cannot store enhanced_query")
            else:
                logger.info(f"[SearchOrchestrator] Query not changed, using original")

        required_agents = state["required_agents"]
        search_agents = [agent for agent in required_agents if agent in self.config.SEARCH_AGENTS]
        logger.info(f"실행할 검색 에이전트: {search_agents}")

        if not search_agents:
            logger.warning("실행할 검색 에이전트가 없습니다")
            state["execution_steps"].append({
                "step": "search_orchestration",
                "result": "skipped - no search agents required",
                "timestamp": datetime.now().isoformat()
            })
            return state

        # 도구 선택기 초기화
        if not self.tool_selector.initialized:
            logger.debug("도구 선택기 초기화 중...")
            await self.tool_selector.initialize()

        # knowledge_hybrid 검색으로 캐시된 유사 결과를 보강 컨텍스트로 활용
        await self._augment_with_cache_hybrid(state)

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

        # Phase 2.7: 비용 인식 라우팅 — 예산 부족 시 저렴한 전략으로 다운그레이드
        remaining_budget = cost_router.get_remaining_budget(state)
        if remaining_budget is not None:
            original_name = selected_strategy.name
            downgraded_name = cost_router.select_strategy(
                preferred=original_name,
                remaining_budget=remaining_budget,
            )
            if downgraded_name != original_name:
                for s in self.strategies:
                    if s.name == downgraded_name:
                        selected_strategy = s
                        logger.info(
                            f"[CostRouter] Downgraded: {original_name} → {downgraded_name} "
                            f"(budget: ${remaining_budget:.2f})"
                        )
                        break

        # 전략 실행 (자동 폴백)
        result_state = await self._execute_with_fallback(
            selected_strategy,
            state,
            search_agents
        )

        # Phase 3.1: 검색 결과에서 KG 자동 구축 (비동기, non-blocking)
        if getattr(settings, "KG_POPULATION_ENABLED", False):
            import asyncio
            search_results = result_state.get("search_results", [])
            if search_results:
                try:
                    from neos.services.kg_population_service import kg_population_service
                    asyncio.create_task(
                        kg_population_service.populate_from_search_results(
                            search_results, session_id=state.get("session_id", "")
                        )
                    )
                except Exception as e:
                    logger.debug(f"[KGPopulation] 시작 실패 (무시): {e}")

        return result_state

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

            # Phase 2.7: 실행 비용 추적
            estimated_cost = cost_router.estimate_cost(strategy.name)
            cost_router.track_cost(state, f"search_{strategy.name}", estimated_cost)

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

    async def _augment_with_cache_hybrid(self, state: AgentState) -> None:
        """knowledge_hybrid (cache_hybrid) 전략으로 캐시된 유사 결과를 보강합니다.

        query_cache 테이블에 이전에 동일/유사한 쿼리의 결과가 있으면
        검색 결과에 추가하여 응답 품질을 높입니다.

        이 메서드는 검색 에이전트 실행 전에 호출되어,
        캐시된 결과가 있으면 검색 결과를 보강합니다.
        """
        query_embedding = state.get("query_embedding")
        if not query_embedding:
            logger.debug("[SearchOrchestrator] cache_hybrid skipped: query_embedding not available")
            return

        try:
            from neos.services.similarity_search_service import similarity_search_service

            cached_results = await similarity_search_service.search(
                query=state["original_query"],
                strategy="cache_hybrid",
                top_n=settings.HYBRID_SEARCH_CANDIDATE_COUNT,
                limit=3,
            )

            if cached_results:
                logger.info(
                    f"[SearchOrchestrator] cache_hybrid found {len(cached_results)} "
                    f"cached results (top RRF: {cached_results[0].get('rrf_score', 0):.3f})"
                )
                # 캐시 결과를 search_results에 보강
                for cr in cached_results:
                    response_data = cr.get("response_data", {})
                    if isinstance(response_data, dict) and response_data.get("response"):
                        state["search_results"].append({
                            "source": "cache_hybrid",
                            "content": str(response_data.get("response", ""))[:500],
                            "query": cr.get("query_text", ""),
                            "rrf_score": cr.get("rrf_score", 0),
                        })

        except Exception as e:
            # cache_hybrid 실패는 검색을 차단하지 않음
            logger.debug(f"[SearchOrchestrator] cache_hybrid augmentation skipped: {e}")

    async def _enhance_query_with_context(
        self,
        original_query: str,
        context: str
    ) -> str:
        """
        대화 컨텍스트를 활용하여 검색 쿼리 개선

        예시:
        - 원본: "그것의 가격은?"
        - 컨텍스트: "user: iPhone 15에 대해 알려줘\nassistant: iPhone 15는..."
        - 개선: "iPhone 15의 가격"

        Args:
            original_query: 원본 사용자 쿼리
            context: 대화 컨텍스트 요약

        Returns:
            개선된 쿼리 또는 원본 쿼리
        """
        try:
            llm = self._get_llm(temperature=0.2, max_tokens=200)

            # 쿼리 개선 프롬프트
            enhancement_prompt = f"""다음 대화 맥락을 고려하여, 현재 사용자의 질문을 검색에 적합한 명확한 쿼리로 변환해주세요.

대화 맥락:
{context}

현재 사용자 질문: {original_query}

요구사항:
1. "그것", "이전", "아까" 등의 참조를 구체적인 대상으로 치환
2. 대화 맥락에서 언급된 주제를 명시적으로 포함
3. 검색에 적합한 명확하고 간결한 형태로 변환
4. 원본 질문의 의도는 유지
5. 개선된 쿼리만 반환 (설명이나 추가 텍스트 없이)

개선된 쿼리:"""

            # LLM 호출
            response = await llm.ainvoke(enhancement_prompt)
            enhanced_query = response.content.strip()

            # 개선된 쿼리가 너무 길거나 비어있으면 원본 반환
            if not enhanced_query or len(enhanced_query) > 200:
                logger.warning(f"[SearchOrchestrator] Enhanced query invalid, using original")
                return original_query

            return enhanced_query

        except Exception as e:
            logger.error(f"[SearchOrchestrator] Query enhancement failed: {e}, using original query")
            return original_query
