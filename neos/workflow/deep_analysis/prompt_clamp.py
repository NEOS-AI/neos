"""Force a finalization prompt under its input allowance.

The floor can only be honoured if the input side is bounded. `reserve()`
charges `conservative_input_bound(request) + output`, so a prompt that grows
with the question tree consumes a stage's whole reserve before one output
token is granted -- which is how `report_assembly` went 574 runs without a
single reservation.

Nothing here estimates. The prompt is measured with `prompt_input_bound`,
the same function the budget charges with, and shrunk until it fits.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .llm import prompt_input_bound


@dataclass(frozen=True, slots=True)
class ClampResult:
    prompt: str
    bound_before: int
    bound_after: int
    dropped_primary: int
    dropped_secondary: int
    exhausted: bool

    @property
    def clamped(self) -> bool:
        return self.bound_after < self.bound_before


def shrink_once(
    primary: list[str],
    secondary: list[str],
) -> tuple[list[str], list[str]] | None:
    """Drop the least valuable remaining input, once.

    Returns the reduced ``(primary, secondary)``, or ``None`` when there is
    nothing left to drop.

    Callers map their own material onto the two slots:

    ==================  ==========================  ====================
    call site           primary                     secondary
    ==================  ==========================  ====================
    Synthesizer         child summary blocks        caveats
      .assemble
    Synthesizer         verified claim lines        child summary lines
      .reduce_node
    ==================  ==========================  ====================

    Neither the root answer (assemble) nor the question text (reduce_node)
    is passed here -- those are never dropped.

    POLICY (design D-6): secondary is dropped from the end first, one item
    at a time; once secondary is empty, the longest remaining primary is
    halved; once no primary is longer than one character, primary is
    dropped from the end, one item at a time. Halving is scale-free -- it
    converges regardless of how oversized the input is, so no tunable
    constant is needed here.
    """
    if secondary:
        return primary, secondary[:-1]
    if not primary:
        return None
    longest = max(range(len(primary)), key=lambda i: len(primary[i]))
    if len(primary[longest]) > 1:
        trimmed = list(primary)
        trimmed[longest] = trimmed[longest][: len(trimmed[longest]) // 2]
        return trimmed, secondary
    return primary[:-1], secondary


def clamp_prompt(
    *,
    model: str,
    allowance: int,
    render_prompt: Callable[[list[str], list[str]], str],
    primary: list[str],
    secondary: list[str],
) -> ClampResult:
    """Render, measure, shrink, repeat until the prompt fits ``allowance``.

    Termination does not depend on ``shrink_once`` being correct: a step
    that returns the same lists it was given ends the loop as surely as one
    that returns ``None``. The policy is the part a human tunes, so the loop
    refuses to trust it.
    """
    original_primary = len(primary)
    original_secondary = len(secondary)
    prompt = render_prompt(primary, secondary)
    bound_before = prompt_input_bound(model, prompt)

    while prompt_input_bound(model, prompt) > allowance:
        shrunk = shrink_once(primary, secondary)
        if shrunk is None or shrunk == (primary, secondary):
            return ClampResult(
                prompt=prompt,
                bound_before=bound_before,
                bound_after=prompt_input_bound(model, prompt),
                dropped_primary=original_primary - len(primary),
                dropped_secondary=original_secondary - len(secondary),
                exhausted=True,
            )
        primary, secondary = shrunk
        prompt = render_prompt(primary, secondary)

    return ClampResult(
        prompt=prompt,
        bound_before=bound_before,
        bound_after=prompt_input_bound(model, prompt),
        dropped_primary=original_primary - len(primary),
        dropped_secondary=original_secondary - len(secondary),
        exhausted=False,
    )
