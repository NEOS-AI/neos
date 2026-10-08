"""commit_pass persists unverified_brief as explore_brief, not a claim."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from neos.workflow.deep_analysis.ledger import Ledger
from neos.workflow.deep_analysis.models import WorkerResult
from neos.config.settings import settings
from neos.workflow.deep_analysis.orchestrator import Orchestrator
from neos.workflow.deep_analysis.stall import Progress, StallTracker, made_progress


pytestmark = pytest.mark.no_db

_LEDGER = Path("neos/workflow/deep_analysis/ledger.py")
_ORCH = Path("neos/workflow/deep_analysis/orchestrator.py")
_BRIEF = "child folded some unverified findings"


@dataclass
class _Question:
    id: str
    text: str = "q?"
    parent_id: str | None = None
    depth: int = 0
    status: str = "investigating"
    spent_tokens: int = 0
    value_est: float = 1.0
    confidence: float = 0.0
    cap_tokens: int = 2000
    fail_streak: int = 0


class _FakeDB:
    def add(self, obj) -> None:
        return

    async def flush(self) -> None:
        return


class _MemoryLedger(Ledger):
    """In-memory Ledger that still runs real commit_pass / reader logic."""

    def __init__(self, question: _Question | None = None) -> None:
        self.db = _FakeDB()
        self.run_id = "run00001"
        self.resolve_threshold = 0.8
        self.claim_retry_cap = 3
        self.question = question or _Question(id="qid00001")
        self.events: list[tuple[str, str | None, dict]] = []
        self.claims: list = []
        self.upsert_calls = 0

    async def get_question(self, question_id: str):
        return self.question if question_id == self.question.id else None

    async def _lock(self) -> None:
        return

    async def _store_blob(self, blob) -> None:
        return

    async def _upsert_claim(self, question_id, proposed_claim):
        self.upsert_calls += 1
        self.claims.append(proposed_claim)
        return "claim0001", []

    async def _record_verdict(self, *args, **kwargs):
        return False

    async def _apply_repairs(self, question_id, repairs) -> None:
        return

    async def _transition(self, question_id, status) -> None:
        self.question.status = status

    async def log(self, kind, qid, payload) -> None:
        self.events.append((kind, qid, dict(payload)))

    async def unverified_and_deadends(self, question_id: str) -> list[str]:
        out: list[str] = []
        for kind, qid, payload in self.events:
            if kind == "dead_end" and qid == question_id:
                out.append(str(payload.get("text", "")))
        out.extend(str(claim.text) for claim in self.claims)
        return out

    async def open_questions(self):
        return [self.question] if self.question.status == "open" else []

    async def root_question(self):
        return self.question

    async def children(self, question_id):
        return []

    async def total_spent(self):
        return self.question.spent_tokens

    async def pending_feedback(self, question_id):
        return []

    async def pending_claims(self, question_id):
        return []

    async def verified_claims(self, question_id):
        return [("already verified", [])]

    async def verified_summaries(self, question_id):
        return "- already verified"

    async def feedback_count(self, question_id):
        return 0

    async def gain_history(self, question_id, last_n=3):
        return []

    async def commit_blobs(self, blobs):
        return


def _brief_result(question_id: str, **overrides) -> WorkerResult:
    payload = {
        "question_id": question_id,
        "status": "completed",
        "claims": [],
        "dead_ends": [],
        "tokens_spent": 12,
        "unverified_brief": _BRIEF,
        "subagent_run_id": "sa_child",
        "subagent_step_kind": "completed",
    }
    payload.update(overrides)
    return WorkerResult(**payload)


def _explore_events(ledger: _MemoryLedger) -> list[tuple[str, str | None, dict]]:
    return [event for event in ledger.events if event[0] == "explore_brief"]


@pytest.mark.asyncio
async def test_explore_brief_persisted_but_not_claimed() -> None:
    ledger = _MemoryLedger()
    result = _brief_result(ledger.question.id)
    assert result.claims == []

    await ledger.commit_pass(ledger.question.id, result, {}, judge_tokens_spent=0)

    explore = _explore_events(ledger)
    assert len(explore) == 1
    assert explore[0][1] == ledger.question.id
    assert explore[0][2]["text"] == _BRIEF
    assert result.claims == []
    assert ledger.upsert_calls == 0
    assert ledger.claims == []
    assert not any(kind.startswith("claim_") for kind, _qid, _payload in ledger.events)


@pytest.mark.asyncio
async def test_explore_brief_not_in_unverified_and_deadends() -> None:
    src = _LEDGER.read_text().split("async def unverified_and_deadends", 1)[1]
    reader = src.split("async def ", 1)[0]
    assert 'DAEvent.kind == "dead_end"' in reader
    assert "explore_brief" not in reader

    ledger = _MemoryLedger()
    await ledger.commit_pass(
        ledger.question.id,
        _brief_result(ledger.question.id),
        {},
        judge_tokens_spent=0,
    )

    memory = await ledger.unverified_and_deadends(ledger.question.id)
    assert _BRIEF not in memory
    assert all(_BRIEF not in item for item in memory)


@pytest.mark.asyncio
async def test_explore_brief_is_not_a_dead_end() -> None:
    ledger = _MemoryLedger()
    dead_end = "search returned nothing useful"
    await ledger.commit_pass(
        ledger.question.id,
        _brief_result(ledger.question.id, dead_ends=[dead_end]),
        {},
        judge_tokens_spent=0,
    )

    kinds = [kind for kind, _qid, _payload in ledger.events]
    assert kinds.index("dead_end") < kinds.index("explore_brief")
    assert kinds.count("dead_end") == 1
    assert kinds.count("explore_brief") == 1

    dead = [payload for kind, _qid, payload in ledger.events if kind == "dead_end"]
    explore = [payload for kind, _qid, payload in ledger.events if kind == "explore_brief"]
    assert dead == [{"text": dead_end}]
    assert explore[0]["text"] == _BRIEF

    memory = await ledger.unverified_and_deadends(ledger.question.id)
    assert memory == [dead_end]


class _RecordingTracker(StallTracker):
    def __init__(self, max_rounds):
        super().__init__(max_rounds)
        self.registered: list[tuple[str, bool]] = []

    def record(self, question_id, made_progress):
        self.registered.append((question_id, made_progress))
        return super().record(question_id, made_progress)


def _seeded_tracker(question_id: str) -> _RecordingTracker:
    """Two no-progress passes already counted -- the same max as the constructor default."""
    tracker = _RecordingTracker(settings.config.deep_analysis.max_stall_rounds)
    tracker.record(question_id, False)
    tracker.record(question_id, False)
    tracker.registered.clear()
    return tracker


class _ContinuingWorker:
    def __init__(self, tokens_spent: int) -> None:
        self.tokens_spent = tokens_spent

    async def investigate(self, brief, effort, qid, repairs=None, question_text=""):
        return WorkerResult(
            question_id=qid,
            status="partial",
            claims=[],
            tokens_spent=self.tokens_spent,
            subagent_step_kind="continuing",
        )

    def flush_partial(self, qid):
        return WorkerResult(question_id=qid, status="partial")


@pytest.mark.asyncio
async def test_continuing_plus_tokens_is_progress() -> None:
    """continuing + tokens_delta is progress even if verified count is flat."""
    source = _ORCH.read_text()
    assert 'if result.subagent_step_kind == "continuing":' in source

    question = _Question(id="qid00001", text="What?", status="open", cap_tokens=999_999)
    ledger = _MemoryLedger(question)
    tracker = _seeded_tracker(question.id)
    orchestrator = Orchestrator(
        session=None,
        run_id="run00001",
        worker_factory=lambda: _ContinuingWorker(tokens_spent=40),
        grader=None,
        ledger=ledger,
        decompose_fn=lambda _text: [],
        global_token_cap=10_000,
        stall_tracker=tracker,
    )

    question.spent_tokens = 40
    assert await made_progress(ledger, question.id, Progress(0, 1, 0)) is True
    question.spent_tokens = 0
    assert await made_progress(ledger, question.id, Progress(0, 1, 0)) is False

    ran = await orchestrator._run_round()

    assert ran is True
    assert tracker.registered == [(question.id, True)]
    assert tracker.count(question.id) == 0
    assert question.spent_tokens == 40


def _kinds(ledger: _MemoryLedger) -> list[str]:
    return [kind for kind, _qid, _payload in ledger.events]


@pytest.mark.asyncio
async def test_empty_unverified_brief_skips_explore_brief() -> None:
    ledger = _MemoryLedger()
    await ledger.commit_pass(
        ledger.question.id,
        _brief_result(ledger.question.id, unverified_brief=""),
        {},
        judge_tokens_spent=0,
    )

    assert _explore_events(ledger) == []
    assert _kinds(ledger) == ["pass_completed"]


@pytest.mark.asyncio
async def test_whitespace_brief_is_not_explore_or_dead_end() -> None:
    ledger = _MemoryLedger()
    await ledger.commit_pass(
        ledger.question.id,
        _brief_result(ledger.question.id, unverified_brief="  \n\t  "),
        {},
        judge_tokens_spent=0,
    )

    assert _explore_events(ledger) == []
    assert "dead_end" not in _kinds(ledger)
    assert _kinds(ledger) == ["pass_completed"]


@pytest.mark.asyncio
async def test_long_brief_is_truncated_with_child_status_fallback() -> None:
    ledger = _MemoryLedger()
    raw = "x" * 16_385
    await ledger.commit_pass(
        ledger.question.id,
        _brief_result(
            ledger.question.id,
            unverified_brief=raw,
            subagent_step_kind="",
            status="partial",
        ),
        {},
        judge_tokens_spent=0,
    )

    explore = _explore_events(ledger)
    assert len(explore) == 1
    payload = explore[0][2]
    assert len(payload["text"]) == 16_384
    assert payload["text"] == raw[:16_384]
    assert payload["truncated"] is True
    assert payload["child_status"] == "partial"


@pytest.mark.asyncio
async def test_continuing_with_zero_tokens_is_still_progress() -> None:
    """continuing counts as progress even when tokens_spent stays 0."""
    question = _Question(id="qid00001", text="What?", status="open", cap_tokens=999_999)
    ledger = _MemoryLedger(question)
    tracker = _seeded_tracker(question.id)
    orchestrator = Orchestrator(
        session=None,
        run_id="run00001",
        worker_factory=lambda: _ContinuingWorker(tokens_spent=0),
        grader=None,
        ledger=ledger,
        decompose_fn=lambda _text: [],
        global_token_cap=10_000,
        stall_tracker=tracker,
    )

    assert question.spent_tokens == 0
    assert await made_progress(ledger, question.id, Progress(0, 1, 0)) is False

    ran = await orchestrator._run_round()

    assert ran is True
    assert tracker.registered == [(question.id, True)]
    assert tracker.count(question.id) == 0
    assert question.spent_tokens == 0


class _RunIdWorker:
    def __init__(self, run_id: str) -> None:
        self.tokens_spent = 0
        self.run_id = run_id

    async def investigate(self, brief, effort, qid, repairs=None, question_text=""):
        return WorkerResult(
            question_id=qid,
            status="partial",
            claims=[],
            tokens_spent=0,
            subagent_run_id=self.run_id,
            subagent_checkpoint_id="sc_1" if self.run_id else "",
            subagent_step_kind="continuing" if self.run_id else "",
        )

    def flush_partial(self, qid):
        return WorkerResult(question_id=qid, status="partial")


def _round_orch(ledger: _MemoryLedger, worker: object) -> Orchestrator:
    return Orchestrator(
        session=None,
        run_id="run00001",
        worker_factory=lambda: worker,
        grader=None,
        ledger=ledger,
        decompose_fn=lambda _text: [],
        global_token_cap=10_000,
    )


@pytest.mark.asyncio
async def test_run_round_logs_subagent_step_only_when_run_id_present() -> None:
    missing = _Question(id="qid00001", text="What?", status="open", cap_tokens=999_999)
    missing_ledger = _MemoryLedger(missing)
    await _round_orch(missing_ledger, _RunIdWorker(""))._run_round()
    assert [kind for kind, _qid, _payload in missing_ledger.events if kind == "subagent_step"] == []

    present = _Question(id="qid00001", text="What?", status="open", cap_tokens=999_999)
    present_ledger = _MemoryLedger(present)
    await _round_orch(present_ledger, _RunIdWorker("sa_child"))._run_round()
    steps = [
        payload
        for kind, qid, payload in present_ledger.events
        if kind == "subagent_step"
    ]
    assert len(steps) == 1
    assert steps[0]["run_id"] == "sa_child"
    assert steps[0]["checkpoint_id"] == "sc_1"
    assert steps[0]["step_kind"] == "continuing"
    assert steps[0]["status"] == "partial"
