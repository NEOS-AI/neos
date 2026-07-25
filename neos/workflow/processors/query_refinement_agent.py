"""쿼리 개선 에이전트

RefinementChecker가 개선이 필요하다고 판단한 쿼리를
실제로 개선하는 에이전트입니다.
"""

from typing import Dict, Any, Optional
from datetime import datetime
import logging

from ..state import AgentState
from neos.utils.llm_factory import create_llm

logger = logging.getLogger(__name__)


class QueryRefinementAgent:
    """
    쿼리를 실제로 개선하는 에이전트

    기능:
    1. 오타 수정 (spell_correction)
    2. 참조 해결 (reference_resolution)
    3. 언어 표준화 (language_normalization)
    4. 쿼리 명확화 (query_clarification)
    """

    def __init__(self):
        self.max_tokens = 200  # 개선된 쿼리는 짧아야 함
        self.temperature = 0.1  # 일관성을 위해 낮은 온도

    def _get_llm(self, temperature: float = None, max_tokens: int = None):
        """LLM 인스턴스 가져오기"""
        # 자동 워크로드 — 모델을 지정하지 않아 everyday 역할 기본값으로 해석된다
        return create_llm(
            temperature=temperature or self.temperature,
            max_tokens=max_tokens or self.max_tokens,
            use_cache=True
        )

    async def refine(self, state: AgentState) -> Dict[str, Any]:
        """
        쿼리 개선 수행

        Args:
            state: 현재 워크플로우 상태

        Returns:
            업데이트할 상태 필드:
            - refined_query: str (개선된 쿼리)
            - original_query_backup: str (원본 쿼리 백업)
            - refinement_applied: List[str] (적용된 개선 항목들)
            - refinement_time_ms: int (개선 소요 시간)
        """
        # 개선이 필요없으면 건너뛰기
        if not state.get("needs_refinement", False):
            logger.info("[QueryRefinementAgent] No refinement needed, skipping")
            return {}

        original_query = state["original_query"]
        refinement_reasons = state.get("refinement_reasons", [])
        conversation_context = state.get("conversation_context", "")

        logger.info(f"[QueryRefinementAgent] Refining query: {original_query[:50]}...")
        logger.info(f"[QueryRefinementAgent] Reasons: {refinement_reasons}")

        start_time = datetime.now()

        # LLM을 사용하여 쿼리 개선
        refined_query = await self._refine_with_llm(
            query=original_query,
            reasons=refinement_reasons,
            context=conversation_context,
            detected_language=state.get("detected_language", "ko")
        )

        # 개선이 실제로 이루어졌는지 확인
        if refined_query and refined_query.strip() != original_query.strip():
            logger.info(
                f"[QueryRefinementAgent] Query refined: "
                f"'{original_query}' → '{refined_query}'"
            )

            # 원본 쿼리는 original_query에 유지되고,
            # 개선된 쿼리는 refined_query에 저장
            # 후속 노드들은 refined_query가 있으면 그것을 사용
            elapsed_ms = self._get_elapsed_ms(start_time)

            return {
                "refined_query": refined_query,
                "original_query_backup": original_query,
                "refinement_applied": refinement_reasons,
                "refinement_time_ms": elapsed_ms
            }
        else:
            logger.info("[QueryRefinementAgent] No changes needed")
            return {
                "refined_query": original_query,
                "refinement_applied": [],
                "refinement_time_ms": self._get_elapsed_ms(start_time)
            }

    async def _refine_with_llm(
        self,
        query: str,
        reasons: list,
        context: str = "",
        detected_language: str = "ko"
    ) -> str:
        """
        LLM을 사용하여 쿼리 개선

        TODO: 프롬프트를 비즈니스 요구사항에 맞게 개선하세요

        현재는 기본 프롬프트만 제공합니다.
        """
        llm = self._get_llm()

        # 개선 작업 목록 생성
        tasks = self._build_refinement_tasks(reasons)

        # 프롬프트 구성
        prompt = self._build_prompt(
            query=query,
            tasks=tasks,
            context=context,
            language=detected_language
        )

        try:
            # LLM 호출
            response = await llm.ainvoke(prompt)
            refined = response.content.strip() if hasattr(response, 'content') else str(response).strip()

            # 프롬프트 템플릿이나 불필요한 텍스트 제거
            refined = self._clean_response(refined)

            return refined

        except Exception as e:
            logger.error(f"[QueryRefinementAgent] LLM refinement failed: {e}")
            # 실패 시 원본 반환
            return query

    def _build_refinement_tasks(self, reasons: list) -> str:
        """개선 작업 목록을 자연어로 변환"""
        task_map = {
            "spell_correction": "오타를 수정하세요",
            "reference_resolution": "대명사나 참조 표현을 구체적인 명사로 대체하세요",
            "language_normalization": "특수문자와 이모티콘을 제거하고 표준 언어로 변환하세요",
            "query_clarification": "모호한 표현을 명확하게 하세요"
        }

        tasks = [task_map.get(reason, f"{reason} 개선") for reason in reasons]
        return "\n".join(f"- {task}" for task in tasks)

    def _build_prompt(
        self,
        query: str,
        tasks: str,
        context: str,
        language: str
    ) -> str:
        """
        쿼리 개선 프롬프트 구성

        TODO: 비즈니스 요구사항에 맞게 프롬프트를 개선하세요

        고려사항:
        - Few-shot 예시 추가
        - 도메인 특화 개선 규칙
        - 언어별 프롬프트 최적화
        """
        # 기본 프롬프트
        prompt = f"""당신은 사용자 쿼리를 개선하는 전문가입니다.

다음 쿼리를 개선해주세요:

**원본 쿼리**: {query}

**개선 작업**:
{tasks}
"""

        # 대화 컨텍스트가 있으면 추가
        if context:
            prompt += f"""
**대화 컨텍스트** (참조 해결에 활용):
{context[:500]}
"""

        prompt += """
**중요 지침**:
1. 원본 쿼리의 의도와 의미를 반드시 유지하세요
2. 이미 올바른 부분은 변경하지 마세요
3. 개선된 쿼리만 출력하세요 (설명이나 추가 텍스트 없이)
4. 자연스러운 {language} 표현을 사용하세요

**개선된 쿼리**:""".format(language="한국어" if language == "ko" else "English")

        return prompt

    def _clean_response(self, response: str) -> str:
        """LLM 응답에서 불필요한 텍스트 제거"""
        # 따옴표 제거
        response = response.strip('"\'`')

        # "개선된 쿼리:", "Answer:" 등의 프리픽스 제거
        prefixes = ["개선된 쿼리:", "refined query:", "answer:", "result:"]
        for prefix in prefixes:
            if response.lower().startswith(prefix):
                response = response[len(prefix):].strip()

        return response

    def _get_elapsed_ms(self, start_time: datetime) -> int:
        """경과 시간 계산 (밀리초)"""
        return int((datetime.now() - start_time).total_seconds() * 1000)
