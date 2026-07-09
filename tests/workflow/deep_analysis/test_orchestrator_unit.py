from dataclasses import dataclass

import pytest

from neos.workflow.deep_analysis.models import (
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
    async def investigate(self, brief, effort, question_id):
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
    async def reduce(self, root_id):
        return (
            "## 요약\n요약\n\n## 본문\n본문\n\n"
            "## 한계와 미확인 사항\n없음\n\n## 출처"
        )


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

    class FailureWorker:
        async def investigate(self, brief, effort, question_id):
            raise RuntimeError("worker exploded")

    session = Session()
    ledger = FailureLedger()

    async def no_decomposition(_root):
        return []

    orchestrator = Orchestrator(
        session,
        "run00001",
        worker_factory=FailureWorker,
        grader=OrderingGrader(ledger),
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
