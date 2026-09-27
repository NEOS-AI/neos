"""Caller-supplied fitness registry. Empty until a caller registers one."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

Evaluator = Callable[..., Any]

_REGISTRY: dict[str, Evaluator] = {}


def register_evaluator(surface: str, fn: Evaluator) -> None:
    """Register the only fitness function for a surface. No default scorer."""
    _REGISTRY[surface] = fn


def get_evaluator(surface: str) -> Evaluator | None:
    """Return the registered evaluator, or None when the surface has none."""
    return _REGISTRY.get(surface)


def clear_evaluators() -> None:
    """Test helper. Production code does not call this."""
    _REGISTRY.clear()
