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
    # How far the anchor had to be cut. `dropped_primary` counts items
    # removed, so an anchor that is halved five times leaves no trace in any
    # other field -- and "the root summary was cut to a fifth" is exactly the
    # thing that has to be visible when the report reads thin.
    anchor_chars_before: int = 0
    anchor_chars_after: int = 0
    # The same measurement for primary, and it exists for the same reason
    # (D58). `dropped_primary` counts items, and `shrink_once` halves before
    # it drops -- so a clamp that kept all seven child blocks while cutting
    # each of them to an eighth reported `dropped_primary=0` and looked
    # untouched. Sample #13 is exactly that: anchor merely halved, no child
    # dropped, and the prompt still fell 17,812 -> 5,883. Nothing on record
    # could say where those tokens went.
    primary_chars_before: int = 0
    primary_chars_after: int = 0

    @property
    def clamped(self) -> bool:
        return self.bound_after < self.bound_before

    @property
    def anchor_clamped(self) -> bool:
        return self.anchor_chars_after < self.anchor_chars_before

    @property
    def primary_clamped(self) -> bool:
        return self.primary_chars_after < self.primary_chars_before


def halve(text: str) -> str:
    """The default way to make one string smaller: keep its front half.

    Scale-free and needs no tuning, which is why the policy has always used
    it. What it does not know is that these characters carry `[C:xxxxxxxx]`
    claim addresses, and that cutting one out costs the report a citation it
    can never get back. Callers that know better pass their own `compact`
    (D62); this stays the default for callers that have nothing to preserve.
    """

    return text[: len(text) // 2]


def _progress(text: str, compact: Callable[[str], str]) -> str:
    """`compact(text)`, or `halve(text)` if it did not actually shrink.

    `clamp_prompt`'s termination no longer rests on the policy alone once the
    policy is injectable: a `compact` that returns its input, or something
    longer, would spin. The iteration cap still catches it, but the cap
    reports `exhausted` on a prompt that could have been shrunk. Falling back
    here keeps a badly-behaved compactor from costing the caller its report.
    """

    shrunk = compact(text)
    return shrunk if len(shrunk) < len(text) else halve(text)


def shrink_once(
    primary: list[str],
    secondary: list[str],
    anchor: str = "",
    compact: Callable[[str], str] = halve,
) -> tuple[list[str], list[str], str] | None:
    """Drop the least valuable remaining input, once.

    Returns the reduced ``(primary, secondary, anchor)``, or ``None`` when
    there is nothing left to drop.

    Callers map their own material onto the three slots:

    ==================  ====================  ==================  ==========
    call site           primary               secondary           anchor
    ==================  ====================  ==================  ==========
    Synthesizer         child summary blocks  caveats             root answer
      .assemble
    Synthesizer         verified claim lines  child summary       (none)
      .reduce_node                            lines
    ==================  ====================  ==================  ==========

    The question text (reduce_node) is still never passed here.

    POLICY (design D-6, amended D54): secondary is dropped from the end
    first, one item at a time; once secondary is empty, **the longest of
    the primaries and the anchor** is halved; once nothing is longer than
    one character, primary is dropped from the end, one item at a time.
    The anchor is never dropped, only halved -- a report with no root
    summary is worse than a short one.

    The anchor used to sit outside this function entirely, on the grounds
    that the root answer is the most valuable material and must survive.
    It does survive -- but "most valuable" was being read as "unbounded",
    and an oversized anchor is paid for by everything else. Sample #11
    measured the end state: 12 of 12 assembly clamps ran to `exhausted`,
    having dropped every child block and every caveat, because a degraded
    root summary alone exceeded the allowance. The report was then written
    with no claims in its prompt to cite.

    Halving the *longest* keeps the old behaviour whenever the anchor is
    normally sized -- it is only ever chosen when it is the thing that
    does not fit, which is exactly when it should be.
    """
    if secondary:
        return primary, secondary[:-1], anchor
    candidates = [*primary, anchor]
    longest = max(range(len(candidates)), key=lambda i: len(candidates[i]))
    if len(candidates[longest]) > 1:
        if longest == len(primary):
            return primary, secondary, _progress(anchor, compact)
        trimmed = list(primary)
        trimmed[longest] = _progress(trimmed[longest], compact)
        return trimmed, secondary, anchor
    if not primary:
        return None
    return primary[:-1], secondary, anchor


def clamp_prompt(
    *,
    model: str,
    allowance: int,
    render_prompt: Callable[[list[str], list[str], str], str],
    primary: list[str],
    secondary: list[str],
    anchor: str = "",
    compact: Callable[[str], str] = halve,
) -> ClampResult:
    """Render, measure, shrink, repeat until the prompt fits ``allowance``.

    Termination does NOT depend on ``shrink_once`` being correct -- but not
    for the reason a fixed-point check alone can promise. A step that
    returns the exact lists it was given is caught immediately (below), but
    a policy that returns something *different* every time without ever
    shrinking -- e.g. one that alternates between two states -- passes that
    check on every step and would loop forever under it alone. A monkeypatched
    policy doing exactly that hung this function past a 10s test timeout
    before this cap existed.

    What actually guarantees termination is ``max_iterations``, derived from
    the inputs themselves: ``len(primary) + len(secondary)`` (the most
    element-drop steps either list can ever take) plus the summed character
    length of both **and of the anchor** (the most halving steps
    ``shrink_once``'s own policy can ever take, since each halving at least
    removes one character and a binary search style halving needs only
    O(log n) of those). Any
    legitimately-progressing policy finishes within that many steps, so the
    cap can never cut one short; a policy that is not progressing hits the
    cap and this function still returns.
    """
    original_primary = len(primary)
    original_secondary = len(secondary)
    original_anchor = len(anchor)
    original_primary_chars = sum(len(item) for item in primary)
    prompt = render_prompt(primary, secondary, anchor)
    bound_before = prompt_input_bound(model, prompt)

    max_iterations = (
        len(primary)
        + len(secondary)
        + sum(len(item) for item in primary)
        + sum(len(item) for item in secondary)
        + len(anchor)
    )
    iterations = 0

    while prompt_input_bound(model, prompt) > allowance:
        shrunk = shrink_once(primary, secondary, anchor, compact)
        if shrunk is None or shrunk == (primary, secondary, anchor):
            return ClampResult(
                prompt=prompt,
                bound_before=bound_before,
                bound_after=prompt_input_bound(model, prompt),
                dropped_primary=original_primary - len(primary),
                dropped_secondary=original_secondary - len(secondary),
                exhausted=True,
                anchor_chars_before=original_anchor,
                anchor_chars_after=len(anchor),
                primary_chars_before=original_primary_chars,
                primary_chars_after=sum(len(item) for item in primary),
            )
        iterations += 1
        if iterations > max_iterations:
            return ClampResult(
                prompt=prompt,
                bound_before=bound_before,
                bound_after=prompt_input_bound(model, prompt),
                dropped_primary=original_primary - len(primary),
                dropped_secondary=original_secondary - len(secondary),
                exhausted=True,
                anchor_chars_before=original_anchor,
                anchor_chars_after=len(anchor),
                primary_chars_before=original_primary_chars,
                primary_chars_after=sum(len(item) for item in primary),
            )
        primary, secondary, anchor = shrunk
        prompt = render_prompt(primary, secondary, anchor)

    return ClampResult(
        prompt=prompt,
        bound_before=bound_before,
        bound_after=prompt_input_bound(model, prompt),
        dropped_primary=original_primary - len(primary),
        dropped_secondary=original_secondary - len(secondary),
        exhausted=False,
        anchor_chars_before=original_anchor,
        anchor_chars_after=len(anchor),
        primary_chars_before=original_primary_chars,
        primary_chars_after=sum(len(item) for item in primary),
    )
