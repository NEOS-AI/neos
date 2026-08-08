"""M3 Task 6: end-to-end acceptance criteria (AC-a/b/c) plus the D15 stall
safety valve, exercised through the *real* Ledger + Orchestrator with only the
worker and grader/synthesizer faked. NO real LLM/network call happens.

This is the first task to drive the repair -> pending -> regrade loop end to
end, so each AC asserts the repaired claim actually converges (reaches its
terminal ledger status), not merely that the loop runs.
"""

import asyncio

import pytest
from sqlalchemy import text as sql

import neos.database.models  # noqa: F401 - register Base metadata
from neos.database.connection import db_manager
from neos.workflow.deep_analysis.ledger import Ledger, create_run
from neos.workflow.deep_analysis.llm import LLMResponse
from neos.workflow.deep_analysis.models import (
    NodeSummary,
    ProposedBlob,
    ProposedClaim,
    ProposedEvidence,
    RepairResult,
    Verdict,
    WorkerResult,
)
from neos.workflow.deep_analysis import orchestrator as orchestrator_module
from neos.workflow.deep_analysis.orchestrator import Orchestrator
from neos.workflow.deep_analysis.synthesizer import Synthesizer


# --- shared fakes --------------------------------------------------------

class OkDet:
    """Deterministic tier always passes; the agentic tier drives verdicts."""

    async def grade(self, claim):
        return Verdict(ok=True)


class ScriptedAgentic:
    """Returns queued verdicts in order, repeating the last once exhausted.

    Injected directly as `agentic_grader`, so tiering/sampling is bypassed and
    every det-passed claim reaches this grader deterministically."""

    def __init__(self, verdicts):
        self._verdicts = list(verdicts)
        self.calls = 0

    async def grade(self, claim, value_est):
        self.calls += 1
        idx = min(self.calls - 1, len(self._verdicts) - 1)
        return self._verdicts[idx]


_STUB_REPORT = (
    "## 요약\nstub\n\n## 본문\nstub\n\n"
    "## 한계와 미확인 사항\n없음\n\n## 출처"
)


class FakeSynth:
    """Network-free stand-in for the finalize seam (reduce_tree/assemble) plus
    backward-compat reduce; returns a citation-free report so CitationRenderer
    is a no-op."""

    async def reduce(self, root_id):
        return _STUB_REPORT

    async def reduce_tree(self, root_id):
        return {root_id: NodeSummary(root_id, "stub", [], 1.0, [])}

    async def assemble(
        self, root_summary, child_summaries, caveats, revision_hints=None
    ):
        return _STUB_REPORT


class CapturingLLMCall:
    """Captures the final_compose prompt so AC-c can assert on the caveats."""

    def __init__(self):
        self.prompt = ""

    async def __call__(self, model, prompt, **kwargs):
        self.prompt = prompt
        return LLMResponse(
            text=(
                "## 요약\n없음\n\n## 본문\n없음\n\n"
                "## 한계와 미확인 사항\n(참조는 프롬프트에 있음)\n\n## 출처"
            ),
            input_tokens=5,
            output_tokens=5,
            model=model,
        )


def _decompose_one(_root):
    return [{"text": "sub", "value_est": 0.9}]


def _first_claim_evidence():
    blob = ProposedBlob(
        content_hash="h1", source_url="http://x", http_status=200,
        raw_text="body",
    )
    ev = ProposedEvidence(source_url="http://x", excerpt="body excerpt",
                          raw_ref="h1")
    return blob, ev


# --- AC-a: E_OVERCLAIM weaken, no re-investigation -----------------------

class WeakenRepairWorker:
    """Round 1 proposes an over-strong claim; once pending feedback arrives
    (repairs non-empty) it returns a weakened RepairResult with NO fetch and NO
    new evidence."""

    async def investigate(self, brief, effort, qid, repairs=None, question_text=""):
        if repairs:
            claim_id = repairs[0]["claim_id"]
            return WorkerResult(
                question_id=qid, status="completed", claims=[], blobs=[],
                repairs=[RepairResult(claim_id=claim_id, action="weakened",
                                      new_text="약화된 클레임")],
                tokens_spent=100, self_assessment=0.9,
            )
        blob, ev = _first_claim_evidence()
        return WorkerResult(
            question_id=qid, status="completed", blobs=[blob],
            claims=[ProposedClaim(text="과장된 클레임", confidence=0.9,
                                  evidence=[ev])],
            tokens_spent=100, self_assessment=0.0,
        )

    def flush_partial(self, qid):
        return WorkerResult(question_id=qid, status="partial")


@pytest.mark.asyncio
async def test_ac_a_overclaim_weakened_then_verified():
    agentic = ScriptedAgentic([
        Verdict(ok=False, code="E_OVERCLAIM", label="PARTIAL", detail="too broad"),
        Verdict(ok=True, label="SUPPORTS"),
    ])
    async with await db_manager.get_session() as s:
        run_id = await create_run(s, "root?", "dev")
        orch = Orchestrator(
            s, run_id, lambda: WeakenRepairWorker(), OkDet(),
            agentic_grader=agentic, decompose_fn=_decompose_one,
            global_token_cap=5000, synthesizer=FakeSynth(),
        )

        async def split_decompose(text, *_a):
            return []

        orch._split_decompose = split_decompose
        await asyncio.wait_for(orch.run("root?"), timeout=30)

        row = (await s.execute(sql(
            "SELECT status, text FROM deep_analysis_claims WHERE run_id=:r"),
            {"r": run_id})).one()
        assert row.status == "verified"
        assert row.text == "약화된 클레임"      # weakened text won
        assert agentic.calls == 2               # round1 PARTIAL, regrade SUPPORTS
        # no re-investigation: evidence count stayed at the single round-1 row
        ev_count = (await s.execute(sql(
            "SELECT COUNT(*) FROM deep_analysis_evidence WHERE run_id=:r"),
            {"r": run_id})).scalar()
        assert ev_count == 1
        # exactly one blob (round 1); the weaken pass fetched nothing
        blob_count = (await s.execute(sql(
            "SELECT COUNT(*) FROM deep_analysis_blobs WHERE run_id=:r"),
            {"r": run_id})).scalar()
        assert blob_count == 1
        await s.rollback()


# --- AC-b: E_CONTRADICTED negation re-entry ------------------------------

class NegationRepairWorker:
    """Round 1 proposes a claim; once feedback arrives it returns a `fixed`
    RepairResult whose new_text is the negation."""

    async def investigate(self, brief, effort, qid, repairs=None, question_text=""):
        if repairs:
            claim_id = repairs[0]["claim_id"]
            return WorkerResult(
                question_id=qid, status="completed", claims=[], blobs=[],
                repairs=[RepairResult(claim_id=claim_id, action="fixed",
                                      new_text="X는 참이 아니다")],
                tokens_spent=100, self_assessment=0.9,
            )
        blob, ev = _first_claim_evidence()
        return WorkerResult(
            question_id=qid, status="completed", blobs=[blob],
            claims=[ProposedClaim(text="X는 참이다", confidence=0.9,
                                  evidence=[ev])],
            tokens_spent=100, self_assessment=0.0,
        )

    def flush_partial(self, qid):
        return WorkerResult(question_id=qid, status="partial")


@pytest.mark.asyncio
async def test_ac_b_contradicted_negation_reenters_and_verifies():
    agentic = ScriptedAgentic([
        Verdict(ok=False, code="E_CONTRADICTED", label="CONTRADICTS",
                detail="evidence says the opposite"),
        Verdict(ok=True, label="SUPPORTS"),
    ])
    async with await db_manager.get_session() as s:
        run_id = await create_run(s, "root?", "dev")
        orch = Orchestrator(
            s, run_id, lambda: NegationRepairWorker(), OkDet(),
            agentic_grader=agentic, decompose_fn=_decompose_one,
            global_token_cap=5000, synthesizer=FakeSynth(),
        )

        async def split_decompose(text, *_a):
            return []

        orch._split_decompose = split_decompose
        await asyncio.wait_for(orch.run("root?"), timeout=30)

        rows = dict((await s.execute(sql(
            "SELECT text, status FROM deep_analysis_claims WHERE run_id=:r"),
            {"r": run_id})).all())
        # the single claim row now carries the negation and is verified
        assert rows.get("X는 참이 아니다") == "verified"
        assert "X는 참이다" not in rows       # original text was overwritten
        assert agentic.calls == 2
        await s.rollback()


# --- AC-c: retry cap -> unverified surfaces in limits --------------------

class AlwaysRejectedWorker:
    """Re-submits the same claim every round; the agentic tier always rejects
    it as UNRELATED, so it exhausts the retry cap and becomes `unverified`."""

    async def investigate(self, brief, effort, qid, repairs=None, question_text=""):
        blob, ev = _first_claim_evidence()
        return WorkerResult(
            question_id=qid, status="completed", blobs=[blob],
            claims=[ProposedClaim(text="AC-c 과잉 클레임", confidence=0.6,
                                  evidence=[ev])],
            tokens_spent=2000, self_assessment=0.0,
        )

    def flush_partial(self, qid):
        return WorkerResult(question_id=qid, status="partial")


@pytest.mark.asyncio
async def test_ac_c_retry_cap_unverified_appears_in_limits():
    agentic = ScriptedAgentic([
        Verdict(ok=False, code="E_UNSUPPORTED", label="UNRELATED",
                detail="not about the question"),
    ])
    async with await db_manager.get_session() as s:
        run_id = await create_run(s, "root?", "dev")
        ledger = Ledger(s, run_id)
        capture = CapturingLLMCall()

        async def fake_node_summary(model, prompt, **kwargs):
            # reduce_node → json_call: return an empty (citation-free)
            # NodeSummary so reduce_tree never touches the network. The
            # unverified caveat is collected by the orchestrator from the
            # ledger, independent of this node answer.
            return (
                {
                    "answer": "",
                    "key_claim_ids": [],
                    "confidence": 0.0,
                    "caveats": [],
                    "conflicts": [],
                },
                LLMResponse(text="", input_tokens=1, output_tokens=1,
                            model=model),
            )

        synth = Synthesizer(ledger, llm_call=capture,
                            json_call=fake_node_summary)
        orch = Orchestrator(
            s, run_id, lambda: AlwaysRejectedWorker(), OkDet(),
            agentic_grader=agentic, ledger=ledger, synthesizer=synth,
            decompose_fn=_decompose_one, global_token_cap=6000,
        )
        await asyncio.wait_for(orch.run("root?"), timeout=30)

        # retry cap (2) exhausted -> claim is unverified
        status = (await s.execute(sql(
            "SELECT status FROM deep_analysis_claims WHERE run_id=:r"),
            {"r": run_id})).scalar()
        assert status == "unverified"
        # and it surfaces in the synthesizer's "한계와 미확인 사항" caveats
        assert "미확인: AC-c 과잉 클레임" in capture.prompt
        await s.rollback()


# --- D15 stall safety valve ---------------------------------------------

class NoProgressWorker:
    """Every pass is inert: 0 claims, 0 blobs, 0 tokens -> no verified, no
    feedback, no token burn. Without the valve this spins forever (score never
    drops below the floor, the global cap is never approached)."""

    async def investigate(self, brief, effort, qid, repairs=None, question_text=""):
        return WorkerResult(question_id=qid, status="completed", claims=[],
                            blobs=[], tokens_spent=0, self_assessment=0.0)

    def flush_partial(self, qid):
        return WorkerResult(question_id=qid, status="partial")


class AlwaysFailingWorker:
    """Models a systemic dependency failure that never spends tokens."""

    async def investigate(
        self,
        brief,
        effort,
        qid,
        repairs=None,
        question_text="",
    ):
        return WorkerResult(
            question_id=qid,
            status="failed",
            tokens_spent=0,
            fail_reason="systemic",
        )

    def flush_partial(self, qid):
        return WorkerResult(question_id=qid, status="partial")


@pytest.mark.asyncio
async def test_zero_token_worker_failure_stops_before_split_tree_expands():
    async with await db_manager.get_session() as s:
        run_id = await create_run(s, "root?", "dev")
        orch = Orchestrator(
            s,
            run_id,
            lambda: AlwaysFailingWorker(),
            OkDet(),
            decompose_fn=_decompose_one,
            global_token_cap=100000,
            max_depth=10,
            max_stall_rounds=2,
            synthesizer=FakeSynth(),
            checkpoint=s.commit,
        )

        async def split_decompose(text, *_a):
            return [
                {"text": f"{text}-child-{index}", "value_est": 0.5}
                for index in range(4)
            ]

        orch._split_decompose = split_decompose

        with pytest.raises(
            orchestrator_module.SystemicWorkerFailure,
            match="2 consecutive",
        ):
            await asyncio.wait_for(orch.run("root?"), timeout=1)

        event_count = (await s.execute(sql(
            "SELECT COUNT(*) FROM deep_analysis_events "
            "WHERE run_id=:r AND kind='systemic_failure_terminated'"
        ), {"r": run_id})).scalar()
        assert event_count == 1

        max_depth = (await s.execute(sql(
            "SELECT MAX(depth) FROM deep_analysis_questions WHERE run_id=:r"
        ), {"r": run_id})).scalar()
        assert max_depth == 1
        await s.rollback()


@pytest.mark.asyncio
async def test_stall_valve_terminates_without_reaching_global_cap():
    async with await db_manager.get_session() as s:
        run_id = await create_run(s, "root?", "dev")
        orch = Orchestrator(
            s, run_id, lambda: NoProgressWorker(), OkDet(),
            decompose_fn=_decompose_one, global_token_cap=100000,
            max_depth=2, max_stall_rounds=3, synthesizer=FakeSynth(),
        )

        async def split_decompose(text, *_a):
            return [{"text": "child", "value_est": 0.5}]

        orch._split_decompose = split_decompose
        # wait_for guards the suite: a broken valve would hang, not spin the CPU
        await asyncio.wait_for(orch.run("root?"), timeout=30)

        # zero tokens burned -> the run stopped because of the valve, not the cap
        assert await Ledger(s, run_id).total_spent() == 0
        # the valve fired at least once (sub force-terminated)
        st = (await s.execute(sql(
            "SELECT COUNT(*) FROM deep_analysis_events "
            "WHERE run_id=:r AND kind='stall_terminated'"),
            {"r": run_id})).scalar()
        assert st >= 1
        # nothing left spinning; the leaf abandoned at max depth
        open_left = (await s.execute(sql(
            "SELECT COUNT(*) FROM deep_analysis_questions "
            "WHERE run_id=:r AND status='open'"), {"r": run_id})).scalar()
        assert open_left == 0
        abandoned = (await s.execute(sql(
            "SELECT COUNT(*) FROM deep_analysis_questions "
            "WHERE run_id=:r AND status='abandoned'"), {"r": run_id})).scalar()
        assert abandoned >= 1
        await s.rollback()
