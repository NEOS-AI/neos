"""Citation Accuracy Grader - Validates citation format and references.

This grader checks:
1. Citation format validity ([1], [2,3], etc.)
2. All citations have corresponding sources
3. No invalid/missing references
4. Citation coverage (% of claims with citations)
"""

import re
from typing import Dict, Any, List, Set, Tuple
import logging

from ..base import BaseGrader, GraderResult, GraderError

logger = logging.getLogger(__name__)


class CitationAccuracyGrader(BaseGrader):
    """Grades citation accuracy and validity.

    Checks:
    - Citation format validity
    - All citations reference actual sources
    - No broken or missing references
    - Citation density and coverage

    Example:
        ```python
        grader = CitationAccuracyGrader()
        result = await grader.grade(task, trial)

        print(f"Score: {result.score}")
        print(f"Invalid citations: {result.details['invalid_citations']}")
        ```
    """

    # Citation patterns
    CITATION_PATTERN = r'\[(\d+(?:,\s*\d+)*)\]'
    CLAIM_INDICATORS = [
        r'studies show',
        r'research indicates',
        r'according to',
        r'evidence suggests',
        r'data reveals',
        r'found that',
        r'demonstrated',
        r'estimated',
        r'measured',
        r'reported'
    ]

    def __init__(self):
        """Initialize citation accuracy grader."""
        super().__init__(
            grader_id="citation_accuracy",
            grader_type="code",
            weight=0.15,
            description="Validates citation format and references"
        )

    async def grade(
        self,
        task: Any,  # EvalTask
        trial: Any,  # EvalTrial
    ) -> GraderResult:
        """Grade citation accuracy.

        Args:
            task: Evaluation task
            trial: Trial with agent output

        Returns:
            GraderResult with citation accuracy score
        """
        try:
            report = trial.final_report
            metadata = trial.metadata

            if not report:
                return GraderResult(
                    grader_id=self.grader_id,
                    score=0.0,
                    passed=False,
                    feedback="No report content to grade",
                    details={"error": "empty_report"}
                )

            # Extract all citations
            citations = self._extract_citations(report)

            if not citations:
                return GraderResult(
                    grader_id=self.grader_id,
                    score=0.0,
                    passed=False,
                    feedback="No citations found in report",
                    details={
                        "total_citations": 0,
                        "valid_citations": 0,
                        "warning": "report_has_no_citations"
                    }
                )

            # Validate citations against metadata
            validation_results = self._validate_citations(citations, metadata)

            # Calculate coverage (if possible)
            coverage_score = self._calculate_coverage(report, len(citations))

            # Calculate overall score
            validity_score = validation_results["validity_score"]
            overall_score = (validity_score * 0.7) + (coverage_score * 0.3)

            # Determine pass/fail
            passed = overall_score >= 0.9  # High bar for citation accuracy

            # Generate feedback
            feedback = self._generate_feedback(validation_results, coverage_score)

            return GraderResult(
                grader_id=self.grader_id,
                score=overall_score,
                passed=passed,
                feedback=feedback,
                details={
                    "total_citations": validation_results["total_citations"],
                    "valid_citations": validation_results["valid_citations"],
                    "invalid_citations": validation_results["invalid_citations"],
                    "missing_sources": validation_results["missing_sources"],
                    "validity_score": validity_score,
                    "coverage_score": coverage_score,
                    "total_sources_available": validation_results["total_sources"],
                }
            )

        except Exception as e:
            logger.error(f"Citation grading failed: {e}", exc_info=True)
            raise GraderError(f"Citation grading failed: {e}")

    def _extract_citations(self, text: str) -> List[int]:
        """Extract all citation numbers from text.

        Args:
            text: Report text

        Returns:
            List of cited source numbers
        """
        citations = []
        matches = re.finditer(self.CITATION_PATTERN, text)

        for match in matches:
            # Parse comma-separated citations: [1,2,3]
            citation_str = match.group(1)
            for num_str in citation_str.split(','):
                try:
                    citations.append(int(num_str.strip()))
                except ValueError:
                    logger.warning(f"Invalid citation number: {num_str}")

        return citations

    def _validate_citations(
        self,
        citations: List[int],
        metadata: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Validate citations against available sources.

        Args:
            citations: List of citation numbers
            metadata: Trial metadata with sources info

        Returns:
            Validation results dictionary
        """
        # Get total sources from metadata
        total_sources = metadata.get("total_sources_collected", 0)

        if total_sources == 0:
            # Try alternative metadata fields
            total_sources = len(metadata.get("unique_domains", set()))

        # Find invalid citations (numbers > total sources)
        unique_citations = set(citations)
        invalid_citations = [c for c in unique_citations if c > total_sources or c < 1]
        valid_citations = [c for c in unique_citations if 1 <= c <= total_sources]

        # Calculate validity score
        if unique_citations:
            validity_score = len(valid_citations) / len(unique_citations)
        else:
            validity_score = 0.0

        return {
            "total_citations": len(citations),
            "unique_citations": len(unique_citations),
            "valid_citations": len(valid_citations),
            "invalid_citations": invalid_citations,
            "missing_sources": [],  # Would need source list to determine
            "validity_score": validity_score,
            "total_sources": total_sources,
        }

    def _calculate_coverage(self, text: str, num_citations: int) -> float:
        """Estimate citation coverage (rough heuristic).

        Args:
            text: Report text
            num_citations: Number of citations found

        Returns:
            Coverage score (0.0 to 1.0)
        """
        # Count potential claims (sentences with claim indicators)
        claim_count = 0

        for pattern in self.CLAIM_INDICATORS:
            matches = re.findall(pattern, text, re.IGNORECASE)
            claim_count += len(matches)

        # Also count section headers as potential claim areas
        section_count = len(re.findall(r'^#+\s+', text, re.MULTILINE))
        estimated_claims = max(claim_count, section_count * 3)  # At least 3 claims per section

        if estimated_claims == 0:
            return 0.5  # Neutral score if can't estimate

        # Calculate coverage
        coverage = min(num_citations / estimated_claims, 1.0)

        # Apply a curve: good coverage is 0.4-0.8 citations per claim
        if 0.4 <= coverage <= 0.8:
            return 1.0  # Optimal
        elif coverage < 0.4:
            return coverage / 0.4  # Scale up to optimal
        else:
            return 1.0 - ((coverage - 0.8) / 0.4)  # Scale down from optimal

    def _generate_feedback(
        self,
        validation_results: Dict[str, Any],
        coverage_score: float
    ) -> str:
        """Generate human-readable feedback.

        Args:
            validation_results: Validation results
            coverage_score: Coverage score

        Returns:
            Feedback string
        """
        total = validation_results["unique_citations"]
        valid = validation_results["valid_citations"]
        invalid = validation_results["invalid_citations"]

        feedback_parts = []

        # Validity feedback
        if valid == total:
            feedback_parts.append(f"All {total} citations are valid")
        else:
            feedback_parts.append(
                f"{valid}/{total} citations valid "
                f"({len(invalid)} invalid: {invalid[:5]}{'...' if len(invalid) > 5 else ''})"
            )

        # Coverage feedback
        if coverage_score >= 0.9:
            feedback_parts.append("Excellent citation coverage")
        elif coverage_score >= 0.7:
            feedback_parts.append("Good citation coverage")
        elif coverage_score >= 0.5:
            feedback_parts.append("Moderate citation coverage")
        else:
            feedback_parts.append("Low citation coverage - add more references")

        return "; ".join(feedback_parts)
