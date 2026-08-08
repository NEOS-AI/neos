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
        # One entry per assemble call, so a test can assert what the loop
        # handed forward from the previous rejection (W3-h).
        self.hints_seen = []

    async def reduce_tree(self, root_id):
        self.reduce_tree_calls += 1
        if self._summaries is not None:
            return dict(self._summaries)
        return {root_id: NodeSummary(root_id, "루트 요약 [C:aaaaaaaa]", [], 0.9, [])}

    async def assemble(
        self, root_summary, child_summaries, caveats, revision_hints=None
    ):
        self.assemble_calls += 1
        self.hints_seen.append(list(revision_hints or []))
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
async def test_a_rejection_reaches_the_next_assembly():
    """W3-h: 재시도는 판정을 되먹여야 한다.

    이전에는 `assemble` 이 매 시도 완전히 같은 세 인자를 받았다 -- 세 번의
    시도가 교정이 아니라 같은 분포에서 뽑은 표본 세 개였다. 표본 #5 의 결과가
    그 모양이다: 인용 없는 비율이 내려가지 않고 배회한다
    (`4098117c` .357 -> .500 -> .267, `d8cda7c5` .316 -> .235 -> .250).
    """
    ledger = FakeLedger()
    synth = FakeSynth()
    renderer = FlakyRenderer(fail_times=0)

    class _HintingGrader:
        async def grade(self, report, root_id):
            return Verdict(
                ok=False,
                code="E_REPORT_UNCITED",
                revision_hints=["- 2024년에 발효되었다"],
            )

    orch = _orch(ledger, synth, renderer, grader=_HintingGrader())

    await orch._finalize("root0001")

    assert synth.assemble_calls == 3
    # 첫 시도는 되먹일 것이 없고, 이후 시도는 직전 반려를 손에 쥔다.
    assert synth.hints_seen[0] == []
    assert synth.hints_seen[1] == ["- 2024년에 발효되었다"]
    assert synth.hints_seen[2] == ["- 2024년에 발효되었다"]


@pytest.mark.asyncio
async def test_an_orphan_citation_gets_its_own_hint_not_a_stale_one():
    """고아 마커 분기는 채점을 건너뛴다 -- 자기 힌트가 없으면 첫 시도에서는
    빈 손으로, 이후에는 *직전* 반려 사유를 그대로 물려주게 된다."""
    ledger = FakeLedger()
    synth = FakeSynth()
    renderer = FlakyRenderer(fail_times=99)
    orch = _orch(ledger, synth, renderer, grader=OkGrader())

    await orch._finalize("root0001")

    assert synth.hints_seen[0] == []
    assert "claim id" in synth.hints_seen[1][0]
    assert synth.hints_seen[2] == synth.hints_seen[1]


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
async def test_cap_exhaustion_ships_the_rendered_draft_not_the_raw_one():
    """W3-a: 캡이 소진돼도 사용자는 렌더된 리포트를 받아야 한다.

    2026-08-07 라이브 표본 6/6 run 이 이 경로로 나갔고, 전부 원본
    `[C:xxxxxxxx]` 마커를 달고 `## 출처` 절 없이 사용자에게 갔다. 원본 마커는
    독자가 따라갈 수 있는 인용이 아니라 내부 주소다. 게이트 정책을 어떻게
    정하든 이건 결함이다.
    """
    ledger = FakeLedger()
    synth = FakeSynth()
    renderer = FlakyRenderer(fail_times=0)  # render always clean
    orch = _orch(ledger, synth, renderer, grader=FailGrader())

    report = await orch._finalize("root0001")

    assert "[1] http://x" in report  # 렌더 결과가 실렸다
    assert "## 부록: 미해결 사유" in report


@pytest.mark.asyncio
async def test_cap_exhaustion_falls_back_to_the_raw_draft_when_nothing_rendered():
    """모든 시도가 orphan 이면 렌더된 텍스트가 존재하지 않는다.

    그 경우에만 원본 draft 로 떨어진다 -- 빈손으로 나가는 것보다 낫다(§6.8).
    """
    ledger = FakeLedger()
    synth = FakeSynth()
    renderer = FlakyRenderer(fail_times=99)
    orch = _orch(ledger, synth, renderer, grader=OkGrader())

    report = await orch._finalize("root0001")

    assert "DRAFT-3" in report
    assert "[1] http://x" not in report
    assert "## 부록: 미해결 사유" in report


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


class DiagnosticGrader:
    """Grader that reports the uncited measurements the real one now carries."""

    def __init__(self, ok):
        self._ok = ok

    async def grade(self, report, root_id):
        return Verdict(
            ok=self._ok,
            code="" if self._ok else "E_REPORT_UNCITED",
            diagnostics={
                "uncited_ratio": 0.75,
                "uncited_assertions": 4,
                "uncited_count": 3,
                "uncited_threshold": 0.2,
            },
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("ok", [True, False])
async def test_report_graded_event_carries_grader_diagnostics(ok):
    """G2: 156 recorded rejections stored only a code.

    Without the ratio and its denominator on the event there is no telling a
    threshold that is too tight from reports that are genuinely uncited. The
    passing case is parametrised too -- logging only rejections leaves a
    distribution censored at the threshold.
    """
    ledger = FakeLedger()
    orch = _orch(ledger, FakeSynth(), FlakyRenderer(fail_times=0),
                 grader=DiagnosticGrader(ok=ok))

    await orch._finalize("root0001")

    graded = [p for p in _graded(ledger) if p.get("code") != "E_ORPHAN_CITE"]
    assert graded
    assert graded[0]["uncited_ratio"] == 0.75
    assert graded[0]["uncited_assertions"] == 4
    assert graded[0]["uncited_count"] == 3
    assert graded[0]["uncited_threshold"] == 0.2


class DegradedJudgeGrader:
    """Mirrors what `ReportGrader.grade` now returns for a budget-starved
    judge: `ok=True` (the deterministic pass survives) with a `diagnostics`
    marker riding along, since `report.py:205`'s `detail` field is never read
    by the orchestrator's sink below.
    """

    async def grade(self, report, root_id):
        return Verdict(
            ok=True,
            detail="judge_budget_exhausted",
            diagnostics={"judge": "budget_exhausted"},
        )


@pytest.mark.asyncio
async def test_report_graded_event_persists_the_judge_budget_marker():
    """FIX 1: the existing report-grader test asserted `verdict.detail` in
    process, which is exactly what let this slip through -- the orchestrator's
    `report_graded` sink (orchestrator.py:886-902) logs `ok`, `attempt`,
    `code`, and `**verdict.diagnostics`, and never reads `detail` at all.

    This asserts the marker at the level that actually matters: what lands in
    the ledger's `report_graded` event, not what the grader returns in
    memory. Before the fix, this payload was byte-identical to a judge that
    ran and approved.
    """
    ledger = FakeLedger()
    orch = _orch(
        ledger, FakeSynth(), FlakyRenderer(fail_times=0),
        grader=DegradedJudgeGrader(),
    )

    await orch._finalize("root0001")

    graded = _graded(ledger)
    assert graded == [{"ok": True, "attempt": 0, "judge": "budget_exhausted"}]


@pytest.mark.asyncio
async def test_report_graded_omits_diagnostics_when_the_grader_reports_none():
    """The orphan-citation path never reached the gate, so it measured
    nothing -- an empty diagnostics dict must not add empty keys."""
    ledger = FakeLedger()
    orch = _orch(ledger, FakeSynth(), FlakyRenderer(fail_times=1),
                 grader=OkGrader())

    await orch._finalize("root0001")

    assert _graded(ledger)[0] == {
        "ok": False, "code": "E_ORPHAN_CITE", "attempt": 0
    }


@pytest.mark.asyncio
async def test_the_harness_guarantees_the_limits_section_the_model_lost():
    """W3-e: 필수 마지막 절은 하네스가 보장한다.

    조립 출력은 세 표본 54회 전부 상한에 정확히 붙어 잘렸고(확장 재시도
    이후에도), 프롬프트가 마지막에 요구하는 `## 한계와 미확인 사항` 이 매번
    죽었다. 두 표본 연속으로 **인용 기준을 넘긴 유일한 시도**가 그 절이
    없다는 이유로 반려됐다(`dd8dc763` #2 ratio 0.267, `a38d441a` #2 ratio
    0.191, 임계값 0.20).

    `## 출처` 는 CitationRenderer 가 붙이므로 잘림과 무관하게 항상 있다.
    한계 절만 모델에게 맡겨져 있었다 -- 그런데 그 내용(`caveats`)은
    `_finalize` 가 이미 손에 들고 있다. 구조적 완전성은 하네스의 일이지
    모델의 일이 아니다.
    """
    ledger = FakeLedger()

    class _TruncatedSynth(FakeSynth):
        async def assemble(
            self, root_summary, child_summaries, caveats, revision_hints=None
        ):
            self.assemble_calls += 1
            # 본문 중간에서 잘린 모양 -- 한계 절에 닿지 못했다.
            return "## 요약\n답.\n\n## 본문\n근거가 이어지다가 잘"

    synth = _TruncatedSynth()
    renderer = FlakyRenderer(fail_times=0)
    orch = _orch(ledger, synth, renderer, grader=OkGrader())

    report = await orch._finalize("root0001")

    assert "## 한계와 미확인 사항" in report
