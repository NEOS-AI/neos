import json
from dataclasses import dataclass

import pytest

from neos.workflow.deep_analysis.graders.report import ReportGrader
from neos.workflow.deep_analysis.llm import TruncatedResponseError
from neos.workflow.deep_analysis.token_budget import TokenBudgetExhausted

pytestmark = pytest.mark.no_db


@dataclass
class Question:
    id: str
    text: str
    status: str = "resolved"


class FakeLedger:
    def __init__(self, children=None, root=None):
        self._children = children or []
        self._root = root

    async def children(self, question_id):
        return self._children

    async def get_question(self, question_id):
        return self._root

    async def root_question(self):
        return self._root


class FakeJudge:
    """Anthropic-shaped fake; only used with judge_model="claude-j" so the
    llm client-dispatch (model.startswith("claude")) routes here instead of
    the OpenAI branch."""

    def __init__(self, answers_question, strength_ok, rationale="r"):
        self.messages = self
        self.calls = 0
        self._payload = {
            "answers_question": answers_question,
            "strength_ok": strength_ok,
            "rationale": rationale,
        }

    async def create(self, **kw):
        self.calls += 1
        payload = json.dumps(self._payload)

        class U:
            input_tokens = 5
            output_tokens = 3

        class B:
            type = "text"
            text = payload

        class R:
            content = [B()]
            usage = U()
            model = kw["model"]

        return R()


class GarbageJudge(FakeJudge):
    async def create(self, **kw):
        self.calls += 1

        class U:
            input_tokens = 1
            output_tokens = 1

        class B:
            type = "text"
            text = "not json"

        class R:
            content = [B()]
            usage = U()
            model = kw["model"]

        return R()


CHILD1 = Question("child001", "시장 규모는 얼마인가", status="resolved")
CHILD2 = Question("child002", "주요 업체는 누구인가", status="resolved")


def _clean_report() -> str:
    return (
        "## 요약\n핵심 내용입니다[1].\n\n"
        "## 본문\n시장 규모는 얼마인가에 대한 답은 100억 달러[1]이다. "
        "주요 업체는 누구인가에 대한 답은 A사와 B사이다[2].\n\n"
        "## 한계와 미확인 사항\n추가 조사가 필요하다.\n\n"
        "## 출처\n[1] https://a.example\n[2] https://b.example\n"
    )


def _grader(ledger, **kw):
    return ReportGrader(ledger, judge_model=kw.pop("judge_model", "claude-j"), **kw)


async def _exhausted_json_call(*args, **kwargs):
    raise TokenBudgetExhausted("cap")


# ---- deterministic ----------------------------------------------------


@pytest.mark.asyncio
async def test_missing_limits_section_fails():
    ledger = FakeLedger(children=[CHILD1, CHILD2])
    report = (
        "## 요약\n핵심 내용입니다[1].\n\n"
        "## 본문\n시장 규모는 얼마인가에 대한 답은 100억 달러[1]이다. "
        "주요 업체는 누구인가에 대한 답은 A사와 B사이다[2].\n\n"
        "## 출처\n[1] https://a.example\n[2] https://b.example\n"
    )

    verdict = await _grader(ledger).grade_deterministic(report, "root0001")

    assert verdict.ok is False
    assert verdict.code == "E_REPORT_NO_LIMITS"


@pytest.mark.asyncio
async def test_uncited_ratio_beats_missing_limits_on_priority():
    """§6.8 order is (a) orphan, (b) uncited, (c) question, (d) limits --
    a report failing both (b) and (d) must surface E_REPORT_UNCITED, not
    E_REPORT_NO_LIMITS."""
    ledger = FakeLedger(children=[CHILD1, CHILD2])
    report = (
        "## 요약\n2020년 매출은 100억 달러였다. "
        "2021년 매출은 120억 달러였다. "
        "2022년 매출은 150억 달러였다.\n\n"
        "## 본문\n시장 규모는 얼마인가에 대한 답은 200억 달러이다. "
        "주요 업체는 누구인가에 대한 답은 A사이다.\n\n"
        "## 출처\n[1] https://a.example\n"
    )
    # sanity: no limits section present, so this report also fails (d) if we
    # ever reach it -- the assertion below proves we don't.
    assert "한계와 미확인 사항" not in report

    verdict = await _grader(ledger).grade_deterministic(report, "root0001")

    assert verdict.ok is False
    assert verdict.code == "E_REPORT_UNCITED"


@pytest.mark.asyncio
async def test_unmentioned_resolved_question_fails():
    ledger = FakeLedger(children=[CHILD1, CHILD2])
    report = (
        "## 요약\n핵심 내용입니다[1].\n\n"
        "## 본문\n시장 규모는 얼마인가에 대한 답은 100억 달러[1]이다.\n\n"
        "## 한계와 미확인 사항\n추가 조사가 필요하다.\n\n"
        "## 출처\n[1] https://a.example\n"
    )

    verdict = await _grader(ledger).grade_deterministic(report, "root0001")

    assert verdict.ok is False
    assert verdict.code == "E_REPORT_MISSING_QUESTION"
    assert "주요 업체는 누구인가" in verdict.detail


@pytest.mark.asyncio
async def test_raw_citation_marker_fails():
    ledger = FakeLedger(children=[])
    report = "## 본문\n검증되지 않은 문장 [C:1234abcd].\n\n## 한계와 미확인 사항\n없음.\n"

    verdict = await _grader(ledger).grade_deterministic(report, "root0001")

    assert verdict.ok is False
    assert verdict.code == "E_ORPHAN_CITE"


@pytest.mark.asyncio
async def test_high_uncited_assertion_ratio_fails():
    ledger = FakeLedger(children=[CHILD1, CHILD2])
    report = (
        "## 요약\n2020년 시장 규모는 100억 달러였다. "
        "2021년에는 120억 달러로 성장했다. "
        "2022년에는 150억 달러였다. "
        "2023년 규모는 180억 달러였다[1]. "
        "시장 규모는 얼마인가에 대한 답은 100억 달러다. "
        "주요 업체는 누구인가에 대한 답은 A사이다.\n\n"
        "## 한계와 미확인 사항\n조사 미흡.\n\n"
        "## 출처\n[1] https://a.example\n"
    )

    verdict = await _grader(ledger).grade_deterministic(report, "root0001")

    assert verdict.ok is False
    assert verdict.code == "E_REPORT_UNCITED"


@pytest.mark.asyncio
async def test_clean_report_passes_deterministic():
    ledger = FakeLedger(children=[CHILD1, CHILD2])

    verdict = await _grader(ledger).grade_deterministic(_clean_report(), "root0001")

    assert verdict.ok is True
    assert verdict.code == ""


@pytest.mark.asyncio
async def test_grade_keeps_deterministic_pass_when_agentic_budget_exhausts():
    root = Question("root0001", "루트 질문")
    grader = _grader(
        FakeLedger(children=[CHILD1, CHILD2], root=root),
        json_call=_exhausted_json_call,
    )

    verdict = await grader.grade(_clean_report(), root.id)

    assert verdict.ok is True


@pytest.mark.asyncio
async def test_grade_keeps_deterministic_pass_when_agentic_judge_is_truncated():
    """재조립은 잘린 judge를 고치지 못한다 — 초안 품질과 무관하기 때문이다.

    반려하면 orchestrator가 초안을 다시 조립하는데, 같은 judge가 같은 상한에서
    또 잘린다. report_retry_cap + 1회의 synthesizer 호출을 태우고 제자리다.
    """
    calls = 0

    async def truncated_json_call(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise TruncatedResponseError("cut off mid-rationale")

    root = Question("root0001", "루트 질문")
    grader = _grader(
        FakeLedger(children=[CHILD1, CHILD2], root=root),
        json_call=truncated_json_call,
    )

    verdict = await grader.grade(_clean_report(), root.id)

    assert verdict.ok is True
    assert verdict.detail == "judge_truncated"
    assert calls == 1


@pytest.mark.asyncio
async def test_truncated_report_judge_does_not_mask_a_deterministic_failure():
    """결정론적 게이트가 먼저 막았으면 judge는 불리지도 않는다."""
    calls = 0

    async def truncated_json_call(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise TruncatedResponseError("cut off mid-rationale")

    grader = _grader(FakeLedger(), json_call=truncated_json_call)

    verdict = await grader.grade("한계 절이 없는 본문.", "root0001")

    assert verdict.ok is False
    assert verdict.code == "E_REPORT_NO_LIMITS"
    assert calls == 0


# ---- agentic ------------------------------------------------------------


@pytest.mark.asyncio
async def test_agentic_fails_when_answers_question_false():
    judge = FakeJudge(answers_question=False, strength_ok=True)
    grader = ReportGrader(FakeLedger(), judge_model="claude-j", llm_client=judge)

    verdict = await grader.grade_agentic(_clean_report(), "루트 질문")

    assert verdict.ok is False
    assert verdict.code == "E_REPORT_AGENTIC"


@pytest.mark.asyncio
async def test_agentic_fails_when_strength_not_ok():
    judge = FakeJudge(answers_question=True, strength_ok=False)
    grader = ReportGrader(FakeLedger(), judge_model="claude-j", llm_client=judge)

    verdict = await grader.grade_agentic(_clean_report(), "루트 질문")

    assert verdict.ok is False
    assert verdict.code == "E_REPORT_AGENTIC"


@pytest.mark.asyncio
async def test_agentic_passes_when_both_true():
    judge = FakeJudge(answers_question=True, strength_ok=True)
    grader = ReportGrader(FakeLedger(), judge_model="claude-j", llm_client=judge)

    verdict = await grader.grade_agentic(_clean_report(), "루트 질문")

    assert verdict.ok is True
    assert judge.calls == 1


@pytest.mark.asyncio
async def test_agentic_unparseable_judge_degrades_to_pass():
    judge = GarbageJudge(answers_question=True, strength_ok=True)
    grader = ReportGrader(FakeLedger(), judge_model="claude-j", llm_client=judge)

    verdict = await grader.grade_agentic(_clean_report(), "루트 질문")

    assert verdict.ok is True
    assert "judge_unparseable" in verdict.detail


# ---- grade() orchestration ----------------------------------------------


@pytest.mark.asyncio
async def test_grade_short_circuits_on_deterministic_failure():
    ledger = FakeLedger(children=[CHILD1, CHILD2], root=Question("root0001", "루트 질문"))
    judge = FakeJudge(answers_question=True, strength_ok=True)
    report = (
        "## 요약\n핵심 내용입니다[1].\n\n"
        "## 본문\n시장 규모는 얼마인가에 대한 답은 100억 달러[1]이다. "
        "주요 업체는 누구인가에 대한 답은 A사와 B사이다[2].\n\n"
        "## 출처\n[1] https://a.example\n[2] https://b.example\n"
    )

    grader = ReportGrader(ledger, judge_model="claude-j", llm_client=judge)
    verdict = await grader.grade(report, "root0001")

    assert verdict.ok is False
    assert verdict.code == "E_REPORT_NO_LIMITS"
    assert judge.calls == 0


@pytest.mark.asyncio
async def test_grade_runs_agentic_after_deterministic_pass():
    root = Question("root0001", "루트 질문")
    ledger = FakeLedger(children=[CHILD1, CHILD2], root=root)
    judge = FakeJudge(answers_question=True, strength_ok=True)

    grader = ReportGrader(ledger, judge_model="claude-j", llm_client=judge)
    verdict = await grader.grade(_clean_report(), "root0001")

    assert verdict.ok is True
    assert judge.calls == 1


class CeilingRecordingJudge(FakeJudge):
    """Records the max_tokens each call was dispatched with."""

    def __init__(self):
        super().__init__(answers_question=True, strength_ok=True)
        self.max_tokens = []

    async def create(self, **kw):
        self.max_tokens.append(kw["max_tokens"])
        return await super().create(**kw)


@pytest.mark.asyncio
async def test_report_judge_ceiling_comes_from_settings_not_a_literal():
    """The ceiling was hardcoded at 400 in report.py.

    It is the same output shape on the same model as the claim judge, so the
    two must not drift apart silently -- a literal in report.py cannot be
    tuned when the sibling stage's measurements move.
    """
    from neos.config.settings import settings

    judge = CeilingRecordingJudge()
    grader = ReportGrader(FakeLedger(), judge_model="claude-j", llm_client=judge)

    await grader.grade_agentic(_clean_report(), "루트 질문")

    expected = settings.config.deep_analysis.report_judge_max_output_tokens
    assert judge.max_tokens == [expected]
    assert expected > 400  # the old literal must no longer bind


# ---- G2: the uncited gate must be observable ------------------------------


def _uncited_diag(verdict):
    return {
        k: verdict.diagnostics.get(k)
        for k in ("uncited_ratio", "uncited_assertions", "uncited_count",
                  "uncited_threshold")
    }


@pytest.mark.asyncio
async def test_rejected_report_reports_the_ratio_and_its_denominator():
    """A bare ratio cannot be calibrated against.

    1.00 from one assertion is a short report; 1.00 from forty is a badly
    cited one. Recording the ratio without its denominator makes the two
    indistinguishable after the fact, which is what left 156 recorded
    rejections uninterpretable.
    """
    report = (
        "## 본문\n"
        "2024년에 규정이 발효되었다.\n"
        "적용 대상은 2026년부터 확대된다.\n"
        "\n## 한계와 미확인 사항\n없음.\n"
    )

    verdict = await _grader(FakeLedger()).grade_deterministic(report, "root0001")

    assert verdict.ok is False
    assert verdict.code == "E_REPORT_UNCITED"
    diag = _uncited_diag(verdict)
    assert diag["uncited_assertions"] == 2
    assert diag["uncited_count"] == 2
    assert diag["uncited_ratio"] == 1.0


def test_latin_proper_nouns_do_not_count_when_a_korean_particle_follows():
    """`\\b[A-Z][A-Za-z]{2,}\\b` cannot fire on "Act가" or "OpenAI가".

    Python's `\\b` sees no boundary between Latin and Hangul -- both are word
    characters -- and Korean attaches its particles directly. So in Korean
    prose the proper-noun half of the assertion heuristic is nearly dead and
    the gate is driven almost entirely by digits.

    That shrinks the denominator, which is what makes the 0.20 threshold so
    easy to breach: at four assertions a single uncited sentence is already
    0.25. Pinned because it is load-bearing for any threshold calibration,
    not because the behaviour is desirable.
    """
    from neos.workflow.deep_analysis.graders.report import _PROPER_NOUN

    assert _PROPER_NOUN.findall("EU AI Act가 적용된다.") == []
    assert _PROPER_NOUN.findall("OpenAI가 발표했다.") == []
    assert _PROPER_NOUN.findall("The Act applies.") == ["The", "Act"]


@pytest.mark.asyncio
async def test_passing_report_also_reports_its_ratio():
    """Logging only rejections yields a censored distribution.

    Calibrating a threshold needs the passing side too — otherwise every
    recorded sample sits above the cut by construction.
    """
    verdict = await _grader(
        FakeLedger(children=[CHILD1, CHILD2])
    ).grade_deterministic(_clean_report(), "root0001")

    assert verdict.ok is True
    diag = _uncited_diag(verdict)
    assert diag["uncited_ratio"] is not None
    assert diag["uncited_assertions"] is not None


@pytest.mark.asyncio
async def test_uncited_threshold_comes_from_settings():
    from neos.config.settings import settings

    verdict = await _grader(
        FakeLedger(children=[CHILD1, CHILD2])
    ).grade_deterministic(_clean_report(), "root0001")

    assert (
        verdict.diagnostics["uncited_threshold"]
        == settings.config.deep_analysis.report_uncited_ratio_max
    )


@pytest.mark.asyncio
async def test_a_report_with_no_assertions_scores_a_perfect_zero():
    """CHARACTERISATION, not endorsement — this is G1's finding.

    `_uncited_stats` returns 0.0 when nothing looks like a factual assertion,
    so a report that asserts nothing is scored as perfectly cited and sails
    through the gate that rejects substantive ones.

    Measured consequence: of 61 runs, the 9 that passed had a median of 0
    verified claims (7 of them had no claims at all), while the 52 that were
    rejected had a median of 4. The gate is passing vacuous reports and
    blocking the ones that found something.

    Pinned so that changing it is a deliberate decision with a failing test,
    not an accident. Whether an assertion-less report should pass, fail, or
    be judged some third way is a policy question this test does not answer.
    """
    empty = "## 본문\n특별한 내용이 없다.\n\n## 한계와 미확인 사항\n없음.\n"

    verdict = await _grader(FakeLedger()).grade_deterministic(empty, "root0001")

    assert verdict.ok is True
    assert verdict.diagnostics["uncited_assertions"] == 0


@pytest.mark.asyncio
async def test_budget_exhausted_judge_is_marked_not_silent():
    root = Question("root0001", "루트 질문")
    grader = _grader(
        FakeLedger(children=[CHILD1, CHILD2], root=root),
        json_call=_exhausted_json_call,
    )

    verdict = await grader.grade(_clean_report(), root.id)

    assert verdict.ok is True
    assert verdict.detail == "judge_budget_exhausted"
    assert verdict.diagnostics["uncited_ratio"] == 0.0
