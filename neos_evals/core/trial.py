"""Evaluation trial data model.

This module defines the EvalTrial dataclass, which represents a single
execution attempt of an evaluation task.
"""

from dataclasses import dataclass, field
from typing import Dict, Any, Optional
from datetime import datetime
import uuid


@dataclass
class EvalTrial:
    """Single trial (execution) of an evaluation task.

    A trial represents one complete execution of the research agent
    on a specific task. Multiple trials can be run for the same task
    to calculate metrics like pass@k.

    Attributes:
        trial_id: Unique identifier for this trial
        task_id: ID of the task being evaluated
        trial_number: Trial number (1, 2, 3 for pass@k)
        started_at: When the trial started
        completed_at: When the trial completed
        status: Current status (running, completed, failed, timeout)
        final_report: Generated research report
        metadata: Agent metadata (from ResearchMetadata)
        transcript: Full execution log with all phases
        grader_scores: Scores from each grader {grader_id: score}
        overall_score: Weighted average of all grader scores
        passed: Whether this trial met the pass threshold
        error: Error message if trial failed

    Example:
        ```python
        trial = EvalTrial(
            task_id="task_123",
            trial_number=1,
            status="running"
        )
        # ... execute agent ...
        trial.status = "completed"
        trial.final_report = report
        trial.overall_score = 0.85
        trial.passed = True
        ```
    """

    # Identifiers
    trial_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    task_id: str = ""
    trial_number: int = 1

    # Timing
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_seconds: float = 0.0

    # Status
    status: str = "pending"  # pending, running, completed, failed, timeout

    # Agent outputs
    final_report: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    transcript: Dict[str, Any] = field(default_factory=dict)

    # Grading results
    grader_scores: Dict[str, float] = field(default_factory=dict)
    grader_feedback: Dict[str, str] = field(default_factory=dict)
    grader_details: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    overall_score: float = 0.0
    passed: bool = False

    # Error handling
    error: Optional[str] = None
    error_phase: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert trial to dictionary for JSON serialization."""
        return {
            "trial_id": self.trial_id,
            "task_id": self.task_id,
            "trial_number": self.trial_number,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_seconds": self.duration_seconds,
            "status": self.status,
            "final_report": self.final_report,
            "metadata": self.metadata,
            "transcript": self.transcript,
            "grader_scores": self.grader_scores,
            "grader_feedback": self.grader_feedback,
            "grader_details": self.grader_details,
            "overall_score": self.overall_score,
            "passed": self.passed,
            "error": self.error,
            "error_phase": self.error_phase,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EvalTrial":
        """Create trial from dictionary."""
        # Handle datetime fields
        if isinstance(data.get("started_at"), str):
            data["started_at"] = datetime.fromisoformat(data["started_at"])
        if isinstance(data.get("completed_at"), str):
            data["completed_at"] = datetime.fromisoformat(data["completed_at"])

        return cls(**data)

    def start(self) -> None:
        """Mark trial as started."""
        self.started_at = datetime.now()
        self.status = "running"

    def complete(self) -> None:
        """Mark trial as completed."""
        self.completed_at = datetime.now()
        self.status = "completed"
        if self.started_at:
            self.duration_seconds = (self.completed_at - self.started_at).total_seconds()

    def fail(self, error: str, phase: Optional[str] = None) -> None:
        """Mark trial as failed.

        Args:
            error: Error message
            phase: Optional phase where error occurred
        """
        self.completed_at = datetime.now()
        self.status = "failed"
        self.error = error
        self.error_phase = phase
        if self.started_at:
            self.duration_seconds = (self.completed_at - self.started_at).total_seconds()

    def timeout(self) -> None:
        """Mark trial as timed out."""
        self.completed_at = datetime.now()
        self.status = "timeout"
        if self.started_at:
            self.duration_seconds = (self.completed_at - self.started_at).total_seconds()

    def add_grader_result(
        self,
        grader_id: str,
        score: float,
        feedback: str = "",
        details: Optional[Dict[str, Any]] = None
    ) -> None:
        """Add result from a grader.

        Args:
            grader_id: Identifier of the grader
            score: Score from 0.0 to 1.0
            feedback: Human-readable feedback
            details: Detailed grader-specific information
        """
        self.grader_scores[grader_id] = score
        self.grader_feedback[grader_id] = feedback
        if details:
            self.grader_details[grader_id] = details

    def calculate_overall_score(self, grader_weights: Dict[str, float]) -> float:
        """Calculate weighted average score from all graders.

        Args:
            grader_weights: Mapping of grader_id to weight

        Returns:
            Weighted average score (0.0 to 1.0)
        """
        total_weight = 0.0
        weighted_score = 0.0

        for grader_id, score in self.grader_scores.items():
            weight = grader_weights.get(grader_id, 0.0)
            weighted_score += score * weight
            total_weight += weight

        if total_weight > 0:
            self.overall_score = weighted_score / total_weight
        else:
            self.overall_score = 0.0

        return self.overall_score

    def check_passed(self, pass_threshold: float) -> bool:
        """Check if trial passed based on overall score.

        Args:
            pass_threshold: Minimum score to pass (0.0 to 1.0)

        Returns:
            True if passed, False otherwise
        """
        self.passed = self.overall_score >= pass_threshold
        return self.passed

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of the trial results.

        Returns:
            Dictionary with key trial information
        """
        return {
            "trial_id": self.trial_id,
            "trial_number": self.trial_number,
            "status": self.status,
            "duration_seconds": self.duration_seconds,
            "overall_score": self.overall_score,
            "passed": self.passed,
            "grader_scores": self.grader_scores,
            "error": self.error,
        }

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"EvalTrial(trial_id='{self.trial_id[:8]}...', "
            f"trial_number={self.trial_number}, "
            f"status='{self.status}', "
            f"score={self.overall_score:.2f}, "
            f"passed={self.passed})"
        )
