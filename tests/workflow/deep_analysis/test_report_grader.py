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
