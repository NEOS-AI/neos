"""Caller-supplied fitness registry. Empty until a caller registers one.

A future DA subject-prompt fitness may call graders on a copy of a subject
prompt. It must not open judge.md or report_judge.md for writing.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

Evaluator = Callable[..., Any]

_REGISTRY: dict[str, Evaluator] = {}
_FORBIDDEN = ("CodingTaskStatus", "VERDICT")


def register_evaluator(surface: str, fn: Evaluator) -> None:
    """Register the only fitness function for a surface. No default scorer."""
    try:
        source = inspect.getsource(fn)
    except OSError:
        source = ""
    if any(token in source for token in _FORBIDDEN):
        raise ValueError("evaluator must not score run status or a verify verdict")
    _REGISTRY[surface] = fn


def get_evaluator(surface: str) -> Evaluator | None:
    """Return the registered evaluator, or None when the surface has none."""
    return _REGISTRY.get(surface)


def clear_evaluators() -> None:
    """Test helper. Production code does not call this."""
    _REGISTRY.clear()
