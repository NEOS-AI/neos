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

            # Phase 4.1: 탐지된 모순에 대해 LLM judge 자동 해결
            if result.get("contradictions") and checker.contradictions:
                await self._resolve_contradictions(result, checker)

            # Phase 3.2: 증거 그래프에 영구 저장
            if getattr(settings, "EVIDENCE_GRAPH_ENABLED", False):
                await self._persist_to_evidence_graph(
                    result, state.get("user_id", ""), state.get("session_id", "")
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

    async def _resolve_contradictions(
        self, result: Dict[str, Any], checker
    ) -> None:
        """Phase 4.1: 모순 자동 해결 — LLM judge 호출"""
        try:
            from neos.services.contradiction_resolver import ContradictionResolver

            resolver = ContradictionResolver()
            resolved_contradictions = await resolver.resolve_batch(
                checker.contradictions
            )

            # result dict에 해결 정보 반영
            resolution_summaries = []
            for c in resolved_contradictions:
                summary = resolver.format_resolution_summary(c)
                if summary:
                    resolution_summaries.append(summary)

            if resolution_summaries:
                result["contradiction_resolutions"] = resolution_summaries
                logger.info(
                    f"[FactCheck] Resolved {len(resolution_summaries)} contradictions"
                )

            # result["contradictions"] dict에도 resolution 정보 추가
            for i, c in enumerate(resolved_contradictions):
                if i < len(result.get("contradictions", [])):
                    result["contradictions"][i]["resolution_status"] = c.resolution_status
                    result["contradictions"][i]["resolution_reasoning"] = c.resolution_reasoning
                    result["contradictions"][i]["resolution_confidence"] = c.resolution_confidence

        except Exception as e:
            logger.warning(f"[FactCheck] Contradiction resolution failed (ignored): {e}")

    async def _persist_to_evidence_graph(
        self, result: Dict[str, Any], user_id: str, session_id: str
    ) -> None:
        """Phase 3.2: fact-check 결과를 evidence graph에 영구 저장"""
        try:
            from neos.services.evidence_graph_service import evidence_graph_service

            claim_id_map = {}  # claim_text -> claim_id

            # 주장 저장
            for claim in result.get("claims", []):
                claim_id = await evidence_graph_service.persist_claim(
                    claim_text=claim.get("text", ""),
                    claim_type=claim.get("claim_type", "fact"),
                    confidence=claim.get("confidence", 0.5),
                    verification_status=claim.get("verification_status", "unverified"),
                    user_id=user_id,
                    session_id=session_id,
                    source_url=claim.get("source_url"),
                    source_title=claim.get("source_title"),
                )
                if claim_id:
                    claim_id_map[claim.get("text", "")] = claim_id

            # 모순 저장 (Phase 4.1: resolution 정보 포함)
            for contradiction in result.get("contradictions", []):
                c1_text = contradiction.get("claim1_text", "")
                c2_text = contradiction.get("claim2_text", "")
                c1_id = claim_id_map.get(c1_text)
                c2_id = claim_id_map.get(c2_text)

                if c1_id and c2_id:
                    resolution_status = contradiction.get(
                        "resolution_status", "unresolved"
                    )
                    await evidence_graph_service.persist_contradiction(
                        claim_id_1=c1_id,
                        claim_id_2=c2_id,
                        contradiction_type=contradiction.get("type", "factual"),
                        severity=contradiction.get("severity", "medium"),
                        explanation=contradiction.get("description", ""),
                        resolution_status=resolution_status,
                        resolution_reasoning=contradiction.get("resolution_reasoning"),
                        resolution_confidence=contradiction.get("resolution_confidence", 0.0),
                        resolved_by="llm_judge" if resolution_status == "resolved" else None,
                    )

            logger.info(
                f"[EvidenceGraph] 저장 완료: claims={len(claim_id_map)}, "
                f"contradictions={len(result.get('contradictions', []))}"
            )

        except Exception as e:
            logger.warning(f"[EvidenceGraph] 저장 실패 (무시): {e}")
