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
async def test_uncited_hints_anchor_length_and_disown_the_quoted_sentences():
    """재시도 힌트는 **고칠 지시**여야지 넣을 재료로 읽혀선 안 된다.

    `assemble` 은 직전 초안을 받지 않는다 -- 힌트에 실린 문장만 프롬프트에
    들어가므로, 출처를 밝히지 않으면 그 문장들이 새 재료처럼 보인다. 표본
    #10 의 재시도 3건 모두 주장 수가 늘고(19->60, 31->46, 16->42) 인용
    비율이 나빠졌다(.400/.435/.714).
    """
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

    assert verdict.code == "E_REPORT_UNCITED"
    header = verdict.revision_hints[0]
    # 길이 앵커가 직전 초안의 실측 주장 수를 그대로 인용한다.
    assertions = verdict.diagnostics["uncited_assertions"]
    assert f"{assertions}개보다 길게 쓰지 마라" in header
    # 인용된 문장이 직전 초안 것임을 밝히고, 다시 쓰지 말라고 말한다.
    assert "직전 초안" in header
    assert "그대로 다시 쓰지 말고" in header


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

    # 인용된 사실 주장을 하나 둔다 -- 그래야 E_REPORT_EMPTY(D-2)를 지나
    # 실제로 "한계 절 없음"에서 막히는지를 본다.
    verdict = await grader.grade(
        "2024년 8월 1일에 발효되었다[1]. 한계 절이 없는 본문.", "root0001"
    )

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
async def test_a_judge_rejection_says_which_of_its_two_checks_failed():
    """표본 #6 에서 판정자가 지배적 반려 사유가 됐다 (18회 중 8회, 직전 3회).
    그런데 8건 중 어느 것도 서로 구분되지 않았다 -- 이벤트에 `code` 밖에
    없었기 때문이다.

    "질문에 답하지 않았다" 와 "근거가 약하다" 는 고치는 방법이 다른 별개의
    실패다. 불리언은 run 을 가로질러 집계되지만 rationale 문자열은 그럴 수
    없으므로, 산문보다 이 둘이 먼저다.
    """
    judge = FakeJudge(
        answers_question=False, strength_ok=True, rationale="질문을 비껴갔다"
    )
    grader = ReportGrader(FakeLedger(), judge_model="claude-j", llm_client=judge)

    verdict = await grader.grade_agentic(_clean_report(), "루트 질문")

    assert verdict.diagnostics["judge"] == "ran"
    assert verdict.diagnostics["judge_answers_question"] is False
    assert verdict.diagnostics["judge_strength_ok"] is True
    assert verdict.diagnostics["judge_rationale"] == "질문을 비껴갔다"


@pytest.mark.asyncio
async def test_an_approving_judge_is_not_silent():
    """승인이 아무것도 남기지 않으면, 원장에서 **판정자가 돌아 승인한 것**과
    **판정자가 아예 못 돈 것**이 구별되지 않는다.

    표본 #5·#6 의 게이트 통과 3건이 전부 `judge=budget_exhausted` 였다 --
    바로 이 구분이 살아남아야 S2 를 제대로 읽을 수 있다.
    """
    judge = FakeJudge(answers_question=True, strength_ok=True)
    grader = ReportGrader(FakeLedger(), judge_model="claude-j", llm_client=judge)

    approved = await grader.grade_agentic(_clean_report(), "루트 질문")

    assert approved.ok is True
    assert approved.diagnostics["judge"] == "ran"

    degraded = GarbageJudge(answers_question=True, strength_ok=True)
    fallback = await ReportGrader(
        FakeLedger(), judge_model="claude-j", llm_client=degraded
    ).grade_agentic(_clean_report(), "루트 질문")

    assert fallback.ok is True
    assert fallback.diagnostics["judge"] != approved.diagnostics["judge"]


@pytest.mark.asyncio
async def test_a_long_judge_rationale_is_bounded_in_the_event():
    """모델 산문이 이벤트 페이로드로 들어가므로 상한이 있어야 한다.
    (판정자가 렌더된 리포트에 대해 스스로 내린 평가이지 가져온 원문이
    아니므로 no-raw 불변식과는 무관하다.)"""
    judge = FakeJudge(
        answers_question=True, strength_ok=False, rationale="가" * 2000
    )
    grader = ReportGrader(FakeLedger(), judge_model="claude-j", llm_client=judge)

    verdict = await grader.grade_agentic(_clean_report(), "루트 질문")

    assert len(verdict.diagnostics["judge_rationale"]) == 400
    # 프로세스 안에서 쓰는 `detail`/힌트는 자르지 않는다 -- 재시도는 전부 본다.
    assert len(verdict.detail) == 2000


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


def test_latin_proper_nouns_count_even_when_a_korean_particle_follows():
    """G3-m1 (2026-08-29): 한글 조사가 붙어도 고유명사를 센다.

    이 테스트는 **뒤집힌 것**이다. 원래 이름은
    `test_latin_proper_nouns_do_not_count_when_a_korean_particle_follows` 였고
    결함을 의도적으로 고정하고 있었다 -- 그 독스트링이 스스로 "not because the
    behaviour is desirable" 이라 적었다.

    **결함:** 파이썬의 `\\b` 는 라틴과 한글 사이에 경계를 만들지 않는다(둘 다
    word character 다). 한국어는 조사를 어간에 붙여 쓰므로 "Act가"·"OpenAI가"
    에서 고유명사 절반의 휴리스틱이 사실상 죽고, 게이트의 분모가 거의 "숫자를
    담은 문장" 뿐이 된다.

    **고친 방법:** 경계를 `\\b` 가 아니라 **라틴 문자에 대한 lookaround** 로
    표현한다. 한글은 라틴이 아니므로 경계가 된다.

    🔴 **이것은 표본 비교 경계다.** 분모가 커지므로 `uncited_ratio` 를 표본
    #1~#21 과 직접 비교할 수 없다. 다음 사전 등록이 그 사실을 적어야 한다.
    """
    from neos.workflow.deep_analysis.graders.report import _PROPER_NOUN

    assert _PROPER_NOUN.findall("EU AI Act가 적용된다.") == ["Act"]
    assert _PROPER_NOUN.findall("OpenAI가 발표했다.") == ["OpenAI"]
    # 영문 문장의 동작은 바뀌지 않는다 -- 뒤집은 것은 한글 경계뿐이다.
    assert _PROPER_NOUN.findall("The Act applies.") == ["The", "Act"]
    # 단어 중간의 대문자는 여전히 잡지 않는다(camelCase 오탐 방지).
    assert _PROPER_NOUN.findall("someWordHere") == []


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
async def test_a_report_with_no_assertions_is_rejected_on_its_own_code():
    """D-2 결정 (2026-08-08): assertion 0건은 **제3 판정**으로 반려한다.

    이 자리에는 반대 동작을 고정한 특성화 테스트가 있었다 -- assertion 이 없으면
    `_uncited_stats` 가 0.0 을 내므로 아무것도 주장하지 않는 리포트가 만점을
    받았다. 그 테스트는 "바꾸려면 의도적으로 깨라"고 적혀 있었고, 이것이 그
    결정이다.

    근거는 2026-08-07 표본이 아니라 **2026-08-08 표본 #2**다. W3-a·W3-b 가
    산출물을 바꾸자 퇴화 케이스가 드러났다: 18회 채점 중 5회가 `assert=0` 으로
    만점을 받았고, 그중 `a82648e3` 의 리포트는 **완전히 빈 문자열**이었다.
    그것을 막은 것은 실질 검사가 아니라 `E_REPORT_NO_LIMITS`, 즉 "한계와
    미확인 사항" 제목이 없다는 **서식** 검사였다. 모델이 그 제목만 찍었다면
    내용 0인 리포트가 게이트를 통과했을 것이다.

    전용 코드를 쓰는 이유는 `_uncited_stats` 독스트링이 이미 적어둔 것과 같다 --
    "1.00 over one assertion is a short report, 1.00 over forty is a badly
    cited one, and the two call for opposite fixes". 빈 리포트와 인용을 안 단
    리포트는 원장에서 구별돼야 한다.
    """
    empty = "## 본문\n특별한 내용이 없다.\n\n## 한계와 미확인 사항\n없음.\n"

    verdict = await _grader(FakeLedger()).grade_deterministic(empty, "root0001")

    assert verdict.ok is False
    assert verdict.code == "E_REPORT_EMPTY"
    assert verdict.diagnostics["uncited_assertions"] == 0
    # 통계 자체는 그대로다 -- 바뀐 것은 판정이지 측정이 아니다.
    assert verdict.diagnostics["uncited_ratio"] == 0.0


@pytest.mark.asyncio
async def test_a_substantive_report_is_still_judged_on_its_citations():
    """전용 코드가 기존 판정을 삼키지 않는다 -- assertion 이 있으면 비율이 정한다."""
    cited = (
        "## 본문\n2024년 8월 1일에 발효되었다[1].\n\n"
        "## 한계와 미확인 사항\n없음.\n"
    )

    verdict = await _grader(FakeLedger()).grade_deterministic(cited, "root0001")

    assert verdict.code != "E_REPORT_EMPTY"
    assert verdict.diagnostics["uncited_assertions"] > 0


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


@pytest.mark.asyncio
async def test_a_starved_judge_records_by_how_much_it_missed():
    """표식은 판정자가 못 돌았다고만 말한다 -- 얼마나 모자랐는지는 말하지 않는다.

    `token_budget_exhausted` 이벤트는 **조사** 정지 경로에서만 기록되므로
    최종화 단계의 고갈은 숫자를 하나도 남기지 않았다(표본 #6: 그 이벤트 0건,
    `judge=budget_exhausted` 통과 2건). G10 이 이미 예외에 숫자를 실어뒀는데
    원장 한 층 앞에서 버려지고 있었다.

    2026-08-09 실측이 이 숫자가 왜 필요한지를 말한다: 판정자 프롬프트가
    5,900~17,084 인데 남은 예산은 3,555~9,443 이었다.
    """

    async def _starved(*args, **kwargs):
        raise TokenBudgetExhausted(
            "cap",
            cause="input_bound",
            stage="report_grading",
            input_bound=8529,
            ceiling=3555,
            requested=800,
            granted=0,
        )

    root = Question("root0001", "루트 질문")
    grader = _grader(
        FakeLedger(children=[CHILD1, CHILD2], root=root),
        json_call=_starved,
    )

    verdict = await grader.grade(_clean_report(), root.id)

    assert verdict.diagnostics["judge"] == "budget_exhausted"
    assert verdict.diagnostics["judge_budget_cause"] == "input_bound"
    assert verdict.diagnostics["judge_budget_input_bound"] == 8529
    assert verdict.diagnostics["judge_budget_ceiling"] == 3555
    assert verdict.diagnostics["judge_budget_granted"] == 0
    # 결정론 측정도 함께 살아남아야 한다 -- 어떤 리포트가 굶었는지 알아야 한다.
    assert "uncited_ratio" in verdict.diagnostics


@pytest.mark.asyncio
async def test_a_markdown_heading_is_not_a_factual_assertion():
    """W3-f: `### 1.` 이 "인용 없는 사실 주장"으로 세어지고 있었다.

    `_sentences` 가 줄바꿈으로 나누므로 제목이 독립 문장이 되고, 번호가 붙어
    있으면 `_DIGIT` 에 걸려 assertion 으로 분류됐다. 2026-08-08 표본 #4 실측:
    run 당 1~7개의 uncited 가 제목 조각이었고, 제외하면 `93795eaf` 는
    0.348 → 0.167, `2ff4761c` 는 0.333 → 0.143 으로 임계값(0.20) 아래로 내려간다.
    """
    report = (
        "## 본문\n"
        "### 1. 배경\n"
        "### 2. 근거\n"
        "2024년 8월 1일에 발효되었다[1].\n\n"
        "## 한계와 미확인 사항\n없음.\n"
    )

    verdict = await _grader(FakeLedger()).grade_deterministic(report, "root0001")

    # 제목 둘은 분모에 들지 않는다 -- 남는 assertion 은 인용된 문장 하나뿐.
    assert verdict.diagnostics["uncited_assertions"] == 1
    assert verdict.diagnostics["uncited_count"] == 0


@pytest.mark.asyncio
async def test_a_numbered_heading_is_excluded_by_its_whole_line():
    """W3-g: 위 W3-f 테스트는 통과했지만 제외는 절반만 작동하고 있었다.

    `_sentences` 가 `_HEADING_LINE` 보다 **먼저** 돌고, 서수의 마침표에서
    문장을 자른다. `### 2. 기준일(2026년 7월 19일) 시점의 상태` 는
    `['### 2.', '기준일(2026년 7월 19일) 시점의 상태']` 가 되고, 뒷조각에는
    `#` 이 없으므로 헤딩 제외를 빠져나간 뒤 `_DIGIT` 에 걸려 인용 없는 주장이
    된다.

    W3-f 가 통하는 것처럼 보인 이유는 그 사례가 `### 1. 배경` 이었기 때문이다 --
    `배경` 은 숫자도 라틴 대문자도 없어 우연히 분모에 들지 않았다. 제목에 연도나
    고유명사가 들어가는 순간 새기 시작한다.

    2026-08-09 표본 #5 카세트 실측: 제목 조각을 빼면 리포트 11건 중 1건이
    반려 → 통과로 바뀌고(0.208 → 0.116), 그 run 이 `94b0483c` 다.
    """
    report = (
        "## 본문\n"
        "### 2. 기준일(2026년 7월 19일) 시점의 상태\n"
        "### 4. GPAI 의무의 적용시점\n"
        "2024년 8월 1일에 발효되었다[1].\n\n"
        "## 한계와 미확인 사항\n없음.\n"
    )

    verdict = await _grader(FakeLedger()).grade_deterministic(report, "root0001")

    # 제목 둘 다 분모 밖 -- 인용된 문장 하나만 남는다.
    assert verdict.diagnostics["uncited_assertions"] == 1
    assert verdict.diagnostics["uncited_count"] == 0


@pytest.mark.asyncio
async def test_the_limits_section_is_not_scored_for_citations():
    """W3-f: 한계 절은 **검증하지 못한 것들의 목록**이다.

    구조상 뒷받침할 verified claim 이 없는 문장들이므로 각주를 요구하는 것은
    불가능한 요구다. `_report_body` 가 `## 출처` 를 빼는 것과 같은 이유이며,
    W3-e 가 그 절을 항상 존재하게 만들면서 문제가 드러났다 -- 표본 #4 의
    `cb1593f2` 는 그 절 때문에 0.353 → 0.455 로 올라갔다.
    """
    report = (
        "## 본문\n"
        "2024년 8월 1일에 발효되었다[1].\n\n"
        "## 한계와 미확인 사항\n"
        "- 미확인: 2025년 이후 EU 집행 통계\n"
        "- 미조사: GPAI 벌칙 조항 3건\n"
    )

    verdict = await _grader(FakeLedger()).grade_deterministic(report, "root0001")

    assert verdict.diagnostics["uncited_assertions"] == 1
    assert verdict.diagnostics["uncited_count"] == 0


@pytest.mark.asyncio
async def test_the_question_coverage_section_is_not_scored_for_citations():
    """W3-l: 하네스가 붙이는 '조사한 하위 질문' 절은 **질문 목록**이다.

    한계 절과 같은 범주다 -- 뒷받침할 verified claim 이 있을 수 없는 줄들이라
    각주를 요구하는 것은 불가능한 요구다. 질문에는 연도와 기관명이 들어가므로
    제외하지 않으면 `_DIGIT`/`_PROPER_NOUN` 에 그대로 걸린다.
    """
    report = (
        "## 본문\n"
        "2024년 8월 1일에 발효되었다[1].\n\n"
        "## 조사한 하위 질문\n"
        "- 2023년 IARC는 아스파탐을 어떤 등급으로 분류했는가? Monographs 134 원문에서 확인하라.\n"
        "- JECFA의 2023년 ADI 유지 여부는? WHO/FAO 요약 원문에서 확인하라.\n\n"
        "## 한계와 미확인 사항\n- 없음\n"
    )

    verdict = await _grader(FakeLedger()).grade_deterministic(report, "root0001")

    assert verdict.diagnostics["uncited_assertions"] == 1
    assert verdict.diagnostics["uncited_count"] == 0
