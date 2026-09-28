"""Pareto parent selection. No database, settings, or upstream gepa."""

from __future__ import annotations

import random

import pytest

from neos.gepa_opt.pareto import select_parent

pytestmark = pytest.mark.no_db


def test_dominated_program_is_dropped_before_draw() -> None:
    """Program 1 shares every val id with program 0; only 0 can be drawn."""
    fronts = {0: {0, 1}, 1: {0}}
    scores = [0.2, 0.9]
    for seed in range(8):
        chosen = select_parent(fronts, scores, random.Random(seed))
        assert chosen == 0


def test_survivor_weight_is_front_frequency() -> None:
    """Neither program is dominated. Multiset is each index repeated by front count."""
    fronts = {0: {0}, 1: {0, 1}, 2: {1}}
    scores = [0.4, 0.6, float("-inf")]
    sampling = [0, 0, 1, 1]
    expected = random.Random(0).choice(sampling)
    assert expected == 1
    chosen = select_parent(fronts, scores, random.Random(0))
    assert chosen == expected


def test_programs_absent_from_every_front_are_not_drawn() -> None:
    fronts = {0: {0}, 1: {0}}
    scores = [0.5, 0.9, 0.1]
    for seed in range(8):
        assert select_parent(fronts, scores, random.Random(seed)) == 0


def test_omitted_candidate_is_not_drawn() -> None:
    """Rejected candidate (no val mean) is left out of fronts and is not a parent."""
    fronts = {0: {0}, 1: {2}}
    scores = [0.5, float("-inf"), 0.7]
    seen: set[int] = set()
    for seed in range(16):
        seen.add(select_parent(fronts, scores, random.Random(seed)))
    assert 1 not in seen
    assert seen <= {0, 2}


def test_empty_survivors_raise() -> None:
    with pytest.raises(RuntimeError):
        select_parent({}, [], random.Random(0))
    with pytest.raises(RuntimeError):
        select_parent({0: set()}, [float("-inf")], random.Random(0))
