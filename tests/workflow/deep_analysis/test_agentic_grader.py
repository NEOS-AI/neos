import pytest

from neos.workflow.deep_analysis.graders.agentic import AgenticGrader
from neos.workflow.deep_analysis.models import ProposedClaim, ProposedEvidence

pytestmark = pytest.mark.no_db


def _claim(conf=0.6):
    return ProposedClaim(
        text="MoE lowers cost",
        confidence=conf,
        evidence=[ProposedEvidence("http://x", "cost drops 40%", "hh")],
    )


class FakeJudge:
    def __init__(self, label):
        self._label = label
        self.messages = self
        self.calls = 0

    async def create(self, **kw):
        self.calls += 1
        payload = '{"label": "%s", "rationale": "r"}' % self._label

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


def test_tiering_high_value_always_grades():
    g = AgenticGrader(judge_model="j", threshold=0.35, sample_rate=0.0)
    assert g.should_grade(value_est=0.8, confidence=0.6) is True  # 0.48 >= 0.35


def test_tiering_low_value_samples():
    g = AgenticGrader(
        judge_model="j", threshold=0.35, sample_rate=0.0, sampler=lambda: 0.99
    )
    assert (
        g.should_grade(value_est=0.1, confidence=0.1) is False
    )  # 0.01<0.35, sample 0.99>=0.0
    g2 = AgenticGrader(
        judge_model="j", threshold=0.35, sample_rate=1.0, sampler=lambda: 0.0
    )
    assert g2.should_grade(value_est=0.1, confidence=0.1) is True


@pytest.mark.parametrize(
    "label,ok,code",
    [
        ("SUPPORTS", True, ""),
        ("PARTIAL", False, "E_OVERCLAIM"),
        ("UNRELATED", False, "E_UNSUPPORTED"),
        ("CONTRADICTS", False, "E_CONTRADICTED"),
    ],
)
async def test_label_to_verdict(label, ok, code):
    g = AgenticGrader(
        judge_model="claude-j",
        threshold=0.0,
        sample_rate=1.0,
        llm_client=FakeJudge(label),
    )
    v = await g.grade(_claim(), value_est=1.0)
    assert v.ok is ok and v.code == code and v.label == label


async def test_unsampled_passes_without_calling_judge():
    judge = FakeJudge("SUPPORTS")
    g = AgenticGrader(
        judge_model="j",
        threshold=0.35,
        sample_rate=0.0,
        llm_client=judge,
        sampler=lambda: 0.99,
    )
    v = await g.grade(_claim(conf=0.01), value_est=0.01)  # 0.0001<0.35, not sampled
    assert v.ok is True and v.label is None and judge.calls == 0
    assert v.diagnostics == {"agentic": "skipped", "agentic_label": None}


async def test_attempted_judgment_reports_pass_or_rejection_state():
    passed = await AgenticGrader(
        judge_model="claude-j",
        threshold=0.0,
        sample_rate=1.0,
        llm_client=FakeJudge("SUPPORTS"),
    ).grade(_claim(), value_est=1.0)
    rejected = await AgenticGrader(
        judge_model="claude-j",
        threshold=0.0,
        sample_rate=1.0,
        llm_client=FakeJudge("PARTIAL"),
    ).grade(_claim(), value_est=1.0)

    assert passed.diagnostics == {
        "agentic": "attempted_passed",
        "agentic_label": "SUPPORTS",
    }
    assert rejected.diagnostics == {
        "agentic": "attempted_rejected",
        "agentic_label": "PARTIAL",
    }


class Garbage(FakeJudge):
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


async def test_unparseable_judge_passes_low_value_sampled_claim():
    # D14: 저가치 **샘플링** 대상은 judge 판정 불가 시 미심사 통과(label=None).
    # threshold=1.0로 두어 value_est*conf=0.6 < 1.0 → 필수 아님(샘플 강제).
    g = AgenticGrader(
        judge_model="claude-j",
        threshold=1.0,
        sample_rate=1.0,
        llm_client=Garbage("x"),
        sampler=lambda: 0.0,
    )
    v = await g.grade(_claim(), value_est=1.0)
    assert v.ok is True and v.label is None and v.detail == "judge_unparseable"


async def test_unparseable_judge_rejects_mandatory_claim():
    # #6/§A4 강화: 필수 심사 대상은 judge 판정 불가 시 자동 verified 금지.
    # value_est*conf=0.6 >= threshold 0.35 → mandatory → E_UNSUPPORTED 반려.
    g = AgenticGrader(
        judge_model="claude-j", threshold=0.35, sample_rate=1.0, llm_client=Garbage("x")
    )
    v = await g.grade(_claim(), value_est=1.0)
    assert v.ok is False and v.code == "E_UNSUPPORTED" and v.label is None
    assert "judge_unparseable_mandatory" in v.detail


async def test_unknown_label_rejects_mandatory_claim():
    # 알 수 없는 라벨도 필수 심사 대상에서는 자동 통과 금지.
    g = AgenticGrader(
        judge_model="claude-j",
        threshold=0.35,
        sample_rate=1.0,
        llm_client=FakeJudge("WOBBLE"),
    )
    v = await g.grade(_claim(), value_est=1.0)
    assert v.ok is False and v.code == "E_UNSUPPORTED" and v.label is None
