"""Model-based graders for subjective evaluation.

This module contains graders that use LLM API calls to evaluate
subjective quality aspects that deterministic code cannot assess.
"""

from .topic_coverage import TopicCoverageGrader
from .quality_assessment import QualityAssessmentGrader
from .factual_accuracy import FactualAccuracyGrader

__all__ = [
    "TopicCoverageGrader",
    "QualityAssessmentGrader",
    "FactualAccuracyGrader",
]


def register_all_model_graders(registry):
    """Register all model-based graders in a registry.

    Args:
        registry: GraderRegistry instance

    Example:
        ```python
        from graders import GraderRegistry
        from graders.model_based import register_all_model_graders

        registry = GraderRegistry()
        register_all_model_graders(registry)
        ```
    """
    registry.register(TopicCoverageGrader())
    registry.register(QualityAssessmentGrader())
    registry.register(FactualAccuracyGrader())
