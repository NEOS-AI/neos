"""Reasoning Chain Executor - 추론 체인 실행 모듈

서브질문들을 순차/병렬로 실행하고 중간 결과를 다음 단계에 주입하는 컴포넌트
"""

import re
import asyncio
import logging
import time
from typing import Dict, Any, List, Optional

from neos.workflow.state import SearchResult, AgentState
from neos.agents.search_agents.multi_hop.models import (
    ReasoningChain,
    SubQuestion,
    HopResult,
    HopStatus,
    MultiHopConfig,
)
from neos.agents.search_agents.multi_hop.answer_extractor import AnswerExtractor
from neos.agents.search_agents.multi_hop.validation_utils import ErrorHandler
from neos.utils.cache import cache_manager

logger = logging.getLogger(__name__)


class ReasoningChainExecutor:
    """추론 체인을 실행하는 컴포넌트

    주요 기능:
    1. 서브질문 실행 순서 관리 (위상 정렬 기반)
    2. 병렬 실행 최적화 (독립적인 질문들)
    3. 쿼리 템플릿에 답변 주입
    4. 실패 처리 및 재시도
    5. 중간 결과 캐싱
    """

    def __init__(
        self,
        answer_extractor: AnswerExtractor,
        config: MultiHopConfig,
    ):
        self.answer_extractor = answer_extractor
        self.config = config

    async def execute_chain(
        self,
        reasoning_chain: ReasoningChain,
        search_function: Any,  # 검색 함수 (query, context) -> List[SearchResult]
        context: Dict[str, Any],
    ) -> ReasoningChain:
        """추론 체인 실행

        Args:
            reasoning_chain: 실행할 추론 체인
            search_function: 검색 수행 함수
            context: 실행 컨텍스트 (session_id, user_id, language 등)

        Returns:
            업데이트된 ReasoningChain (hop_results 포함)
        """
        logger.info(
            f"Executing reasoning chain with {len(reasoning_chain.sub_questions)} sub-questions"
        )

        # 실행 통계
        start_time = time.time()
        total_hops = len(reasoning_chain.sub_questions)

        try:
            # 위상 정렬 순서대로 실행
            for hop_index, question_id in enumerate(reasoning_chain.execution_order, 1):
                logger.info(f"Executing hop {hop_index}/{total_hops}: {question_id}")

                # 해당 질문 찾기
                sub_question = next(
                    (q for q in reasoning_chain.sub_questions if q.id == question_id),
                    None
                )

                if not sub_question:
                    logger.error(f"Question {question_id} not found in sub_questions")
                    continue

                # Hop 실행
                hop_result = await self._execute_hop(
                    sub_question,
                    reasoning_chain,
                    search_function,
                    context,
                )

                # 결과 저장
                reasoning_chain.hop_results.append(hop_result)

                # 실패 처리
                if not hop_result.is_successful():
                    logger.warning(
                        f"Hop {question_id} failed: {hop_result.error_message}"
                    )

                    # 재시도
                    if self.config.max_retries_per_hop > 0:
                        hop_result = await self._retry_hop(
                            sub_question,
                            reasoning_chain,
                            search_function,
                            context,
                            self.config.max_retries_per_hop,
                        )
                        # 재시도 결과로 업데이트
                        reasoning_chain.hop_results[-1] = hop_result

                    # 재시도 후에도 실패하면 체인 중단
                    if not hop_result.is_successful():
                        logger.error(
                            f"Hop {question_id} failed after retries, stopping chain"
                        )
                        break

                logger.info(
                    f"Hop {question_id} completed: '{hop_result.answer}' (confidence: {hop_result.confidence:.2f})"
                )

            # 실행 시간 기록
            total_time = time.time() - start_time
            logger.info(
                f"Chain execution completed in {total_time:.2f}s: {len(reasoning_chain.hop_results)}/{total_hops} hops successful"
            )

            return reasoning_chain

        except Exception as e:
            logger.error(f"Error executing reasoning chain: {e}", exc_info=True)
            return reasoning_chain

    async def _execute_hop(
        self,
        sub_question: SubQuestion,
        reasoning_chain: ReasoningChain,
        search_function: Any,
        context: Dict[str, Any],
    ) -> HopResult:
        """단일 Hop 실행

        Args:
            sub_question: 실행할 서브질문
            reasoning_chain: 현재 추론 체인 (이전 답변 참조용)
            search_function: 검색 함수
            context: 실행 컨텍스트

        Returns:
            HopResult
        """
        hop_start_time = time.time()

        try:
            # 1. 쿼리 템플릿에 이전 답변 주입
            actual_query = self._inject_answers_to_query(
                sub_question.query_template,
                reasoning_chain,
            )

            logger.info(
                f"Injected query: '{sub_question.query_template}' -> '{actual_query}'"
            )

            # 2. 캐시 확인
            cache_key = self._generate_cache_key(actual_query, context)
            cached_result = await self._check_cache(cache_key)

            if cached_result:
                logger.info(f"Cache hit for query: {actual_query}")
                return cached_result

            # 3. 검색 수행
            logger.info(f"Searching for: {actual_query}")
            search_results = await search_function(actual_query, context)

            logger.info(f"Found {len(search_results)} search results")

            # 4. 답변 추출
            answer, confidence, reasoning = await self.answer_extractor.extract_answer(
                sub_question=sub_question,
                search_results=search_results,
                session_id=context.get("session_id", ""),
                user_id=context.get("user_id", ""),
                language=context.get("detected_language", "ko"),
            )

            # 5. HopResult 생성
            hop_result = HopResult(
                question_id=sub_question.id,
                query_executed=actual_query,
                answer=answer,
                confidence=confidence,
                sources=search_results,
                reasoning=reasoning,
                status=HopStatus.COMPLETED if confidence >= self.config.min_answer_confidence else HopStatus.FAILED,
                execution_time=time.time() - hop_start_time,
                intermediate_results={
                    "original_template": sub_question.query_template,
                    "num_sources": len(search_results),
                },
            )

            # 6. 캐싱
            if hop_result.is_successful() and self.config.reuse_intermediate_results:
                await self._cache_result(cache_key, hop_result)

            return hop_result

        except asyncio.TimeoutError:
            logger.error(f"Hop execution timeout for question: {sub_question.id}")
            return HopResult(
                question_id=sub_question.id,
                query_executed=sub_question.query,
                answer="",
                confidence=0.0,
                sources=[],
                status=HopStatus.FAILED,
                error_message="Execution timeout",
                execution_time=time.time() - hop_start_time,
            )

        except Exception as e:
            logger.error(f"Error executing hop: {e}", exc_info=True)
            return HopResult(
                question_id=sub_question.id,
                query_executed=sub_question.query,
                answer="",
                confidence=0.0,
                sources=[],
                status=HopStatus.FAILED,
                error_message=str(e),
                execution_time=time.time() - hop_start_time,
            )

    def _inject_answers_to_query(
        self,
        query_template: str,
        reasoning_chain: ReasoningChain,
    ) -> str:
        """쿼리 템플릿에 이전 답변 주입

        템플릿 형식: "{qN.answer}"을 실제 답변으로 치환

        예:
            템플릿: "{q1.answer}의 CEO는?"
            q1의 답변이 "Apple"이면
            결과: "Apple의 CEO는?"

        Args:
            query_template: 쿼리 템플릿
            reasoning_chain: 현재 추론 체인

        Returns:
            주입된 실제 쿼리
        """
        # {qN.answer} 패턴 찾기
        pattern = r"\{(q\d+)\.answer\}"
        matches = re.findall(pattern, query_template)

        if not matches:
            # 템플릿이 아니면 그대로 반환
            return query_template

        # 각 참조를 실제 답변으로 치환
        result_query = query_template
        for question_id in matches:
            answer = reasoning_chain.get_answer_for_question(question_id)

            if answer:
                # {qN.answer}를 실제 답변으로 치환
                placeholder = f"{{{question_id}.answer}}"
                result_query = result_query.replace(placeholder, answer)
                logger.debug(f"Replaced {placeholder} with '{answer}'")
            else:
                # 답변을 찾을 수 없으면 에러
                logger.error(
                    f"Cannot find answer for {question_id} in reasoning chain"
                )
                # 플레이스홀더를 "Unknown"으로 대체
                placeholder = f"{{{question_id}.answer}}"
                result_query = result_query.replace(placeholder, "[Unknown]")

        return result_query

    async def _retry_hop(
        self,
        sub_question: SubQuestion,
        reasoning_chain: ReasoningChain,
        search_function: Any,
        context: Dict[str, Any],
        max_retries: int,
    ) -> HopResult:
        """Hop 재시도 (개선된 exponential backoff)

        Args:
            sub_question: 재시도할 서브질문
            reasoning_chain: 추론 체인
            search_function: 검색 함수
            context: 실행 컨텍스트
            max_retries: 최대 재시도 횟수

        Returns:
            HopResult
        """
        logger.info(f"Retrying hop {sub_question.id} (max {max_retries} times)")

        last_error = None
        last_result = None

        for retry_count in range(1, max_retries + 1):
            try:
                hop_result = await self._execute_hop(
                    sub_question,
                    reasoning_chain,
                    search_function,
                    context,
                )

                if hop_result.is_successful():
                    logger.info(f"Retry succeeded on attempt {retry_count}")
                    return hop_result

                # 실패했지만 예외는 아님
                last_result = hop_result

                # 재시도 여부 결정 (ErrorHandler 사용)
                if hop_result.error_message:
                    # 가상의 예외 객체 생성 (에러 메시지 기반)
                    error = Exception(hop_result.error_message)
                    should_retry, wait_time = ErrorHandler.should_retry(
                        error, retry_count, max_retries
                    )

                    if not should_retry:
                        logger.info(f"Non-retryable error detected, stopping retries")
                        return hop_result

                    # Exponential backoff
                    logger.info(f"Retry attempt {retry_count}/{max_retries}, waiting {wait_time}s")
                    await asyncio.sleep(wait_time)
                else:
                    # 에러 메시지가 없으면 기본 backoff
                    wait_time = min(2 ** retry_count, 60)
                    logger.info(f"Retry attempt {retry_count}/{max_retries}, waiting {wait_time}s")
                    await asyncio.sleep(wait_time)

            except Exception as e:
                last_error = e
                logger.error(f"Exception during retry attempt {retry_count}: {e}")

                # 재시도 여부 결정
                should_retry, wait_time = ErrorHandler.should_retry(
                    e, retry_count, max_retries
                )

                if not should_retry:
                    logger.info(f"Non-retryable exception, stopping retries")
                    # 실패 결과 반환
                    return HopResult(
                        question_id=sub_question.id,
                        query_executed=sub_question.query,
                        answer="",
                        confidence=0.0,
                        sources=[],
                        status=HopStatus.FAILED,
                        error_message=ErrorHandler.sanitize_error_message(e),
                        execution_time=0.0,
                    )

                # Exponential backoff
                logger.info(f"Retry attempt {retry_count}/{max_retries}, waiting {wait_time}s")
                await asyncio.sleep(wait_time)

        # 모든 재시도 실패
        logger.error(f"All {max_retries} retry attempts failed")

        if last_result:
            return last_result

        if last_error:
            return HopResult(
                question_id=sub_question.id,
                query_executed=sub_question.query,
                answer="",
                confidence=0.0,
                sources=[],
                status=HopStatus.FAILED,
                error_message=ErrorHandler.sanitize_error_message(last_error),
                execution_time=0.0,
            )

        # Fallback (이론적으로 도달 불가)
        return HopResult(
            question_id=sub_question.id,
            query_executed=sub_question.query,
            answer="",
            confidence=0.0,
            sources=[],
            status=HopStatus.FAILED,
            error_message="All retries failed with unknown error",
            execution_time=0.0,
        )

    def _generate_cache_key(self, query: str, context: Dict[str, Any]) -> str:
        """캐시 키 생성

        Args:
            query: 쿼리
            context: 컨텍스트

        Returns:
            캐시 키
        """
        language = context.get("detected_language", "ko")
        return cache_manager.make_key(
            "multi_hop_result",
            hash(query),
            language,
        )

    async def _check_cache(self, cache_key: str) -> Optional[HopResult]:
        """캐시된 결과 확인

        Args:
            cache_key: 캐시 키

        Returns:
            캐시된 HopResult 또는 None
        """
        try:
            cached_data = await cache_manager.get(cache_key)
            if cached_data:
                # dict를 HopResult로 변환
                # (캐시에서는 객체가 dict로 저장됨)
                if isinstance(cached_data, dict):
                    return HopResult(**cached_data)
                return cached_data
        except Exception as e:
            logger.warning(f"Cache check error: {e}")

        return None

    async def _cache_result(self, cache_key: str, hop_result: HopResult) -> None:
        """결과 캐싱

        Args:
            cache_key: 캐시 키
            hop_result: 캐싱할 HopResult
        """
        try:
            # HopResult를 dict로 변환 (일부 필드만)
            cache_data = {
                "question_id": hop_result.question_id,
                "query_executed": hop_result.query_executed,
                "answer": hop_result.answer,
                "confidence": hop_result.confidence,
                "sources": [],  # 소스는 너무 커서 제외
                "reasoning": hop_result.reasoning,
                "status": hop_result.status,
                "execution_time": hop_result.execution_time,
            }

            # 1시간 TTL
            await cache_manager.set(cache_key, cache_data, ttl=3600)
            logger.debug(f"Cached hop result: {cache_key}")

        except Exception as e:
            logger.warning(f"Cache set error: {e}")
