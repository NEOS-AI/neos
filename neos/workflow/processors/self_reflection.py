"""Self-Reflection Processor (Phase 2.6)

통합된 결과를 최종 응답 생성 전에 검토합니다:
1. 추론 오류: 논리적 불일치, 비약
2. 미지원 주장: 검색 결과에 근거 없는 진술
3. 커버리지 gap: 분류된 sub_topics 중 미다뤄진 항목
4. 개선 제안: 더 나은 결과를 위한 추가 검색 방향
"""

import logging
from typing import Dict, Any, List

from neos.config.settings import settings
from ..state import AgentState

logger = logging.getLogger(__name__)


class SelfReflectionProcessor:
    """최종 응답 전 자기 성찰 분석

    quality_validator 이후, response_generator 이전에 실행됩니다.
    심각한 이슈 발견 시 reflection_result에 기록하여
    response_generator가 참고할 수 있도록 합니다.
    """

    async def reflect(self, state: AgentState) -> Dict[str, Any]:
        """통합 결과에 대한 self-reflection 수행"""
        integrated = state.get("integrated_results") or {}
        search_results = state.get("search_results", [])
        classification = state.get("query_classification") or {}
        sub_topics = classification.get("sub_topics", [])

        # 경량 쿼리는 reflection skip
        complexity = classification.get("complexity_score", 0.0)
        if complexity < 0.4 and len(search_results) < 3:
            logger.debug("Self-reflection skipped (low complexity)")
            state["reflection_result"] = {"skipped": True, "reason": "low_complexity"}
            return state

        try:
            reflection = await self._perform_reflection(
                query=state.get("original_query", ""),
                integrated=integrated,
                search_results=search_results,
                sub_topics=sub_topics,
                language=state.get("detected_language", "en"),
            )
            state["reflection_result"] = reflection
            logger.info(
                f"Self-reflection completed: "
                f"{len(reflection.get('issues', []))} issues found, "
                f"{len(reflection.get('coverage_gaps', []))} coverage gaps"
            )
        except Exception as e:
            logger.warning(f"Self-reflection failed: {e}")
            state["reflection_result"] = {"skipped": True, "reason": f"error: {e}"}

        return state

    async def _perform_reflection(
        self,
        query: str,
        integrated: Dict[str, Any],
        search_results: List,
        sub_topics: List[str],
        language: str,
    ) -> Dict[str, Any]:
        """LLM 기반 self-reflection 수행"""
        from neos.utils.llm_factory import create_llm

        llm = create_llm(
            model=getattr(settings, "QUERY_CLASSIFIER_LLM_MODEL", "claude-haiku-4-5-20251001"),
            temperature=0.0,
            max_tokens=800,
            request_timeout=15,
        )

        # 검색 결과 요약
        sources_summary = ""
        for sr in search_results[:5]:
            title = getattr(sr, "title", "")
            content = getattr(sr, "content", "")[:200]
            sources_summary += f"- {title}: {content}\n"

        prompt = f"""Analyze the following research results for potential issues.

Query: {query}
Expected sub-topics: {', '.join(sub_topics) if sub_topics else 'not specified'}

Sources found:
{sources_summary}

Integrated summary: {str(integrated)[:1000]}

Identify:
1. ISSUES: Any unsupported claims, logical errors, or contradictions (list each as a brief string)
2. COVERAGE_GAPS: Sub-topics from the query that aren't addressed by the results
3. SUGGESTIONS: 1-2 brief suggestions for improving the response

Return a JSON object with keys: issues (list), coverage_gaps (list), suggestions (list), overall_quality (float 0-1)
Return ONLY valid JSON."""

        response = await llm.ainvoke(prompt)
        content = response.content if hasattr(response, "content") else str(response)

        # JSON 파싱
        import json
        try:
            text = content.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()
            result = json.loads(text)
            return {
                "issues": result.get("issues", []),
                "coverage_gaps": result.get("coverage_gaps", []),
                "suggestions": result.get("suggestions", []),
                "overall_quality": float(result.get("overall_quality", 0.7)),
                "skipped": False,
            }
        except (json.JSONDecodeError, ValueError):
            return {
                "issues": [],
                "coverage_gaps": [],
                "suggestions": [],
                "overall_quality": 0.7,
                "skipped": False,
                "raw_response": content[:500],
            }
