"""Metadata Validation Grader - Validates agent execution metadata.

This grader checks:
1. Metadata completeness
2. Reasonable metric values
3. All phases completed successfully
4. No critical errors or warnings
"""

from typing import Dict, Any, List
import logging

from ..base import BaseGrader, GraderResult, GraderError

logger = logging.getLogger(__name__)


class MetadataValidationGrader(BaseGrader):
    """Grades agent metadata quality and completeness.

    Evaluates:
    - All required metadata fields present
    - Metric values are reasonable
    - Phase completion status
    - Error/warning tracking

    Example:
        ```python
        grader = MetadataValidationGrader()
        result = await grader.grade(task, trial)

        print(f"Metadata completeness: {result.details['completeness']}")
        print(f"Phases completed: {result.details['phases_completed']}")
        ```
    """

    # Expected metadata fields from ResearchMetadata
    EXPECTED_FIELDS = [
        "total_queries_executed",
        "total_sources_collected",
        "unique_domains",
        "analysis_iterations_completed",
        "critical_reviews_completed",
        "llm_calls",
        "estimated_total_tokens",
    ]

    # Reasonable ranges for metrics (min, max)
    METRIC_RANGES = {
        "total_queries_executed": (5, 500),
        "total_sources_collected": (20, 500),
        "analysis_iterations_completed": (0, 10),
        "llm_calls": (5, 200),
        "estimated_total_tokens": (1000, 500000),
    }

    def __init__(self):
        """Initialize metadata validation grader."""
        super().__init__(
            grader_id="metadata_validation",
            grader_type="code",
            weight=0.05,
            description="Validates agent execution metadata"
        )

    async def grade(
        self,
        task: Any,  # EvalTask
        trial: Any,  # EvalTrial
    ) -> GraderResult:
        """Grade metadata quality.

        Args:
            task: Evaluation task
            trial: Trial with metadata

        Returns:
            GraderResult with metadata validation score
        """
        try:
            metadata = trial.metadata

            if not metadata:
                return GraderResult(
                    grader_id=self.grader_id,
                    score=0.0,
                    passed=False,
                    feedback="No metadata available",
                    details={"error": "missing_metadata"}
                )

            # Check completeness
            completeness_analysis = self._check_completeness(metadata)

            # Validate metric ranges
            range_analysis = self._validate_ranges(metadata)

            # Check for errors/warnings
            error_analysis = self._check_errors(metadata)

            # Calculate scores
            completeness_score = completeness_analysis["completeness_score"]
            validity_score = range_analysis["validity_score"]
            error_score = error_analysis["error_score"]

            # Overall score (weighted)
            overall_score = (
                completeness_score * 0.4 +
                validity_score * 0.4 +
                error_score * 0.2
            )

            # Pass criteria
            passed = (
                completeness_score >= 0.8 and
                len(error_analysis["critical_issues"]) == 0
            )

            # Generate feedback
            feedback = self._generate_feedback(
                completeness_analysis,
                range_analysis,
                error_analysis
            )

            return GraderResult(
                grader_id=self.grader_id,
                score=overall_score,
                passed=passed,
                feedback=feedback,
                details={
                    "completeness_score": completeness_score,
                    "missing_fields": completeness_analysis["missing_fields"],
                    "validity_score": validity_score,
                    "out_of_range_metrics": range_analysis["out_of_range"],
                    "error_score": error_score,
                    "critical_issues": error_analysis["critical_issues"],
                    "warnings": error_analysis["warnings"],
                }
            )

        except Exception as e:
            logger.error(f"Metadata validation failed: {e}", exc_info=True)
            raise GraderError(f"Metadata validation failed: {e}")

    def _check_completeness(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """Check metadata completeness.

        Args:
            metadata: Metadata dictionary

        Returns:
            Completeness analysis results
        """
        missing_fields = []
        present_fields = []

        for field in self.EXPECTED_FIELDS:
            if field in metadata and metadata[field] is not None:
                present_fields.append(field)
            else:
                missing_fields.append(field)

        # Calculate completeness score
        completeness_score = len(present_fields) / len(self.EXPECTED_FIELDS)

        return {
            "completeness_score": completeness_score,
            "present_fields": present_fields,
            "missing_fields": missing_fields,
        }

    def _validate_ranges(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """Validate metric values are in reasonable ranges.

        Args:
            metadata: Metadata dictionary

        Returns:
            Range validation results
        """
        out_of_range = []
        warnings = []

        for metric, (min_val, max_val) in self.METRIC_RANGES.items():
            if metric in metadata:
                value = metadata[metric]

                # Handle set types (unique_domains)
                if isinstance(value, set):
                    value = len(value)

                if not isinstance(value, (int, float)):
                    warnings.append(f"{metric}: non-numeric value")
                    continue

                if value < min_val:
                    out_of_range.append(f"{metric}: {value} < {min_val} (too low)")
                elif value > max_val:
                    out_of_range.append(f"{metric}: {value} > {max_val} (too high)")

        # Calculate validity score
        total_metrics = len(self.METRIC_RANGES)
        invalid_count = len(out_of_range)
        validity_score = max(0.0, 1.0 - (invalid_count / total_metrics))

        return {
            "validity_score": validity_score,
            "out_of_range": out_of_range,
            "warnings": warnings,
        }

    def _check_errors(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """Check for errors and warnings in metadata.

        Args:
            metadata: Metadata dictionary

        Returns:
            Error analysis results
        """
        critical_issues = []
        warnings = []

        # Check for error indicators
        if metadata.get("api_rate_limit_hits", 0) > 10:
            warnings.append("High API rate limit hits")

        if metadata.get("total_sources_collected", 0) == 0:
            critical_issues.append("No sources collected")

        if metadata.get("llm_calls", 0) == 0:
            critical_issues.append("No LLM calls recorded")

        # Check for phase completion (if available)
        if "phases_completed" in metadata:
            phases = metadata["phases_completed"]
            if not phases or len(phases) < 5:
                warnings.append(f"Only {len(phases)} phases completed")

        # Calculate error score
        if critical_issues:
            error_score = 0.0
        elif len(warnings) > 2:
            error_score = 0.5
        elif warnings:
            error_score = 0.7
        else:
            error_score = 1.0

        return {
            "error_score": error_score,
            "critical_issues": critical_issues,
            "warnings": warnings,
        }

    def _generate_feedback(
        self,
        completeness_analysis: Dict[str, Any],
        range_analysis: Dict[str, Any],
        error_analysis: Dict[str, Any]
    ) -> str:
        """Generate human-readable feedback.

        Args:
            completeness_analysis: Completeness results
            range_analysis: Range validation results
            error_analysis: Error analysis results

        Returns:
            Feedback string
        """
        feedback_parts = []

        # Completeness feedback
        present = len(completeness_analysis["present_fields"])
        total = len(self.EXPECTED_FIELDS)

        if completeness_analysis["completeness_score"] == 1.0:
            feedback_parts.append("All metadata fields present")
        else:
            missing = completeness_analysis["missing_fields"]
            feedback_parts.append(
                f"{present}/{total} metadata fields present; "
                f"missing: {', '.join(missing[:3])}"
            )

        # Range validation feedback
        out_of_range = range_analysis["out_of_range"]

        if not out_of_range:
            feedback_parts.append("All metrics within expected ranges")
        else:
            feedback_parts.append(
                f"{len(out_of_range)} metrics out of range: "
                f"{', '.join(out_of_range[:2])}"
            )

        # Error feedback
        critical = error_analysis["critical_issues"]
        warnings = error_analysis["warnings"]

        if critical:
            feedback_parts.append(f"CRITICAL: {', '.join(critical)}")
        elif warnings:
            feedback_parts.append(f"{len(warnings)} warnings")

        return "; ".join(feedback_parts)
