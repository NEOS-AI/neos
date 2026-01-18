"""Performance Grader - Evaluates execution performance.

This grader checks:
1. Execution time within reasonable bounds
2. Token usage efficiency
3. API call efficiency
4. Resource utilization
"""

from typing import Dict, Any
import logging

from ..base import BaseGrader, GraderResult, GraderError

logger = logging.getLogger(__name__)


class PerformanceGrader(BaseGrader):
    """Grades agent execution performance.

    Evaluates:
    - Execution time
    - Token efficiency
    - API call efficiency
    - Overall resource usage

    Example:
        ```python
        grader = PerformanceGrader()
        result = await grader.grade(task, trial)

        print(f"Duration: {result.details['duration_seconds']}s")
        print(f"Tokens used: {result.details['total_tokens']}")
        ```
    """

    # Performance thresholds
    MAX_DURATION_SECONDS = 1200  # 20 minutes
    OPTIMAL_DURATION_SECONDS = 600  # 10 minutes

    MAX_TOKENS = 300000
    OPTIMAL_TOKENS = 150000

    MAX_LLM_CALLS = 100
    OPTIMAL_LLM_CALLS = 50

    def __init__(self):
        """Initialize performance grader."""
        super().__init__(
            grader_id="performance",
            grader_type="code",
            weight=0.05,
            description="Evaluates execution performance and efficiency"
        )

    async def grade(
        self,
        task: Any,  # EvalTask
        trial: Any,  # EvalTrial
    ) -> GraderResult:
        """Grade performance.

        Args:
            task: Evaluation task with estimated_runtime
            trial: Trial with timing and metadata

        Returns:
            GraderResult with performance score
        """
        try:
            # Extract metrics
            duration = trial.duration_seconds
            metadata = trial.metadata

            tokens = metadata.get("estimated_total_tokens", 0)
            llm_calls = metadata.get("llm_calls", 0)

            # Calculate individual scores
            time_score = self._calculate_time_score(duration, task.estimated_runtime)
            token_score = self._calculate_token_score(tokens)
            call_score = self._calculate_call_score(llm_calls)

            # Overall score (weighted)
            overall_score = (
                time_score * 0.5 +
                token_score * 0.3 +
                call_score * 0.2
            )

            # Pass criteria (not too strict - just flag major issues)
            passed = (
                duration <= self.MAX_DURATION_SECONDS and
                tokens <= self.MAX_TOKENS
            )

            # Generate feedback
            feedback = self._generate_feedback(
                duration=duration,
                time_score=time_score,
                tokens=tokens,
                token_score=token_score,
                llm_calls=llm_calls,
                call_score=call_score
            )

            return GraderResult(
                grader_id=self.grader_id,
                score=overall_score,
                passed=passed,
                feedback=feedback,
                details={
                    "duration_seconds": duration,
                    "estimated_runtime": task.estimated_runtime,
                    "time_score": time_score,
                    "total_tokens": tokens,
                    "token_score": token_score,
                    "llm_calls": llm_calls,
                    "call_score": call_score,
                }
            )

        except Exception as e:
            logger.error(f"Performance grading failed: {e}", exc_info=True)
            raise GraderError(f"Performance grading failed: {e}")

    def _calculate_time_score(
        self,
        duration: float,
        estimated: int
    ) -> float:
        """Calculate time efficiency score.

        Args:
            duration: Actual duration in seconds
            estimated: Estimated duration in seconds

        Returns:
            Time score (0.0 to 1.0)
        """
        if duration <= self.OPTIMAL_DURATION_SECONDS:
            return 1.0  # Excellent

        if duration <= estimated:
            # Good: within estimate
            return 0.8

        if duration <= self.MAX_DURATION_SECONDS:
            # Acceptable: within max bounds
            ratio = (self.MAX_DURATION_SECONDS - duration) / (
                self.MAX_DURATION_SECONDS - estimated
            )
            return 0.5 + (ratio * 0.3)

        # Poor: exceeded max
        return max(0.0, 0.5 - ((duration - self.MAX_DURATION_SECONDS) / self.MAX_DURATION_SECONDS))

    def _calculate_token_score(self, tokens: int) -> float:
        """Calculate token efficiency score.

        Args:
            tokens: Total tokens used

        Returns:
            Token score (0.0 to 1.0)
        """
        if tokens <= self.OPTIMAL_TOKENS:
            return 1.0  # Excellent efficiency

        if tokens <= self.MAX_TOKENS:
            # Acceptable
            ratio = (self.MAX_TOKENS - tokens) / (
                self.MAX_TOKENS - self.OPTIMAL_TOKENS
            )
            return 0.6 + (ratio * 0.4)

        # Poor: exceeded max
        return max(0.0, 0.6 - ((tokens - self.MAX_TOKENS) / self.MAX_TOKENS))

    def _calculate_call_score(self, llm_calls: int) -> float:
        """Calculate LLM call efficiency score.

        Args:
            llm_calls: Number of LLM API calls

        Returns:
            Call efficiency score (0.0 to 1.0)
        """
        if llm_calls <= self.OPTIMAL_LLM_CALLS:
            return 1.0  # Excellent efficiency

        if llm_calls <= self.MAX_LLM_CALLS:
            # Acceptable
            ratio = (self.MAX_LLM_CALLS - llm_calls) / (
                self.MAX_LLM_CALLS - self.OPTIMAL_LLM_CALLS
            )
            return 0.6 + (ratio * 0.4)

        # Poor: too many calls
        return max(0.0, 0.6 - ((llm_calls - self.MAX_LLM_CALLS) / self.MAX_LLM_CALLS))

    def _generate_feedback(
        self,
        duration: float,
        time_score: float,
        tokens: int,
        token_score: float,
        llm_calls: int,
        call_score: float
    ) -> str:
        """Generate human-readable feedback.

        Args:
            duration: Execution duration
            time_score: Time efficiency score
            tokens: Token count
            token_score: Token efficiency score
            llm_calls: LLM call count
            call_score: Call efficiency score

        Returns:
            Feedback string
        """
        feedback_parts = []

        # Time feedback
        if time_score >= 0.8:
            feedback_parts.append(f"Completed in {duration:.0f}s (efficient)")
        elif time_score >= 0.5:
            feedback_parts.append(f"Completed in {duration:.0f}s (acceptable)")
        else:
            feedback_parts.append(f"Slow execution: {duration:.0f}s")

        # Token feedback
        if token_score >= 0.8:
            feedback_parts.append(f"{tokens:,} tokens (efficient)")
        elif token_score >= 0.6:
            feedback_parts.append(f"{tokens:,} tokens (acceptable)")
        else:
            feedback_parts.append(f"High token usage: {tokens:,}")

        # Call feedback
        if llm_calls > self.MAX_LLM_CALLS:
            feedback_parts.append(f"Many LLM calls: {llm_calls}")
        elif llm_calls <= self.OPTIMAL_LLM_CALLS:
            feedback_parts.append(f"{llm_calls} LLM calls (efficient)")

        return "; ".join(feedback_parts)
