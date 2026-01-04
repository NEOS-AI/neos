"""Answer Extractor - 답변 추출 및 검증 모듈

검색 결과에서 서브질문에 대한 답변을 추출하고 신뢰도를 평가하는 컴포넌트
"""

import json
import logging
from typing import List, Dict, Any, Optional, Tuple
from collections import Counter
from langchain_core.messages import HumanMessage

from neos.workflow.state import SearchResult
from neos.agents.search_agents.multi_hop.models import SubQuestion
from neos.utils.llm_wrapper import create_tracked_llm, extract_text_from_response

logger = logging.getLogger(__name__)


class AnswerExtractor:
    """검색 결과에서 답변을 추출하고 검증하는 컴포넌트

    주요 기능:
    1. LLM 기반 답변 추출
    2. 다중 소스 답변 통합 및 충돌 해결
    3. 답변 신뢰도 평가
    4. 답변 검증 (형식, 완전성)
    """

    def __init__(self, min_confidence: float = 0.7):
        self.min_confidence = min_confidence

    async def extract_answer(
        self,
        sub_question: SubQuestion,
        search_results: List[SearchResult],
        session_id: str = "",
        user_id: str = "",
        language: str = "ko",
    ) -> Tuple[str, float, str]:
        """검색 결과에서 서브질문에 대한 답변 추출

        Args:
            sub_question: 서브질문
            search_results: 검색 결과 리스트
            session_id: 세션 ID
            user_id: 사용자 ID
            language: 언어

        Returns:
            (답변, 신뢰도, 추론 과정)
        """
        if not search_results:
            logger.warning(f"No search results for question: {sub_question.query}")
            return "", 0.0, "No search results available"

        try:
            # 1. LLM으로 답변 추출
            answer, confidence, reasoning = await self._extract_with_llm(
                sub_question, search_results, session_id, user_id, language
            )

            # 2. 답변 검증
            is_valid, validation_message = self._validate_answer(
                answer, sub_question.expected_answer_type
            )

            if not is_valid:
                logger.warning(
                    f"Answer validation failed: {validation_message}"
                )
                confidence *= 0.5  # 검증 실패 시 신뢰도 감소

            # 3. 신뢰도가 너무 낮으면 다중 소스 통합 시도
            if confidence < self.min_confidence and len(search_results) > 1:
                logger.info("Low confidence, trying multi-source integration")
                integrated_answer, integrated_confidence = await self._integrate_multiple_sources(
                    sub_question, search_results, session_id, user_id, language
                )
                if integrated_confidence > confidence:
                    answer = integrated_answer
                    confidence = integrated_confidence
                    reasoning += f"\n[Multi-source integration applied, new confidence: {integrated_confidence:.2f}]"

            logger.info(
                f"Extracted answer for '{sub_question.query}': '{answer}' (confidence: {confidence:.2f})"
            )

            return answer, confidence, reasoning

        except Exception as e:
            logger.error(f"Error extracting answer: {e}", exc_info=True)
            return "", 0.0, f"Error: {str(e)}"

    async def _extract_with_llm(
        self,
        sub_question: SubQuestion,
        search_results: List[SearchResult],
        session_id: str,
        user_id: str,
        language: str,
    ) -> Tuple[str, float, str]:
        """LLM을 사용하여 답변 추출

        이 메서드는 검색 결과에서 정확한 답변을 추출하는 핵심 로직입니다.
        프롬프트 품질이 답변 정확도를 결정합니다.

        TODO: 사용자가 프롬프트 작성
        """
        llm = create_tracked_llm(session_id=session_id, user_id=user_id)

        # 검색 결과 포맷팅 (상위 5개만 사용)
        sources_text = "\n\n".join(
            [
                f"[출처 {i+1}] {result.title}\nURL: {result.url}\n내용: {result.content[:500]}..."
                for i, result in enumerate(search_results[:5])
            ]
        )

        # TODO: 여기에 프롬프트를 작성해주세요
        #
        # 프롬프트 작성 가이드라인:
        # 1. 질문에 대한 명확하고 간결한 답변 요구
        # 2. 여러 소스가 다른 답변을 제시하면 가장 신뢰할 만한 것 선택
        # 3. 답변을 찾을 수 없으면 솔직하게 인정
        # 4. 신뢰도 점수 제공 (0.0-1.0)
        # 5. 추론 과정 설명
        #
        # 출력 형식:
        # {
        #   "answer": "간결한 답변 (예: Apple, 캘리포니아, Tim Cook)",
        #   "confidence": 0.0-1.0,
        #   "reasoning": "어떻게 이 답변에 도달했는지 설명"
        # }

        prompts = {
            "ko": f"""다음 검색 결과에서 질문에 대한 답변을 추출해주세요.

질문: {sub_question.query}
질문 유형: {sub_question.question_type}
예상 답변 유형: {sub_question.expected_answer_type}

검색 결과:
{sources_text}

답변 추출 지침:
1. 질문에 대한 가장 정확하고 간결한 답변을 제공하세요
2. 여러 출처가 일치하는 정보를 우선시하세요
3. 최신 정보를 우선하되, 신뢰할 수 있는 출처를 선택하세요
4. 답변을 찾을 수 없으면 "정보 없음"이라고 답하세요
5. 예상 답변 유형에 맞는 형식으로 답변하세요
   - entity: 구체적인 이름, 회사명, 인물명 등
   - location: 도시, 국가, 주소 등
   - date: 날짜, 연도
   - number: 숫자
   - yes_no: 예/아니오
   - description: 간단한 설명 (1-2문장)

신뢰도 평가 기준:
- 1.0: 여러 신뢰할 만한 출처가 동일한 답변 제공
- 0.8-0.9: 대부분의 출처가 일치하는 답변 제공
- 0.6-0.7: 일부 출처만 답변 제공하거나 약간의 불일치
- 0.4-0.5: 출처 간 상당한 불일치 또는 정보 부족
- 0.0-0.3: 답변을 찾을 수 없거나 매우 불확실함

다음 JSON 형식으로만 답변하세요:
{{
  "answer": "간결한 답변 (10단어 이내 권장)",
  "confidence": 0.0-1.0,
  "reasoning": "답변 추출 과정과 신뢰도 판단 근거 (1-2문장)"
}}""",
            "en": f"""Extract the answer to the question from the following search results.

Question: {sub_question.query}
Question Type: {sub_question.question_type}
Expected Answer Type: {sub_question.expected_answer_type}

Search Results:
{sources_text}

Answer extraction guidelines:
1. Provide the most accurate and concise answer to the question
2. Prioritize information that is consistent across multiple sources
3. Prefer recent information, but choose reliable sources
4. If the answer cannot be found, respond with "No information"
5. Format the answer according to the expected answer type
   - entity: specific name, company, person, etc.
   - location: city, country, address, etc.
   - date: date, year
   - number: number
   - yes_no: yes/no
   - description: brief description (1-2 sentences)

Confidence scoring criteria:
- 1.0: Multiple reliable sources provide the same answer
- 0.8-0.9: Most sources provide consistent answers
- 0.6-0.7: Only some sources provide answers or slight inconsistencies
- 0.4-0.5: Significant inconsistencies or lack of information
- 0.0-0.3: Answer not found or very uncertain

Respond ONLY in this JSON format:
{{
  "answer": "concise answer (recommended within 10 words)",
  "confidence": 0.0-1.0,
  "reasoning": "extraction process and confidence rationale (1-2 sentences)"
}}""",
        }

        prompt = prompts.get(language, prompts["en"])

        try:
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            response_text = extract_text_from_response(response).strip()

            # JSON 파싱
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0].strip()

            data = json.loads(response_text)
            answer = data.get("answer", "").strip()
            confidence = float(data.get("confidence", 0.5))
            reasoning = data.get("reasoning", "No reasoning provided")

            return answer, confidence, reasoning

        except Exception as e:
            logger.error(f"Error in LLM extraction: {e}", exc_info=True)
            return "", 0.0, f"LLM extraction error: {str(e)}"

    async def _integrate_multiple_sources(
        self,
        sub_question: SubQuestion,
        search_results: List[SearchResult],
        session_id: str,
        user_id: str,
        language: str,
    ) -> Tuple[str, float]:
        """여러 소스의 답변을 통합하여 신뢰도 향상

        각 소스에서 개별적으로 답변을 추출하고, 다수결 또는 가중 평균으로 통합
        """
        # 각 검색 결과에서 개별적으로 답변 추출
        individual_answers = []

        for result in search_results[:5]:  # 상위 5개만
            answer, confidence, _ = await self._extract_with_llm(
                sub_question, [result], session_id, user_id, language
            )
            if answer and answer != "정보 없음" and answer != "No information":
                individual_answers.append((answer, confidence, result.score))

        if not individual_answers:
            return "", 0.0

        # 답변별 신뢰도 합산 (가중 평균)
        answer_scores = {}
        for answer, confidence, source_score in individual_answers:
            # 정규화된 답변 (대소문자 무시, 공백 제거)
            normalized_answer = answer.lower().strip()

            # 가중치 = LLM 신뢰도 * 검색 결과 점수
            weight = confidence * (source_score if source_score > 0 else 0.5)

            if normalized_answer in answer_scores:
                answer_scores[normalized_answer]["weight"] += weight
                answer_scores[normalized_answer]["count"] += 1
                answer_scores[normalized_answer]["original"] = answer  # 마지막 원본 저장
            else:
                answer_scores[normalized_answer] = {
                    "weight": weight,
                    "count": 1,
                    "original": answer,
                }

        # 가장 높은 가중치의 답변 선택
        best_answer_data = max(answer_scores.values(), key=lambda x: x["weight"])
        best_answer = best_answer_data["original"]

        # 통합 신뢰도 계산
        # = (가중치 합) / (총 소스 수) * (일치하는 소스 비율)
        total_weight = best_answer_data["weight"]
        agreement_ratio = best_answer_data["count"] / len(individual_answers)
        integrated_confidence = min((total_weight / len(individual_answers)) * agreement_ratio, 1.0)

        logger.info(
            f"Integrated answer: '{best_answer}' from {best_answer_data['count']}/{len(individual_answers)} sources (confidence: {integrated_confidence:.2f})"
        )

        return best_answer, integrated_confidence

    def _validate_answer(
        self, answer: str, expected_type: str
    ) -> Tuple[bool, str]:
        """답변 형식 및 완전성 검증

        Args:
            answer: 추출된 답변
            expected_type: 예상 답변 유형

        Returns:
            (유효 여부, 검증 메시지)
        """
        if not answer or answer.strip() == "":
            return False, "Empty answer"

        # "정보 없음" 류의 답변 체크
        no_info_keywords = ["정보 없음", "no information", "not found", "unknown", "알 수 없음"]
        if any(keyword in answer.lower() for keyword in no_info_keywords):
            return False, "No information found"

        # 답변 길이 체크 (너무 길면 설명이지 답변이 아닐 수 있음)
        if expected_type in ["entity", "location", "date", "number", "yes_no"]:
            if len(answer) > 100:
                return False, f"Answer too long for type {expected_type}"

        # 유형별 검증
        if expected_type == "number":
            # 숫자가 포함되어 있는지 확인
            if not any(char.isdigit() for char in answer):
                return False, "Expected number but no digits found"

        elif expected_type == "yes_no":
            # yes/no 또는 예/아니오 포함 확인
            yes_no_keywords = ["yes", "no", "예", "아니오", "네", "아니"]
            if not any(keyword in answer.lower() for keyword in yes_no_keywords):
                return False, "Expected yes/no answer"

        elif expected_type == "date":
            # 날짜 관련 키워드나 숫자 포함 확인
            if not any(char.isdigit() for char in answer):
                return False, "Expected date but no numbers found"

        return True, "Valid answer"
