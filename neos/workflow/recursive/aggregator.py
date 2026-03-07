"""
RecursiveAggregator: 계층별 결과 통합기

하위 태스크 결과를 bottom-up으로 통합하여 부모 태스크 맥락에서 요약합니다.
충돌/모순 정보를 감지하고 표시합니다.
"""

import json
import logging
from typing import Any, Dict, List

from neos.config.settings import settings
from neos.utils.llm_factory import LLMFactory

from .models import RecursiveTaskNode

logger = logging.getLogger(__name__)

_AGGREGATE_PROMPT = """You are a research synthesis expert. Integrate the results from multiple sub-tasks to answer the parent task.

Parent task: {parent_description}
Original research query: {original_query}

Sub-task results:
{subtask_results}

Instructions:
- Synthesize the sub-task results into a coherent, comprehensive answer for the parent task
- Preserve important details and nuances from each sub-task
- If there are contradictions between sub-task results, explicitly note them
- Structure the response clearly (use headings if appropriate)
- Focus on answering the parent task, not just summarizing sub-tasks

Provide your integrated response:"""

_CONTRADICTION_PROMPT = """Analyze these research results and identify any contradictions or inconsistencies.

Results:
{results}

Return ONLY a valid JSON object:
{{
  "has_contradictions": true/false,
  "contradictions": [
    {{
      "topic": "what the contradiction is about",
      "claim_a": "first claim",
      "claim_b": "contradicting claim"
    }}
  ]
}}"""


class RecursiveAggregator:
    """계층별 결과 통합기.

    하위 태스크 결과를 bottom-up으로 통합합니다:
    1. 각 레벨에서 하위 결과를 부모 맥락에서 요약
    2. 충돌/모순 정보 감지 및 표시
    3. 토큰 효율을 위해 각 레벨에서 결과 압축
    """

    def __init__(self):
        self._model = settings.RECURSIVE_ATOMIZER_MODEL  # Haiku (비용 절감)

    async def aggregate(
        self,
        parent_task: RecursiveTaskNode,
        child_nodes: List[RecursiveTaskNode],
        context: Dict[str, Any],
    ) -> str:
        """자식 태스크 결과를 부모 태스크 맥락에서 통합.

        Args:
            parent_task: 부모 태스크 노드
            child_nodes: 완료된 자식 태스크 목록
            context: 실행 컨텍스트

        Returns:
            통합된 결과 문자열
        """
        completed_children = [n for n in child_nodes if n.result]
        if not completed_children:
            logger.warning(f"[Aggregator] No completed children for: {parent_task.description[:50]}")
            return f"하위 태스크 결과 없음: {parent_task.description}"

        # 자식 결과가 1개이면 바로 반환 (aggregation 불필요)
        if len(completed_children) == 1:
            return completed_children[0].result or ""

        subtask_results = self._format_subtask_results(completed_children)
        original_query = context.get("original_query", parent_task.description)

        # 모순 감지 (선택적 - 결과가 3개 이상일 때)
        contradictions = []
        if len(completed_children) >= 3:
            contradictions = await self._detect_contradictions(subtask_results)

        # 통합 프롬프트 실행
        result = await self._call_llm_aggregate(
            parent_description=parent_task.description,
            original_query=original_query,
            subtask_results=subtask_results,
            contradictions=contradictions,
        )

        logger.info(
            f"[Aggregator] Aggregated {len(completed_children)} children "
            f"for '{parent_task.description[:40]}' "
            f"(contradictions={len(contradictions)})"
        )
        return result

    def _format_subtask_results(self, children: List[RecursiveTaskNode]) -> str:
        """자식 태스크 결과를 포맷팅."""
        parts = []
        for i, child in enumerate(children, 1):
            result_preview = (child.result or "결과 없음")[:800]
            parts.append(f"Sub-task {i}: {child.description}\nResult: {result_preview}")
        return "\n\n".join(parts)

    async def _call_llm_aggregate(
        self,
        parent_description: str,
        original_query: str,
        subtask_results: str,
        contradictions: List[Dict[str, Any]],
    ) -> str:
        """LLM을 호출하여 결과 통합."""
        contradiction_note = ""
        if contradictions:
            contradiction_note = "\n\nNote: The following contradictions were detected:\n"
            for c in contradictions:
                contradiction_note += f"- {c.get('topic', '')}: {c.get('claim_a', '')} vs {c.get('claim_b', '')}\n"

        prompt = _AGGREGATE_PROMPT.format(
            parent_description=parent_description,
            original_query=original_query,
            subtask_results=subtask_results + contradiction_note,
        )

        try:
            provider = "anthropic" if "claude" in self._model.lower() else settings.LLM_PROVIDER
            llm = LLMFactory.create_llm(
                provider=provider,
                model=self._model,
                temperature=0.2,
                max_tokens=3000,
            )
            response = await llm.ainvoke(prompt)
            content = response.content if hasattr(response, "content") else str(response)
            return content.strip()
        except Exception as e:
            logger.error(f"[Aggregator] LLM call failed: {e}")
            # 실패 시 자식 결과를 단순 연결
            return self._fallback_join(subtask_results)

    async def _detect_contradictions(self, results_text: str) -> List[Dict[str, Any]]:
        """결과 간 모순 탐지 (선택적 - Haiku 사용)."""
        prompt = _CONTRADICTION_PROMPT.format(results=results_text[:2000])

        try:
            provider = "anthropic" if "claude" in self._model.lower() else settings.LLM_PROVIDER
            llm = LLMFactory.create_llm(
                provider=provider,
                model=self._model,
                temperature=0.0,
                max_tokens=500,
            )
            response = await llm.ainvoke(prompt)
            content = response.content if hasattr(response, "content") else str(response)

            text = content.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()

            parsed = json.loads(text)
            if parsed.get("has_contradictions"):
                return parsed.get("contradictions", [])
            return []
        except Exception as e:
            logger.debug(f"[Aggregator] Contradiction detection failed: {e}")
            return []

    def _fallback_join(self, subtask_results: str) -> str:
        """LLM 실패 시 단순 연결 fallback."""
        return f"다음 하위 연구 결과를 종합하였습니다:\n\n{subtask_results}"
