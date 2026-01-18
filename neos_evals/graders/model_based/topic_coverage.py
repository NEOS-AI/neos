"""Topic Coverage Grader - LLM-based evaluation of topic coverage.

This grader uses an LLM to determine if all required topics
are adequately covered in the report.
"""

import logging
from typing import Dict, Any

from ..base import BaseGrader, GraderResult, GraderError
from utils.llm_client import get_global_llm_client

logger = logging.getLogger(__name__)


class TopicCoverageGrader(BaseGrader):
    """Grades topic coverage using LLM evaluation.

    Uses an LLM to assess:
    - Presence of each required topic
    - Depth of coverage for each topic
    - Overall topic completeness

    Example:
        ```python
        grader = TopicCoverageGrader()
        result = await grader.grade(task, trial)

        print(f"Coverage: {result.details['coverage_by_topic']}")
        ```
    """

    def __init__(self):
        """Initialize topic coverage grader."""
        super().__init__(
            grader_id="topic_coverage",
            grader_type="model",
            weight=0.20,
            description="LLM-based evaluation of topic coverage"
        )
        self.llm_client = get_global_llm_client()

    async def grade(
        self,
        task: Any,  # EvalTask
        trial: Any,  # EvalTrial
    ) -> GraderResult:
        """Grade topic coverage.

        Args:
            task: Evaluation task with required_topics
            trial: Trial with report content

        Returns:
            GraderResult with topic coverage score
        """
        try:
            report = trial.final_report
            required_topics = task.required_topics

            if not report:
                return GraderResult(
                    grader_id=self.grader_id,
                    score=0.0,
                    passed=False,
                    feedback="No report content to grade",
                    details={"error": "empty_report"}
                )

            if not required_topics:
                # No specific topics required - give full score
                return GraderResult(
                    grader_id=self.grader_id,
                    score=1.0,
                    passed=True,
                    feedback="No specific topics required",
                    details={"required_topics": 0}
                )

            # Evaluate topic coverage with LLM
            coverage_data = await self._evaluate_coverage(report, required_topics)

            # Calculate overall score
            overall_score = coverage_data["overall_score"]

            # Pass criteria
            passed = overall_score >= 0.85  # High bar for topic coverage

            # Generate feedback
            feedback = self._generate_feedback(coverage_data, required_topics)

            return GraderResult(
                grader_id=self.grader_id,
                score=overall_score,
                passed=passed,
                feedback=feedback,
                details={
                    "required_topics": len(required_topics),
                    "coverage_by_topic": coverage_data["coverage_by_topic"],
                    "covered_count": coverage_data["covered_count"],
                    "partially_covered_count": coverage_data["partially_covered_count"],
                    "missing_count": coverage_data["missing_count"],
                }
            )

        except Exception as e:
            logger.error(f"Topic coverage grading failed: {e}", exc_info=True)
            raise GraderError(f"Topic coverage grading failed: {e}")

    async def _evaluate_coverage(
        self,
        report: str,
        required_topics: list
    ) -> Dict[str, Any]:
        """Evaluate topic coverage using LLM.

        Args:
            report: Report text
            required_topics: List of required topics

        Returns:
            Coverage evaluation data
        """
        # Truncate report if too long (max 8000 chars for context)
        report_excerpt = report[:8000]
        if len(report) > 8000:
            report_excerpt += "\n\n[... report truncated for evaluation ...]"

        # Build prompt
        prompt = f"""You are evaluating a research report for topic coverage.

Required Topics:
{self._format_topics(required_topics)}

Report Content:
{report_excerpt}

For each required topic, evaluate coverage on a scale:
- 2 = Well covered (substantial discussion, multiple aspects, depth)
- 1 = Partially covered (mentioned but lacking depth)
- 0 = Not covered (not mentioned or only passing reference)

Return JSON in this exact format:
{{
  "topic_name_1": {{"score": 2, "rationale": "brief explanation"}},
  "topic_name_2": {{"score": 1, "rationale": "brief explanation"}},
  ...
}}

Evaluate all {len(required_topics)} topics."""

        try:
            response = await self.llm_client.call_with_json(
                prompt=prompt,
                max_tokens=2000,
                temperature=0.0
            )

            # Process response
            coverage_by_topic = {}
            total_score = 0
            max_score = len(required_topics) * 2  # Max 2 per topic

            covered_count = 0
            partially_covered_count = 0
            missing_count = 0

            for topic in required_topics:
                # Try to find topic in response (case-insensitive)
                topic_data = None
                for key in response.keys():
                    if topic.lower() in key.lower() or key.lower() in topic.lower():
                        topic_data = response[key]
                        break

                if topic_data:
                    score = topic_data.get("score", 0)
                    rationale = topic_data.get("rationale", "")

                    coverage_by_topic[topic] = {
                        "score": score,
                        "rationale": rationale
                    }

                    total_score += score

                    if score >= 2:
                        covered_count += 1
                    elif score >= 1:
                        partially_covered_count += 1
                    else:
                        missing_count += 1
                else:
                    # Topic not found in response
                    coverage_by_topic[topic] = {
                        "score": 0,
                        "rationale": "Not evaluated by LLM"
                    }
                    missing_count += 1

            # Calculate overall score (0.0 to 1.0)
            overall_score = total_score / max_score if max_score > 0 else 0.0

            return {
                "overall_score": overall_score,
                "coverage_by_topic": coverage_by_topic,
                "covered_count": covered_count,
                "partially_covered_count": partially_covered_count,
                "missing_count": missing_count,
            }

        except Exception as e:
            logger.error(f"LLM evaluation failed: {e}")
            # Return low score on error
            return {
                "overall_score": 0.0,
                "coverage_by_topic": {t: {"score": 0, "rationale": f"Error: {e}"} for t in required_topics},
                "covered_count": 0,
                "partially_covered_count": 0,
                "missing_count": len(required_topics),
            }

    def _format_topics(self, topics: list) -> str:
        """Format topics for prompt.

        Args:
            topics: List of topic strings

        Returns:
            Formatted string
        """
        return "\n".join(f"{i+1}. {topic}" for i, topic in enumerate(topics))

    def _generate_feedback(
        self,
        coverage_data: Dict[str, Any],
        required_topics: list
    ) -> str:
        """Generate human-readable feedback.

        Args:
            coverage_data: Coverage evaluation data
            required_topics: Required topics list

        Returns:
            Feedback string
        """
        covered = coverage_data["covered_count"]
        partial = coverage_data["partially_covered_count"]
        missing = coverage_data["missing_count"]
        total = len(required_topics)

        feedback_parts = []

        # Overall coverage
        if missing == 0:
            feedback_parts.append(f"All {total} topics covered")
        else:
            feedback_parts.append(
                f"{covered + partial}/{total} topics covered "
                f"({covered} well-covered, {partial} partial)"
            )

        # Missing topics
        if missing > 0:
            missing_topics = [
                topic for topic, data in coverage_data["coverage_by_topic"].items()
                if data["score"] == 0
            ]
            feedback_parts.append(
                f"Missing: {', '.join(missing_topics[:3])}"
                f"{'...' if len(missing_topics) > 3 else ''}"
            )

        return "; ".join(feedback_parts)
