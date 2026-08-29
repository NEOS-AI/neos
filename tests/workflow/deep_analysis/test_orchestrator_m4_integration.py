"""M4 Task 6: end-to-end integration of the whole M4 finalize path (AC-a/b/c)
exercised through the *real* Ledger + Synthesizer with only the worker,
grader, json/llm seams, and (for AC-c) the citation renderer faked. NO real
LLM/network call happens anywhere in this module.

This is the M4 closing gate: the three acceptance criteria that Tasks 1-5
proved in isolation are re-proven together, riding on top of a genuine ledger
so the hierarchical reduce, the deterministic both-sides annotation, and the
assembly retry loop are shown to compose.

- AC-a (bounded per-node context): `reduce_tree` over a depth-3 tree on the
  real ledger; the root's logged `node_summary.prompt_chars` does NOT scale
  with grandchild count, and no grandchild-level text leaks into the root
  prompt. (Driven straight through `reduce_tree` per the task brief -- a full
  `run()` cannot deterministically shape a depth-3 tree with a fixed number of
  grandchildren.)
- AC-b (both-sides): a full `Orchestrator.run()` where the worker emits an
  equal-tier contradiction; the reduced child summary carries a `ConflictNote`,
  conflict resolution appends the deterministic "양론 병기" clause with both
  `[C:...]` markers, and those markers survive assembly and resolve to real
  footnotes in the final report.
- AC-c (orphan -> assembly retry): a full `Orchestrator.run()` whose citation
  renderer raises `OrphanCitationError` on the first assembly then renders
  cleanly; the run retries and the `report_graded` events show the attempt-0
  failure followed by the attempt-1 success.
"""

import json
import re
from types import SimpleNamespace

import pytest
from sqlalchemy import text as sql

import neos.database.models  # noqa: F401 - register Base metadata / FK targets
from neos.database.connection import db_manager
from neos.workflow.deep_analysis.citation import (
    CitationRenderer,
    OrphanCitationError,
)
from neos.workflow.deep_analysis.ledger import Ledger, create_run
from neos.workflow.deep_analysis.llm import LLMResponse
from neos.workflow.deep_analysis.models import (
    ProposedBlob,
    ProposedClaim,
    ProposedEvidence,
    Verdict,
    WorkerResult,
)
from neos.workflow.deep_analysis.orchestrator import Orchestrator
from neos.workflow.deep_analysis.synthesizer import Synthesizer


# --- shared helpers ------------------------------------------------------

_QID_RE = re.compile(r"질문 ID: (\w+)")
_OWN_BLOCK_RE = re.compile(r"내 verified 클레임:\n(.*?)\n\n자식 요약:", re.S)
_MARKER_RE = re.compile(r"\[C:([0-9a-f]{8})\]")
_CHILD_BLOCK_RE = re.compile(r"직계 자식 요약:\n(.*?)\n\n한계와 미조사 사항:", re.S)


def _node_payload(qid, answer, *, conflicts=None, key_claim_ids=None):
    return {
        "question_id": qid,
        "answer": answer,
        "key_claim_ids": list(key_claim_ids or []),
        "confidence": 0.7,
        "caveats": [],
        "conflicts": list(conflicts or []),
    }


async def _events(session, run_id, kind):
    rows = (
        await session.execute(
            sql(
                "SELECT payload FROM deep_analysis_events "
                "WHERE run_id=:r AND kind=:k ORDER BY seq"
            ),
            {"r": run_id, "k": kind},
        )
    ).scalars()
    return [json.loads(p) for p in rows]


class OkDet:
    async def grade(self, claim):
        return Verdict(ok=True)


class OkReportGrader:
    async def grade(self, report, root_id):
        return Verdict(ok=True)


def _decompose_one(_root):
    return [{"text": "sub", "value_est": 0.5}]


async def _no_split(_text, *_a):
    return []


# =========================================================================
# AC-a: bounded per-node context through the real ledger + reduce_tree
# =========================================================================

class QidMapJSON:
    """reduce_node seam: captures every prompt and returns a scripted answer
    keyed by the node's question id (parsed from the rendered prompt). The
    child's answer is a FIXED-length token regardless of how many
    grandchildren fed into it -- that constant is what keeps the root's
    context bounded."""

    def __init__(self, answers):
        self.answers = answers
        self.prompts = []

    async def __call__(self, model, prompt, **kw):
        self.prompts.append(prompt)
        qid = _QID_RE.search(prompt).group(1)
        data = _node_payload(qid, self.answers.get(qid, "?"))
        return data, SimpleNamespace(
            input_tokens=len(prompt) // 4, output_tokens=10
        )


async def _build_depth3_and_reduce(session, num_grandchildren):
    """root -> child -> [grandchildren] on the real ledger, each grandchild
    carrying one verified claim with a unique excerpt. Returns
    (run_id, capture, summaries, root_id)."""
    run_id = await create_run(session, "root?", "dev")
    ledger = Ledger(session, run_id)
    root_id = await ledger.open_question(
        "root question", None, value_est=1.0, cap_tokens=100000, depth=0
    )
    child_id = await ledger.open_question(
        "child question", root_id, value_est=0.5, cap_tokens=50000, depth=1
    )
    gc_ids = []
    for i in range(num_grandchildren):
        gid = await ledger.open_question(
            f"grandchild {i}", child_id, value_est=0.5, cap_tokens=10000, depth=2
        )
        gc_ids.append(gid)
        await ledger._transition(gid, "investigating")
        result = WorkerResult(
            question_id=gid,
            status="completed",
            blobs=[
                ProposedBlob(
                    content_hash=f"{i:016d}",
                    source_url=f"http://gc{i}",
                    http_status=200,
                    raw_text="body",
                )
            ],
            claims=[
                ProposedClaim(
                    text=f"grandchild claim content {i}",
                    confidence=0.7,
                    evidence=[
                        ProposedEvidence(
                            f"http://gc{i}",
                            f"UNIQUE_GRANDCHILD_EXCERPT_{i}",
                            f"{i:016d}",
                        )
                    ],
                )
            ],
            tokens_spent=10,
            self_assessment=0.9,
        )
        await ledger.commit_pass(
            gid, result, {c.text: Verdict(ok=True) for c in result.claims},
            judge_tokens_spent=0,
        )
    await ledger.record_split(child_id, gc_ids)
    await ledger.record_split(root_id, [child_id])

    answers = {root_id: "root ans", child_id: "CHILD_FIXED_LENGTH_SUMMARY_TOKEN"}
    for i, gid in enumerate(gc_ids):
        answers[gid] = f"g{i} summary"
    capture = QidMapJSON(answers)
    synth = Synthesizer(ledger, json_call=capture)
    summaries = await synth.reduce_tree(root_id)
    return run_id, capture, summaries, root_id


async def _root_prompt_chars(session, run_id, root_id):
    rows = (
        await session.execute(
            sql(
                "SELECT payload FROM deep_analysis_events "
                "WHERE run_id=:r AND kind='node_summary' AND qid=:q ORDER BY seq"
            ),
            {"r": run_id, "q": root_id},
        )
    ).scalars()
    payloads = [json.loads(p) for p in rows]
    assert payloads, "no node_summary event logged for root"
    return payloads[-1]["prompt_chars"]


@pytest.mark.asyncio
async def test_ac_a_root_context_is_bounded_across_grandchild_counts():
    async with await db_manager.get_session() as session:
        run_small, cap_small, sums_small, root_small = (
            await _build_depth3_and_reduce(session, 1)
        )
        run_large, cap_large, sums_large, root_large = (
            await _build_depth3_and_reduce(session, 5)
        )

        # Both trees fully reduced bottom-up: root + child + every grandchild.
        assert root_small in sums_small
        assert sums_large[root_large].answer == "root ans"
        gc_answers = {
            s.answer for s in sums_large.values() if s.answer.startswith("g")
        }
        assert gc_answers == {f"g{i} summary" for i in range(5)}

        # The root prompt is the LAST prompt captured in each run (post-order
        # visits the root last). No grandchild-level content -- neither a raw
        # excerpt nor a per-grandchild summary answer -- may appear in it.
        root_prompt_small = cap_small.prompts[-1]
        root_prompt_large = cap_large.prompts[-1]
        for i in range(5):
            assert f"UNIQUE_GRANDCHILD_EXCERPT_{i}" not in root_prompt_small
            assert f"UNIQUE_GRANDCHILD_EXCERPT_{i}" not in root_prompt_large
            assert f"g{i} summary" not in root_prompt_small
            assert f"g{i} summary" not in root_prompt_large

        # AC-a signal: the root's logged prompt_chars does NOT scale with the
        # grandchild count -- it depends only on the child's constant-length
        # answer, so the two runs' root prompts are (near-)identical in size.
        chars_small = await _root_prompt_chars(session, run_small, root_small)
        chars_large = await _root_prompt_chars(session, run_large, root_large)
        assert abs(chars_small - chars_large) <= 5
        assert abs(len(root_prompt_small) - len(root_prompt_large)) <= 5

        await session.rollback()


# =========================================================================
# AC-b: equal-tier contradiction -> both-sides ("양론") in the final report
# =========================================================================

class ConflictWorker:
    """One completed pass with two equal-tier (tier-2) contradicting claims;
    high self-assessment so the question resolves in a single round."""

    async def investigate(self, brief, effort, qid, repairs=None, question_text=""):
        return WorkerResult(
            question_id=qid,
            status="completed",
            blobs=[
                ProposedBlob("a" * 16, "https://example.com/a", 200, "A body"),
                ProposedBlob("b" * 16, "https://example.net/b", 200, "B body"),
            ],
            claims=[
                ProposedClaim(
                    "지연이 40% 감소했다",
                    0.6,
                    [ProposedEvidence("https://example.com/a", "40% 감소", "a" * 16)],
                ),
                ProposedClaim(
                    "지연이 10% 증가했다",
                    0.6,
                    [ProposedEvidence("https://example.net/b", "10% 증가", "b" * 16)],
                ),
            ],
            tokens_spent=100,
            self_assessment=0.9,
        )

    def flush_partial(self, qid):
        return WorkerResult(question_id=qid, status="partial")


class ConflictJSON:
    """reduce_node seam. The node that owns the two contradicting claims (its
    '내 verified 클레임' block carries both markers) emits a ConflictNote
    between them; every other node (e.g. the root, whose own block is empty)
    emits no conflict."""

    async def __call__(self, model, prompt, **kw):
        qid = _QID_RE.search(prompt).group(1)
        own_block = _OWN_BLOCK_RE.search(prompt).group(1)
        own_ids = _MARKER_RE.findall(own_block)
        if len(own_ids) >= 2:
            a, b = own_ids[0], own_ids[1]
            data = _node_payload(
                qid,
                f"두 근거가 상충한다 [C:{a}] 및 [C:{b}]",
                key_claim_ids=[a, b],
                conflicts=[{"claim_a": a, "claim_b": b, "nature": "수치 불일치"}],
            )
        else:
            data = _node_payload(qid, "루트 종합")
        return data, SimpleNamespace(
            input_tokens=len(prompt) // 4, output_tokens=10
        )


class EchoAssembleLLM:
    """assemble seam: echoes the prompt's direct-child block (which now carries
    the both-sides clause + markers) into a well-formed report so the markers
    reach the real CitationRenderer."""

    def __init__(self):
        self.drafts = []

    async def __call__(self, model, prompt, **kw):
        child_block = _CHILD_BLOCK_RE.search(prompt).group(1)
        text = (
            "## 요약\n연구 종합.\n\n## 본문\n"
            f"{child_block}\n\n## 한계와 미확인 사항\n없음\n\n## 출처"
        )
        self.drafts.append(text)
        return LLMResponse(text=text, input_tokens=5, output_tokens=5, model=model)


@pytest.mark.asyncio
async def test_ac_b_equal_tier_conflict_yields_both_sides_in_report():
    async with await db_manager.get_session() as session:
        run_id = await create_run(session, "root?", "dev")
        ledger = Ledger(session, run_id)
        assemble_llm = EchoAssembleLLM()
        synth = Synthesizer(ledger, llm_call=assemble_llm, json_call=ConflictJSON())
        orch = Orchestrator(
            session,
            run_id,
            lambda: ConflictWorker(),
            OkDet(),
            ledger=ledger,
            synthesizer=synth,
            citation_renderer=CitationRenderer(ledger),
            report_grader=OkReportGrader(),
            decompose_fn=_decompose_one,
            global_token_cap=5000,
        )
        orch._split_decompose = _no_split

        out = await orch.run("root?")
        report = out["report_markdown"]

        # The pre-render draft carries the deterministic both-sides clause with
        # BOTH literal [C:...] markers (AC-b core assertion).
        draft = assemble_llm.drafts[-1]
        assert "양론" in draft
        markers = _MARKER_RE.findall(draft)
        assert len(set(markers)) == 2, markers

        # value_est (0.5) is below conflict_value_threshold (0.6), so the
        # conflict does NOT trigger reinvestigation: a single assembly ships.
        assert len(assemble_llm.drafts) == 1
        reinvest = await _events(session, run_id, "conflict_reinvestigation")
        assert reinvest == []

        # In the final rendered report the both-sides clause survives and both
        # markers resolve to real footnotes (equal-tier -> neither is dropped).
        assert "양론" in report
        assert "[1]" in report and "[2]" in report
        assert "example.com/a" in report and "example.net/b" in report

        graded = await _events(session, run_id, "report_graded")
        assert graded == [{"ok": True, "attempt": 0}]
        await session.rollback()


# =========================================================================
# AC-c: orphan citation on first assembly -> retry -> success, through run()
# =========================================================================

class SimpleWorker:
    """One completed pass with a single verified claim; resolves in one round."""

    async def investigate(self, brief, effort, qid, repairs=None, question_text=""):
        return WorkerResult(
            question_id=qid,
            status="completed",
            blobs=[ProposedBlob("h1", "http://x", 200, "body")],
            claims=[
                ProposedClaim(
                    "검증된 발견이다",
                    0.7,
                    [ProposedEvidence("http://x", "excerpt", "h1")],
                )
            ],
            tokens_spent=100,
            self_assessment=0.9,
        )

    def flush_partial(self, qid):
        return WorkerResult(question_id=qid, status="partial")


class PlainJSON:
    """reduce_node seam: conflict-free NodeSummary keyed by node id."""

    async def __call__(self, model, prompt, **kw):
        qid = _QID_RE.search(prompt).group(1)
        return _node_payload(qid, "노드 요약"), SimpleNamespace(
            input_tokens=len(prompt) // 4, output_tokens=10
        )


class NumberedAssembleLLM:
    """assemble seam: a fresh numbered draft each call so a retry is visible."""

    def __init__(self):
        self.calls = 0

    async def __call__(self, model, prompt, **kw):
        self.calls += 1
        return LLMResponse(
            text=f"DRAFT-{self.calls}\n\n## 출처",
            input_tokens=5,
            output_tokens=5,
            model=model,
        )


class FlakyRenderer:
    """Raises OrphanCitationError on the first render, then renders cleanly."""

    def __init__(self, fail_times):
        self.fail_times = fail_times
        self.calls = 0

    async def render(self, draft):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise OrphanCitationError("aaaaaaaa")
        return draft + "\n[1] http://x"


@pytest.mark.asyncio
async def test_ac_c_orphan_citation_retries_assembly_through_run():
    async with await db_manager.get_session() as session:
        run_id = await create_run(session, "root?", "dev")
        ledger = Ledger(session, run_id)
        assemble_llm = NumberedAssembleLLM()
        synth = Synthesizer(ledger, llm_call=assemble_llm, json_call=PlainJSON())
        renderer = FlakyRenderer(fail_times=1)
        orch = Orchestrator(
            session,
            run_id,
            lambda: SimpleWorker(),
            OkDet(),
            ledger=ledger,
            synthesizer=synth,
            citation_renderer=renderer,
            report_grader=OkReportGrader(),
            decompose_fn=_decompose_one,
            global_token_cap=5000,
        )
        orch._split_decompose = _no_split

        out = await orch.run("root?")
        report = out["report_markdown"]

        # The second assembly is the one that shipped (first orphaned).
        assert "DRAFT-2" in report
        assert assemble_llm.calls == 2

        # report_graded events show the attempt-0 orphan failure then the
        # attempt-1 success -- the retry trace AC-c calls for.
        graded = await _events(session, run_id, "report_graded")
        assert graded[0] == {
        "ok": False,
        "code": "E_ORPHAN_CITE",
        "attempt": 0,
        "orphan_claim_id": "aaaaaaaa",
    }
        assert graded[1] == {"ok": True, "attempt": 1}

        completed = (
            await session.execute(
                sql(
                    "SELECT status FROM deep_analysis_runs WHERE id=:r"
                ),
                {"r": run_id},
            )
        ).scalar()
        assert completed == "completed"
        await session.rollback()
