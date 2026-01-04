"""Multi-Hop Search Agent

복잡한 질문을 서브질문으로 분해하고 순차적 추론을 통해 답변을 생성하는 멀티홉 검색 에이전트
"""

import logging
import asyncio
from typing import Dict, Any, List, Optional
from tavily import TavilyClient

from neos.agents.base import SearchAgent
from neos.workflow.state import SearchResult
from neos.config.settings import settings
from neos.agents.search_agents.multi_hop import (
    QueryDecomposer,
    AnswerExtractor,
    ReasoningChainExecutor,
    ResultIntegrator,
    MultiHopConfig,
)
from neos.agents.search_agents.multi_hop.validation_utils import (
    InputValidator,
    ErrorHandler,
)

logger = logging.getLogger(__name__)


class MultiHopSearchAgent(SearchAgent):
    """멀티홉 검색 에이전트

    복잡한 질문을 서브질문으로 분해하고, 각 서브질문에 순차적으로 답변하며,
    중간 결과를 다음 단계에 활용하는 멀티홉 검색 시스템

    작동 방식:
    1. QueryDecomposer: 질문을 서브질문 체인으로 분해
    2. ReasoningChainExecutor: 각 서브질문을 순차/병렬 실행
    3. AnswerExtractor: 검색 결과에서 답변 추출
    4. ResultIntegrator: 최종 답변 통합 및 추론 과정 시각화

    예시:
        질문: "아이폰을 개발한 사람의 모교 위치는?"

        Hop 1: "아이폰을 개발한 주요 인물은?" → "스티브 잡스"
        Hop 2: "스티브 잡스의 출신 대학은?" → "Reed College"
        Hop 3: "Reed College의 위치는?" → "Oregon, Portland"

        최종 답변: "아이폰을 개발한 스티브 잡스의 모교는 오레곤 주 포틀랜드에 위치한 Reed College입니다."
    """

    def __init__(self, config: Optional[MultiHopConfig] = None):
        super().__init__(
            name="multi_hop_search",
            search_type="multi_hop",
        )

        # 설정
        self.config = config or MultiHopConfig()

        # 컴포넌트 초기화
        self.query_decomposer = QueryDecomposer()
        self.answer_extractor = AnswerExtractor(
            min_confidence=self.config.min_answer_confidence
        )
        self.result_integrator = ResultIntegrator()
        self.reasoning_chain_executor = ReasoningChainExecutor(
            answer_extractor=self.answer_extractor,
            config=self.config,
        )

        # Tavily 클라이언트 초기화 (검색용)
        self.api_available = False
        if settings.TAVILY_API_KEY and settings.TAVILY_API_KEY.strip():
            try:
                self.tavily_client = TavilyClient(api_key=settings.TAVILY_API_KEY)
                self.api_available = True
                logger.info("Tavily client initialized successfully")
            except Exception as e:
                logger.warning(f"Failed to create TavilyClient: {e}")
                self.tavily_client = None
        else:
            logger.warning("TAVILY_API_KEY not set, multi-hop search will be limited")

    async def execute(self, query: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
        """멀티홉 검색 실행

        Args:
            query: 사용자 질문
            context: 실행 컨텍스트 (session_id, user_id, language 등)

        Returns:
            {
                "success": bool,
                "result": List[SearchResult],  # 최종 답변 + 모든 소스
                "metadata": {
                    "search_type": "multi_hop",
                    "hop_count": int,
                    "total_confidence": float,
                    "reasoning_trace": str,
                    ...
                }
            }
        """
        logger.info(f"MultiHopSearchAgent executing query: {query[:100] if query else 'None'}...")

        # 입력 검증 (향상된 검증)
        validation_result = InputValidator.validate_query(query)
        if not validation_result.is_valid:
            logger.error(f"Query validation failed: {validation_result.error_message}")
            return {
                "success": False,
                "error": f"Invalid query: {validation_result.error_message}",
                "metadata": {"search_type": "multi_hop", "validation_error": True}
            }

        # 정제된 쿼리 사용
        query = validation_result.sanitized_value

        # 기본 입력 검증 (BaseAgent)
        if not self.validate_input(query, context):
            logger.error("Base validation failed")
            return {
                "success": False,
                "error": "Invalid input",
                "metadata": {"search_type": "multi_hop"}
            }

        try:
            # 컨텍스트 추출
            session_id = context.get("session_id", "") if context else ""
            user_id = context.get("user_id", "") if context else ""
            language = context.get("detected_language", "ko") if context else "ko"

            # 1. 질문 분해
            logger.info("Step 1: Decomposing query into sub-questions")
            reasoning_chain = await self.query_decomposer.decompose(
                query=query,
                session_id=session_id,
                user_id=user_id,
                language=language,
            )

            # 분해 불필요하거나 실패 시 일반 검색으로 폴백
            if not reasoning_chain:
                logger.info("Query decomposition not needed or failed, falling back to standard search")
                return await self._fallback_to_standard_search(query, context)

            logger.info(
                f"Query decomposed into {len(reasoning_chain.sub_questions)} sub-questions"
            )

            # 2. 추론 체인 실행
            logger.info("Step 2: Executing reasoning chain")
            reasoning_chain = await self.reasoning_chain_executor.execute_chain(
                reasoning_chain=reasoning_chain,
                search_function=self._search_for_hop,
                context={
                    "session_id": session_id,
                    "user_id": user_id,
                    "detected_language": language,
                },
            )

            # 3. 결과 통합
            logger.info("Step 3: Integrating results")
            multi_hop_result = await self.result_integrator.integrate(
                reasoning_chain=reasoning_chain,
                session_id=session_id,
                user_id=user_id,
                language=language,
            )

            # 4. SearchResult 형식으로 변환
            search_results = self._convert_to_search_results(multi_hop_result)

            # 5. 메타데이터 생성
            metadata = {
                "search_type": "multi_hop",
                "hop_count": multi_hop_result.get_hop_count(),
                "total_confidence": multi_hop_result.total_confidence,
                "success_rate": multi_hop_result.get_success_rate(),
                "total_sources": multi_hop_result.total_sources,
                "total_execution_time": multi_hop_result.total_execution_time,
                "reasoning_trace": multi_hop_result.reasoning_trace,
            }

            logger.info(
                f"Multi-hop search completed: {multi_hop_result.get_hop_count()} hops, "
                f"confidence: {multi_hop_result.total_confidence:.2f}"
            )

            return self.format_output(search_results, metadata)

        except asyncio.TimeoutError as e:
            logger.error(f"Multi-hop search timed out: {e}", exc_info=True)
            # 타임아웃 시 fallback 시도
            logger.info("Attempting fallback to standard search after timeout")
            return await self._fallback_to_standard_search(query, context)

        except ValueError as e:
            # 입력 검증 실패 등
            error_msg = ErrorHandler.sanitize_error_message(e)
            logger.error(f"Value error in multi-hop search: {error_msg}")
            return {
                "success": False,
                "error": f"Invalid input or configuration: {error_msg}",
                "metadata": {"search_type": "multi_hop", "error_type": "ValueError"},
            }

        except KeyError as e:
            # 필수 키 누락
            error_msg = ErrorHandler.sanitize_error_message(e)
            logger.error(f"Missing required key in multi-hop search: {error_msg}")
            return {
                "success": False,
                "error": f"Missing required information: {error_msg}",
                "metadata": {"search_type": "multi_hop", "error_type": "KeyError"},
            }

        except Exception as e:
            # 기타 모든 예외
            error_msg = ErrorHandler.sanitize_error_message(e)
            logger.error(f"Multi-hop search execution failed: {error_msg}", exc_info=True)

            # Fallback 시도
            logger.info("Attempting fallback to standard search after unexpected error")
            try:
                return await self._fallback_to_standard_search(query, context)
            except Exception as fallback_error:
                # Fallback도 실패하면 에러 반환
                fallback_msg = ErrorHandler.sanitize_error_message(fallback_error)
                logger.error(f"Fallback also failed: {fallback_msg}")
                return {
                    "success": False,
                    "error": f"Multi-hop search failed: {error_msg}. Fallback also failed: {fallback_msg}",
                    "metadata": {"search_type": "multi_hop", "fallback_failed": True},
                }

    async def _search_for_hop(
        self, query: str, context: Dict[str, Any]
    ) -> List[SearchResult]:
        """개별 hop에 대한 검색 수행

        Args:
            query: 검색 쿼리
            context: 컨텍스트

        Returns:
            검색 결과 리스트
        """
        if not self.api_available:
            logger.warning("Tavily API not available")
            return []

        try:
            # Tavily 검색
            tavily_results = await self._tavily_search(query)

            # SearchResult 객체로 변환
            search_results = []
            for item in tavily_results[:5]:  # 상위 5개만
                search_results.append(
                    SearchResult(
                        source="tavily",
                        title=item.get("title", ""),
                        content=item.get("content", ""),
                        url=item.get("url", ""),
                        score=item.get("score", 0.0),
                        metadata={
                            "domain": item.get("domain", ""),
                            "published_date": item.get("published_date"),
                        },
                    )
                )

            logger.info(f"Search for '{query}' returned {len(search_results)} results")
            return search_results

        except Exception as e:
            logger.error(f"Error searching for hop: {e}", exc_info=True)
            return []

    async def _tavily_search(self, query: str) -> List[Dict[str, Any]]:
        """Tavily 검색 실행

        Args:
            query: 검색 쿼리

        Returns:
            Tavily 검색 결과
        """
        try:
            # Tavily 검색 실행
            response = self.tavily_client.search(
                query=query,
                search_depth="basic",
                max_results=5,
                include_answer=False,
                include_raw_content=False,
            )

            results = response.get("results", [])
            logger.debug(f"Tavily returned {len(results)} results for: {query}")

            return results

        except Exception as e:
            logger.error(f"Tavily search error: {e}", exc_info=True)
            return []

    async def _fallback_to_standard_search(
        self, query: str, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """표준 검색으로 폴백

        멀티홉이 불필요하거나 실패한 경우 일반 검색 수행

        Args:
            query: 검색 쿼리
            context: 컨텍스트

        Returns:
            검색 결과
        """
        logger.info("Falling back to standard search")

        try:
            search_results = await self._search_for_hop(query, context or {})

            return self.format_output(
                search_results,
                {
                    "search_type": "multi_hop_fallback",
                    "note": "Standard search used (multi-hop not applicable)",
                },
            )

        except Exception as e:
            logger.error(f"Fallback search failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "metadata": {"search_type": "multi_hop_fallback"},
            }

    def _convert_to_search_results(
        self, multi_hop_result
    ) -> List[SearchResult]:
        """MultiHopResult를 SearchResult 리스트로 변환

        최종 답변을 첫 번째 결과로, 각 hop의 소스들을 추가 결과로 반환

        Args:
            multi_hop_result: MultiHopResult 객체

        Returns:
            SearchResult 리스트
        """
        results = []

        # 1. 최종 통합 답변을 첫 번째 결과로
        final_result = SearchResult(
            source="multi_hop_final",
            title=f"멀티홉 검색 최종 답변 ({multi_hop_result.get_hop_count()} 단계)",
            content=multi_hop_result.final_answer,
            url=None,
            score=multi_hop_result.total_confidence,
            metadata={
                "type": "final_answer",
                "hop_count": multi_hop_result.get_hop_count(),
                "total_confidence": multi_hop_result.total_confidence,
                "reasoning_trace": multi_hop_result.reasoning_trace,
            },
        )
        results.append(final_result)

        # 2. 각 hop의 소스들 추가 (중복 제거)
        all_sources = multi_hop_result.get_all_sources()
        results.extend(all_sources[:10])  # 최대 10개 소스

        return results
