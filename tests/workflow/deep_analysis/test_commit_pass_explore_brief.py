"""commit_pass persists unverified_brief as explore_brief, not a claim."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from neos.workflow.deep_analysis.ledger import Ledger
from neos.workflow.deep_analysis.models import WorkerResult
from neos.workflow.deep_analysis.orchestrator import Orchestrator


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
    orchestrator = Orchestrator(
        session=None,
        run_id="run00001",
        worker_factory=lambda: _ContinuingWorker(tokens_spent=40),
        grader=None,
        ledger=ledger,
        decompose_fn=lambda _text: [],
        global_token_cap=10_000,
    )
    registered: list[tuple[str, bool]] = []
    original = orchestrator._register_progress

    async def spy(question_id, made_progress):
        registered.append((question_id, made_progress))
        await original(question_id, made_progress)

    orchestrator._register_progress = spy
    orchestrator._stall_counts[question.id] = 2

    question.spent_tokens = 40
    assert await orchestrator._made_progress(question.id, 0, 1, 0) is True
    question.spent_tokens = 0
    assert await orchestrator._made_progress(question.id, 0, 1, 0) is False

    ran = await orchestrator._run_round()

    assert ran is True
    assert registered == [(question.id, True)]
    assert orchestrator._stall_counts[question.id] == 0
    assert question.spent_tokens == 40
