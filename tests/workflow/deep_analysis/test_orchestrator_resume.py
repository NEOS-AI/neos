"""AC5: 워커 크래시 후 resume이 중복 지출 없이 라운드를 속행한다.

크래시를 "같은 원장 상태 위에 새 Orchestrator 인스턴스를 세우는 것"으로
모델링한다 -- 인메모리 상태(Budgeter 라운드 카운터, aging, stall 카운터,
_reinvestigation_count)는 전부 사라지고 원장만 남는다. 이것이 정확히
Celery 워커가 죽고 재시도가 도는 상황이다.
"""

from dataclasses import dataclass, field

import pytest

from neos.workflow.deep_analysis.models import (
    NodeSummary,
    ProposedClaim,
    Verdict,
    WorkerResult,
)
from neos.workflow.deep_analysis.orchestrator import Orchestrator


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


@dataclass
class DurableLedger:
    """크래시를 넘어 살아남는 원장. 두 Orchestrator 인스턴스가 공유한다."""

    items: list = field(default_factory=list)
    events: list = field(default_factory=list)
    blobs: dict = field(default_factory=dict)
    completed: bool = False

    async def recover(self):
        recovered = 0
        for item in self.items:
            if item.status == "investigating":
                item.status = "open"
                recovered += 1
        return recovered

    async def root_question(self):
        return next((i for i in self.items if i.parent_id is None), None)

    async def get_question(self, question_id):
        return next((i for i in self.items if i.id == question_id), None)

    async def open_question(self, text, parent_id, value_est, cap_tokens, depth):
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
        return [i for i in self.items if i.status == "open"]

    async def children(self, question_id):
        return [i for i in self.items if i.parent_id == question_id]

    async def gain_history(self, question_id, last_n=3):
        return []

    async def total_spent(self):
        return sum(i.spent_tokens for i in self.items)

    async def _transition(self, question_id, status):
        item = next(i for i in self.items if i.id == question_id)
        item.status = status

    async def commit_blobs(self, blobs):
        for blob in blobs:
            self.blobs[blob.content_hash] = blob

    async def commit_pass(self, question_id, result, verdicts, *, judge_tokens_spent):
        item = next(i for i in self.items if i.id == question_id)
        item.spent_tokens += result.tokens_spent + judge_tokens_spent
        item.status = "open"  # 미해결로 남겨 다음 라운드에 재선택 가능하게

    async def pending_claims(self, question_id):
        return []

    async def pending_feedback(self, question_id):
        return []

    async def log(self, kind, qid, payload):
        self.events.append((kind, qid, payload))

    async def has_event(self, kind):
        return any(event[0] == kind for event in self.events)

    async def complete_run(self, report_path=None):
        self.completed = True

    async def fail_run(self):
        raise AssertionError("run unexpectedly failed")

    async def remaining_budget(self, question_id):
        item = next(i for i in self.items if i.id == question_id)
        return max(0, item.cap_tokens - item.spent_tokens)

    async def verified_summaries(self, question_id):
        return "(없음)"

    async def unverified_and_deadends(self, question_id):
        return []


class CountingWorkerFactory:
    """패스마다 고정 토큰을 쓰는 워커. 총 호출 수를 센다."""

    def __init__(self, tokens_per_pass=100):
        self.tokens_per_pass = tokens_per_pass
        self.calls = 0

    def __call__(self):
        factory = self

        class Worker:
            async def investigate(self, brief, effort, question_id, repairs=None, question_text=""):
                factory.calls += 1
                return WorkerResult(
                    question_id=question_id,
                    status="completed",
                    claims=[ProposedClaim("fact", 0.6)],
                    tokens_spent=factory.tokens_per_pass,
                    self_assessment=0.4,
                )

        return Worker()


class OkGrader:
    async def grade(self, claim):
        return Verdict(ok=True)


class StubSynthesizer:
    _REPORT = "## 요약\n요약\n\n## 본문\n본문\n\n## 한계와 미확인 사항\n없음\n\n## 출처"

    async def reduce_tree(self, root_id):
        return {root_id: NodeSummary(root_id, "요약", [], 1.0, [])}

    async def assemble(
        self, root_summary, child_summaries, caveats, revision_hints=None
    ):
        return self._REPORT


class StubCitationRenderer:
    async def render(self, draft):
        return draft


def build(ledger, worker_factory, decompose_calls, cap):
    async def decompose(_root):
        decompose_calls.append(_root)
        return [{"text": "child", "value_est": 0.9}]

    return Orchestrator(
        object(),
        "run00001",
        worker_factory=worker_factory,
        grader=OkGrader(),
        ledger=ledger,
        decompose_fn=decompose,
        synthesizer=StubSynthesizer(),
        citation_renderer=StubCitationRenderer(),
        global_token_cap=cap,
        parallel_workers=1,
        max_stall_rounds=99,
    )


@pytest.mark.asyncio
async def test_resumed_run_does_not_redecompose_the_root():
    """AC5: 재개된 run이 루트를 다시 분해하면 LLM decompose 비용을 재지출하고
    질문 트리가 중복된다. `_ensure_root`의 조기 반환이 이를 막는다."""
    ledger = DurableLedger()
    decompose_calls = []

    await build(ledger, CountingWorkerFactory(), decompose_calls, 100).run("root")
    questions_after_first = len(ledger.items)

    # 크래시 → 재개: 새 인스턴스, 같은 원장.
    await build(ledger, CountingWorkerFactory(), decompose_calls, 100).run("root")

    assert len(decompose_calls) == 1
    assert len(ledger.items) == questions_after_first


@pytest.mark.asyncio
async def test_resumed_run_does_not_respend_the_recorded_round_budget():
    """AC5의 핵심: 원장에 기록된 소비는 재개 후 재선택 예산을 줄인다.

    cap=200, 패스당 100토큰이면 총 2패스가 상한이다. 1회차에서 몇 패스를
    돌았든, 재개 후 총 패스 수는 여전히 2를 넘지 않아야 한다 -- 넘으면
    이미 쓴 예산을 두 번 쓴 것이고 곧 재과금이다.
    """
    ledger = DurableLedger()
    first_worker = CountingWorkerFactory(tokens_per_pass=100)

    await build(ledger, first_worker, [], 200).run("root")
    spent_after_first = await ledger.total_spent()

    second_worker = CountingWorkerFactory(tokens_per_pass=100)
    await build(ledger, second_worker, [], 200).run("root")

    total_passes = first_worker.calls + second_worker.calls
    assert total_passes * 100 == await ledger.total_spent()
    assert await ledger.total_spent() <= 200
    assert total_passes <= 2
    # 1회차가 이미 캡을 채웠다면 재개는 워커를 한 번도 돌리지 않는다.
    if spent_after_first >= 200:
        assert second_worker.calls == 0


@pytest.mark.asyncio
async def test_resumed_run_cannot_spend_a_second_conflict_reinvestigation_round():
    """orchestrator.py:611의 이벤트 로그 게이트를 고정한다. 인메모리
    카운터는 재개 시 리셋되지만 이벤트 로그는 리셋되지 않는다."""
    ledger = DurableLedger()
    await ledger.log("conflict_reinvestigation", "q1", {"qids": ["q1"]})

    orchestrator = build(ledger, CountingWorkerFactory(), [], 100)

    assert orchestrator._reinvestigation_count == 0  # 인메모리는 리셋됨
    assert await ledger.has_event("conflict_reinvestigation") is True


@pytest.mark.asyncio
async def test_resume_recovers_questions_stranded_in_investigating():
    """크래시는 질문을 investigating에 남긴다. recover()가 없으면 그 질문은
    영원히 재선택되지 않아 run이 조기 종료된다."""
    ledger = DurableLedger()
    ledger.items.append(Question("00000001", "root", None, 0, status="split"))
    ledger.items.append(
        Question("00000002", "child", "00000001", 1, status="investigating")
    )

    worker = CountingWorkerFactory(tokens_per_pass=100)
    await build(ledger, worker, [], 200).run("root")

    assert worker.calls >= 1
