"""Query Decomposer - 질문 분해 모듈

복잡한 질문을 서브질문 체인으로 분해하는 핵심 컴포넌트
"""

import json
import logging
from typing import List, Dict, Any, Optional, Tuple
from langchain_core.messages import HumanMessage

from neos.agents.search_agents.multi_hop.models import (
    SubQuestion,
    ReasoningChain,
    QuestionType,
)
from neos.utils.llm_wrapper import create_tracked_llm, extract_text_from_response

logger = logging.getLogger(__name__)


class QueryDecomposer:
    """복잡한 질문을 서브질문으로 분해하는 컴포넌트

    주요 기능:
    1. 질문 복잡도 평가
    2. 서브질문 체인 생성
    3. 의존성 그래프 검증 (순환 참조 방지)
    4. 실행 순서 결정 (위상 정렬)
    """

    def __init__(self):
        self.complexity_threshold = 0.6  # 멀티홉 적용 최소 복잡도

    async def decompose(
        self,
        query: str,
        session_id: str = "",
        user_id: str = "",
        language: str = "ko",
    ) -> Optional[ReasoningChain]:
        """질문을 서브질문 체인으로 분해

        Args:
            query: 원본 질문
            session_id: 세션 ID
            user_id: 사용자 ID
            language: 언어 코드

        Returns:
            ReasoningChain 또는 None (분해 불필요/실패 시)
        """
        try:
            # 1. 질문 복잡도 평가
            complexity_score, complexity_reason = await self._assess_complexity(
                query, session_id, user_id, language
            )

            logger.info(
                f"Query complexity: {complexity_score:.2f} - {complexity_reason}"
            )

            # 복잡도가 낮으면 멀티홉 불필요
            if complexity_score < self.complexity_threshold:
                logger.info(
                    f"Query is too simple for multi-hop (score: {complexity_score:.2f})"
                )
                return None

            # 2. 서브질문 생성
            sub_questions = await self._generate_sub_questions(
                query, session_id, user_id, language
            )

            if not sub_questions:
                logger.warning("Failed to generate sub-questions")
                return None

            # 3. 의존성 검증
            if not self._validate_dependencies(sub_questions):
                logger.error("Invalid dependency graph (circular reference detected)")
                return None

            # 4. 실행 순서 결정
            execution_order = self._topological_sort(sub_questions)

            # 5. ReasoningChain 생성
            chain = ReasoningChain(
                original_query=query,
                sub_questions=sub_questions,
                execution_order=execution_order,
            )

            logger.info(
                f"Successfully decomposed query into {len(sub_questions)} sub-questions"
            )

            return chain

        except Exception as e:
            logger.error(f"Error decomposing query: {e}", exc_info=True)
            return None

    async def _assess_complexity(
        self,
        query: str,
        session_id: str,
        user_id: str,
        language: str,
    ) -> Tuple[float, str]:
        """질문 복잡도 평가

        Args:
            query: 질문
            session_id: 세션 ID
            user_id: 사용자 ID
            language: 언어

        Returns:
            (복잡도 점수 0-1, 이유)
        """
        llm = create_tracked_llm(session_id=session_id, user_id=user_id)

        prompts = {
            "ko": f"""다음 질문의 복잡도를 0.0에서 1.0 사이의 점수로 평가해주세요.

질문: {query}

평가 기준:
- 0.0-0.3: 단순 질문 (직접 답변 가능, 예: "오늘 날씨는?")
- 0.4-0.6: 중간 복잡도 (일부 추론 필요, 예: "iPhone 15의 주요 기능은?")
- 0.7-1.0: 높은 복잡도 (여러 단계 추론 필요, 예: "Apple CEO의 이전 회사는?")

복잡도가 높은 질문의 특징:
1. 여러 개체 간의 관계를 추론해야 함
2. "~의 ~", "~가 만든 ~" 등 연쇄적 관계 포함
3. 중간 단계의 정보 수집이 필요
4. 비교나 분석을 위해 여러 정보 필요

다음 JSON 형식으로만 답변하세요:
{{
  "complexity_score": 0.0-1.0 사이의 숫자,
  "reason": "점수를 부여한 이유 (한 문장)"
}}""",
            "en": f"""Evaluate the complexity of the following question on a scale from 0.0 to 1.0.

Question: {query}

Evaluation criteria:
- 0.0-0.3: Simple question (directly answerable, e.g., "What's the weather today?")
- 0.4-0.6: Medium complexity (requires some reasoning, e.g., "What are the main features of iPhone 15?")
- 0.7-1.0: High complexity (requires multi-step reasoning, e.g., "What company did Apple's CEO work for previously?")

Characteristics of high-complexity questions:
1. Requires reasoning about relationships between multiple entities
2. Contains chained relationships like "X's Y", "Y created by X"
3. Requires intermediate information gathering
4. Needs multiple pieces of information for comparison or analysis

Respond ONLY in this JSON format:
{{
  "complexity_score": a number between 0.0 and 1.0,
  "reason": "reason for the score (one sentence)"
}}""",
        }

        prompt = prompts.get(language, prompts["en"])

        try:
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            response_text = extract_text_from_response(response).strip()

            # JSON 파싱
            # LLM이 ```json ... ``` 형식으로 반환할 수 있으므로 처리
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0].strip()

            data = json.loads(response_text)
            complexity_score = float(data.get("complexity_score", 0.5))
            reason = data.get("reason", "No reason provided")

            return complexity_score, reason

        except Exception as e:
            logger.error(f"Error assessing complexity: {e}", exc_info=True)
            # 기본값 반환 (안전하게 낮은 복잡도로 처리)
            return 0.5, f"Error during assessment: {str(e)}"

    async def _generate_sub_questions(
        self,
        query: str,
        session_id: str,
        user_id: str,
        language: str,
    ) -> List[SubQuestion]:
        """LLM을 사용하여 서브질문 생성

        이 메서드는 멀티홉 검색의 핵심입니다.
        어떻게 질문을 분해할지 결정하는 프롬프트가 전체 시스템의 품질을 결정합니다.

        TODO: 사용자가 프롬프트 작성
        """
        llm = create_tracked_llm(session_id=session_id, user_id=user_id)

        # TODO: 여기에 프롬프트를 작성해주세요
        #
        # 프롬프트 작성 가이드라인:
        # 1. Few-shot 예시를 포함하여 LLM이 원하는 형식을 이해하도록 함
        # 2. 의존성 관계를 명확히 표현하도록 지시
        # 3. JSON 형식으로 구조화된 출력 요구
        # 4. 질문 유형(QuestionType) 지정 요청
        #
        # 출력 형식 예시:
        # {
        #   "sub_questions": [
        #     {
        #       "id": "q1",
        #       "query": "아이폰을 만든 회사는?",
        #       "query_template": "아이폰을 만든 회사는?",
        #       "depends_on": [],
        #       "question_type": "factual",
        #       "reasoning": "최종 답변을 위해 먼저 회사를 찾아야 함",
        #       "expected_answer_type": "entity"
        #     },
        #     {
        #       "id": "q2",
        #       "query": "{q1.answer}의 CEO는?",
        #       "query_template": "{q1.answer}의 CEO는?",
        #       "depends_on": ["q1"],
        #       "question_type": "relational",
        #       "reasoning": "회사를 알았으니 CEO를 찾음",
        #       "expected_answer_type": "entity"
        #     }
        #   ]
        # }

        prompts = {
            "ko": f"""다음 질문을 서브질문들로 분해하여 단계적으로 답변할 수 있도록 해주세요.

원본 질문: {query}

서브질문 생성 지침:
1. 질문을 단계별로 분해하세요 (2-5개의 서브질문)
2. 각 서브질문은 이전 질문의 답변에 의존할 수 있습니다
3. 의존성이 있는 경우 query_template에서 {{qN.answer}} 형식으로 참조하세요
4. 각 질문의 유형을 지정하세요 (factual, relational, comparative, temporal, spatial)
5. 질문은 구체적이고 검색 가능해야 합니다

예시:
질문: "아이폰을 개발한 사람의 모교 위치는?"
분해:
- q1: "아이폰을 개발한 주요 인물은?" (depends_on: [], factual)
- q2: "{{q1.answer}}의 출신 대학은?" (depends_on: ["q1"], relational)
- q3: "{{q2.answer}}의 위치는?" (depends_on: ["q2"], spatial)

다음 JSON 형식으로만 답변하세요:
{{
  "sub_questions": [
    {{
      "id": "q1",
      "query": "첫 번째 서브질문",
      "query_template": "첫 번째 서브질문",
      "depends_on": [],
      "question_type": "factual|relational|comparative|temporal|spatial",
      "reasoning": "이 질문이 왜 필요한지",
      "expected_answer_type": "entity|yes_no|number|date|location|description"
    }}
  ]
}}""",
            "en": f"""Decompose the following question into sub-questions that can be answered step-by-step.

Original Question: {query}

Sub-question generation guidelines:
1. Break down the question into steps (2-5 sub-questions)
2. Each sub-question can depend on answers from previous questions
3. Use {{qN.answer}} format in query_template to reference dependencies
4. Specify the type of each question (factual, relational, comparative, temporal, spatial)
5. Questions should be specific and searchable

Example:
Question: "Where is the alma mater of the person who developed the iPhone?"
Breakdown:
- q1: "Who is the main person who developed the iPhone?" (depends_on: [], factual)
- q2: "What is {{q1.answer}}'s alma mater?" (depends_on: ["q1"], relational)
- q3: "Where is {{q2.answer}} located?" (depends_on: ["q2"], spatial)

Respond ONLY in this JSON format:
{{
  "sub_questions": [
    {{
      "id": "q1",
      "query": "first sub-question",
      "query_template": "first sub-question",
      "depends_on": [],
      "question_type": "factual|relational|comparative|temporal|spatial",
      "reasoning": "why this question is needed",
      "expected_answer_type": "entity|yes_no|number|date|location|description"
    }}
  ]
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
            sub_questions_data = data.get("sub_questions", [])

            # SubQuestion 객체로 변환
            sub_questions = []
            for sq_data in sub_questions_data:
                sub_question = SubQuestion(
                    id=sq_data.get("id", f"q{len(sub_questions) + 1}"),
                    query=sq_data.get("query", ""),
                    query_template=sq_data.get("query_template", sq_data.get("query", "")),
                    depends_on=sq_data.get("depends_on", []),
                    question_type=QuestionType(sq_data.get("question_type", "factual")),
                    reasoning=sq_data.get("reasoning", ""),
                    expected_answer_type=sq_data.get("expected_answer_type", "entity"),
                )
                sub_questions.append(sub_question)

            logger.info(f"Generated {len(sub_questions)} sub-questions")
            return sub_questions

        except Exception as e:
            logger.error(f"Error generating sub-questions: {e}", exc_info=True)
            return []

    def _validate_dependencies(self, sub_questions: List[SubQuestion]) -> bool:
        """의존성 그래프 검증 (순환 참조 체크)

        Args:
            sub_questions: 서브질문 리스트

        Returns:
            유효한 DAG이면 True, 순환 참조 발견 시 False
        """
        # 질문 ID 집합
        question_ids = {q.id for q in sub_questions}

        # 1. 모든 의존성 ID가 유효한지 확인
        for question in sub_questions:
            for dep_id in question.depends_on:
                if dep_id not in question_ids:
                    logger.error(
                        f"Invalid dependency: {question.id} depends on non-existent {dep_id}"
                    )
                    return False

        # 2. 순환 참조 체크 (DFS 기반)
        visited = set()
        rec_stack = set()  # 재귀 스택

        def has_cycle(question_id: str) -> bool:
            """DFS로 순환 참조 탐지"""
            visited.add(question_id)
            rec_stack.add(question_id)

            # 이 질문이 의존하는 질문들 탐색
            question = next((q for q in sub_questions if q.id == question_id), None)
            if question:
                for dep_id in question.depends_on:
                    # 아직 방문 안 했으면 재귀 탐색
                    if dep_id not in visited:
                        if has_cycle(dep_id):
                            return True
                    # 재귀 스택에 있으면 순환 참조
                    elif dep_id in rec_stack:
                        logger.error(
                            f"Circular dependency detected: {question_id} -> {dep_id}"
                        )
                        return True

            rec_stack.remove(question_id)
            return False

        # 모든 노드에서 순환 체크
        for question in sub_questions:
            if question.id not in visited:
                if has_cycle(question.id):
                    return False

        return True

    def _topological_sort(self, sub_questions: List[SubQuestion]) -> List[str]:
        """위상 정렬로 실행 순서 결정

        Args:
            sub_questions: 서브질문 리스트

        Returns:
            실행 순서 (질문 ID 리스트)
        """
        # 진입 차수 계산
        in_degree = {q.id: len(q.depends_on) for q in sub_questions}

        # 진입 차수가 0인 노드들로 시작
        queue = [q.id for q in sub_questions if in_degree[q.id] == 0]
        result = []

        while queue:
            # 큐에서 노드 추출
            current_id = queue.pop(0)
            result.append(current_id)

            # 이 노드에 의존하는 노드들의 진입 차수 감소
            for question in sub_questions:
                if current_id in question.depends_on:
                    in_degree[question.id] -= 1
                    if in_degree[question.id] == 0:
                        queue.append(question.id)

        logger.info(f"Execution order: {' -> '.join(result)}")
        return result
