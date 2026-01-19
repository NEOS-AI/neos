"""Base grader classes and interfaces.

This module defines the abstract base class for all graders and the
GraderResult dataclass for returning grading results.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, Any, Optional
from datetime import datetime


@dataclass
class GraderResult:
    """Result from a single grader evaluation.

    Attributes:
        grader_id: Identifier of the grader
        score: Numeric score from 0.0 (worst) to 1.0 (best)
        passed: Boolean indicating if this grader's criteria were met
        feedback: Human-readable explanation of the result
        details: Additional grader-specific information
        execution_time: Time taken to grade (seconds)
        timestamp: When grading occurred

    Example:
        ```python
        result = GraderResult(
            grader_id="citation_accuracy",
            score=0.92,
            passed=True,
            feedback="46/50 citations valid and properly formatted",
            details={
                "total_citations": 50,
                "valid_citations": 46,
                "invalid_citations": ["[99]", "[100]", "[101]", "[102]"],
                "missing_sources": []
            }
        )
        ```
    """

    grader_id: str
    score: float
    passed: bool
    feedback: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    execution_time: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "grader_id": self.grader_id,
            "score": self.score,
            "passed": self.passed,
            "feedback": self.feedback,
            "details": self.details,
            "execution_time": self.execution_time,
            "timestamp": self.timestamp.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GraderResult":
        """Create from dictionary."""
        if isinstance(data.get("timestamp"), str):
            data["timestamp"] = datetime.fromisoformat(data["timestamp"])
        return cls(**data)

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"GraderResult(grader_id='{self.grader_id}', "
            f"score={self.score:.2f}, "
            f"passed={self.passed})"
        )


class BaseGrader(ABC):
    """Abstract base class for all graders.

    Graders evaluate the quality of agent outputs across different
    dimensions. There are three types of graders:

    1. Code-based: Deterministic, fast, objective checks
    2. Model-based: LLM-powered, flexible, subjective evaluation
    3. Human: Expert review for gold-standard calibration

    Attributes:
        grader_id: Unique identifier for this grader
        grader_type: Type of grader ("code", "model", "human")
        weight: Contribution to overall score (0.0 to 1.0)
        description: Human-readable description

    Example:
        ```python
        class CitationAccuracyGrader(BaseGrader):
            def __init__(self):
                super().__init__(
                    grader_id="citation_accuracy",
                    grader_type="code",
                    weight=0.15,
                    description="Validates citation format and references"
                )

            async def grade(self, task, trial) -> GraderResult:
                # Implementation here
                pass
        ```
    """

    def __init__(
        self,
        grader_id: str,
        grader_type: str,
        weight: float = 1.0,
        description: str = "",
    ):
        """Initialize grader.

        Args:
            grader_id: Unique identifier
            grader_type: "code", "model", or "human"
            weight: Weight in overall score calculation
            description: Human-readable description
        """
        self.grader_id = grader_id
        self.grader_type = grader_type
        self.weight = weight
        self.description = description

        # Validate
        if grader_type not in ["code", "model", "human"]:
            raise ValueError(f"Invalid grader_type: {grader_type}")

        if not 0.0 <= weight <= 1.0:
            raise ValueError(f"Weight must be between 0.0 and 1.0: {weight}")

    @abstractmethod
    async def grade(
        self,
        task: "EvalTask",  # type: ignore
        trial: "EvalTrial",  # type: ignore
    ) -> GraderResult:
        """Grade a trial's output.

        Args:
            task: The evaluation task being graded
            trial: The trial containing agent outputs

        Returns:
            GraderResult with score, feedback, and details

        Raises:
            GraderError: If grading fails
        """
        pass

    async def grade_with_timing(
        self,
        task: "EvalTask",  # type: ignore
        trial: "EvalTrial",  # type: ignore
    ) -> GraderResult:
        """Grade with execution time tracking.

        This is a convenience wrapper that measures grading time.

        Args:
            task: The evaluation task
            trial: The trial to grade

        Returns:
            GraderResult with execution_time populated
        """
        import time

        start_time = time.time()
        try:
            result = await self.grade(task, trial)
            result.execution_time = time.time() - start_time
            return result
        except Exception as e:
            execution_time = time.time() - start_time
            return GraderResult(
                grader_id=self.grader_id,
                score=0.0,
                passed=False,
                feedback=f"Grading failed: {str(e)}",
                details={"error": str(e), "error_type": type(e).__name__},
                execution_time=execution_time,
            )

    def get_info(self) -> Dict[str, Any]:
        """Get grader information.

        Returns:
            Dictionary with grader metadata
        """
        return {
            "grader_id": self.grader_id,
            "grader_type": self.grader_type,
            "weight": self.weight,
            "description": self.description,
        }

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"{self.__class__.__name__}("
            f"grader_id='{self.grader_id}', "
            f"type='{self.grader_type}', "
            f"weight={self.weight})"
        )


class GraderError(Exception):
    """Exception raised when grading fails."""

    pass
