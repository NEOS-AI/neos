"""
RecursiveVerifier: 충족도 검증기

통합된 결과가 원래 태스크 요구사항을 충족하는지 검증합니다.
기존 SelfReflectionProcessor의 gap 분석 로직을 참고하여 구현합니다.
"""

import json
import logging
from typing import Any, Dict, List

from neos.config.settings import settings
from neos.utils.llm_factory import LLMFactory

from .models import RecursiveTaskNode, extract_llm_cost

logger = logging.getLogger(__name__)

_VERIFY_PROMPT = """You are a quality assessment expert. Evaluate whether the provided answer sufficiently addresses the original task.

Original task: {task_description}
Original user query: {original_query}

Proposed answer:
{aggregated_result}

Evaluate the answer on these criteria:
1. Completeness: Does it address all aspects of the task?
2. Accuracy: Is the information factually sound?
3. Relevance: Is all content directly relevant to the task?
4. Depth: Is the level of detail appropriate?

Return ONLY a valid JSON object:
{{
  "satisfied": true/false,
  "score": 0.0-1.0,
  "gaps": ["gap1", "gap2"],  // list of missing aspects (empty if satisfied)
  "suggestion": "how to improve (empty if satisfied)"
}}

Be strict: set satisfied=true only if score >= {threshold}."""


class RecursiveVerifier:
    """충족도 검증기.

    통합 결과가 원래 태스크를 충족하는지 검증합니다.
    - threshold: WORKFLOW_MIN_QUALITY_SCORE 또는 0.65 중 더 높은 값 (R-08: 코드와 일치)
    - 검증 실패 시 gaps 목록을 반환하여 재계획에 활용
    """

    def __init__(self):
        self._model = settings.RECURSIVE_ATOMIZER_MODEL  # Haiku (비용 절감)
        self._threshold = max(
            getattr(settings, "WORKFLOW_MIN_QUALITY_SCORE", 0.4),
            0.65,  # ROMA는 최소 0.65 이상 요구
        )

    async def verify(
        self,
        original_task: RecursiveTaskNode,
        aggregated_result: str,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """결과 충족도 검증.

        Args:
            original_task: 검증 기준이 될 원본 태스크
            aggregated_result: 검증할 통합 결과
            context: 실행 컨텍스트

        Returns:
            {
                "satisfied": bool,
                "score": float,
                "gaps": List[str],
                "suggestion": str
            }
        """
        original_query = context.get("original_query", original_task.description)

        # 결과가 너무 짧으면 즉시 실패
        if len(aggregated_result.strip()) < 50:
            return {
                "satisfied": False,
                "score": 0.0,
                "gaps": ["결과가 너무 짧거나 비어있습니다"],
                "suggestion": "더 상세한 실행이 필요합니다",
            }

        try:
            result, cost = await self._call_llm(
                task_description=original_task.description,
                original_query=original_query,
                aggregated_result=aggregated_result,
            )
            # R-01: 비용 누적
            original_task.cost += cost
            cost_acc = context.get("_cost_accumulator")
            if cost_acc is not None:
                cost_acc[0] += cost
            return result
        except Exception as e:
            logger.warning(f"[Verifier] LLM call failed, using heuristic: {e}")
            return self._heuristic_verify(aggregated_result)

    async def _call_llm(
        self,
        task_description: str,
        original_query: str,
        aggregated_result: str,
    ) -> tuple[Dict[str, Any], float]:
        """LLM을 호출하여 충족도 검증. (검증 결과, 호출 비용 USD) 반환."""
        prompt = _VERIFY_PROMPT.format(
            task_description=task_description,
            original_query=original_query,
            aggregated_result=aggregated_result[:3000],
            threshold=self._threshold,
        )

        provider = "anthropic" if "claude" in self._model.lower() else settings.LLM_PROVIDER
        llm = LLMFactory.create_llm(
            provider=provider,
            model=self._model,
            temperature=0.0,
            max_tokens=500,
        )

        response = await llm.ainvoke(prompt)
        # R-01: 비용 파싱
        cost = extract_llm_cost(response, self._model, provider)
        content = response.content if hasattr(response, "content") else str(response)
        return self._parse_response(content), cost

    def _parse_response(self, content: str) -> Dict[str, Any]:
        """LLM 응답 파싱."""
        try:
            text = content.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()

            parsed = json.loads(text)
            score = float(parsed.get("score", 0.5))
            score = max(0.0, min(1.0, score))
            satisfied = parsed.get("satisfied", score >= self._threshold)
            gaps: List[str] = parsed.get("gaps", [])
            suggestion: str = parsed.get("suggestion", "")

            logger.info(
                f"[Verifier] score={score:.2f} satisfied={satisfied} "
                f"gaps={len(gaps)}"
            )

            return {
                "satisfied": satisfied,
                "score": score,
                "gaps": gaps,
                "suggestion": suggestion,
            }
        except (json.JSONDecodeError, ValueError) as e:
            logger.debug(f"[Verifier] JSON parse error: {e}")
            return self._heuristic_verify("")

    def _heuristic_verify(self, result: str) -> Dict[str, Any]:
        """LLM 실패 시 휴리스틱 검증 (길이 기반)."""
        score = min(1.0, len(result) / 500) * 0.7  # 최대 0.7점
        return {
            "satisfied": score >= self._threshold,
            "score": score,
            "gaps": [] if score >= self._threshold else ["상세 검증 불가 - 추가 분석 권장"],
            "suggestion": "",
        }
