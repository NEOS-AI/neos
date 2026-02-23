"""Adaptive Research Replanner (Phase 2.4)

HyperDeepResearch의 각 검색 라운드 후 중간 결과를 기반으로 연구 계획을 재수립합니다.
LLM classification의 sub_topics (Phase 2.3)을 활용하여 커버리지 gap을 분석합니다.
"""

import logging
from typing import Dict, Any, List

from neos.config.settings import settings
from ..state import AgentState

logger = logging.getLogger(__name__)

MAX_REPLANS = 2  # 최대 재계획 횟수


class ResearchReplanner:
    """검색 결과 기반 적응형 연구 재계획

    워크플로우에서 SEARCH_ORCHESTRATOR 후 조건부로 실행되어:
    1. 현재 검색 결과와 원래 sub_topics를 비교
    2. 답변된 질문, 새 질문, 우선순위 낮출 태스크 식별
    3. PlanningAgent.revise_plan() 호출하여 계획 수정
    """

    async def evaluate_and_replan(self, state: AgentState) -> Dict[str, Any]:
        """중간 결과 평가 및 재계획"""
        replan_count = state.get("replan_count", 0)

        # 최대 재계획 횟수 초과
        if replan_count >= MAX_REPLANS:
            logger.info(f"Max replans ({MAX_REPLANS}) reached, proceeding")
            return state

        classification = state.get("query_classification") or {}
        sub_topics = classification.get("sub_topics", [])
        search_results = state.get("search_results", [])

        # sub_topics가 없거나 검색 결과가 충분하면 skip
        if not sub_topics or len(search_results) >= 10:
            return state

        try:
            analysis = await self._analyze_coverage(
                query=state.get("original_query", ""),
                sub_topics=sub_topics,
                search_results=search_results,
            )

            answered = analysis.get("answered_questions", [])
            new_questions = analysis.get("new_questions", [])
            gaps = analysis.get("coverage_gaps", [])

            state["answered_questions"] = answered
            state["replan_count"] = replan_count + 1

            if gaps:
                # 추가 검색이 필요한 gap이 있으면 remaining_questions 업데이트
                state["remaining_questions"] = new_questions + gaps
                logger.info(
                    f"Replanner: {len(answered)} answered, "
                    f"{len(gaps)} gaps, {len(new_questions)} new questions"
                )

        except Exception as e:
            logger.warning(f"Research replanning failed: {e}")

        return state

    async def _analyze_coverage(
        self,
        query: str,
        sub_topics: List[str],
        search_results: List,
    ) -> Dict[str, Any]:
        """검색 결과의 sub_topic 커버리지 분석"""
        from neos.utils.llm_factory import create_llm

        llm = create_llm(
            model=getattr(settings, "QUERY_CLASSIFIER_LLM_MODEL", "claude-haiku-4-5-20251001"),
            temperature=0.0,
            max_tokens=500,
            request_timeout=10,
        )

        # 검색 결과 요약
        results_summary = ""
        for sr in search_results[:8]:
            title = getattr(sr, "title", "")
            results_summary += f"- {title}\n"

        prompt = f"""Analyze coverage of search results against expected sub-topics.

Query: {query}
Expected sub-topics: {', '.join(sub_topics)}

Search results found:
{results_summary}

Return JSON with:
- answered_questions: list of sub-topics well covered
- coverage_gaps: list of sub-topics NOT covered
- new_questions: list of new questions discovered
Return ONLY valid JSON."""

        response = await llm.ainvoke(prompt)
        content = response.content if hasattr(response, "content") else str(response)

        import json
        try:
            text = content.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()
            return json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return {"answered_questions": [], "coverage_gaps": sub_topics, "new_questions": []}
