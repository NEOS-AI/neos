from dataclasses import dataclass

import pytest

from neos.workflow.deep_analysis.models import (
    NodeSummary,
    ProposedBlob,
    ProposedClaim,
    WorkerResult,
)
from neos.workflow.deep_analysis.orchestrator import Orchestrator
from neos.workflow.deep_analysis.models import Verdict


pytestmark = pytest.mark.no_db


@dataclass
class Question:
    id: str
    text: str
    parent_id: str | None
    depth: int
    status: str = "open"
    spent_tokens: int = 0
    value_est: float = 1.0
    confidence: float = 0.0
    cap_tokens: int = 999_999
    fail_streak: int = 0


class FakeLedger:
    def __init__(self):
        self.items = []
        self.blobs = {}
        self.events = []
        self.completed = False

    async def recover(self):
        return 0

    async def root_question(self):
        return next(
            (item for item in self.items if item.parent_id is None),
            None,
        )

    async def get_question(self, question_id):
        # Mirror real Ledger.get_question: return the row or None. The
        # orchestrator reads `.value_est` off this and uses None to trip the
        # question_id guard.
        return next(
            (item for item in self.items if item.id == question_id),
            None,
        )

    async def pending_claims(self, question_id):
        # Mirror real Ledger.pending_claims: this fake never leaves a claim in
        # `pending` (commit_pass resolves everything), so there is nothing to
        # re-grade -> post-commit _regrade_pending is a no-op.
        return []

    async def pending_feedback(self, question_id):
        # Mirror real Ledger.pending_feedback: this fake never writes
        # feedback rows, so _partition always sees "no pending feedback".
        return []

    async def open_question(
        self,
        text,
        parent_id,
        value_est,
        cap_tokens,
        depth,
    ):
        question_id = f"{len(self.items) + 1:08x}"
        self.items.append(
            Question(
                question_id,
                text,
                parent_id,
                depth,
                value_est=value_est,
                cap_tokens=cap_tokens,
            )
        )
        return question_id

    async def record_split(self, question_id, child_ids):
        await self._transition(question_id, "split")

    async def open_questions(self):
        return [item for item in self.items if item.status == "open"]

    async def children(self, question_id):
        return [item for item in self.items if item.parent_id == question_id]

    async def gain_history(self, question_id, last_n=3):
        return []

    async def total_spent(self):
        return sum(item.spent_tokens for item in self.items)

    async def _transition(self, question_id, status):
        item = next(item for item in self.items if item.id == question_id)
        item.status = status

    async def commit_blobs(self, blobs):
        for blob in blobs:
            self.blobs[blob.content_hash] = blob

    async def commit_pass(self, question_id, result, verdicts):
        item = next(item for item in self.items if item.id == question_id)
        item.status = "resolved"
        item.spent_tokens += result.tokens_spent

    async def log(self, kind, qid, payload):
        self.events.append((kind, qid, payload))

    async def complete_run(self):
        self.completed = True

    async def fail_run(self):
        raise AssertionError("run unexpectedly failed")


class FakeWorker:
    async def investigate(self, brief, effort, question_id, repairs=None, question_text=""):
        return WorkerResult(
            question_id=question_id,
            status="completed",
            blobs=[
                ProposedBlob(
                    "abcdef0123456789",
                    "https://example.com",
                    200,
                    "source",
                )
            ],
            claims=[ProposedClaim("fact", 0.6)],
            tokens_spent=10,
            self_assessment=0.8,
        )


class OrderingGrader:
    def __init__(self, ledger):
        self.ledger = ledger

    async def grade(self, claim):
        assert self.ledger.blobs, "grader ran before blob commit"
        return Verdict(ok=True)


class FakeSynthesizer:
    _REPORT = (
        "## 요약\n요약\n\n## 본문\n본문\n\n"
        "## 한계와 미확인 사항\n없음\n\n## 출처"
    )

    async def reduce(self, root_id):
        return self._REPORT

    async def reduce_tree(self, root_id):
        return {root_id: NodeSummary(root_id, "요약", [], 1.0, [])}

    async def assemble(
        self, root_summary, child_summaries, caveats, revision_hints=None
    ):
        return self._REPORT


class FakeCitationRenderer:
    async def render(self, draft):
        return draft


@pytest.mark.asyncio
async def test_orchestrator_stages_blobs_before_grading():
    ledger = FakeLedger()

    async def decompose(_root):
        return [{"text": "child", "value_est": 0.8}]

    orchestrator = Orchestrator(
        object(),
        "run00001",
        worker_factory=FakeWorker,
        grader=OrderingGrader(ledger),
        ledger=ledger,
        decompose_fn=decompose,
        synthesizer=FakeSynthesizer(),
        citation_renderer=FakeCitationRenderer(),
        global_token_cap=100,
    )

    result = await orchestrator.run("root")

    assert result["run_id"] == "run00001"
    assert ledger.items[0].status == "split"
    assert ledger.items[1].status == "resolved"
    assert ledger.completed


@pytest.mark.asyncio
async def test_orchestrator_rolls_back_failed_transaction_before_marking_run_failed():
    class Session:
        def __init__(self):
            self.rollbacks = 0

        async def rollback(self):
            self.rollbacks += 1

    class FailureLedger(FakeLedger):
        def __init__(self):
            super().__init__()
            self.failed = False

        async def fail_run(self):
            self.failed = True

    class FailureGrader:
        # A1: worker exceptions are absorbed into a "failed" result by
        # _run_worker, so surface the mid-run error from the grader instead
        # (still on run()'s critical, uncaught path).
        async def grade(self, claim):
            raise RuntimeError("worker exploded")

    session = Session()
    ledger = FailureLedger()

    async def no_decomposition(_root):
        return []

    orchestrator = Orchestrator(
        session,
        "run00001",
        worker_factory=FakeWorker,
        grader=FailureGrader(),
        ledger=ledger,
        decompose_fn=no_decomposition,
        synthesizer=FakeSynthesizer(),
        citation_renderer=FakeCitationRenderer(),
        global_token_cap=100,
    )

    with pytest.raises(RuntimeError, match="worker exploded"):
        await orchestrator.run("root")

    assert session.rollbacks == 1
    assert ledger.failed


async def test_partition_feeds_prior_findings_dead_ends_and_configured_caps_into_brief(
    monkeypatch,
):
    """재조사 패스의 worker brief는 이 질문의 확정된 발견과 막다른 길을
    포함해야 한다(worker_brief.md [3] "확정된 발견 — 재조사 금지").
    이전에는 항상 "(없음)"으로 하드코딩되어 문맥이 유실됐다."""
    from neos.workflow.deep_analysis.models import Effort

    class BriefLedger:
        async def pending_feedback(self, question_id):
            return []

        async def verified_summaries(self, question_id):
            return "- 지구는 둥글다"

        async def unverified_and_deadends(self, question_id):
            return ["평평한 지구설은 근거 없음"]

    question = Question(id="q1000000", text="지구 모양은?", parent_id="root0000", depth=1)
    orchestrator = Orchestrator(
        session=None,
        run_id="run00001",
        worker_factory=FakeWorker,
        grader=None,  # _partition은 grader를 사용하지 않는다
        ledger=BriefLedger(),
    )
    from neos.config.settings import settings

    monkeypatch.setitem(settings.config.deep_analysis.confidence_cap, 1, 0.55)
    monkeypatch.setitem(settings.config.deep_analysis.confidence_cap, 2, 0.75)
    monkeypatch.setitem(settings.config.deep_analysis.confidence_cap, 3, 0.9)

    assignments, splits = await orchestrator._partition([(question, Effort.SCOUT)])

    assert splits == []
    assert len(assignments) == 1
    brief = assignments[0].brief
    assert "지구는 둥글다" in brief
    assert "평평한 지구설은 근거 없음" in brief
    assert "1개 0.55" in brief
    assert "2개 0.75" in brief
    assert "3개 이상 0.9" in brief
