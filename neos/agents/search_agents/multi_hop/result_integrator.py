"""Result Integrator - 결과 통합 모듈

모든 hop의 결과를 하나의 최종 답변으로 통합하고 추론 과정을 시각화하는 컴포넌트
"""

import json
import logging
from typing import Dict, Any, List
from langchain_core.messages import HumanMessage

from neos.agents.search_agents.multi_hop.models import (
    ReasoningChain,
    MultiHopResult,
)
from neos.utils.llm_wrapper import create_tracked_llm, extract_text_from_response

logger = logging.getLogger(__name__)


class ResultIntegrator:
    """추론 체인의 결과를 최종 답변으로 통합하는 컴포넌트

    주요 기능:
    1. 모든 hop의 답변을 하나의 최종 답변으로 통합
    2. 추론 과정 시각화 (reasoning trace)
    3. 전체 신뢰도 계산 (조화평균)
    4. 출처 추적 및 인용
    """

    async def integrate(
        self,
        reasoning_chain: ReasoningChain,
        session_id: str = "",
        user_id: str = "",
        language: str = "ko",
    ) -> MultiHopResult:
        """추론 체인 결과를 최종 답변으로 통합

        Args:
            reasoning_chain: 실행 완료된 추론 체인
            session_id: 세션 ID
            user_id: 사용자 ID
            language: 언어

        Returns:
            MultiHopResult
        """
        logger.info(
            f"Integrating {len(reasoning_chain.hop_results)} hop results"
        )

        try:
            # 1. 최종 답변 생성 (LLM 사용)
            final_answer = await self._generate_final_answer(
                reasoning_chain, session_id, user_id, language
            )

            # 2. 추론 과정 시각화
            reasoning_trace = self._generate_reasoning_trace(reasoning_chain)

            # 3. 전체 신뢰도 계산
            total_confidence = self._calculate_total_confidence(reasoning_chain)

            # 4. 실행 시간 합산
            total_execution_time = sum(
                hop.execution_time for hop in reasoning_chain.hop_results
            )

            # 5. 모든 소스 수집
            all_sources = []
            for hop_result in reasoning_chain.hop_results:
                all_sources.extend(hop_result.sources)

            # 6. MultiHopResult 생성
            result = MultiHopResult(
                original_query=reasoning_chain.original_query,
                final_answer=final_answer,
                reasoning_chain=reasoning_chain,
                total_confidence=total_confidence,
                reasoning_trace=reasoning_trace,
                total_sources=len(all_sources),
                total_execution_time=total_execution_time,
                metadata={
                    "hop_count": len(reasoning_chain.hop_results),
                    "success_rate": self._calculate_success_rate(reasoning_chain),
                    "average_hop_confidence": self._calculate_average_confidence(reasoning_chain),
                },
            )

            logger.info(
                f"Integration complete: confidence={total_confidence:.2f}, hops={result.get_hop_count()}"
            )

            return result

        except Exception as e:
            logger.error(f"Error integrating results: {e}", exc_info=True)

            # 실패 시 기본 결과 반환
            return MultiHopResult(
                original_query=reasoning_chain.original_query,
                final_answer="답변 생성 중 오류가 발생했습니다.",
                reasoning_chain=reasoning_chain,
                total_confidence=0.0,
                reasoning_trace=f"Error: {str(e)}",
                metadata={"error": str(e)},
            )

    async def _generate_final_answer(
        self,
        reasoning_chain: ReasoningChain,
        session_id: str,
        user_id: str,
        language: str,
    ) -> str:
        """LLM을 사용하여 최종 답변 생성

        모든 hop의 답변을 종합하여 자연스러운 최종 답변 생성

        이 메서드는 멀티홉 검색의 최종 결과물을 결정합니다.
        사용자가 받는 답변의 품질과 형식을 정의하는 중요한 부분입니다.
        """
        llm = create_tracked_llm(session_id=session_id, user_id=user_id)

        # Hop 결과를 텍스트로 포맷팅
        hops_text = []
        for i, hop_result in enumerate(reasoning_chain.hop_results, 1):
            # 해당 질문 찾기
            sub_question = next(
                (q for q in reasoning_chain.sub_questions if q.id == hop_result.question_id),
                None
            )

            question_text = sub_question.query if sub_question else hop_result.query_executed

            hops_text.append(
                f"단계 {i}: {question_text}\n"
                f"답변: {hop_result.answer}\n"
                f"신뢰도: {hop_result.confidence:.2f}\n"
                f"근거: {hop_result.reasoning}"
            )

        hops_summary = "\n\n".join(hops_text)

        # 최종 hop의 답변 (가장 중요)
        final_hop = reasoning_chain.hop_results[-1] if reasoning_chain.hop_results else None
        final_hop_answer = final_hop.answer if final_hop else "정보 없음"

        prompts = {
            "ko": f"""다음은 복잡한 질문에 답하기 위해 여러 단계로 나누어 검색한 결과입니다.
이를 바탕으로 원본 질문에 대한 최종 답변을 생성해주세요.

원본 질문: {reasoning_chain.original_query}

단계별 검색 결과:
{hops_summary}

답변 생성 지침:
1. 모든 단계의 답변을 종합하여 원본 질문에 직접 답변하세요
2. 마지막 단계의 답변이 가장 중요하지만, 중간 단계의 맥락도 활용하세요
3. 자연스럽고 완전한 문장으로 답변하세요
4. 답변은 간결하되 충분한 정보를 포함하세요 (1-3문장 권장)
5. 중간 단계를 언급할 필요는 없습니다 - 최종 답변만 제공하세요

예시:
질문: "아이폰을 개발한 사람의 모교 위치는?"
단계 1: "아이폰을 개발한 주요 인물은?" → "스티브 잡스"
단계 2: "스티브 잡스의 모교는?" → "Reed College"
단계 3: "Reed College의 위치는?" → "Oregon, Portland"

좋은 답변: "아이폰을 개발한 스티브 잡스의 모교는 오레곤 주 포틀랜드에 위치한 Reed College입니다."
나쁜 답변: "Oregon, Portland" (맥락 부족)

최종 답변:""",
            "en": f"""Here are the results of a multi-step search to answer a complex question.
Generate a final answer to the original question based on these results.

Original Question: {reasoning_chain.original_query}

Step-by-step Search Results:
{hops_summary}

Answer generation guidelines:
1. Synthesize all step answers to directly answer the original question
2. The last step's answer is most important, but use context from intermediate steps
3. Provide a natural and complete sentence answer
4. Keep it concise but informative (1-3 sentences recommended)
5. Don't mention the intermediate steps - just provide the final answer

Example:
Question: "Where is the alma mater of the person who developed the iPhone?"
Step 1: "Who developed the iPhone?" → "Steve Jobs"
Step 2: "What is Steve Jobs' alma mater?" → "Reed College"
Step 3: "Where is Reed College located?" → "Oregon, Portland"

Good answer: "Steve Jobs, who developed the iPhone, attended Reed College, which is located in Portland, Oregon."
Bad answer: "Oregon, Portland" (lacks context)

Final Answer:""",
        }

        prompt = prompts.get(language, prompts["en"])

        try:
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            final_answer = extract_text_from_response(response).strip()

            # 답변이 너무 짧거나 의미 없으면 마지막 hop 답변 사용
            if len(final_answer) < 10 or not final_answer:
                logger.warning("LLM generated insufficient answer, using last hop answer")
                final_answer = final_hop_answer

            return final_answer

        except Exception as e:
            logger.error(f"Error generating final answer: {e}", exc_info=True)
            # 실패 시 마지막 hop의 답변 사용
            return final_hop_answer

    def _generate_reasoning_trace(self, reasoning_chain: ReasoningChain) -> str:
        """추론 과정 시각화

        텍스트 기반으로 추론 흐름을 시각화

        Returns:
            Reasoning trace 문자열
        """
        lines = []
        lines.append("=" * 60)
        lines.append("멀티홉 검색 추론 과정")
        lines.append("=" * 60)
        lines.append(f"\n원본 질문: {reasoning_chain.original_query}\n")

        for i, hop_result in enumerate(reasoning_chain.hop_results, 1):
            # 해당 질문 찾기
            sub_question = next(
                (q for q in reasoning_chain.sub_questions if q.id == hop_result.question_id),
                None
            )

            lines.append(f"[HOP {i}] {hop_result.question_id}")
            lines.append("-" * 60)

            if sub_question:
                lines.append(f"질문 유형: {sub_question.question_type}")
                lines.append(f"이유: {sub_question.reasoning}")

            lines.append(f"실행 쿼리: {hop_result.query_executed}")
            lines.append(f"답변: {hop_result.answer}")
            lines.append(f"신뢰도: {hop_result.confidence:.2f}")
            lines.append(f"소스 수: {len(hop_result.sources)}")
            lines.append(f"실행 시간: {hop_result.execution_time:.2f}s")
            lines.append(f"상태: {hop_result.status}")

            if hop_result.error_message:
                lines.append(f"오류: {hop_result.error_message}")

            lines.append(f"추론: {hop_result.reasoning}")
            lines.append("")

        lines.append("=" * 60)
        lines.append(f"총 HOP 수: {len(reasoning_chain.hop_results)}")
        lines.append(f"성공률: {self._calculate_success_rate(reasoning_chain):.1%}")
        lines.append(f"평균 신뢰도: {self._calculate_average_confidence(reasoning_chain):.2f}")
        lines.append("=" * 60)

        return "\n".join(lines)

    def _calculate_total_confidence(self, reasoning_chain: ReasoningChain) -> float:
        """전체 신뢰도 계산 (조화평균)

        조화평균을 사용하는 이유:
        - 체인의 약한 고리가 전체 신뢰도에 큰 영향
        - 한 hop이라도 신뢰도가 낮으면 전체 신뢰도 하락
        - 모든 hop이 고르게 높은 신뢰도를 가져야 함

        Returns:
            전체 신뢰도 (0.0 ~ 1.0)
        """
        successful_hops = [
            hop for hop in reasoning_chain.hop_results
            if hop.is_successful()
        ]

        if not successful_hops:
            return 0.0

        # 조화평균 = n / (1/x1 + 1/x2 + ... + 1/xn)
        n = len(successful_hops)
        sum_reciprocals = sum(
            1 / hop.confidence if hop.confidence > 0 else 0
            for hop in successful_hops
        )

        if sum_reciprocals == 0:
            return 0.0

        harmonic_mean = n / sum_reciprocals

        return min(harmonic_mean, 1.0)

    def _calculate_success_rate(self, reasoning_chain: ReasoningChain) -> float:
        """성공한 hop의 비율 계산

        Returns:
            성공률 (0.0 ~ 1.0)
        """
        if not reasoning_chain.hop_results:
            return 0.0

        successful_count = sum(
            1 for hop in reasoning_chain.hop_results
            if hop.is_successful()
        )

        return successful_count / len(reasoning_chain.hop_results)

    def _calculate_average_confidence(self, reasoning_chain: ReasoningChain) -> float:
        """평균 신뢰도 계산 (산술평균)

        Returns:
            평균 신뢰도 (0.0 ~ 1.0)
        """
        if not reasoning_chain.hop_results:
            return 0.0

        total_confidence = sum(
            hop.confidence for hop in reasoning_chain.hop_results
        )

        return total_confidence / len(reasoning_chain.hop_results)
