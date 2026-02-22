"""
Fact-Check Processor — 워크플로우 그래프 노드

result_integrator와 quality_validator 사이에서 실행되어
검색 결과의 사실 정확성을 검증합니다.

조건부 실행: complexity_score >= FACT_CHECK_COMPLEXITY_THRESHOLD (기본 0.4)
경량 쿼리는 skip하여 불필요한 LLM 호출을 방지합니다.
"""

import logging
from typing import Dict, Any
from datetime import datetime

from neos.utils.llm_factory import create_llm
from neos.utils.llm_wrapper import extract_text_from_response
from neos.config.settings import settings
from ..state import AgentState

logger = logging.getLogger(__name__)


class FactCheckProcessor:
    """FactChecker를 워크플로우 노드로 감싸는 프로세서.

    기존 HyperDeepResearch의 FactChecker를 lazy import하여 사용합니다.
    """

    def __init__(self):
        pass

    def _get_llm(self):
        return create_llm(
            temperature=0.1,
            max_tokens=2000,
            use_cache=True,
        )

    async def check_facts(self, state: AgentState) -> Dict[str, Any]:
        """워크플로우 노드: 조건부 fact-checking 실행.

        Returns:
            fact_check_result, fact_check_skipped 상태 업데이트
        """
        # FACT_CHECK_ENABLED가 False면 skip
        if not settings.FACT_CHECK_ENABLED:
            logger.debug("[FactCheck] Disabled via settings")
            return {"fact_check_result": None, "fact_check_skipped": True}

        # complexity_score 기반 조건부 실행
        query_classification = state.get("query_classification") or {}
        complexity_score = float(query_classification.get("complexity_score", 0.0))

        if complexity_score < settings.FACT_CHECK_COMPLEXITY_THRESHOLD:
            logger.debug(
                f"[FactCheck] Skipping (complexity={complexity_score:.2f} < "
                f"{settings.FACT_CHECK_COMPLEXITY_THRESHOLD})"
            )
            return {"fact_check_result": None, "fact_check_skipped": True}

        search_results = state.get("search_results", [])
        if not search_results:
            logger.debug("[FactCheck] No search results to verify")
            return {"fact_check_result": None, "fact_check_skipped": True}

        logger.info(
            f"[FactCheck] Running on {len(search_results)} sources "
            f"(complexity={complexity_score:.2f})"
        )

        try:
            # Lazy import to avoid circular dependency
            from neos.agents.search_agents.hyper_deep_research.utils.fact_checker import FactChecker

            llm = self._get_llm()
            checker = FactChecker()

            # SearchResult 객체를 FactChecker가 기대하는 dict 형식으로 변환
            sources = []
            for r in search_results:
                sources.append({
                    "url": getattr(r, "url", "") or "",
                    "title": getattr(r, "title", "") or "",
                    "content": getattr(r, "content", "") or "",
                })

            detected_language = state.get("detected_language", "en")

            # FactChecker는 llm_callable([HumanMessage(content=prompt)]) 형태로 호출함
            # 따라서 messages 리스트를 그대로 전달해야 중첩 방지
            async def llm_callable(messages) -> Any:
                if isinstance(messages, list):
                    return await llm.ainvoke(messages)
                from langchain_core.messages import HumanMessage
                return await llm.ainvoke([HumanMessage(content=messages)])

            result = await checker.verify_sources(
                sources=sources,
                llm_callable=llm_callable,
                language=detected_language,
            )

            state["execution_steps"].append({
                "step": "fact_check",
                "result": (
                    f"claims={result['stats']['total_claims']}, "
                    f"contradictions={result['stats']['contradictions_found']}"
                ),
                "timestamp": datetime.now().isoformat(),
            })

            logger.info(
                f"[FactCheck] Completed: {result['stats']['total_claims']} claims, "
                f"{result['stats']['contradictions_found']} contradictions"
            )

            return {
                "fact_check_result": result,
                "fact_check_skipped": False,
            }

        except Exception as e:
            logger.error(f"[FactCheck] Error during fact-checking: {e}")
            state["execution_steps"].append({
                "step": "fact_check",
                "result": f"error: {str(e)}",
                "timestamp": datetime.now().isoformat(),
            })
            return {
                "fact_check_result": None,
                "fact_check_skipped": True,
            }
