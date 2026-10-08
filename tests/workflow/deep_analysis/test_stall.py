"""Stall policy (D15): counting is pure; the Orchestrator acts on the verdict."""

from types import SimpleNamespace

import pytest

from neos.workflow.deep_analysis.stall import (
    Progress,
    StallTracker,
    made_progress,
    snapshot,
)

pytestmark = pytest.mark.no_db


class _Ledger:
    def __init__(self, spent=0, verified=0, feedback=0):
        self.question = SimpleNamespace(id="q1", spent_tokens=spent)
        self.verified = verified
        self.feedback = feedback
        self.reads: list[str] = []

    async def get_question(self, qid):
        self.reads.append("get_question")
        return self.question

    async def verified_claims(self, qid):
        self.reads.append("verified_claims")
        return [object()] * self.verified

    async def feedback_count(self, qid):
        self.reads.append("feedback_count")
        return self.feedback


class _MinimalLedger:
    async def get_question(self, qid):
        return SimpleNamespace(id=qid, spent_tokens=0)


def test_record_counts_no_progress_and_reports_the_cap() -> None:
    tracker = StallTracker(max_rounds=2)

    assert tracker.record("q1", False) is False
    assert tracker.record("q1", False) is True
    assert tracker.count("q1") == 2


def test_progress_resets_the_count() -> None:
    tracker = StallTracker(max_rounds=3)
    tracker.record("q1", False)

    assert tracker.record("q1", True) is False
    assert tracker.count("q1") == 0


def test_clear_forgets_a_question() -> None:
    tracker = StallTracker(max_rounds=3)
    tracker.record("q1", False)
    tracker.clear("q1")

    assert tracker.count("q1") == 0
    assert tracker.count("unknown") == 0


def test_record_round_resets_on_any_non_failure() -> None:
    tracker = StallTracker(max_rounds=2)

    assert tracker.record_round(all_failed=True) is None
    assert tracker.record_round(all_failed=False) is None
    assert tracker.record_round(all_failed=True) is None
    assert tracker.record_round(all_failed=True) == 2


def test_failed_rounds_reads_the_streak() -> None:
    tracker = StallTracker(max_rounds=5)
    tracker.record_round(all_failed=True)
    tracker.record_round(all_failed=True)

    assert tracker.failed_rounds == 2


@pytest.mark.asyncio
async def test_snapshot_reads_tokens_from_the_question_and_signals_from_the_ledger() -> None:
    ledger = _Ledger(verified=2, feedback=1)

    before = await snapshot(ledger, SimpleNamespace(id="q1", spent_tokens=7))

    assert before == Progress(spent_tokens=7, verified=2, feedback=1)
    assert ledger.reads == ["verified_claims", "feedback_count"]


@pytest.mark.asyncio
async def test_made_progress_stops_reading_once_tokens_moved() -> None:
    ledger = _Ledger(spent=5)

    assert await made_progress(ledger, "q1", Progress(0, 0, 0)) is True
    assert ledger.reads == ["get_question"]


@pytest.mark.asyncio
async def test_no_new_signal_is_no_progress() -> None:
    ledger = _Ledger(spent=0, verified=1, feedback=0)

    assert await made_progress(ledger, "q1", Progress(0, 1, 0)) is False
    assert ledger.reads == ["get_question", "verified_claims", "feedback_count"]


@pytest.mark.asyncio
async def test_unknown_signals_count_as_progress() -> None:
    assert await made_progress(_MinimalLedger(), "q1", Progress(0, None, None)) is True
    assert await snapshot(_MinimalLedger(), SimpleNamespace(id="q1", spent_tokens=0)) == Progress(0, None, None)
