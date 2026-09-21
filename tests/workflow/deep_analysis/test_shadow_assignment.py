"""섀도는 오케스트레이터와 **같은 함수로** 지시를 짓는다 (로드맵 J3).

`build_assignment` 를 `Orchestrator._partition` 에서 뽑아낸 이유가 이것이다.
섀도가 brief 를 따로 지으면 비교한 것이 두 워커가 아니라 **두 프롬프트**가
된다 -- 그리고 그 차이는 보고서 어디에도 나타나지 않는다.

## 이 brief 는 역사적 재현이 아니다

`verified_summaries` 와 `unverified_and_deadends` 는 **지금** 원장이 말하는
것을 읽는다. 끝난 run 을 섀도로 돌리면 그때 워커가 본 것보다 더 많은 확정
발견이 들어간다 -- 그 패스의 brief 를 되짚는 방법은 없다(원장에 저장되지
않는다).

그래서 J3 가 답하는 질문은 "그때 그 워커를 다시 돌리면?" 이 아니라 **"이
run 이 쌓은 지식을 주면 조사 워커는 무엇을 제안하는가?"** 다. 둘은 다른
질문이고, 보고서가 어느 쪽인지 말하지 않으면 읽는 쪽이 앞엣것으로 읽는다.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from neos.workflow.deep_analysis.models import Effort

pytestmark = pytest.mark.no_db


@dataclass
class _Q:
    id: str
    text: str


class _Ledger:
    """최소 test double -- `verified_summaries` 도 `unverified_and_deadends` 도
    구현하지 않는다. `build_assignment` 가 방어적으로 읽는 것이 그 때문이다."""

    async def pending_feedback(self, question_id):
        return []


@pytest.mark.asyncio
async def test_the_shadow_brief_is_the_orchestrators_brief() -> None:
    """같은 원장·같은 질문·같은 노력이면 **같은 바이트**여야 한다.

    두 벌이 되는 순간 한쪽만 고쳐지는 날이 오고, 그날 섀도는 프로덕션이
    쓰지 않는 프롬프트로 워커를 돌린다.
    """
    from neos.workflow.deep_analysis.assignment import build_assignment
    from neos.workflow.deep_analysis.orchestrator import Orchestrator

    ledger, question = _Ledger(), _Q("q_1", "MoE 라우팅은 비용을 낮추는가?")
    orchestrator = Orchestrator(
        object(),
        "run00001",
        worker_factory=lambda: object(),
        grader=object(),
        ledger=ledger,
    )

    assignments, splits = await orchestrator._partition([(question, Effort.DIG)])
    direct = await build_assignment(ledger, question, Effort.DIG)

    assert splits == []
    assert assignments[0].brief == direct.brief
    assert assignments[0].question_text == direct.question_text
    assert assignments[0].effort == direct.effort


@pytest.mark.asyncio
async def test_a_split_never_becomes_an_assignment() -> None:
    """분할은 지시가 아니라 다른 행동이다. 거르는 것은 부르는 쪽이다."""
    from neos.workflow.deep_analysis.orchestrator import Orchestrator

    question = _Q("q_1", "질문")
    orchestrator = Orchestrator(
        object(),
        "run00001",
        worker_factory=lambda: object(),
        grader=object(),
        ledger=_Ledger(),
    )

    assignments, splits = await orchestrator._partition([(question, Effort.SPLIT)])

    assert assignments == []
    assert splits == [question]


@pytest.mark.asyncio
async def test_the_effort_changes_the_brief() -> None:
    """노력 수준이 token_cap 을 바꾸고 그것이 brief 에 박힌다.

    이 단언이 없으면 위 동일성 테스트가 "brief 가 상수라서" 통과할 수도 있다.
    """
    from neos.workflow.deep_analysis.assignment import build_assignment

    ledger, question = _Ledger(), _Q("q_1", "질문")

    scout = await build_assignment(ledger, question, Effort.SCOUT)
    dig = await build_assignment(ledger, question, Effort.DIG)

    assert scout.brief != dig.brief
