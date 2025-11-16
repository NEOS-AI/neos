"""Source quality scoring system.

Evaluates and ranks sources based on credibility, recency, relevance, and content quality.
"""

from typing import Dict, Any, List
from datetime import datetime, timedelta
from urllib.parse import urlparse
import re
import logging

logger = logging.getLogger(__name__)


class SourceQualityScorer:
    """Evaluates source quality with multi-factor scoring."""

    # Trusted domain patterns with weights
    TRUSTED_DOMAINS = {
        # Academic and Educational (highest trust)
        ".edu": 1.0,
        ".ac.uk": 1.0,
        "scholar.google": 1.0,
        "arxiv.org": 0.95,
        "researchgate.net": 0.9,
        "jstor.org": 0.95,
        "sciencedirect.com": 0.95,
        "nature.com": 0.95,
        "science.org": 0.95,
        "ieee.org": 0.95,

        # Government and International Organizations
        ".gov": 0.95,
        ".mil": 0.9,
        "who.int": 0.95,
        "un.org": 0.9,
        "europa.eu": 0.9,
        "nih.gov": 0.95,

        # Reputable News and Media
        "nytimes.com": 0.85,
        "wsj.com": 0.85,
        "reuters.com": 0.9,
        "bbc.com": 0.85,
        "theguardian.com": 0.8,
        "economist.com": 0.85,
        "ft.com": 0.85,
        "bloomberg.com": 0.85,
        "apnews.com": 0.9,

        # Tech and Industry Leaders
        "techcrunch.com": 0.75,
        "arstechnica.com": 0.8,
        "wired.com": 0.75,
        "medium.com": 0.6,
        "stackoverflow.com": 0.8,
        "github.com": 0.7,

        # Medical and Health
        "mayoclinic.org": 0.9,
        "webmd.com": 0.75,
        "healthline.com": 0.7,

        # Think Tanks and Research
        "brookings.edu": 0.85,
        "rand.org": 0.85,
        "pewresearch.org": 0.85,
    }

    # Low credibility indicators
    LOW_CREDIBILITY_PATTERNS = [
        r"blog\.",
        r"\.blogspot\.",
        r"\.wordpress\.",
        r"\.tumblr\.",
        r"\.weebly\.",
        r"forum",
        r"\.wiki",  # except wikipedia
    ]

    def __init__(self):
        """Initialize the scorer."""
        self.stats = {
            "sources_scored": 0,
            "avg_quality_score": 0.0,
            "high_quality_count": 0,  # score >= 0.7
        }

    def score_source(self, source: Dict[str, Any]) -> float:
        """Calculate comprehensive quality score for a source.

        Score components:
        - Domain credibility: 40%
        - Recency: 30%
        - Relevance: 20%
        - Content quality: 10%

        Args:
            source: Source dictionary with url, title, content, published_date, score

        Returns:
            Quality score (0.0 to 1.0)
        """
        try:
            url = source.get("url", "")
            title = source.get("title", "")
            content = source.get("content", "")
            published_date = source.get("published_date", "")
            relevance_score = source.get("score", 0.5)  # From search engine

            # Component scores
            domain_score = self._score_domain_credibility(url)
            recency_score = self._score_recency(published_date)
            relevance_score = self._score_relevance(relevance_score)
            content_score = self._score_content_quality(title, content)

            # Weighted combination
            final_score = (
                domain_score * 0.40 +
                recency_score * 0.30 +
                relevance_score * 0.20 +
                content_score * 0.10
            )

            # Update stats
            self.stats["sources_scored"] += 1
            self.stats["avg_quality_score"] = (
                (self.stats["avg_quality_score"] * (self.stats["sources_scored"] - 1) + final_score)
                / self.stats["sources_scored"]
            )
            if final_score >= 0.7:
                self.stats["high_quality_count"] += 1

            return final_score

        except Exception as e:
            logger.warning(f"[SourceQualityScorer] Scoring error: {e}")
            return 0.5  # Default mid-range score

    def _score_domain_credibility(self, url: str) -> float:
        """Score domain credibility.

        Args:
            url: Source URL

        Returns:
            Credibility score (0.0 to 1.0)
        """
        if not url:
            return 0.5

        try:
            parsed = urlparse(url.lower())
            domain = parsed.netloc

            # Check trusted domains
            for pattern, score in self.TRUSTED_DOMAINS.items():
                if pattern in domain:
                    return score

            # Check low credibility patterns
            for pattern in self.LOW_CREDIBILITY_PATTERNS:
                if re.search(pattern, domain):
                    return 0.4

            # Check TLD quality
            if domain.endswith(('.org', '.net')):
                return 0.6
            elif domain.endswith(('.com', '.io')):
                return 0.55

            return 0.5  # Default score

        except Exception as e:
            logger.warning(f"[SourceQualityScorer] Domain parsing error: {e}")
            return 0.5

    def _score_recency(self, published_date: str) -> float:
        """Score source recency.

        Scoring:
        - Last 1 month: 1.0
        - Last 6 months: 0.9
        - Last 1 year: 0.7
        - Last 2 years: 0.5
        - Last 5 years: 0.3
        - Older: 0.2
        - Unknown: 0.5 (default)

        Args:
            published_date: Publication date string

        Returns:
            Recency score (0.0 to 1.0)
        """
        if not published_date:
            return 0.5  # No date = default mid-range

        try:
            # Try to parse various date formats
            date_obj = self._parse_date(published_date)
            if not date_obj:
                return 0.5

            age = datetime.now() - date_obj

            if age <= timedelta(days=30):
                return 1.0
            elif age <= timedelta(days=180):
                return 0.9
            elif age <= timedelta(days=365):
                return 0.7
            elif age <= timedelta(days=730):
                return 0.5
            elif age <= timedelta(days=1825):
                return 0.3
            else:
                return 0.2

        except Exception as e:
            logger.warning(f"[SourceQualityScorer] Date parsing error: {e}")
            return 0.5

    def _parse_date(self, date_str: str) -> datetime:
        """Parse date string in various formats.

        Args:
            date_str: Date string

        Returns:
            Datetime object or None
        """
        date_formats = [
            "%Y-%m-%d",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S.%fZ",
            "%d %b %Y",
            "%B %d, %Y",
            "%Y/%m/%d",
        ]

        for fmt in date_formats:
            try:
                return datetime.strptime(date_str[:19], fmt[:19])
            except (ValueError, IndexError):
                continue

        return None

    def _score_relevance(self, search_score: float) -> float:
        """Score relevance based on search engine ranking.

        Args:
            search_score: Score from search engine (0.0 to 1.0)

        Returns:
            Normalized relevance score
        """
        # Tavily scores are typically 0.0 to 1.0
        # Normalize and boost slightly
        if search_score >= 0.9:
            return 1.0
        elif search_score >= 0.7:
            return 0.9
        elif search_score >= 0.5:
            return 0.7
        elif search_score >= 0.3:
            return 0.5
        else:
            return 0.3

    def _score_content_quality(self, title: str, content: str) -> float:
        """Score content quality based on length and structure.

        Args:
            title: Source title
            content: Source content

        Returns:
            Content quality score (0.0 to 1.0)
        """
        score = 0.5  # Base score

        # Title quality
        if title:
            title_length = len(title)
            if 30 <= title_length <= 150:
                score += 0.15
            elif 15 <= title_length <= 200:
                score += 0.1
            elif title_length > 0:
                score += 0.05

        # Content quality
        if content:
            content_length = len(content)

            # Length score
            if content_length >= 2000:
                score += 0.2
            elif content_length >= 1000:
                score += 0.15
            elif content_length >= 500:
                score += 0.1
            elif content_length >= 200:
                score += 0.05

            # Structure indicators
            if re.search(r'\n\n', content):  # Has paragraphs
                score += 0.05
            if re.search(r'\d+\.|•|–', content):  # Has lists
                score += 0.05
            if re.search(r'[A-Z][a-z]+\s+\([0-9]{4}\)', content):  # Has citations
                score += 0.1

        return min(score, 1.0)

    def rank_sources(self, sources: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Score and rank sources by quality.

        Args:
            sources: List of source dictionaries

        Returns:
            Sorted list with quality scores added
        """
        scored_sources = []

        for source in sources:
            quality_score = self.score_source(source)
            source_with_score = source.copy()
            source_with_score["quality_score"] = quality_score
            scored_sources.append(source_with_score)

        # Sort by quality score (descending)
        scored_sources.sort(key=lambda x: x.get("quality_score", 0), reverse=True)

        return scored_sources

    def filter_by_quality(
        self,
        sources: List[Dict[str, Any]],
        min_score: float = 0.5
    ) -> List[Dict[str, Any]]:
        """Filter sources by minimum quality score.

        Args:
            sources: List of source dictionaries
            min_score: Minimum quality threshold

        Returns:
            Filtered and scored sources
        """
        ranked = self.rank_sources(sources)
        return [s for s in ranked if s.get("quality_score", 0) >= min_score]

    def get_stats(self) -> Dict[str, Any]:
        """Get scoring statistics.

        Returns:
            Statistics dictionary
        """
        high_quality_pct = (
            (self.stats["high_quality_count"] / self.stats["sources_scored"] * 100)
            if self.stats["sources_scored"] > 0 else 0
        )

        return {
            **self.stats,
            "high_quality_percentage": high_quality_pct,
        }
