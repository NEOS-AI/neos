"""Code-based graders for deterministic evaluation.

This module contains graders that perform objective, deterministic
checks on agent outputs without requiring LLM calls.
"""

from .citation_accuracy import CitationAccuracyGrader
from .source_diversity import SourceDiversityGrader
from .structure_completeness import StructureCompletenessGrader
from .metadata_validation import MetadataValidationGrader
from .performance import PerformanceGrader

__all__ = [
    "CitationAccuracyGrader",
    "SourceDiversityGrader",
    "StructureCompletenessGrader",
    "MetadataValidationGrader",
    "PerformanceGrader",
]


def register_all_code_graders(registry):
    """Register all code-based graders in a registry.

    Args:
        registry: GraderRegistry instance

    Example:
        ```python
        from graders import GraderRegistry
        from graders.code_based import register_all_code_graders

        registry = GraderRegistry()
        register_all_code_graders(registry)
        ```
    """
    registry.register(CitationAccuracyGrader())
    registry.register(SourceDiversityGrader())
    registry.register(StructureCompletenessGrader())
    registry.register(MetadataValidationGrader())
    registry.register(PerformanceGrader())
