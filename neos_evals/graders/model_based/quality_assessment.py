"""Quality Assessment Grader - Multi-dimensional quality evaluation.

This grader uses an LLM to assess multiple quality dimensions:
- Factual accuracy
- Logical coherence
- Depth of analysis
- Clarity and readability
- Objectivity and balance
"""

import logging
from typing import Dict, Any

from ..base import BaseGrader, GraderResult, GraderError
from utils.llm_client import get_global_llm_client

logger = logging.getLogger(__name__)


class QualityAssessmentGrader(BaseGrader):
    """Grades overall report quality across multiple dimensions.

    Evaluates:
    - Factual accuracy (are claims plausible?)
    - Logical coherence (does it flow well?)
    - Depth of analysis (is it thorough?)
    - Clarity (is it readable?)
    - Objectivity (is it balanced?)

    Example:
        ```python
        grader = QualityAssessmentGrader()
        result = await grader.grade(task, trial)

        print(f"Quality dimensions: {result.details['dimension_scores']}")
        ```
    """

    # Quality dimensions and their weights
    DIMENSIONS = {
        "factual_accuracy": {
            "weight": 0.25,
            "description": "Claims are plausible and well-supported"
        },
        "logical_coherence": {
            "weight": 0.20,
            "description": "Ideas flow logically and connect well"
        },
        "depth_of_analysis": {
            "weight": 0.25,
            "description": "Thorough exploration with sufficient detail"
        },
        "clarity": {
            "weight": 0.15,
            "description": "Clear, readable, well-organized writing"
        },
        "objectivity": {
            "weight": 0.15,
            "description": "Balanced presentation without bias"
        }
    }

    def __init__(self):
        """Initialize quality assessment grader."""
        super().__init__(
            grader_id="quality_assessment",
            grader_type="model",
            weight=0.20,
            description="Multi-dimensional quality evaluation"
        )
        self.llm_client = get_global_llm_client()

    async def grade(
        self,
        task: Any,  # EvalTask
        trial: Any,  # EvalTrial
    ) -> GraderResult:
        """Grade overall quality.

        Args:
            task: Evaluation task
            trial: Trial with report content

        Returns:
            GraderResult with quality assessment
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

            # Evaluate quality dimensions
            quality_data = await self._evaluate_quality(report, task)

            # Calculate weighted overall score
            overall_score = self._calculate_weighted_score(
                quality_data["dimension_scores"]
            )

            # Pass criteria
            passed = overall_score >= task.quality_threshold

            # Generate feedback
            feedback = self._generate_feedback(quality_data, task.quality_threshold)

            return GraderResult(
                grader_id=self.grader_id,
                score=overall_score,
                passed=passed,
                feedback=feedback,
                details={
                    "dimension_scores": quality_data["dimension_scores"],
                    "dimension_rationales": quality_data["dimension_rationales"],
                    "quality_threshold": task.quality_threshold,
                }
            )

        except Exception as e:
            logger.error(f"Quality assessment failed: {e}", exc_info=True)
            raise GraderError(f"Quality assessment failed: {e}")

    async def _evaluate_quality(
        self,
        report: str,
        task: Any
    ) -> Dict[str, Any]:
        """Evaluate quality dimensions using LLM.

        Args:
            report: Report text
            task: Evaluation task

        Returns:
            Quality evaluation data
        """
        # Truncate report if too long
        report_excerpt = report[:10000]
        if len(report) > 10000:
            report_excerpt += "\n\n[... report truncated for evaluation ...]"

        # Build evaluation prompt
        dimensions_desc = "\n".join([
            f"- {dim}: {info['description']}"
            for dim, info in self.DIMENSIONS.items()
        ])

        prompt = f"""You are evaluating the quality of a research report.

Report Query: {task.query}
Report Category: {task.category}

Report Content:
{report_excerpt}

Evaluate the report on these quality dimensions (score 0.0 to 1.0):

{dimensions_desc}

For each dimension:
- 0.9-1.0: Excellent quality
- 0.7-0.8: Good quality
- 0.5-0.6: Acceptable quality
- 0.3-0.4: Poor quality
- 0.0-0.2: Very poor quality

Return JSON in this exact format:
{{
  "factual_accuracy": {{"score": 0.85, "rationale": "brief explanation"}},
  "logical_coherence": {{"score": 0.90, "rationale": "brief explanation"}},
  "depth_of_analysis": {{"score": 0.75, "rationale": "brief explanation"}},
  "clarity": {{"score": 0.80, "rationale": "brief explanation"}},
  "objectivity": {{"score": 0.85, "rationale": "brief explanation"}}
}}

Be objective and specific in your rationales."""

        try:
            response = await self.llm_client.call_with_json(
                prompt=prompt,
                max_tokens=1500,
                temperature=0.0
            )

            # Extract scores and rationales
            dimension_scores = {}
            dimension_rationales = {}

            for dimension in self.DIMENSIONS.keys():
                if dimension in response:
                    dimension_scores[dimension] = response[dimension].get("score", 0.5)
                    dimension_rationales[dimension] = response[dimension].get(
                        "rationale", "No rationale provided"
                    )
                else:
                    # Default if missing
                    dimension_scores[dimension] = 0.5
                    dimension_rationales[dimension] = "Not evaluated"

            return {
                "dimension_scores": dimension_scores,
                "dimension_rationales": dimension_rationales,
            }

        except Exception as e:
            logger.error(f"LLM quality evaluation failed: {e}")
            # Return neutral scores on error
            return {
                "dimension_scores": {d: 0.5 for d in self.DIMENSIONS.keys()},
                "dimension_rationales": {d: f"Error: {e}" for d in self.DIMENSIONS.keys()},
            }

    def _calculate_weighted_score(
        self,
        dimension_scores: Dict[str, float]
    ) -> float:
        """Calculate weighted overall score.

        Args:
            dimension_scores: Scores for each dimension

        Returns:
            Weighted overall score (0.0 to 1.0)
        """
        total_score = 0.0
        total_weight = 0.0

        for dimension, score in dimension_scores.items():
            if dimension in self.DIMENSIONS:
                weight = self.DIMENSIONS[dimension]["weight"]
                total_score += score * weight
                total_weight += weight

        return total_score / total_weight if total_weight > 0 else 0.0

    def _generate_feedback(
        self,
        quality_data: Dict[str, Any],
        threshold: float
    ) -> str:
        """Generate human-readable feedback.

        Args:
            quality_data: Quality evaluation data
            threshold: Quality threshold from task

        Returns:
            Feedback string
        """
        scores = quality_data["dimension_scores"]

        # Identify strengths and weaknesses
        strengths = []
        weaknesses = []

        for dimension, score in scores.items():
            if score >= 0.85:
                strengths.append(dimension.replace("_", " "))
            elif score < 0.65:
                weaknesses.append(dimension.replace("_", " "))

        feedback_parts = []

        # Overall assessment
        avg_score = sum(scores.values()) / len(scores)
        if avg_score >= threshold:
            feedback_parts.append(f"Quality threshold met ({avg_score:.2f} >= {threshold})")
        else:
            feedback_parts.append(f"Below threshold ({avg_score:.2f} < {threshold})")

        # Strengths
        if strengths:
            feedback_parts.append(f"Strengths: {', '.join(strengths[:2])}")

        # Weaknesses
        if weaknesses:
            feedback_parts.append(f"Needs improvement: {', '.join(weaknesses[:2])}")

        return "; ".join(feedback_parts)
