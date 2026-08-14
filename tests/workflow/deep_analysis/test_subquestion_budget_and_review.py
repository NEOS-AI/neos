"""채택된 자식의 예산 분배와 §6.3.2 독립 심사자 (D68).

표본 #17 이 둘 다의 근거다. dev 5건에서 질문이 **74 -> 155** 로 늘었는데
`claim_verified` 는 **129 -> 116** 으로 줄었고, 채택 88건 중 `resolved` 는 2건,
새로 생긴 `abandoned` 가 15건이다. 넓이는 늘고 근거는 줄었다.

두 손잡이를 **따로** 켤 수 있게 두는 것이 요점이다 -- 표본 하나는 변경 하나만
잰다(§10.2). 그래서 기본값은 둘 다 표본 #17 이 측정한 동작 그대로다.
"""

from dataclasses import dataclass

import pytest

from neos.workflow.deep_analysis.models import ProposedSubquestion
from neos.workflow.deep_analysis.orchestrator import (
    Orchestrator,
    _apply_review,
    adopted_child_caps,
)

pytestmark = pytest.mark.no_db


# ---------------------------------------------------------------------------
# 예산 분배
# ---------------------------------------------------------------------------


def test_uniform_leaves_the_parent_a_share():
    """부모는 채택 후에도 계속 조사하므로 `n + 1` 로 나눈다.

    `_do_split` 이 `n` 으로 나누는 것과 다른 이유가 이것이다 -- 거기서는 부모가
    `split` 로 끝난다.
    """
    assert adopted_child_caps(9_000, [0.9, 0.9], "uniform") == [3_000, 3_000]


def test_value_weighted_gives_the_more_valuable_branch_more():
    caps = adopted_child_caps(9_000, [0.75, 0.25], "value_weighted")

    # 자식 몫 총합(6,000)은 그대로 두고 비율만 바꾼다 -- 부모 몫은 건드리지
    # 않는다.
    assert sum(caps) == 6_000
    assert caps == [4_500, 1_500]


def test_value_weighted_falls_back_when_no_proposal_carries_value():
    """옛 형태(문자열) 제안은 `value_est=0.0` 이다. 전부 0 이면 '값에 비례' 가
    아무 의미도 없으므로 균등으로 떨어진다."""
    assert adopted_child_caps(9_000, [0.0, 0.0], "value_weighted") == [3_000, 3_000]


def test_every_child_gets_at_least_one_token():
    """0 토큰짜리 자식은 열리자마자 바닥에 걸린다 -- 여는 의미가 없다."""
    caps = adopted_child_caps(4, [0.999, 0.001], "value_weighted")

    assert all(cap >= 1 for cap in caps)


def test_no_children_no_caps():
    assert adopted_child_caps(9_000, [], "value_weighted") == []


def test_an_unknown_policy_behaves_as_uniform():
    """설정 오타가 예산을 0 으로 만들거나 터뜨리면 안 된다."""
    assert adopted_child_caps(9_000, [0.9, 0.1], "그런정책없음") == [3_000, 3_000]


# ---------------------------------------------------------------------------
# 심사자 응답 해석
# ---------------------------------------------------------------------------


def test_review_rescores_by_index_and_never_rewrites_text():
    """심사자는 인덱스로 말한다.

    텍스트를 되받아 적게 하면 그것이 곧 재작성이고, 워커가 실제 증거에서 뽑은
    문장이 심사 과정에서 조용히 바뀐다.
    """
    proposals = [ProposedSubquestion("원문 그대로", 0.4)]

    reviewed = _apply_review(
        proposals, [{"index": 0, "value_est": 0.9, "text": "심사자가 고쳐 쓴 문장"}]
    )

    assert reviewed[0].text == "원문 그대로"
    assert reviewed[0].value_est == 0.9


def test_indexes_the_reviewer_omits_are_dropped():
    """의미 중복 병합의 결과다 -- 남길 것만 배열에 넣게 되어 있다."""
    proposals = [
        ProposedSubquestion("A", 0.5),
        ProposedSubquestion("A 를 다르게 쓴 것", 0.5),
    ]

    reviewed = _apply_review(proposals, [{"index": 0, "value_est": 0.8}])

    assert [p.text for p in reviewed] == ["A"]


def test_garbage_from_the_reviewer_cannot_delete_proposals():
    """심사자의 실수로 제안이 사라지면 D65 가 고친 손실이 되돌아온다."""
    proposals = [ProposedSubquestion("살아남아야 한다", 0.5)]

    for junk in ([], [{"index": 99, "value_est": 0.9}], ["문자열"], [{"index": "x"}]):
        assert _apply_review(proposals, junk) == proposals


def test_review_clamps_and_ignores_repeated_indexes():
    proposals = [ProposedSubquestion("A", 0.5), ProposedSubquestion("B", 0.5)]

    reviewed = _apply_review(
        proposals,
        [
            {"index": 0, "value_est": 4.2},
            {"index": 0, "value_est": 0.1},
            {"index": 1, "value_est": -1},
        ],
    )

    assert [(p.text, p.value_est) for p in reviewed] == [("A", 1.0), ("B", 0.0)]


# ---------------------------------------------------------------------------
# 심사자 배선
# ---------------------------------------------------------------------------


@dataclass
class _Q:
    id: str
    text: str
    depth: int = 0


class _Ledger:
    def __init__(self):
        self.events: list[tuple[str, str, dict]] = []

    async def log(self, kind, qid, payload):
        self.events.append((kind, qid, payload))


def _orchestrator(ledger):
    orch = Orchestrator.__new__(Orchestrator)
    orch.ledger = ledger
    orch.llm_client = None
    orch.cassette = None
    return orch


@pytest.mark.asyncio
async def test_the_reviewer_is_off_by_default(monkeypatch):
    """기본값은 표본 #17 이 측정한 동작이다. 표본 하나는 변경 하나만 잰다."""
    from neos.config.settings import settings

    assert settings.config.deep_analysis.subq_reviewer_enabled is False

    ledger = _Ledger()
    proposals = [ProposedSubquestion("그대로", 0.5)]

    async def explode(*_a, **_k):
        raise AssertionError("꺼져 있는데 LLM 을 불렀다")

    monkeypatch.setattr(
        "neos.workflow.deep_analysis.orchestrator.call_json", explode
    )

    result = await _orchestrator(ledger)._review_subquestions(
        _Q("q0000001", "부모 질문"), proposals
    )

    assert result == proposals
    assert ledger.events == []


@pytest.mark.asyncio
async def test_a_failing_reviewer_keeps_the_workers_proposals(monkeypatch):
    """심사자는 조사를 돕는 장치이지 관문이 아니다.

    여기서 터졌다고 제안이 사라지면, 워커가 실제로 수집한 증거에서 나온 질문이
    통째로 없어진다 -- D65 가 고친 바로 그 손실이다. 대신 흔적을 남긴다.
    """
    from neos.config.settings import settings

    monkeypatch.setattr(
        settings.config.deep_analysis, "subq_reviewer_enabled", True
    )

    async def boom(*_a, **_k):
        raise TimeoutError("심사자 타임아웃")

    monkeypatch.setattr("neos.workflow.deep_analysis.orchestrator.call_json", boom)

    ledger = _Ledger()
    proposals = [ProposedSubquestion("살아남아야 한다", 0.5)]

    result = await _orchestrator(ledger)._review_subquestions(
        _Q("q0000001", "부모 질문"), proposals
    )

    assert result == proposals
    assert [kind for kind, _q, _p in ledger.events] == ["subq_review_failed"]


@pytest.mark.asyncio
async def test_the_reviewer_rescores_and_records_what_it_changed(monkeypatch):
    from neos.config.settings import settings

    monkeypatch.setattr(
        settings.config.deep_analysis, "subq_reviewer_enabled", True
    )

    async def review(*_a, **_k):
        return {"reviewed": [{"index": 1, "value_est": 0.9}]}, None

    monkeypatch.setattr("neos.workflow.deep_analysis.orchestrator.call_json", review)

    ledger = _Ledger()
    result = await _orchestrator(ledger)._review_subquestions(
        _Q("q0000001", "부모 질문"),
        [ProposedSubquestion("버려질 것", 0.8), ProposedSubquestion("핵심 축", 0.4)],
    )

    assert [(p.text, p.value_est) for p in result] == [("핵심 축", 0.9)]

    kind, qid, payload = ledger.events[0]
    assert (kind, qid) == ("subq_reviewed", "q0000001")
    assert payload["before"] == 2
    assert payload["after"] == 1
    # 워커 평균 0.6 -> 심사자 0.9. 이 두 수가 같은 자리에 남아야 "심사자가
    # 값을 올리기만 하는가" 를 나중에 실측으로 물을 수 있다.
    assert payload["value_before"] == 0.6
    assert payload["value_after"] == 0.9
