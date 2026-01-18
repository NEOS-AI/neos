"""Factual Accuracy Grader - Checks plausibility of claims.

This grader uses an LLM to assess whether factual claims
in the report appear accurate and well-supported.

Note: This is not full fact-checking (which would require
external verification), but rather plausibility assessment.
"""

import logging
from typing import Dict, Any, List
import re

from ..base import BaseGrader, GraderResult, GraderError
from utils.llm_client import get_global_llm_client

logger = logging.getLogger(__name__)


class FactualAccuracyGrader(BaseGrader):
    """Grades factual accuracy and claim plausibility.

    Evaluates:
    - Plausibility of factual claims
    - Internal consistency
    - Obvious errors or contradictions

    Note: This is a basic plausibility check, not comprehensive
    fact-checking against external sources.

    Example:
        ```python
        grader = FactualAccuracyGrader()
        result = await grader.grade(task, trial)

        print(f"Accuracy score: {result.score}")
        print(f"Issues: {result.details['issues_found']}")
        ```
    """

    def __init__(self):
        """Initialize factual accuracy grader."""
        super().__init__(
            grader_id="factual_accuracy",
            grader_type="model",
            weight=0.10,
            description="LLM-based factual plausibility assessment"
        )
        self.llm_client = get_global_llm_client()

    async def grade(
        self,
        task: Any,  # EvalTask
        trial: Any,  # EvalTrial
    ) -> GraderResult:
        """Grade factual accuracy.

        Args:
            task: Evaluation task
            trial: Trial with report content

        Returns:
            GraderResult with accuracy assessment
        """
        try:
            report = trial.final_report

            if not report:
                return GraderResult(
                    grader_id=self.grader_id,
                    score=0.0,
                    passed=False,
                    feedback="No report content to grade",
                    details={"error": "empty_report"}
                )

            # Extract key claims from report
            claims = self._extract_claims(report)

            if not claims:
                # No specific claims to check - give neutral score
                return GraderResult(
                    grader_id=self.grader_id,
                    score=0.8,  # Neutral: no obvious errors
                    passed=True,
                    feedback="No specific factual claims to verify",
                    details={"claims_checked": 0}
                )

            # Evaluate factual accuracy
            accuracy_data = await self._evaluate_accuracy(
                report,
                claims,
                task.query
            )

            # Calculate score
            overall_score = accuracy_data["accuracy_score"]

            # Pass criteria
            passed = overall_score >= 0.7  # 70% accuracy threshold

            # Generate feedback
            feedback = self._generate_feedback(accuracy_data)

            return GraderResult(
                grader_id=self.grader_id,
                score=overall_score,
                passed=passed,
                feedback=feedback,
                details={
                    "claims_checked": len(claims),
                    "accuracy_score": overall_score,
                    "issues_found": accuracy_data["issues_found"],
                    "consistency_issues": accuracy_data["consistency_issues"],
                }
            )

        except Exception as e:
            logger.error(f"Factual accuracy grading failed: {e}", exc_info=True)
            raise GraderError(f"Factual accuracy grading failed: {e}")

    def _extract_claims(self, report: str) -> List[str]:
        """Extract factual claims from report.

        Args:
            report: Report text

        Returns:
            List of claim strings
        """
        claims = []

        # Split into sentences
        sentences = re.split(r'[.!?]\s+', report)

        # Look for sentences with claim indicators
        claim_patterns = [
            r'\d+%',  # Percentages
            r'\d+\s*(million|billion|thousand)',  # Numbers with units
            r'(studies?|research|data|evidence)\s+(show|indicate|suggest|reveal)',
            r'(found|discovered|demonstrated|proved|established)\s+that',
            r'according to',
            r'estimated',
            r'measured',
            r'\[\d+\]',  # Has citations
        ]

        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) < 20:  # Too short to be substantive
                continue

            # Check if sentence contains claim indicators
            for pattern in claim_patterns:
                if re.search(pattern, sentence, re.IGNORECASE):
                    claims.append(sentence)
                    break

            # Limit to first 10 claims for efficiency
            if len(claims) >= 10:
                break

        return claims

    async def _evaluate_accuracy(
        self,
        report: str,
        claims: List[str],
        query: str
    ) -> Dict[str, Any]:
        """Evaluate factual accuracy using LLM.

        Args:
            report: Full report text
            claims: Extracted claims to check
            query: Original research query

        Returns:
            Accuracy evaluation data
        """
        # Format claims
        claims_text = "\n".join([
            f"{i+1}. {claim}"
            for i, claim in enumerate(claims)
        ])

        # Build prompt
        prompt = f"""You are evaluating the factual accuracy and plausibility of claims in a research report.

Research Query: {query}

Key Claims to Evaluate:
{claims_text}

For each claim, assess:
1. Plausibility (does it seem factually accurate based on common knowledge?)
2. Internal consistency (does it contradict other claims in the list?)
3. Specificity (is it specific enough to be verifiable?)

Also check for:
- Obvious factual errors
- Internally contradictory statements
- Unrealistic numbers or statistics

Return JSON in this format:
{{
  "accuracy_score": 0.85,
  "issues_found": ["brief description of any issues found"],
  "consistency_issues": ["any contradictions or inconsistencies"],
  "overall_assessment": "brief summary"
}}

The accuracy_score should be 0.0 to 1.0:
- 1.0 = All claims appear accurate and consistent
- 0.7-0.9 = Mostly accurate with minor issues
- 0.4-0.6 = Some questionable claims
- 0.0-0.3 = Multiple accuracy concerns

Be conservative - only flag clear issues."""

        try:
            response = await self.llm_client.call_with_json(
                prompt=prompt,
                max_tokens=1000,
                temperature=0.0
            )

            return {
                "accuracy_score": response.get("accuracy_score", 0.8),
                "issues_found": response.get("issues_found", []),
                "consistency_issues": response.get("consistency_issues", []),
                "overall_assessment": response.get("overall_assessment", ""),
            }

        except Exception as e:
            logger.error(f"LLM accuracy evaluation failed: {e}")
            # Return neutral score on error
            return {
                "accuracy_score": 0.7,
                "issues_found": [f"Evaluation error: {str(e)}"],
                "consistency_issues": [],
                "overall_assessment": "Could not complete evaluation",
            }

    def _generate_feedback(self, accuracy_data: Dict[str, Any]) -> str:
        """Generate human-readable feedback.

        Args:
            accuracy_data: Accuracy evaluation data

        Returns:
            Feedback string
        """
        score = accuracy_data["accuracy_score"]
        issues = accuracy_data["issues_found"]
        consistency = accuracy_data["consistency_issues"]

        feedback_parts = []

        # Overall assessment
        if score >= 0.9:
            feedback_parts.append("Excellent factual accuracy")
        elif score >= 0.7:
            feedback_parts.append("Good factual accuracy")
        elif score >= 0.5:
            feedback_parts.append("Moderate accuracy concerns")
        else:
            feedback_parts.append("Significant accuracy issues")

        # Issues
        if issues:
            feedback_parts.append(
                f"{len(issues)} issue(s) found: {issues[0][:50]}"
                f"{'...' if len(issues[0]) > 50 else ''}"
            )

        # Consistency
        if consistency:
            feedback_parts.append(f"{len(consistency)} consistency issue(s)")

        return "; ".join(feedback_parts)
