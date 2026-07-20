"""라운드 안에서 커밋이 패스마다 일어나는지 고정한다.

이벤트는 `Ledger.log()`가 flush만 하므로, 별도 세션에서 읽는 SSE 소비자는
`_checkpoint()`가 커밋해야 비로소 이벤트를 볼 수 있다. 커밋이 라운드 끝에
한 번뿐이면 그 라운드의 모든 패스가 한꺼번에 나타난다 -- 진행 상황이 뭉텅이로
보이고(D22/D23이 남긴 "라운드 단위 해상도"), 크래시 시 라운드 전체의 작업이
날아간다.

패스마다 커밋하면 해상도가 패스 단위로 올라가고 유실 범위도 패스 하나로 줄어든다.
"""

import pytest
import neos.database.models  # noqa: F401 - Base 메타데이터 등록
from neos.database.connection import db_manager
from neos.workflow.deep_analysis.graders.deterministic import DeterministicGrader
from neos.workflow.deep_analysis.ledger import Ledger, create_run
from neos.workflow.deep_analysis.models import (
    ProposedBlob,
    ProposedClaim,
    ProposedEvidence,
    WorkerResult,
)
from neos.workflow.deep_analysis.orchestrator import Orchestrator


class FakeWorker:
    async def investigate(
        self, brief, effort, question_id, repairs=None, question_text=""
    ):
        blob = ProposedBlob(
            content_hash=f"blob{question_id[:12]}",
            source_url=f"https://example.com/{question_id}",
            http_status=200,
            raw_text="Fact body text from the source.",
        )
        return WorkerResult(
            question_id=question_id,
            status="completed",
            blobs=[blob],
            claims=[
                ProposedClaim(
                    text=f"A verified fact for {question_id}",
                    confidence=0.6,
                    evidence=[
                        ProposedEvidence(
                            source_url=blob.source_url,
                            excerpt="Fact body text from the source.",
                            raw_ref=blob.content_hash,
                        )
                    ],
                )
            ],
            tokens_spent=100,
            self_assessment=0.8,
        )


@pytest.mark.asyncio
async def test_round_checkpoints_once_per_pass_not_once_per_round():
    async with await db_manager.get_session() as session:
        run_id = await create_run(session, "Root question?", "dev")
        ledger = Ledger(session, run_id)
        grader = DeterministicGrader(
            ledger,
            quote_threshold=0.92,
            confidence_cap={1: 0.6, 2: 0.8, 3: 0.95},
        )

        async def decompose(_root):
            return [
                {"text": "Sub question one", "value_est": 0.8},
                {"text": "Sub question two", "value_est": 0.8},
            ]

        checkpoints: list[int] = []
        passes: list[str] = []

        original_commit_pass = ledger.commit_pass

        async def counting_commit_pass(question_id, result, verdicts):
            passes.append(question_id)
            return await original_commit_pass(question_id, result, verdicts)

        ledger.commit_pass = counting_commit_pass

        orchestrator = Orchestrator(
            session,
            run_id,
            worker_factory=FakeWorker,
            grader=grader,
            decompose_fn=decompose,
            ledger=ledger,
            checkpoint=lambda: checkpoints.append(len(passes)),
            global_token_cap=1000,
            parallel_workers=2,
        )
        await orchestrator._ensure_root("Root question?")
        await orchestrator._run_round()

        assert len(passes) == 2, f"두 질문이 각각 한 패스씩 돌아야 한다: {passes}"

        # 패스가 끝날 때마다 커밋돼야 한다. 라운드 끝 한 번이면 checkpoints에
        # 기록된 값이 전부 2(모든 패스 완료 후)가 된다.
        after_first_pass = [c for c in checkpoints if c == 1]
        assert after_first_pass, (
            f"첫 패스 직후 커밋이 없다 -- 라운드 단위 해상도다: {checkpoints}"
        )

        await session.rollback()
