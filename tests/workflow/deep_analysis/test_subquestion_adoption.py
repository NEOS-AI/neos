"""워커가 제안한 하위 질문의 트리 채택 (D65).

이 자리는 D11 -> D13 으로 두 번 연기되어 로깅만 하고 있었다. 표본 #16 에서
**고유 제안 161건이 버려지고 실제 조사된 질문은 82건**이었고, 버려진 것들이
판정자가 빠졌다고 지적한 바로 그 축이었다.
"""

from dataclasses import dataclass

import pytest

from neos.workflow.deep_analysis.models import ProposedSubquestion
from neos.workflow.deep_analysis.orchestrator import (
    _ADOPT_CAP,
    Orchestrator,
    _normalize_question,
)
from neos.workflow.deep_analysis.worker import _parse_subquestions

pytestmark = pytest.mark.no_db


@dataclass
class _Q:
    id: str
    text: str
    depth: int = 0


class _Ledger:
    def __init__(self, questions):
        self._questions = list(questions)
        self.opened: list[tuple[str, str, float, int, int]] = []
        self.events: list[tuple[str, str, dict]] = []

    async def get_question(self, qid):
        return next((q for q in self._questions if q.id == qid), None)

    async def questions(self):
        return list(self._questions)

    async def remaining_budget(self, qid):
        return 9_000

    async def open_question(self, text, parent_id, value_est, cap_tokens, depth):
        qid = f"new{len(self.opened):04d}"
        self.opened.append((qid, text, value_est, cap_tokens, depth))
        self._questions.append(_Q(qid, text, depth))
        return qid

    async def log(self, kind, qid, payload):
        self.events.append((kind, qid, payload))


def _orchestrator(ledger, *, max_depth=4):
    orch = Orchestrator.__new__(Orchestrator)
    orch.ledger = ledger
    orch.max_depth = max_depth

    async def _emit(*_args, **_kwargs):
        return None

    orch._emit = _emit
    return orch


# ---------------------------------------------------------------------------
# 파싱 -- 값이 없으면 채택되지 않는다
# ---------------------------------------------------------------------------


def test_a_bare_string_proposal_scores_zero_and_will_not_be_adopted():
    """옛 형태(문자열)를 내는 응답은 이 기능이 없던 시절과 똑같이 동작해야
    한다. 값을 모르는 제안에 관대하면 그것은 "임계값 없이 전부 채택" 이다."""
    parsed = _parse_subquestions(["그냥 문자열 질문"])

    assert len(parsed) == 1
    assert parsed[0].value_est == 0.0


def test_proposals_carry_their_value_and_are_clamped():
    parsed = _parse_subquestions(
        [
            {"text": "핵심 축", "value_est": 0.9},
            {"text": "범위 밖", "value_est": 4.2},
            {"text": "음수", "value_est": -1},
            {"text": "숫자가 아님", "value_est": "높음"},
            {"text": "   "},
            "문자열",
            12345,
        ]
    )

    assert [(p.text, p.value_est) for p in parsed] == [
        ("핵심 축", 0.9),
        ("범위 밖", 1.0),
        ("음수", 0.0),
        ("숫자가 아님", 0.0),
        ("문자열", 0.0),
    ]


# ---------------------------------------------------------------------------
# 채택 정책
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_only_proposals_above_the_threshold_are_adopted(monkeypatch):
    """`subq_adopt_threshold` 는 config 에 정의만 되어 있고 코드 어디에서도
    쓰이지 않던 죽은 노브였다. 이제 이것이 쓰인다."""
    from neos.config.settings import settings

    threshold = settings.config.deep_analysis.subq_adopt_threshold
    ledger = _Ledger([_Q("root0001", "루트 질문")])
    orch = _orchestrator(ledger)

    await orch._adopt_subquestions(
        "root0001",
        [
            ProposedSubquestion("채택될 것", threshold + 0.1),
            ProposedSubquestion("경계값", threshold),
            ProposedSubquestion("버려질 것", threshold - 0.1),
        ],
    )

    adopted = [text for _qid, text, *_rest in ledger.opened]
    assert adopted == ["채택될 것", "경계값"]


@pytest.mark.asyncio
async def test_a_proposal_that_repeats_an_existing_question_is_dropped():
    """같은 질문을 글자만 다르게 다시 조사하지 않는다. 완전한 의미 중복
    제거는 아니지만(원 설계 §6.3.2 는 LLM 심사자를 쓴다) 재탕은 막는다."""
    ledger = _Ledger(
        [_Q("root0001", "루트 질문"), _Q("q0000002", "EU AI Act 의 적용일은?")]
    )
    orch = _orchestrator(ledger)

    await orch._adopt_subquestions(
        "root0001",
        [
            ProposedSubquestion("  eu ai act 의   적용일은  ", 0.9),
            ProposedSubquestion("전혀 다른 질문", 0.9),
        ],
    )

    assert [text for _q, text, *_r in ledger.opened] == ["전혀 다른 질문"]


@pytest.mark.asyncio
async def test_adoption_stops_at_the_cap_and_takes_the_most_valuable():
    ledger = _Ledger([_Q("root0001", "루트 질문")])
    orch = _orchestrator(ledger)

    await orch._adopt_subquestions(
        "root0001",
        [
            ProposedSubquestion(f"제안 {i}", 0.5 + i / 100)
            for i in range(_ADOPT_CAP + 5)
        ],
    )

    assert len(ledger.opened) == _ADOPT_CAP
    # 값이 높은 것부터.
    assert [text for _q, text, *_r in ledger.opened] == [
        f"제안 {i}" for i in range(_ADOPT_CAP + 4, _ADOPT_CAP, -1)
    ]


@pytest.mark.asyncio
async def test_adoption_respects_max_depth():
    ledger = _Ledger([_Q("q0000001", "깊이 2 질문", depth=2)])
    orch = _orchestrator(ledger, max_depth=2)

    await orch._adopt_subquestions(
        "q0000001", [ProposedSubquestion("더 깊이", 0.9)]
    )

    assert ledger.opened == []


@pytest.mark.asyncio
async def test_the_parent_keeps_a_share_of_its_own_budget():
    """`_do_split` 은 부모가 끝나므로 잔여를 자식 수로 나눈다. 채택된 부모는
    계속 조사하므로 자기 몫을 남겨야 한다 -- `n + 1` 로 나눈다."""
    ledger = _Ledger([_Q("root0001", "루트 질문")])
    orch = _orchestrator(ledger)

    await orch._adopt_subquestions(
        "root0001",
        [ProposedSubquestion("A", 0.9), ProposedSubquestion("B", 0.9)],
    )

    caps = {cap for _q, _t, _v, cap, _d in ledger.opened}
    assert caps == {9_000 // 3}


@pytest.mark.asyncio
async def test_adoption_does_not_end_the_parents_own_investigation():
    """`record_split` 은 부모를 `split` 으로 전이시켜 **조사를 끝낸다.**
    채택은 부모가 살아 있는 채로 가지를 더하는 일이므로 그것을 부르면 안
    된다. `ledger.children()` 은 `parent_id` 로 조회하므로 트리는 성립한다."""
    ledger = _Ledger([_Q("root0001", "루트 질문")])
    orch = _orchestrator(ledger)

    await orch._adopt_subquestions(
        "root0001", [ProposedSubquestion("자식", 0.9)]
    )

    assert "split" not in [kind for kind, _q, _p in ledger.events]
    assert [kind for kind, _q, _p in ledger.events] == ["subq_adopted"]
    assert ledger.opened[0][1] == "자식"


@pytest.mark.asyncio
async def test_nothing_is_adopted_when_nothing_clears_the_bar():
    ledger = _Ledger([_Q("root0001", "루트 질문")])
    orch = _orchestrator(ledger)

    await orch._adopt_subquestions(
        "root0001", [ProposedSubquestion("낮은 값", 0.0)]
    )

    assert ledger.opened == []
    assert ledger.events == []


def test_normalization_folds_whitespace_case_and_trailing_punctuation():
    assert _normalize_question("  EU  AI Act 의 적용일은?  ") == _normalize_question(
        "eu ai act 의 적용일은"
    )
