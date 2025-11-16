"""Fact checking and cross-validation of information across sources.

Detects contradictions, verifies claims, and assesses evidence strength.
"""

from typing import Dict, Any, List, Optional, Callable
import re
import logging
from collections import defaultdict

logger = logging.getLogger(__name__)


class Claim:
    """Represents a factual claim extracted from a source."""

    def __init__(
        self,
        text: str,
        source_url: str,
        source_title: str,
        claim_type: str = "general",
        confidence: float = 0.5,
    ):
        """Initialize claim.

        Args:
            text: Claim text
            source_url: Source URL
            source_title: Source title
            claim_type: Type of claim (fact, opinion, statistic, etc.)
            confidence: Confidence in claim (0-1)
        """
        self.text = text
        self.source_url = source_url
        self.source_title = source_title
        self.claim_type = claim_type
        self.confidence = confidence
        self.verification_status = "unverified"
        self.supporting_sources = []
        self.contradicting_sources = []


class Contradiction:
    """Represents a contradiction between sources."""

    def __init__(
        self,
        claim1: Claim,
        claim2: Claim,
        contradiction_type: str,
        severity: str = "medium",
    ):
        """Initialize contradiction.

        Args:
            claim1: First claim
            claim2: Contradicting claim
            contradiction_type: Type of contradiction
            severity: Severity level (low, medium, high)
        """
        self.claim1 = claim1
        self.claim2 = claim2
        self.contradiction_type = contradiction_type
        self.severity = severity


class FactChecker:
    """Fact checker for cross-validating information across sources."""

    def __init__(self):
        """Initialize fact checker."""
        self.claims = []
        self.contradictions = []
        self.verification_results = []

        self.stats = {
            "total_claims": 0,
            "verified_claims": 0,
            "contradictions_found": 0,
            "numerical_inconsistencies": 0,
        }

    async def verify_sources(
        self,
        sources: List[Dict[str, Any]],
        llm_callable: Callable,
        language: str = "en",
    ) -> Dict[str, Any]:
        """Verify facts across multiple sources.

        Args:
            sources: List of source dictionaries
            llm_callable: LLM callable for analysis
            language: Language code

        Returns:
            Verification results dictionary
        """
        try:
            logger.info(f"[FactChecker] Verifying facts across {len(sources)} sources...")

            # Step 1: Extract claims from sources
            claims = await self._extract_claims_batch(
                sources[:30],  # Limit to avoid overwhelming
                llm_callable,
                language
            )

            self.claims.extend(claims)
            self.stats["total_claims"] = len(self.claims)

            logger.info(f"[FactChecker] Extracted {len(claims)} claims")

            # Step 2: Detect contradictions
            contradictions = await self._detect_contradictions(
                claims,
                llm_callable,
                language
            )

            self.contradictions.extend(contradictions)
            self.stats["contradictions_found"] = len(self.contradictions)

            logger.info(
                f"[FactChecker] Found {len(contradictions)} potential contradictions"
            )

            # Step 3: Verify numerical data
            numerical_issues = await self._verify_numerical_consistency(
                sources,
                llm_callable,
                language
            )

            self.stats["numerical_inconsistencies"] = len(numerical_issues)

            # Step 4: Generate verification report
            report = await self._generate_verification_report(
                claims,
                contradictions,
                numerical_issues,
                llm_callable,
                language
            )

            return {
                "claims": [self._claim_to_dict(c) for c in claims],
                "contradictions": [self._contradiction_to_dict(c) for c in contradictions],
                "numerical_issues": numerical_issues,
                "report": report,
                "stats": self.stats.copy(),
            }

        except Exception as e:
            logger.error(f"[FactChecker] Verification error: {e}")
            return {
                "claims": [],
                "contradictions": [],
                "numerical_issues": [],
                "report": "Fact checking pending",
                "stats": self.stats.copy(),
            }

    async def _extract_claims_batch(
        self,
        sources: List[Dict[str, Any]],
        llm_callable: Callable,
        language: str,
    ) -> List[Claim]:
        """Extract claims from sources.

        Args:
            sources: List of sources
            llm_callable: LLM callable
            language: Language code

        Returns:
            List of extracted claims
        """
        claims = []

        # Sample sources to extract claims from
        sample = sources[:10]  # Limit to 10 sources

        for source in sample:
            source_claims = await self._extract_claims_from_source(
                source,
                llm_callable,
                language
            )
            claims.extend(source_claims)

        return claims

    async def _extract_claims_from_source(
        self,
        source: Dict[str, Any],
        llm_callable: Callable,
        language: str,
    ) -> List[Claim]:
        """Extract claims from a single source.

        Args:
            source: Source dictionary
            llm_callable: LLM callable
            language: Language code

        Returns:
            List of claims
        """
        try:
            content = source.get("content", "")[:1000]  # Limit content length
            title = source.get("title", "")
            url = source.get("url", "")

            if not content:
                return []

            # Build prompt for claim extraction
            if language == "ko":
                prompt = f"""다음 텍스트에서 검증 가능한 사실적 주장을 추출하세요.

텍스트: {content}

각 주장을 한 줄로 작성하고, 유형을 표시하세요:
[FACT] 사실적 주장
[STAT] 통계/수치
[OPINION] 의견

최대 5개의 주요 주장만 추출하세요."""
            else:
                prompt = f"""Extract verifiable factual claims from the following text.

Text: {content}

Format each claim on one line with type:
[FACT] Factual claim
[STAT] Statistical/numerical claim
[OPINION] Opinion or interpretation

Extract up to 5 main claims only."""

            from langchain.schema import HumanMessage
            response = await llm_callable([HumanMessage(content=prompt)])

            # Parse claims from response
            claims = []
            for line in response.content.strip().split('\n'):
                line = line.strip()
                if not line:
                    continue

                # Extract claim type and text
                claim_type = "general"
                claim_text = line

                if line.startswith('[FACT]'):
                    claim_type = "fact"
                    claim_text = line[6:].strip()
                elif line.startswith('[STAT]'):
                    claim_type = "statistic"
                    claim_text = line[6:].strip()
                elif line.startswith('[OPINION]'):
                    claim_type = "opinion"
                    claim_text = line[9:].strip()

                if len(claim_text) > 20:  # Filter very short claims
                    claims.append(Claim(
                        text=claim_text,
                        source_url=url,
                        source_title=title,
                        claim_type=claim_type,
                        confidence=0.7 if claim_type == "fact" else 0.5
                    ))

            return claims[:5]  # Limit to 5 claims per source

        except Exception as e:
            logger.warning(f"[FactChecker] Claim extraction error: {e}")
            return []

    async def _detect_contradictions(
        self,
        claims: List[Claim],
        llm_callable: Callable,
        language: str,
    ) -> List[Contradiction]:
        """Detect contradictions between claims.

        Args:
            claims: List of claims
            llm_callable: LLM callable
            language: Language code

        Returns:
            List of contradictions
        """
        contradictions = []

        if len(claims) < 2:
            return contradictions

        try:
            # Group claims by topic for efficient comparison
            # For simplicity, compare all pairs (could be optimized)
            claims_text = "\n".join([
                f"{i+1}. [{c.claim_type.upper()}] {c.text} (from: {c.source_title})"
                for i, c in enumerate(claims[:20])  # Limit to 20 claims
            ])

            if language == "ko":
                prompt = f"""다음 주장들 중 서로 모순되는 것이 있는지 확인하세요:

{claims_text}

모순을 발견하면 다음 형식으로 작성:
CONTRADICTION: [번호1] vs [번호2]
TYPE: [직접적/부분적/수치적]
SEVERITY: [high/medium/low]

모순이 없으면 "No contradictions found"라고 작성하세요."""
            else:
                prompt = f"""Identify any contradictions among these claims:

{claims_text}

If contradictions found, format as:
CONTRADICTION: [number1] vs [number2]
TYPE: [direct/partial/numerical]
SEVERITY: [high/medium/low]

If no contradictions, write "No contradictions found"."""

            from langchain.schema import HumanMessage
            response = await llm_callable([HumanMessage(content=prompt)])

            # Parse contradictions
            lines = response.content.strip().split('\n')
            i = 0
            while i < len(lines):
                line = lines[i].strip()

                if line.startswith('CONTRADICTION:'):
                    # Extract claim numbers
                    match = re.search(r'\[(\d+)\]\s*vs\s*\[(\d+)\]', line)
                    if match:
                        idx1 = int(match.group(1)) - 1
                        idx2 = int(match.group(2)) - 1

                        # Get type and severity
                        contradiction_type = "unknown"
                        severity = "medium"

                        if i + 1 < len(lines) and lines[i+1].startswith('TYPE:'):
                            type_match = re.search(r'TYPE:\s*\[?(\w+)\]?', lines[i+1])
                            if type_match:
                                contradiction_type = type_match.group(1)
                            i += 1

                        if i + 1 < len(lines) and lines[i+1].startswith('SEVERITY:'):
                            sev_match = re.search(r'SEVERITY:\s*\[?(\w+)\]?', lines[i+1])
                            if sev_match:
                                severity = sev_match.group(1)
                            i += 1

                        # Create contradiction
                        if 0 <= idx1 < len(claims) and 0 <= idx2 < len(claims):
                            contradictions.append(Contradiction(
                                claim1=claims[idx1],
                                claim2=claims[idx2],
                                contradiction_type=contradiction_type,
                                severity=severity
                            ))

                i += 1

        except Exception as e:
            logger.warning(f"[FactChecker] Contradiction detection error: {e}")

        return contradictions

    async def _verify_numerical_consistency(
        self,
        sources: List[Dict[str, Any]],
        llm_callable: Callable,
        language: str,
    ) -> List[Dict[str, Any]]:
        """Verify numerical data consistency.

        Args:
            sources: List of sources
            llm_callable: LLM callable
            language: Language code

        Returns:
            List of numerical inconsistencies
        """
        issues = []

        try:
            # Extract numerical claims
            numerical_data = []
            for source in sources[:10]:
                content = source.get("content", "")
                title = source.get("title", "")

                # Find numbers in content (simple regex)
                numbers = re.findall(r'\d+(?:\.\d+)?%?', content[:500])
                if numbers:
                    numerical_data.append({
                        "source": title,
                        "numbers": numbers[:5],  # Top 5 numbers
                    })

            # Compare numerical data (simplified)
            # In production, would use more sophisticated analysis

        except Exception as e:
            logger.warning(f"[FactChecker] Numerical verification error: {e}")

        return issues

    async def _generate_verification_report(
        self,
        claims: List[Claim],
        contradictions: List[Contradiction],
        numerical_issues: List[Dict[str, Any]],
        llm_callable: Callable,
        language: str,
    ) -> str:
        """Generate fact verification report.

        Args:
            claims: List of claims
            contradictions: List of contradictions
            numerical_issues: List of numerical issues
            llm_callable: LLM callable
            language: Language code

        Returns:
            Report text
        """
        try:
            # Build summary
            summary = f"""
Fact Verification Summary:
- Total Claims Analyzed: {len(claims)}
- Factual Claims: {sum(1 for c in claims if c.claim_type == 'fact')}
- Statistical Claims: {sum(1 for c in claims if c.claim_type == 'statistic')}
- Opinion Statements: {sum(1 for c in claims if c.claim_type == 'opinion')}
- Contradictions Found: {len(contradictions)}
- High Severity: {sum(1 for c in contradictions if c.severity == 'high')}
- Medium Severity: {sum(1 for c in contradictions if c.severity == 'medium')}
- Low Severity: {sum(1 for c in contradictions if c.severity == 'low')}
"""

            # Add contradiction details
            if contradictions:
                summary += "\n## ⚠️ Contradictions Detected:\n"
                for i, contra in enumerate(contradictions[:5], 1):
                    summary += f"\n{i}. [{contra.severity.upper()}] {contra.contradiction_type}\n"
                    summary += f"   Claim A: {contra.claim1.text}\n"
                    summary += f"   Claim B: {contra.claim2.text}\n"

            return summary.strip()

        except Exception as e:
            logger.error(f"[FactChecker] Report generation error: {e}")
            return "Verification report pending"

    def _claim_to_dict(self, claim: Claim) -> Dict[str, Any]:
        """Convert claim to dictionary.

        Args:
            claim: Claim object

        Returns:
            Dictionary representation
        """
        return {
            "text": claim.text,
            "source_url": claim.source_url,
            "source_title": claim.source_title,
            "type": claim.claim_type,
            "confidence": claim.confidence,
        }

    def _contradiction_to_dict(self, contradiction: Contradiction) -> Dict[str, Any]:
        """Convert contradiction to dictionary.

        Args:
            contradiction: Contradiction object

        Returns:
            Dictionary representation
        """
        return {
            "claim1": self._claim_to_dict(contradiction.claim1),
            "claim2": self._claim_to_dict(contradiction.claim2),
            "type": contradiction.contradiction_type,
            "severity": contradiction.severity,
        }

    def get_stats(self) -> Dict[str, Any]:
        """Get fact checking statistics.

        Returns:
            Statistics dictionary
        """
        return self.stats.copy()
