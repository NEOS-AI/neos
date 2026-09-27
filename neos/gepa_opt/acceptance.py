"""Strict minibatch-sum acceptance. Does not consult val or test."""

from __future__ import annotations

from collections.abc import Sequence


def accept_strict_minibatch_sum(
    scores_before: Sequence[float],
    scores_after: Sequence[float],
) -> bool:
    """True only when the minibatch sum is strictly greater.

    Empty or unequal lengths return False. Does not consult val or test.
    """
    if len(scores_before) == 0 or len(scores_after) == 0:
        return False
    if len(scores_before) != len(scores_after):
        return False
    return sum(scores_after) > sum(scores_before)
