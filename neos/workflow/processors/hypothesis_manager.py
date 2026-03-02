"""Hypothesis-Driven Research Manager (Phase 2.5)

복잡한 연구 쿼리에 대해 경쟁 가설을 생성하고,
각 가설별 독립 검색 분기를 실행한 후 증거를 종합합니다.

연구 흐름:
1. 쿼리에서 2-3개 경쟁 가설 생성
2. 각 가설별 독립 검색 분기 실행
3. 증거 수집 후 가설 평가 및 종합
"""

import json
import logging
from typing import Dict, Any, List

from neos.config.settings import settings
from ..state import AgentState

logger = logging.getLogger(__name__)


class HypothesisManager:
    """가설 기반 연구 관리자

    DEEP_RESEARCH/COMPLEX_ANALYSIS + high complexity 쿼리에서 활성화됩니다.
    """

    async def generate_hypotheses(
        self,
        query: str,
        classification: Dict[str, Any] = None,
    ) -> List[Dict[str, Any]]:
        """쿼리에서 경쟁 가설 2-3개 생성

        Returns:
            List of hypothesis dicts:
              - id: "H1", "H2", "H3"
              - hypothesis: 가설 진술
              - search_query: 가설 검증을 위한 검색 쿼리
              - evidence_for: [] (나중에 채워짐)
              - evidence_against: [] (나중에 채워짐)
              - confidence: 0.0 (나중에 평가)
        """
        from neos.utils.llm_factory import create_llm

        llm = create_llm(
            model=getattr(settings, "QUERY_CLASSIFIER_LLM_MODEL", "claude-haiku-4-5-20251001"),
            temperature=0.3,
            max_tokens=600,
            request_timeout=15,
        )

        sub_topics = ""
        if classification and classification.get("sub_topics"):
            sub_topics = f"\nRelevant sub-topics: {', '.join(classification['sub_topics'][:5])}"

        prompt = f"""Given the research query below, generate 2-3 competing hypotheses.
Each hypothesis should represent a different possible answer or perspective.

Query: {query}{sub_topics}

Return a JSON array where each element has:
- "hypothesis": the hypothesis statement
- "search_query": a search query to test this hypothesis

Return ONLY valid JSON array:"""

        try:
            response = await llm.ainvoke(prompt)
            content = response.content if hasattr(response, "content") else str(response)

            text = content.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()

            raw = json.loads(text)
            if not isinstance(raw, list):
                raw = [raw]

            hypotheses = []
            for i, h in enumerate(raw[:3]):
                hypotheses.append({
                    "id": f"H{i+1}",
                    "hypothesis": h.get("hypothesis", ""),
                    "search_query": h.get("search_query", query),
                    "evidence_for": [],
                    "evidence_against": [],
                    "confidence": 0.0,
                })

            logger.info(f"Generated {len(hypotheses)} hypotheses for: {query[:50]}")
            return hypotheses

        except Exception as e:
            logger.warning(f"Hypothesis generation failed: {e}")
            return [{
                "id": "H1",
                "hypothesis": query,
                "search_query": query,
                "evidence_for": [],
                "evidence_against": [],
                "confidence": 0.0,
            }]

    async def evaluate_hypotheses(
        self,
        hypotheses: List[Dict[str, Any]],
        search_results: List,
    ) -> Dict[str, Any]:
        """검색 결과를 기반으로 가설 평가 및 종합

        Returns:
            - evaluated_hypotheses: 평가된 가설 리스트
            - strongest: 가장 강한 가설 ID
            - synthesis: 종합 분석 텍스트
        """
        from neos.utils.llm_factory import create_llm

        llm = create_llm(
            model=getattr(settings, "QUERY_CLASSIFIER_LLM_MODEL", "claude-haiku-4-5-20251001"),
            temperature=0.0,
            max_tokens=800,
            request_timeout=15,
        )

        # 검색 결과 요약
        results_text = ""
        for sr in search_results[:10]:
            title = getattr(sr, "title", "")
            content = getattr(sr, "content", "")[:200]
            results_text += f"- {title}: {content}\n"

        hypotheses_text = "\n".join(
            f"{h['id']}: {h['hypothesis']}" for h in hypotheses
        )

        prompt = f"""Evaluate these competing hypotheses against the search evidence.

Hypotheses:
{hypotheses_text}

Evidence from search:
{results_text}

Return JSON with:
- "evaluations": array of {{"id": "H1", "confidence": 0.0-1.0, "key_evidence": "brief summary"}}
- "strongest": id of the strongest hypothesis
- "synthesis": 2-3 sentence balanced synthesis

Return ONLY valid JSON:"""

        try:
            response = await llm.ainvoke(prompt)
            content = response.content if hasattr(response, "content") else str(response)

            text = content.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()

            result = json.loads(text)

            # 가설에 평가 결과 반영
            evals = {e["id"]: e for e in result.get("evaluations", [])}
            for h in hypotheses:
                if h["id"] in evals:
                    h["confidence"] = float(evals[h["id"]].get("confidence", 0.5))
                    h["evidence_for"] = [evals[h["id"]].get("key_evidence", "")]

            return {
                "evaluated_hypotheses": hypotheses,
                "strongest": result.get("strongest", hypotheses[0]["id"] if hypotheses else ""),
                "synthesis": result.get("synthesis", ""),
            }

        except Exception as e:
            logger.warning(f"Hypothesis evaluation failed: {e}")
            return {
                "evaluated_hypotheses": hypotheses,
                "strongest": hypotheses[0]["id"] if hypotheses else "",
                "synthesis": "",
            }
