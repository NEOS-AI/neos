"""M4 Task 5: Orchestrator._finalize -- hierarchical reduce + bounded conflict
reinvestigation + assembly retry loop (AC-c).

These are contract tests driven straight through `_finalize` with a fake synth
seam (reduce_tree/assemble), a fake citation renderer, and a fake report
grader -- no real LLM/network call happens. The reinvestigation cap is proven
by monkeypatching `resolve_conflicts` to report a persistent conflict and
asserting only one extra investigation round is spent.
"""

import pytest

import neos.workflow.deep_analysis.orchestrator as orch_mod
from neos.workflow.deep_analysis.citation import OrphanCitationError
from neos.workflow.deep_analysis.ledger import (
    IllegalTransition,
    _LEGAL_TRANSITIONS,
    _TERMINAL_STATUSES,
)
from neos.workflow.deep_analysis.models import NodeSummary, Verdict
from neos.workflow.deep_analysis.orchestrator import Orchestrator


pytestmark = pytest.mark.no_db


class FakeLedger:
    """Minimal ledger double whose state machine mirrors the REAL one.

    `_transition` enforces `_LEGAL_TRANSITIONS`/`_TERMINAL_STATUSES` and raises
    `IllegalTransition` on illegal moves, so a `resolved -> open` reopen can no
    longer silently no-op. `reopen_for_reinvestigation` is the §6.7 exception
    (direct status set + `question_reopened` log), matching the real ledger.
    """

    def __init__(self, statuses=None):
        self.events = []
        self.completed = False
        self.transitions = []
        self.reopened = []
        # question_id -> status; default open when unseen.
        self.statuses = dict(statuses or {})

    async def children(self, qid):
        return []

    async def unverified_and_deadends(self, qid):
        return []

    async def questions(self):
        return []

    async def log(self, kind, qid, payload):
        self.events.append((kind, qid, payload))

    async def complete_run(self):
        self.completed = True

    async def has_event(self, kind):
        return any(k == kind for (k, _q, _p) in self.events)

    async def _transition(self, qid, to_status):
        current = self.statuses.get(qid, "open")
        if (
            current in _TERMINAL_STATUSES
            or (current, to_status) not in _LEGAL_TRANSITIONS
        ):
            raise IllegalTransition(f"{current} -> {to_status} (qid={qid})")
        self.statuses[qid] = to_status
        self.transitions.append((qid, to_status))

    async def reopen_for_reinvestigation(self, qid):
        previous = self.statuses.get(qid, "open")
        self.statuses[qid] = "open"
        self.reopened.append(qid)
        if previous != "open":
            await self.log(
                "question_reopened",
                qid,
                {"from": previous, "reason": "conflict_reinvestigation"},
            )


class FakeSynth:
    """reduce_tree returns a fixed single-node tree; assemble returns a fresh,
    numbered draft each call so retries are observable."""

    def __init__(self, summaries=None):
        self._summaries = summaries
        self.assemble_calls = 0
        self.reduce_tree_calls = 0

    async def reduce_tree(self, root_id):
        self.reduce_tree_calls += 1
        if self._summaries is not None:
            return dict(self._summaries)
        return {root_id: NodeSummary(root_id, "루트 요약 [C:aaaaaaaa]", [], 0.9, [])}

    async def assemble(self, root_summary, child_summaries, caveats):
        self.assemble_calls += 1
        return f"DRAFT-{self.assemble_calls}\n\n## 출처"


class FlakyRenderer:
    """Raises OrphanCitationError on the first `fail_times` renders, then
    resolves the draft (appending a footnote) on every subsequent call."""

    def __init__(self, fail_times):
        self.fail_times = fail_times
        self.calls = 0

    async def render(self, draft):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise OrphanCitationError("aaaaaaaa")
        return draft + "\n[1] http://x"


class OkGrader:
    async def grade(self, report, root_id):
        return Verdict(ok=True)


class FailGrader:
    async def grade(self, report, root_id):
        return Verdict(ok=False, code="E_REPORT_AGENTIC", detail="weak")


def _orch(ledger, synth, renderer, grader=None):
    return Orchestrator(
        object(),
        "run00001",
        worker_factory=lambda: None,
        grader=object(),
        ledger=ledger,
        synthesizer=synth,
        citation_renderer=renderer,
        report_grader=grader,
    )


def _graded(ledger):
    return [p for (k, _q, p) in ledger.events if k == "report_graded"]


@pytest.mark.asyncio
async def test_orphan_citation_retries_assembly_then_succeeds():
    # AC-c: first render raises OrphanCitationError -> loop re-assembles; the
    # second assembly renders cleanly and grades ok.
    ledger = FakeLedger()
    synth = FakeSynth()
    renderer = FlakyRenderer(fail_times=1)
    orch = _orch(ledger, synth, renderer, grader=OkGrader())

    report = await orch._finalize("root0001")

    assert "DRAFT-2" in report  # second assembly is the one that shipped
    assert synth.assemble_calls == 2
    graded = _graded(ledger)
    assert graded[0] == {"ok": False, "code": "E_ORPHAN_CITE", "attempt": 0}
    assert graded[1] == {"ok": True, "attempt": 1}
    assert ledger.completed


@pytest.mark.asyncio
async def test_orphan_every_attempt_exhausts_cap_and_appends_appendix():
    # AC-c cap: orphan on every render -> cap (report_retry_cap=2) exhausted;
    # never exits empty-handed (§6.8): a failure appendix is appended.
    ledger = FakeLedger()
    synth = FakeSynth()
    renderer = FlakyRenderer(fail_times=99)
    orch = _orch(ledger, synth, renderer, grader=OkGrader())

    report = await orch._finalize("root0001")

    assert "## 부록: 미해결 사유" in report
    assert "DRAFT-3" in report  # last draft retained under the appendix
    assert synth.assemble_calls == 3  # cap(2) + 1 attempts
    graded = _graded(ledger)
    assert len(graded) == 3
    assert all(p["ok"] is False for p in graded)
    assert all(p["code"] == "E_ORPHAN_CITE" for p in graded)
    assert ledger.completed


@pytest.mark.asyncio
async def test_report_grader_rejection_exhausts_cap_and_appends_appendix():
    ledger = FakeLedger()
    synth = FakeSynth()
    renderer = FlakyRenderer(fail_times=0)  # render always clean
    orch = _orch(ledger, synth, renderer, grader=FailGrader())

    report = await orch._finalize("root0001")

    assert "## 부록: 미해결 사유" in report
    assert synth.assemble_calls == 3
    graded = _graded(ledger)
    assert [p["code"] for p in graded] == ["E_REPORT_AGENTIC"] * 3
    assert ledger.completed


@pytest.mark.asyncio
async def test_missing_report_grader_defaults_to_ok():
    ledger = FakeLedger()
    synth = FakeSynth()
    orch = _orch(ledger, synth, FlakyRenderer(fail_times=0), grader=None)

    report = await orch._finalize("root0001")

    assert "DRAFT-1" in report
    assert synth.assemble_calls == 1
    assert _graded(ledger) == [{"ok": True, "attempt": 0}]
    assert ledger.completed


@pytest.mark.asyncio
async def test_conflict_reinvestigation_is_globally_capped_at_one(monkeypatch):
    # A persistent equal-tier conflict must trigger AT MOST one extra
    # investigation round (global cap 1), then proceed with both-sides
    # annotations only. subq0001 starts `resolved` (terminal): the reopen must
    # go through the §6.7 `reopen_for_reinvestigation` path, NOT a raw
    # `_transition` (which would raise IllegalTransition here).
    ledger = FakeLedger(statuses={"subq0001": "resolved"})
    synth = FakeSynth()
    orch = _orch(ledger, synth, FlakyRenderer(fail_times=0), grader=OkGrader())

    async def always_reinvestigate(_ledger, summary, _tiers):
        return summary, ["subq0001"]

    monkeypatch.setattr(orch_mod, "resolve_conflicts", always_reinvestigate)

    rounds = {"n": 0}

    async def fake_round():
        rounds["n"] += 1
        return True

    orch._run_round = fake_round

    report = await orch._finalize("root0001")

    assert rounds["n"] == 1  # exactly one bounded reinvestigation round
    assert orch._reinvestigation_count == 1
    reinvest = [e for e in ledger.events if e[0] == "conflict_reinvestigation"]
    assert len(reinvest) == 1
    assert reinvest[0][1] == "subq0001"
    # reopen actually happened through the sanctioned §6.7 path.
    assert ledger.reopened == ["subq0001"]
    assert ledger.statuses["subq0001"] == "open"
    assert ("subq0001", "open") not in ledger.transitions  # not a raw _transition
    reopened_events = [e for e in ledger.events if e[0] == "question_reopened"]
    assert len(reopened_events) == 1 and reopened_events[0][1] == "subq0001"
    # reduce_tree ran twice: initial + post-reinvestigation re-reduce.
    assert synth.reduce_tree_calls == 2
    assert ledger.completed
    assert "DRAFT" in report


@pytest.mark.asyncio
async def test_reinvestigation_gate_is_event_based_and_durable(monkeypatch):
    # Fix 2: the global cap is gated on the EVENT LOG, not the in-memory
    # counter. A resumed run whose ledger already has a prior
    # `conflict_reinvestigation` event must NOT reopen/reinvestigate again --
    # even though the in-memory counter is 0 after "recovery".
    ledger = FakeLedger(statuses={"subq0001": "resolved"})
    # Simulate a prior run having already spent its reinvestigation.
    await ledger.log("conflict_reinvestigation", "subq0001", {"qids": ["subq0001"]})
    synth = FakeSynth()
    orch = _orch(ledger, synth, FlakyRenderer(fail_times=0), grader=OkGrader())
    assert orch._reinvestigation_count == 0  # fresh in-memory counter (resumed)

    async def always_reinvestigate(_ledger, summary, _tiers):
        return summary, ["subq0001"]

    monkeypatch.setattr(orch_mod, "resolve_conflicts", always_reinvestigate)

    rounds = {"n": 0}

    async def fake_round():
        rounds["n"] += 1
        return True

    orch._run_round = fake_round

    await orch._finalize("root0001")

    assert rounds["n"] == 0  # no extra round on the resumed run
    assert ledger.reopened == []  # nothing reopened
    reinvest = [e for e in ledger.events if e[0] == "conflict_reinvestigation"]
    assert len(reinvest) == 1  # still exactly one, from the prior run
    assert ledger.completed
