"""Evaluation task data model.

This module defines the EvalTask dataclass, which represents a single
evaluation scenario for the research agent.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from datetime import datetime
import uuid


@dataclass
class EvalTask:
    """Single evaluation task for the research agent.

    An evaluation task defines:
    - Input query
    - Expected outcomes (sections, topics, sources)
    - Success criteria (graders, thresholds)
    - Task metadata (difficulty, category)

    Example:
        ```python
        task = EvalTask(
            name="Basic Quantum Computing",
            query="What is quantum computing?",
            expected_sections=["Introduction", "Technical Principles"],
            required_topics=["qubits", "superposition"],
            min_sources=50,
            quality_threshold=0.8,
            graders=["citation_accuracy", "topic_coverage"],
            pass_threshold=0.8,
            difficulty="easy",
            category="factual"
        )
        ```
    """

    # Identifiers
    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""

    # Input
    query: str = ""

    # Expected outcomes
    expected_sections: List[str] = field(default_factory=list)
    required_topics: List[str] = field(default_factory=list)
    min_sources: int = 50
    quality_threshold: float = 0.8

    # Success criteria
    graders: List[str] = field(default_factory=list)
    pass_threshold: float = 0.8

    # Metadata
    difficulty: str = "medium"  # "easy", "medium", "hard"
    category: str = "factual"   # "factual", "comparative", "controversial", "regression"
    estimated_runtime: int = 600  # Seconds

    # Optional fields
    description: Optional[str] = None
    reference_solution: Optional[str] = None
    tags: List[str] = field(default_factory=list)

    # Tracking
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """Convert task to dictionary for JSON serialization."""
        return {
            "task_id": self.task_id,
            "name": self.name,
            "query": self.query,
            "expected_sections": self.expected_sections,
            "required_topics": self.required_topics,
            "min_sources": self.min_sources,
            "quality_threshold": self.quality_threshold,
            "graders": self.graders,
            "pass_threshold": self.pass_threshold,
            "difficulty": self.difficulty,
            "category": self.category,
            "estimated_runtime": self.estimated_runtime,
            "description": self.description,
            "reference_solution": self.reference_solution,
            "tags": self.tags,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EvalTask":
        """Create task from dictionary."""
        # Handle datetime fields
        if isinstance(data.get("created_at"), str):
            data["created_at"] = datetime.fromisoformat(data["created_at"])
        if isinstance(data.get("updated_at"), str):
            data["updated_at"] = datetime.fromisoformat(data["updated_at"])

        return cls(**data)

    def validate(self) -> List[str]:
        """Validate task configuration.

        Returns:
            List of validation error messages. Empty list if valid.
        """
        errors = []

        if not self.name:
            errors.append("Task name is required")

        if not self.query:
            errors.append("Query is required")

        if not self.graders:
            errors.append("At least one grader must be specified")

        if not 0.0 <= self.pass_threshold <= 1.0:
            errors.append("Pass threshold must be between 0.0 and 1.0")

        if not 0.0 <= self.quality_threshold <= 1.0:
            errors.append("Quality threshold must be between 0.0 and 1.0")

        if self.min_sources < 0:
            errors.append("min_sources must be non-negative")

        if self.difficulty not in ["easy", "medium", "hard"]:
            errors.append("difficulty must be 'easy', 'medium', or 'hard'")

        if self.category not in ["factual", "comparative", "controversial", "regression"]:
            errors.append("category must be one of: factual, comparative, controversial, regression")

        return errors

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"EvalTask(name='{self.name}', "
            f"category='{self.category}', "
            f"difficulty='{self.difficulty}')"
        )
