"""Pareto parent selection. No settings, jobs, or database."""

from __future__ import annotations

import random


def select_parent(
    fronts: dict[int, set[int]],
    scores: list[float],
    rng: random.Random,
) -> int:
    """Draw a non-dominated parent. Weight is how many surviving fronts contain it."""
    programs = sorted({idx for owners in fronts.values() for idx in owners})
    ordered = sorted(programs, key=lambda idx: scores[idx])
    remaining = set(programs)
    active = {vid: owners for vid, owners in fronts.items() if owners}

    while True:
        removed = False
        for program in ordered:
            if program not in remaining:
                continue
            dominated = True
            for owners in active.values():
                if program not in owners:
                    continue
                if not (owners & remaining) - {program}:
                    dominated = False
                    break
            if dominated:
                remaining.remove(program)
                removed = True
                break
        if not removed:
            break

    frequency = dict.fromkeys(remaining, 0)
    for owners in active.values():
        for program in owners:
            if program in frequency:
                frequency[program] += 1

    sampling_list: list[int] = []
    for program in sorted(remaining):
        sampling_list.extend([program] * frequency[program])
    if not sampling_list:
        raise RuntimeError("no pareto survivors")
    return rng.choice(sampling_list)
