"""Bias detection and perspective diversity analysis.

Identifies political, ideological, commercial, and other biases in sources.
Ensures balanced coverage from multiple perspectives.
"""

from typing import Dict, Any, List, Callable
import logging
from collections import defaultdict
import re

from neos.utils.llm_wrapper import extract_text_from_response

logger = logging.getLogger(__name__)


class BiasIndicator:
    """Represents a detected bias indicator."""

    def __init__(
        self,
        bias_type: str,
        description: str,
        severity: str,
        source_url: str,
        source_title: str,
        evidence: str = "",
    ):
        """Initialize bias indicator.

        Args:
            bias_type: Type of bias (political, commercial, ideological, etc.)
            description: Description of the bias
            severity: Severity level (low, medium, high)
            source_url: Source URL
            source_title: Source title
            evidence: Evidence text
        """
        self.bias_type = bias_type
        self.description = description
        self.severity = severity
        self.source_url = source_url
        self.source_title = source_title
        self.evidence = evidence


class BiasDetector:
    """Detects bias and analyzes perspective diversity in sources."""

    def __init__(self):
        """Initialize bias detector."""
        self.bias_indicators = []
        self.perspective_analysis = {}

        self.stats = {
            "sources_analyzed": 0,
            "biases_detected": 0,
            "high_severity_biases": 0,
            "perspective_diversity_score": 0.0,
        }

        # Known bias indicators by type
        self.bias_patterns = {
            "political_left": [
                r"\b(progressive|liberal|left-wing|socialist|democrat)\b",
                r"\b(social justice|equity|redistribution)\b",
            ],
            "political_right": [
                r"\b(conservative|right-wing|republican|libertarian)\b",
                r"\b(traditional values|free market|deregulation)\b",
            ],
            "commercial": [
                r"\b(sponsored|advertorial|paid partnership)\b",
                r"\b(affiliate link|product placement)\b",
            ],
            "sensational": [
                r"\b(shocking|unbelievable|you won't believe)\b",
                r"\b(breaking|exclusive|bombshell)\b",
            ],
        }

    async def analyze_bias(
        self,
        sources: List[Dict[str, Any]],
        llm_callable: Callable,
        language: str = "en",
    ) -> Dict[str, Any]:
        """Analyze bias and perspective diversity across sources.

        Args:
            sources: List of source dictionaries
            llm_callable: LLM callable for analysis
            language: Language code

        Returns:
            Bias analysis dictionary
        """
        try:
            logger.info(f"[BiasDetector] Analyzing bias across {len(sources)} sources...")

            # Step 1: Detect bias indicators
            bias_indicators = await self._detect_bias_indicators(
                sources, llm_callable, language
            )
            self.bias_indicators.extend(bias_indicators)

            # Step 2: Analyze perspective diversity
            diversity_analysis = await self._analyze_perspective_diversity(
                sources, llm_callable, language
            )

            # Step 3: Analyze geographic and temporal bias
            geographic_bias = self._analyze_geographic_bias(sources)
            temporal_bias = self._analyze_temporal_bias(sources)

            # Step 4: Calculate overall diversity score
            diversity_score = self._calculate_diversity_score(
                diversity_analysis, geographic_bias, temporal_bias
            )

            # Step 5: Generate bias report
            report = await self._generate_bias_report(
                bias_indicators,
                diversity_analysis,
                geographic_bias,
                temporal_bias,
                diversity_score,
                llm_callable,
                language,
            )

            # Update statistics
            self.stats["sources_analyzed"] = len(sources)
            self.stats["biases_detected"] = len(bias_indicators)
            self.stats["high_severity_biases"] = sum(
                1 for b in bias_indicators if b.severity == "high"
            )
            self.stats["perspective_diversity_score"] = diversity_score

            return {
                "bias_indicators": [self._indicator_to_dict(b) for b in bias_indicators],
                "diversity_analysis": diversity_analysis,
                "geographic_bias": geographic_bias,
                "temporal_bias": temporal_bias,
                "diversity_score": diversity_score,
                "report": report,
                "stats": self.stats.copy(),
            }

        except Exception as e:
            logger.error(f"[BiasDetector] Analysis error: {e}")
            return {
                "bias_indicators": [],
                "diversity_analysis": {},
                "geographic_bias": {},
                "temporal_bias": {},
                "diversity_score": 0.0,
                "report": "Bias analysis pending",
                "stats": self.stats.copy(),
            }

    async def _detect_bias_indicators(
        self,
        sources: List[Dict[str, Any]],
        llm_callable: Callable,
        language: str,
    ) -> List[BiasIndicator]:
        """Detect bias indicators in sources using LLM.

        Args:
            sources: List of sources
            llm_callable: LLM callable
            language: Language code

        Returns:
            List of bias indicators
        """
        indicators = []

        # Sample sources for analysis (limit to avoid cost)
        sample = sources[:15]

        for source in sample:
            try:
                source_indicators = await self._analyze_source_bias(
                    source, llm_callable, language
                )
                indicators.extend(source_indicators)
            except Exception as e:
                logger.warning(f"[BiasDetector] Source bias detection error: {e}")

        return indicators

    async def _analyze_source_bias(
        self,
        source: Dict[str, Any],
        llm_callable: Callable,
        language: str,
    ) -> List[BiasIndicator]:
        """Analyze bias in a single source.

        Args:
            source: Source dictionary
            llm_callable: LLM callable
            language: Language code

        Returns:
            List of bias indicators
        """
        try:
            title = source.get("title", "")
            content = source.get("content", "")[:800]
            url = source.get("url", "")

            if not content:
                return []

            # Build bias detection prompt
            if language == "ko":
                prompt = f"""다음 출처의 편향을 분석하세요:

제목: {title}
내용: {content}

다음 유형의 편향을 확인하세요:
1. [POLITICAL] 정치적 편향 (좌파/우파)
2. [COMMERCIAL] 상업적 편향 (광고, 제품 홍보)
3. [IDEOLOGICAL] 이념적 편향
4. [SENSATIONAL] 선정적 표현
5. [CONFIRMATION] 확증 편향

발견된 각 편향에 대해 다음 형식으로 작성:
BIAS: [유형]
SEVERITY: [high/medium/low]
DESCRIPTION: 한 줄 설명

편향이 없으면 "No significant bias detected"라고 작성하세요."""
            else:
                prompt = f"""Analyze bias in the following source:

Title: {title}
Content: {content}

Check for these bias types:
1. [POLITICAL] Political bias (left/right)
2. [COMMERCIAL] Commercial bias (advertising, product promotion)
3. [IDEOLOGICAL] Ideological bias
4. [SENSATIONAL] Sensationalism
5. [CONFIRMATION] Confirmation bias

For each bias found, format as:
BIAS: [type]
SEVERITY: [high/medium/low]
DESCRIPTION: One-line description

If no bias, write "No significant bias detected"."""

            from langchain_core.messages import HumanMessage
            response = await llm_callable([HumanMessage(content=prompt)])

            # Parse bias indicators
            indicators = []
            lines = extract_text_from_response(response).strip().split('\n')
            i = 0

            while i < len(lines):
                line = lines[i].strip()

                if line.startswith('BIAS:'):
                    # Extract bias type
                    bias_type_match = re.search(r'BIAS:\s*\[?(\w+)\]?', line)
                    if not bias_type_match:
                        i += 1
                        continue

                    bias_type = bias_type_match.group(1).lower()

                    # Get severity and description
                    severity = "medium"
                    description = ""

                    if i + 1 < len(lines) and lines[i+1].strip().startswith('SEVERITY:'):
                        sev_match = re.search(r'SEVERITY:\s*\[?(\w+)\]?', lines[i+1])
                        if sev_match:
                            severity = sev_match.group(1).lower()
                        i += 1

                    if i + 1 < len(lines) and lines[i+1].strip().startswith('DESCRIPTION:'):
                        desc_parts = lines[i+1].strip().split('DESCRIPTION:', 1)
                        if len(desc_parts) > 1:
                            description = desc_parts[1].strip()
                        i += 1

                    # Create indicator
                    indicators.append(BiasIndicator(
                        bias_type=bias_type,
                        description=description,
                        severity=severity,
                        source_url=url,
                        source_title=title,
                        evidence=content[:200]
                    ))

                i += 1

            return indicators

        except Exception as e:
            logger.warning(f"[BiasDetector] Source analysis error: {e}")
            return []

    async def _analyze_perspective_diversity(
        self,
        sources: List[Dict[str, Any]],
        llm_callable: Callable,
        language: str,
    ) -> Dict[str, Any]:
        """Analyze diversity of perspectives across sources.

        Args:
            sources: List of sources
            llm_callable: LLM callable
            language: Language code

        Returns:
            Perspective diversity analysis
        """
        try:
            # Sample sources
            sample = sources[:20]

            # Combine source summaries
            sources_text = "\n\n".join([
                f"{i+1}. {s.get('title', '')} - {s.get('content', '')[:200]}"
                for i, s in enumerate(sample)
            ])

            # Build diversity analysis prompt
            if language == "ko":
                prompt = f"""다음 출처들의 관점 다양성을 분석하세요:

{sources_text}

분석 항목:
1. 정치적 스펙트럼 다양성 (좌파/중도/우파)
2. 지역적 다양성
3. 전문가/일반인 관점 균형
4. 찬성/반대 의견 균형

다음 형식으로 작성:
POLITICAL_SPECTRUM: [좌파/중도/우파 분포]
GEOGRAPHIC_DIVERSITY: [high/medium/low]
EXPERT_VS_PUBLIC: [균형/편향]
PRO_VS_CON: [균형/편향]
GAPS: 부족한 관점 나열

간결하게 작성하세요."""
            else:
                prompt = f"""Analyze perspective diversity across these sources:

{sources_text}

Analyze:
1. Political spectrum diversity (left/center/right)
2. Geographic diversity
3. Expert vs. public perspective balance
4. Pro vs. con argument balance

Format as:
POLITICAL_SPECTRUM: [distribution across left/center/right]
GEOGRAPHIC_DIVERSITY: [high/medium/low]
EXPERT_VS_PUBLIC: [balanced/skewed]
PRO_VS_CON: [balanced/skewed]
GAPS: List missing perspectives

Keep it concise."""

            from langchain_core.messages import HumanMessage
            response = await llm_callable([HumanMessage(content=prompt)])

            # Parse response
            analysis = {
                "political_spectrum": "unknown",
                "geographic_diversity": "medium",
                "expert_vs_public": "unknown",
                "pro_vs_con": "unknown",
                "gaps": [],
            }

            for line in extract_text_from_response(response).strip().split('\n'):
                line = line.strip()
                if line.startswith('POLITICAL_SPECTRUM:'):
                    analysis["political_spectrum"] = line.split(':', 1)[1].strip()
                elif line.startswith('GEOGRAPHIC_DIVERSITY:'):
                    analysis["geographic_diversity"] = line.split(':', 1)[1].strip()
                elif line.startswith('EXPERT_VS_PUBLIC:'):
                    analysis["expert_vs_public"] = line.split(':', 1)[1].strip()
                elif line.startswith('PRO_VS_CON:'):
                    analysis["pro_vs_con"] = line.split(':', 1)[1].strip()
                elif line.startswith('GAPS:'):
                    gaps_text = line.split(':', 1)[1].strip()
                    analysis["gaps"] = [g.strip() for g in gaps_text.split(',')]

            return analysis

        except Exception as e:
            logger.error(f"[BiasDetector] Perspective diversity analysis error: {e}")
            return {
                "political_spectrum": "unknown",
                "geographic_diversity": "medium",
                "gaps": [],
            }

    def _analyze_geographic_bias(
        self,
        sources: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Analyze geographic bias in source selection.

        Args:
            sources: List of sources

        Returns:
            Geographic bias analysis
        """
        try:
            from urllib.parse import urlparse

            # Count domains by country/region (simplified)
            domain_counts = defaultdict(int)
            region_patterns = {
                "us": [".com", ".org", ".net"],
                "uk": [".uk", ".co.uk"],
                "eu": [".de", ".fr", ".eu"],
                "asia": [".jp", ".cn", ".kr", ".in"],
                "global": [".org", ".int"],
            }

            for source in sources:
                url = source.get("url", "")
                if url:
                    domain = urlparse(url).netloc
                    # Determine region (simplified)
                    for region, patterns in region_patterns.items():
                        if any(pattern in domain for pattern in patterns):
                            domain_counts[region] += 1
                            break

            total = sum(domain_counts.values())
            if total == 0:
                return {"bias_detected": False, "distribution": {}}

            # Calculate percentages
            distribution = {
                region: (count / total) * 100
                for region, count in domain_counts.items()
            }

            # Check for bias (>70% from one region)
            max_region = max(distribution.items(), key=lambda x: x[1])
            bias_detected = max_region[1] > 70

            return {
                "bias_detected": bias_detected,
                "dominant_region": max_region[0] if bias_detected else None,
                "distribution": distribution,
            }

        except Exception as e:
            logger.warning(f"[BiasDetector] Geographic bias analysis error: {e}")
            return {"bias_detected": False, "distribution": {}}

    def _analyze_temporal_bias(
        self,
        sources: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Analyze temporal bias (recency bias).

        Args:
            sources: List of sources

        Returns:
            Temporal bias analysis
        """
        try:
            from datetime import datetime, timedelta

            # Count sources by age
            now = datetime.now()
            age_distribution = {
                "recent_24h": 0,
                "recent_week": 0,
                "recent_month": 0,
                "older": 0,
                "unknown": 0,
            }

            for source in sources:
                published = source.get("published_date")
                if not published:
                    age_distribution["unknown"] += 1
                    continue

                try:
                    if isinstance(published, str):
                        pub_date = datetime.fromisoformat(published.replace('Z', '+00:00'))
                    else:
                        pub_date = published

                    age = now - pub_date

                    if age < timedelta(days=1):
                        age_distribution["recent_24h"] += 1
                    elif age < timedelta(days=7):
                        age_distribution["recent_week"] += 1
                    elif age < timedelta(days=30):
                        age_distribution["recent_month"] += 1
                    else:
                        age_distribution["older"] += 1

                except Exception:
                    age_distribution["unknown"] += 1

            total = len(sources)
            recent_pct = (
                (age_distribution["recent_24h"] + age_distribution["recent_week"]) / total * 100
                if total > 0 else 0
            )

            # Recency bias if >80% from last week
            bias_detected = recent_pct > 80

            return {
                "bias_detected": bias_detected,
                "recent_percentage": recent_pct,
                "distribution": age_distribution,
            }

        except Exception as e:
            logger.warning(f"[BiasDetector] Temporal bias analysis error: {e}")
            return {"bias_detected": False, "distribution": {}}

    def _calculate_diversity_score(
        self,
        diversity_analysis: Dict[str, Any],
        geographic_bias: Dict[str, Any],
        temporal_bias: Dict[str, Any],
    ) -> float:
        """Calculate overall diversity score (0-100).

        Args:
            diversity_analysis: Perspective diversity analysis
            geographic_bias: Geographic bias analysis
            temporal_bias: Temporal bias analysis

        Returns:
            Diversity score (0-100)
        """
        try:
            score = 100.0

            # Deduct for geographic bias
            if geographic_bias.get("bias_detected"):
                score -= 20

            # Deduct for temporal bias
            if temporal_bias.get("bias_detected"):
                score -= 15

            # Deduct for perspective imbalance
            if diversity_analysis.get("expert_vs_public") == "skewed":
                score -= 10
            if diversity_analysis.get("pro_vs_con") == "skewed":
                score -= 15

            # Deduct for perspective gaps
            gaps = diversity_analysis.get("gaps", [])
            score -= min(len(gaps) * 5, 20)

            return max(0.0, min(100.0, score))

        except Exception as e:
            logger.warning(f"[BiasDetector] Diversity score calculation error: {e}")
            return 50.0

    async def _generate_bias_report(
        self,
        bias_indicators: List[BiasIndicator],
        diversity_analysis: Dict[str, Any],
        geographic_bias: Dict[str, Any],
        temporal_bias: Dict[str, Any],
        diversity_score: float,
        llm_callable: Callable,
        language: str,
    ) -> str:
        """Generate bias analysis report.

        Args:
            bias_indicators: List of bias indicators
            diversity_analysis: Diversity analysis
            geographic_bias: Geographic bias analysis
            temporal_bias: Temporal bias analysis
            diversity_score: Overall diversity score
            llm_callable: LLM callable
            language: Language code

        Returns:
            Report text
        """
        try:
            # Build report
            report = f"""
Bias & Perspective Diversity Analysis:

📊 Overall Diversity Score: {diversity_score:.1f}/100

🔍 Bias Indicators Detected: {len(bias_indicators)}
"""

            # Add high-severity biases
            high_severity = [b for b in bias_indicators if b.severity == "high"]
            if high_severity:
                report += f"\n⚠️ High Severity Biases: {len(high_severity)}\n"
                for bias in high_severity[:3]:
                    report += f"   - {bias.bias_type.upper()}: {bias.description}\n"

            # Add perspective analysis
            report += "\n👁️ Perspective Diversity:\n"
            report += f"   - Political Spectrum: {diversity_analysis.get('political_spectrum', 'N/A')}\n"
            report += f"   - Geographic Diversity: {diversity_analysis.get('geographic_diversity', 'N/A')}\n"
            report += f"   - Expert vs. Public: {diversity_analysis.get('expert_vs_public', 'N/A')}\n"
            report += f"   - Pro vs. Con Balance: {diversity_analysis.get('pro_vs_con', 'N/A')}\n"

            # Add gaps
            gaps = diversity_analysis.get("gaps", [])
            if gaps:
                report += "\n🎯 Identified Gaps:\n"
                for gap in gaps[:5]:
                    if gap:
                        report += f"   - {gap}\n"

            # Add geographic bias
            if geographic_bias.get("bias_detected"):
                report += f"\n🌍 Geographic Bias: Detected ({geographic_bias.get('dominant_region', 'unknown')} dominant)\n"

            # Add temporal bias
            if temporal_bias.get("bias_detected"):
                recent_pct = temporal_bias.get("recent_percentage", 0)
                report += f"\n⏰ Temporal Bias: Detected ({recent_pct:.0f}% recent sources)\n"

            return report.strip()

        except Exception as e:
            logger.error(f"[BiasDetector] Report generation error: {e}")
            return "Bias report pending"

    def _indicator_to_dict(self, indicator: BiasIndicator) -> Dict[str, Any]:
        """Convert bias indicator to dictionary.

        Args:
            indicator: BiasIndicator object

        Returns:
            Dictionary representation
        """
        return {
            "type": indicator.bias_type,
            "description": indicator.description,
            "severity": indicator.severity,
            "source_url": indicator.source_url,
            "source_title": indicator.source_title,
        }

    def get_stats(self) -> Dict[str, Any]:
        """Get bias detection statistics.

        Returns:
            Statistics dictionary
        """
        return self.stats.copy()
