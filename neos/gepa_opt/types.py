"""GEPA kernel types. No settings, jobs, or database."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast


Candidate = dict[str, str]
SplitName = Literal["train", "val", "test"]
EngineLabel = Literal["gepa", "not-gepa"]
OverlayStatus = Literal["staged", "approved", "archived"]

_OVERLAY_STATUSES = frozenset({"staged", "approved", "archived"})


def validate_candidate(candidate: Mapping[object, object]) -> Candidate:
    """Reject a component value that is not str. Keys are non-empty strings."""
    if isinstance(candidate, str) or not isinstance(candidate, Mapping):
        raise TypeError("candidate must be a mapping of str to str")
    checked: Candidate = {}
    for key, value in candidate.items():
        if not isinstance(key, str):
            raise TypeError("candidate component key must be str")
        if key == "":
            raise ValueError("candidate component key must be non-empty")
        if not isinstance(value, str):
            raise TypeError("candidate component value must be str")
        checked[key] = value
    return checked


def validate_overlay_status(status: str) -> OverlayStatus:
    """Only staged, approved, or archived."""
    if status not in _OVERLAY_STATUSES:
        raise ValueError(
            "overlay status must be staged, approved, or archived"
        )
    return cast(OverlayStatus, status)


@dataclass(frozen=True, slots=True)
class EngineConfig:
    """Search config. merge is fixed off. component_cursor is not persisted here."""

    engine_label: EngineLabel
    pareto: bool
    merge: Literal[False] = False
    component_cursor: int = 0

    def __post_init__(self) -> None:
        if self.merge is not False:
            raise ValueError("merge must be False")
        if self.engine_label == "gepa":
            if self.pareto is not True:
                raise ValueError("engine_label='gepa' requires pareto=True")
        elif self.engine_label == "not-gepa":
            if self.pareto is not False:
                raise ValueError("engine_label='not-gepa' requires pareto=False")
        else:
            raise ValueError("engine_label must be 'gepa' or 'not-gepa'")


@dataclass(frozen=True, slots=True)
class ProposerView:
    """What reflection and parent selection may read. No test split."""

    train: Sequence[Mapping[str, Any]]
    val: Sequence[Mapping[str, Any]]
