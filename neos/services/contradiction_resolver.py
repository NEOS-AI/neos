"""
Active Contradiction Resolution Service (Phase 4.1)

FactChecker가 탐지한 모순에 대해 LLM judge가 소스 신뢰도, 최신성, 구체성을
평가하여 해결 판정을 생성합니다.
"""

import json
import logging
from typing import Dict, Any, Optional

from neos.config.settings import settings
from neos.agents.search_agents.hyper_deep_research.utils.fact_checker import (
    Claim,
    Contradiction,
)

logger = logging.getLogger(__name__)

# 소스 타입별 기본 신뢰도 계층
SOURCE_TRUST_HIERARCHY = {
    "academic": 0.95,      # 학술 논문 (peer-reviewed)
    "government": 0.90,    # 정부 기관 자료
    "institutional": 0.85, # 기관/연구소 보고서
    "news_major": 0.75,    # 주요 언론사
    "encyclopedia": 0.70,  # 백과사전 (Wikipedia 등)
    "news_minor": 0.60,    # 소규모 언론
    "blog": 0.40,          # 블로그, 개인 사이트
    "social": 0.30,        # 소셜 미디어
    "unknown": 0.50,       # 출처 불명
}

_JUDGE_PROMPT = """You are an impartial fact-checking judge. Two claims from different sources contradict each other. Evaluate which claim is more likely correct.

## Claim A
- Text: {claim1_text}
- Source: {claim1_source} ({claim1_url})
- Type: {claim1_type}
- Confidence: {claim1_confidence}

## Claim B
- Text: {claim2_text}
- Source: {claim2_source} ({claim2_url})
- Type: {claim2_type}
- Confidence: {claim2_confidence}

## Contradiction Type: {contradiction_type}
## Severity: {severity}

## Evaluation Criteria
1. **Source reliability**: Academic/government > major news > blog/social
2. **Recency**: More recent data generally preferred for evolving topics
3. **Specificity**: Claims with specific numbers/data > vague generalizations
4. **Corroboration**: Claims supported by multiple independent sources > single-source claims

Return ONLY a valid JSON object:
{{
  "winner": "A" or "B" or "inconclusive",
  "reasoning": "<2-3 sentence explanation of your judgment>",
  "confidence": <float 0.0-1.0>,
  "factors": {{
    "source_reliability": "A" or "B" or "equal",
    "recency": "A" or "B" or "equal" or "unknown",
    "specificity": "A" or "B" or "equal"
  }}
}}"""


class ContradictionResolver:
    """LLM judge 기반 모순 해결 서비스"""

    # severity=high만 자동 해결, medium은 선택적
    MIN_SEVERITY_FOR_AUTO_RESOLVE = "medium"

    def __init__(self):
        self._llm = None

    async def _get_llm(self):
        if self._llm is None:
            from neos.utils.llm_factory import create_llm

            self._llm = create_llm(
                temperature=0.0,
                model=settings.FAST_LLM_MODEL,
            )
        return self._llm

    def _should_resolve(self, contradiction: Contradiction) -> bool:
        """자동 해결 대상인지 판단"""
        severity_order = {"low": 0, "medium": 1, "high": 2}
        min_level = severity_order.get(self.MIN_SEVERITY_FOR_AUTO_RESOLVE, 1)
        current_level = severity_order.get(contradiction.severity, 1)
        return current_level >= min_level

    async def resolve(
        self, contradiction: Contradiction
    ) -> Contradiction:
        """
        모순을 분석하여 해결 판정을 생성합니다.

        Args:
            contradiction: 해결할 모순 객체

        Returns:
            resolution 필드가 업데이트된 Contradiction 객체
        """
        if not self._should_resolve(contradiction):
            logger.debug(
                f"[ContradictionResolver] Skipping low-severity contradiction: "
                f"{contradiction.severity}"
            )
            return contradiction

        try:
            llm = await self._get_llm()

            prompt = _JUDGE_PROMPT.format(
                claim1_text=contradiction.claim1.text,
                claim1_source=contradiction.claim1.source_title,
                claim1_url=contradiction.claim1.source_url,
                claim1_type=contradiction.claim1.claim_type,
                claim1_confidence=contradiction.claim1.confidence,
                claim2_text=contradiction.claim2.text,
                claim2_source=contradiction.claim2.source_title,
                claim2_url=contradiction.claim2.source_url,
                claim2_type=contradiction.claim2.claim_type,
                claim2_confidence=contradiction.claim2.confidence,
                contradiction_type=contradiction.contradiction_type,
                severity=contradiction.severity,
            )

            from langchain_core.messages import HumanMessage
            from neos.utils.llm_wrapper import extract_text_from_response

            response = await llm.ainvoke([HumanMessage(content=prompt)])
            text = extract_text_from_response(response)

            # JSON 파싱
            text = text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

            result = json.loads(text)
            winner = result.get("winner", "inconclusive")
            reasoning = result.get("reasoning", "")
            confidence = float(result.get("confidence", 0.0))

            # Contradiction 객체 업데이트
            if winner == "A":
                contradiction.resolution_status = "resolved"
                contradiction.winner_claim = contradiction.claim1
            elif winner == "B":
                contradiction.resolution_status = "resolved"
                contradiction.winner_claim = contradiction.claim2
            else:
                contradiction.resolution_status = "inconclusive"
                contradiction.winner_claim = None

            contradiction.resolution_reasoning = reasoning
            contradiction.resolution_confidence = confidence

            logger.info(
                f"[ContradictionResolver] Resolved ({contradiction.severity}): "
                f"winner={winner}, confidence={confidence:.2f}"
            )
            return contradiction

        except json.JSONDecodeError as e:
            logger.warning(f"[ContradictionResolver] JSON parse error: {e}")
            contradiction.resolution_status = "inconclusive"
            contradiction.resolution_reasoning = f"Judge response parse error: {e}"
            return contradiction
        except Exception as e:
            logger.warning(f"[ContradictionResolver] Resolution failed: {e}")
            contradiction.resolution_status = "unresolved"
            return contradiction

    async def resolve_batch(
        self, contradictions: list[Contradiction]
    ) -> list[Contradiction]:
        """여러 모순을 순차적으로 해결"""
        resolved = []
        for contradiction in contradictions:
            result = await self.resolve(contradiction)
            resolved.append(result)
        return resolved

    def format_resolution_summary(
        self, contradiction: Contradiction
    ) -> Optional[str]:
        """해결된 모순을 사용자 친화적 텍스트로 포맷"""
        if contradiction.resolution_status == "unresolved":
            return None

        if contradiction.resolution_status == "inconclusive":
            return (
                f"**모순 발견 (미해결)**: "
                f'"{contradiction.claim1.text[:80]}..." vs '
                f'"{contradiction.claim2.text[:80]}..."\n'
                f"  판정: 결론을 내리기 어려움 — {contradiction.resolution_reasoning}"
            )

        winner = contradiction.winner_claim
        loser = (
            contradiction.claim2
            if winner is contradiction.claim1
            else contradiction.claim1
        )
        return (
            f"**모순 해결** (확신도: {contradiction.resolution_confidence:.0%}):\n"
            f'  채택: "{winner.text[:100]}..." '
            f"(출처: {winner.source_title})\n"
            f'  기각: "{loser.text[:100]}..." '
            f"(출처: {loser.source_title})\n"
            f"  근거: {contradiction.resolution_reasoning}"
        )
