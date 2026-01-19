"""Grader registry for managing and accessing graders.

This module provides a centralized registry for all graders in the
evaluation framework.
"""

from typing import Dict, List, Optional, Type
from .base import BaseGrader, GraderResult


class GraderRegistry:
    """Central registry for all graders.

    The registry allows:
    - Registering graders by ID
    - Looking up graders by ID or type
    - Getting grader weights for scoring
    - Listing available graders

    Example:
        ```python
        registry = GraderRegistry()

        # Register a grader
        registry.register(CitationAccuracyGrader())

        # Get a grader
        grader = registry.get("citation_accuracy")

        # List all graders
        all_graders = registry.list_all()

        # Get grader weights
        weights = registry.get_weights()
        ```
    """

    def __init__(self):
        """Initialize empty registry."""
        self._graders: Dict[str, BaseGrader] = {}

    def register(self, grader: BaseGrader) -> None:
        """Register a grader.

        Args:
            grader: The grader instance to register

        Raises:
            ValueError: If grader_id already registered
        """
        if grader.grader_id in self._graders:
            raise ValueError(f"Grader '{grader.grader_id}' is already registered")

        self._graders[grader.grader_id] = grader

    def unregister(self, grader_id: str) -> None:
        """Unregister a grader.

        Args:
            grader_id: ID of grader to remove

        Raises:
            KeyError: If grader_id not found
        """
        if grader_id not in self._graders:
            raise KeyError(f"Grader '{grader_id}' not found in registry")

        del self._graders[grader_id]

    def get(self, grader_id: str) -> Optional[BaseGrader]:
        """Get a grader by ID.

        Args:
            grader_id: ID of grader to retrieve

        Returns:
            Grader instance or None if not found
        """
        return self._graders.get(grader_id)

    def get_by_type(self, grader_type: str) -> List[BaseGrader]:
        """Get all graders of a specific type.

        Args:
            grader_type: "code", "model", or "human"

        Returns:
            List of graders matching the type
        """
        return [
            grader
            for grader in self._graders.values()
            if grader.grader_type == grader_type
        ]

    def list_all(self) -> List[BaseGrader]:
        """Get all registered graders.

        Returns:
            List of all graders
        """
        return list(self._graders.values())

    def list_ids(self) -> List[str]:
        """Get all registered grader IDs.

        Returns:
            List of grader IDs
        """
        return list(self._graders.keys())

    def get_weights(self) -> Dict[str, float]:
        """Get weights for all registered graders.

        Returns:
            Dictionary mapping grader_id to weight
        """
        return {
            grader_id: grader.weight
            for grader_id, grader in self._graders.items()
        }

    def set_weight(self, grader_id: str, weight: float) -> None:
        """Update a grader's weight.

        Args:
            grader_id: ID of grader to update
            weight: New weight (0.0 to 1.0)

        Raises:
            KeyError: If grader not found
            ValueError: If weight out of range
        """
        if grader_id not in self._graders:
            raise KeyError(f"Grader '{grader_id}' not found")

        if not 0.0 <= weight <= 1.0:
            raise ValueError(f"Weight must be between 0.0 and 1.0: {weight}")

        self._graders[grader_id].weight = weight

    def has_grader(self, grader_id: str) -> bool:
        """Check if a grader is registered.

        Args:
            grader_id: ID to check

        Returns:
            True if registered, False otherwise
        """
        return grader_id in self._graders

    def get_info(self) -> List[Dict[str, any]]:
        """Get information about all registered graders.

        Returns:
            List of grader info dictionaries
        """
        return [grader.get_info() for grader in self._graders.values()]

    def clear(self) -> None:
        """Remove all graders from registry."""
        self._graders.clear()

    def __len__(self) -> int:
        """Get number of registered graders."""
        return len(self._graders)

    def __repr__(self) -> str:
        """String representation."""
        return f"GraderRegistry(graders={len(self._graders)})"


# Global registry instance
_global_registry = GraderRegistry()


def get_global_registry() -> GraderRegistry:
    """Get the global grader registry instance.

    Returns:
        Global GraderRegistry instance
    """
    return _global_registry


def register_grader(grader: BaseGrader) -> None:
    """Register a grader in the global registry.

    Args:
        grader: Grader to register
    """
    _global_registry.register(grader)


def get_grader(grader_id: str) -> Optional[BaseGrader]:
    """Get a grader from the global registry.

    Args:
        grader_id: ID of grader

    Returns:
        Grader instance or None
    """
    return _global_registry.get(grader_id)
