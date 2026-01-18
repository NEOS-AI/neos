"""Source Diversity Grader - Checks variety and quality of sources.

This grader evaluates:
1. Number of unique domains
2. Diversity of source types (academic, news, government, etc.)
3. Geographic diversity (if detectable)
4. Meets minimum source requirements
"""

from typing import Dict, Any, Set, List
from urllib.parse import urlparse
import logging

from ..base import BaseGrader, GraderResult, GraderError

logger = logging.getLogger(__name__)


class SourceDiversityGrader(BaseGrader):
    """Grades source diversity and variety.

    Evaluates:
    - Number of unique domains
    - Source type diversity
    - Meets minimum source count
    - Domain authority (if metadata available)

    Example:
        ```python
        grader = SourceDiversityGrader()
        result = await grader.grade(task, trial)

        print(f"Unique domains: {result.details['unique_domains']}")
        print(f"Source types: {result.details['source_types']}")
        ```
    """

    # Source type indicators (domain patterns)
    SOURCE_TYPE_PATTERNS = {
        "academic": [
            ".edu",
            ".ac.",
            "arxiv.org",
            "scholar.google",
            "researchgate",
            "jstor",
            "springer",
            "sciencedirect",
            "ieee.org",
            "acm.org"
        ],
        "government": [
            ".gov",
            ".mil",
            "europa.eu",
            "who.int",
            "un.org",
            "oecd.org"
        ],
        "news": [
            "nytimes",
            "washingtonpost",
            "reuters",
            "bbc.co",
            "theguardian",
            "wsj.com",
            "bloomberg",
            "ft.com",
            "economist.com",
            "apnews"
        ],
        "technical": [
            "github.com",
            "stackoverflow",
            "docs.",
            "developer.",
            "techcrunch",
            "wired.com",
            "arstechnica",
            "mit.edu",
            "medium.com"
        ]
    }

    def __init__(self):
        """Initialize source diversity grader."""
        super().__init__(
            grader_id="source_diversity",
            grader_type="code",
            weight=0.10,
            description="Evaluates source variety and diversity"
        )

    async def grade(
        self,
        task: Any,  # EvalTask
        trial: Any,  # EvalTrial
    ) -> GraderResult:
        """Grade source diversity.

        Args:
            task: Evaluation task with min_sources requirement
            trial: Trial with metadata containing source info

        Returns:
            GraderResult with diversity score
        """
        try:
            metadata = trial.metadata

            # Extract source information
            unique_domains = metadata.get("unique_domains", set())
            total_sources = metadata.get("total_sources_collected", 0)

            # Convert set to list if needed
            if isinstance(unique_domains, set):
                unique_domains = list(unique_domains)

            # Check minimum sources requirement
            meets_minimum = total_sources >= task.min_sources

            # Analyze source diversity
            diversity_analysis = self._analyze_diversity(unique_domains)

            # Calculate scores
            quantity_score = self._calculate_quantity_score(
                total_sources,
                task.min_sources
            )
            diversity_score = self._calculate_diversity_score(diversity_analysis)

            # Overall score (weighted combination)
            overall_score = (quantity_score * 0.5) + (diversity_score * 0.5)

            # Pass criteria
            passed = meets_minimum and diversity_score >= 0.7

            # Generate feedback
            feedback = self._generate_feedback(
                total_sources=total_sources,
                min_sources=task.min_sources,
                unique_domains=len(unique_domains),
                diversity_analysis=diversity_analysis
            )

            return GraderResult(
                grader_id=self.grader_id,
                score=overall_score,
                passed=passed,
                feedback=feedback,
                details={
                    "total_sources": total_sources,
                    "min_sources_required": task.min_sources,
                    "meets_minimum": meets_minimum,
                    "unique_domains": len(unique_domains),
                    "source_types": diversity_analysis["source_types"],
                    "type_counts": diversity_analysis["type_counts"],
                    "quantity_score": quantity_score,
                    "diversity_score": diversity_score,
                }
            )

        except Exception as e:
            logger.error(f"Source diversity grading failed: {e}", exc_info=True)
            raise GraderError(f"Source diversity grading failed: {e}")

    def _analyze_diversity(self, domains: List[str]) -> Dict[str, Any]:
        """Analyze diversity of source domains.

        Args:
            domains: List of domain names

        Returns:
            Diversity analysis results
        """
        source_types = set()
        type_counts = {
            "academic": 0,
            "government": 0,
            "news": 0,
            "technical": 0,
            "other": 0
        }

        for domain in domains:
            domain_lower = domain.lower()
            classified = False

            # Check each source type
            for source_type, patterns in self.SOURCE_TYPE_PATTERNS.items():
                if any(pattern in domain_lower for pattern in patterns):
                    source_types.add(source_type)
                    type_counts[source_type] += 1
                    classified = True
                    break

            if not classified:
                type_counts["other"] += 1

        return {
            "source_types": list(source_types),
            "num_types": len(source_types),
            "type_counts": type_counts,
        }

    def _calculate_quantity_score(
        self,
        total_sources: int,
        min_sources: int
    ) -> float:
        """Calculate score based on source quantity.

        Args:
            total_sources: Actual number of sources
            min_sources: Minimum required sources

        Returns:
            Quantity score (0.0 to 1.0)
        """
        if min_sources == 0:
            return 1.0

        ratio = total_sources / min_sources

        if ratio >= 1.5:
            return 1.0  # Excellent: 150%+ of minimum
        elif ratio >= 1.0:
            return 0.7 + (ratio - 1.0) * 0.6  # Good: 100-150%
        elif ratio >= 0.8:
            return 0.5 + (ratio - 0.8) * 1.0  # Acceptable: 80-100%
        else:
            return ratio * 0.625  # Poor: < 80%

    def _calculate_diversity_score(self, diversity_analysis: Dict[str, Any]) -> float:
        """Calculate score based on source diversity.

        Args:
            diversity_analysis: Diversity analysis results

        Returns:
            Diversity score (0.0 to 1.0)
        """
        num_types = diversity_analysis["num_types"]
        type_counts = diversity_analysis["type_counts"]

        # Base score from number of types
        if num_types >= 4:
            type_score = 1.0  # Excellent diversity
        elif num_types == 3:
            type_score = 0.85  # Good diversity
        elif num_types == 2:
            type_score = 0.7  # Moderate diversity
        elif num_types == 1:
            type_score = 0.5  # Limited diversity
        else:
            type_score = 0.0  # No diversity

        # Balance score (how evenly distributed across types)
        if num_types > 1:
            # Calculate coefficient of variation
            counts = [c for c in type_counts.values() if c > 0]
            if counts:
                mean = sum(counts) / len(counts)
                std_dev = (sum((x - mean) ** 2 for x in counts) / len(counts)) ** 0.5
                cv = std_dev / mean if mean > 0 else 1.0
                balance_score = max(0.0, 1.0 - cv)  # Lower CV = better balance
            else:
                balance_score = 0.0
        else:
            balance_score = 0.0

        # Combine scores
        return (type_score * 0.7) + (balance_score * 0.3)

    def _generate_feedback(
        self,
        total_sources: int,
        min_sources: int,
        unique_domains: int,
        diversity_analysis: Dict[str, Any]
    ) -> str:
        """Generate human-readable feedback.

        Args:
            total_sources: Total source count
            min_sources: Minimum required
            unique_domains: Number of unique domains
            diversity_analysis: Diversity analysis results

        Returns:
            Feedback string
        """
        feedback_parts = []

        # Quantity feedback
        if total_sources >= min_sources:
            feedback_parts.append(
                f"Meets source requirement: {total_sources}/{min_sources} sources"
            )
        else:
            feedback_parts.append(
                f"Below minimum: {total_sources}/{min_sources} sources "
                f"({min_sources - total_sources} short)"
            )

        # Diversity feedback
        feedback_parts.append(f"{unique_domains} unique domains")

        num_types = diversity_analysis["num_types"]
        source_types = diversity_analysis["source_types"]

        if num_types >= 3:
            feedback_parts.append(
                f"Good diversity: {num_types} source types ({', '.join(source_types)})"
            )
        elif num_types >= 2:
            feedback_parts.append(
                f"Moderate diversity: {num_types} source types ({', '.join(source_types)})"
            )
        else:
            feedback_parts.append(
                f"Limited diversity: only {num_types} source type - consider adding varied sources"
            )

        return "; ".join(feedback_parts)
