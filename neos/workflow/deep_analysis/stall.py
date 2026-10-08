"""D15 stall policy: when a question has stopped moving, and when a whole run has.

The tracker only counts and decides. What a stall *does* -- the ledger line,
the event, cancelling the child, splitting the question, `SystemicWorkerFailure`
-- stays with the Orchestrator, which acts on the verdict. The counts are
in-memory: a resumed run starts them at zero, as it always has.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Progress:
    """A question's progress signals at one moment. `None` = the ledger cannot say."""

    spent_tokens: int
    verified: int | None
    feedback: int | None


async def _verified_count(ledger, question_id: str) -> int | None:
    fn = getattr(ledger, "verified_claims", None)
    if fn is None:
        return None
    return len(await fn(question_id))


async def _feedback_signal(ledger, question_id: str) -> int | None:
    fn = getattr(ledger, "feedback_count", None)
    if fn is None:
        return None
    return await fn(question_id)


async def snapshot(ledger, question) -> Progress:
    """The signals before a pass mutates anything."""
    return Progress(
        spent_tokens=question.spent_tokens,
        verified=await _verified_count(ledger, question.id),
        feedback=await _feedback_signal(ledger, question.id),
    )


async def made_progress(ledger, question_id: str, before: Progress) -> bool:
    """A pass made progress iff it produced a new verified claim, new rejection
    feedback, or burned tokens. An inert pass (partial with 0 tokens/0 claims,
    or a mismatch-skipped assignment) fails all three. Unavailable signals
    (limited fakes) count as progress -> no stall. Reads stop at the first
    signal that moved."""
    question = await ledger.get_question(question_id)
    spent_after = question.spent_tokens if question is not None else before.spent_tokens
    if spent_after > before.spent_tokens:
        return True
    verified_after = await _verified_count(ledger, question_id)
    if before.verified is None or verified_after is None or verified_after > before.verified:
        return True
    feedback_after = await _feedback_signal(ledger, question_id)
    if before.feedback is None or feedback_after is None or feedback_after > before.feedback:
        return True
    return False


class StallTracker:
    """Consecutive no-progress passes per question, and consecutive all-failed rounds."""

    def __init__(self, max_rounds: int) -> None:
        self.max_rounds = max_rounds
        self._counts: dict[str, int] = {}
        self._all_failed_rounds = 0

    def record(self, question_id: str, made_progress: bool) -> bool:
        """Count one pass. True when this question just reached the cap."""
        if made_progress:
            self._counts[question_id] = 0
            return False
        count = self._counts.get(question_id, 0) + 1
        self._counts[question_id] = count
        return count >= self.max_rounds

    def count(self, question_id: str) -> int:
        return self._counts.get(question_id, 0)

    @property
    def failed_rounds(self) -> int:
        return self._all_failed_rounds

    def clear(self, question_id: str) -> None:
        self._counts[question_id] = 0

    def record_round(self, all_failed: bool) -> int | None:
        """Count one round. The streak length once it reaches the cap, else None."""
        if not all_failed:
            self._all_failed_rounds = 0
            return None
        self._all_failed_rounds += 1
        if self._all_failed_rounds < self.max_rounds:
            return None
        return self._all_failed_rounds
