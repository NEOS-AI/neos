"""Jev 밴딩이 durable 루프에 실제로 닿는가 -- 로드맵 L2 배선.

단위 테스트(`tests/jev/`)는 밴딩 **함수**가 옳다고 말한다. 이 파일은 그
함수가 **불린다**고 말한다. 둘은 다른 주장이고, 이 저장소가 실제로 치른
실패는 뒤쪽이다 -- 고침이 한 호출부에만 도착한 전례가 반복된다.

게이트가 통과를 허용하는 자리는 셋이다(`_advance_one_tool_body` 의 읽기 전용
배치 · 본 판정 · 투기적 prefetch). 셋 다 여기서 겨눈다.
"""

from __future__ import annotations

import pytest

from neos.coding.domain.approvals import evaluate_approval
from neos.jev.banding import RiskBandThresholds
from neos.jev.gate import JEV_RISK_SCORED, JEV_UNAVAILABLE, JevToolRiskGate, RiskScore
from neos.coding.model.base import ModelCompleted, ModelUsage, ToolCallCompleted
from tests.coding.fakes import text_turn, tool_turn

pytestmark = pytest.mark.no_db

THRESHOLDS = RiskBandThresholds(low_below=0.3, high_at_or_above=0.7)


class StubScorer:
    def __init__(self, probability: float) -> None:
        self._probability = probability
        self.calls = 0

    async def score_tool_risk(self, state):
        del state
        self.calls += 1
        return RiskScore(
            probability=self._probability,
            model="jev-test-pin",
            rubric_digest="d" * 64,
        )


class FailingScorer:
    def __init__(self) -> None:
        self.calls = 0

    async def score_tool_risk(self, state):
        del state
        self.calls += 1
        raise TimeoutError("jev did not answer")


def jev(scorer, *, enforce: bool) -> JevToolRiskGate:
    return JevToolRiskGate(scorer=scorer, thresholds=THRESHOLDS, enforce=enforce)


async def run_script(harness) -> list:
    """스크립트를 끝까지 물리고 원장을 돌려준다.

    루프가 체크포인트와 함께 커밋하는 이벤트는 `advance()` 의 **반환값**으로
    나오고, `deps.events.append` 로 다는 이벤트(= jev)는 이벤트 저장소에
    쌓인다. 둘 다 원장이므로 둘 다 모은다.
    """
    committed = []
    for _ in range(20):
        event = await harness.advance(worker_id="w1")
        committed.append(event)
        if event.type == "run.completed":
            break
    stored = await harness.events.list_after("ct_real")
    return committed + list(stored)


def kinds(events) -> list[str]:
    return [event.type for event in events]


#: 정적 정책이 **ALLOW** 하는 호출을 쓴다. 승인을 요구하는 도구를 쓰면 루프가
#: 승인 대기로 멈춰서, 재는 것이 밴딩이 아니라 승인 흐름이 된다.
#:
#: 그리고 이 대상이라야 L2·L3 의 흥미로운 전이를 본다 -- ALLOW 를 Jev 가
#: 좁히는가. 정적으로 이미 막힌 호출은 §12.2 ② 때문에 Jev 를 보지도 않는다.
READ_SCRIPT = [
    tool_turn("read_file.v1", {"path": "calc.py"}, tool_call_id="t1"),
    text_turn("done"),
]


async def test_jev_off_writes_no_jev_events(real_loop_harness) -> None:
    """S9. 플래그 off 면 어휘가 늘지 않는다."""
    harness = await real_loop_harness(script=READ_SCRIPT, approval_evaluator=evaluate_approval)
    events = await run_script(harness)
    assert JEV_RISK_SCORED not in kinds(events)
    assert JEV_UNAVAILABLE not in kinds(events)


async def test_shadow_records_the_score_without_denying(real_loop_harness) -> None:
    """L2 는 기록만 한다. 확률이 아무리 높아도 도구는 그대로 돈다."""
    scorer = StubScorer(0.99)
    harness = await real_loop_harness(
        script=READ_SCRIPT,
        approval_evaluator=evaluate_approval,
        jev=jev(scorer, enforce=False),
    )
    events = await run_script(harness)
    assert scorer.calls >= 1
    scored = [e for e in events if e.type == JEV_RISK_SCORED]
    assert scored, f"jev 이벤트가 없다: {kinds(events)}"
    assert scored[0].payload["enforced"] is False
    assert scored[0].payload["probability"] == 0.99


async def test_the_recorded_event_can_reproduce_the_decision(real_loop_harness) -> None:
    """S13. 임계값·루브릭 digest·해소된 모델 id 가 원장에 있어야 한다."""
    harness = await real_loop_harness(
        script=READ_SCRIPT,
        approval_evaluator=evaluate_approval,
        jev=jev(StubScorer(0.99), enforce=False),
    )
    events = await run_script(harness)
    payload = next(e.payload for e in events if e.type == JEV_RISK_SCORED)
    assert payload["low_below"] == 0.3
    assert payload["high_at_or_above"] == 0.7
    assert payload["rubric_digest"] == "d" * 64
    assert payload["model"] == "jev-test-pin"


async def test_enforcing_denies_a_high_band_write(real_loop_harness) -> None:
    """L3. 같은 확률에 `enforce` 만 켜면 도구가 막힌다."""
    harness = await real_loop_harness(
        script=READ_SCRIPT,
        approval_evaluator=evaluate_approval,
        jev=jev(StubScorer(0.99), enforce=True),
    )
    events = await run_script(harness)
    assert "tool.denied" in kinds(events)


async def test_an_unavailable_jev_is_loud_and_does_not_block(real_loop_harness) -> None:
    """D-L1 · S12. 폴백의 최악은 "Jev 도입 이전"이지 "정책 없음"이 아니다."""
    scorer = FailingScorer()
    harness = await real_loop_harness(
        script=READ_SCRIPT,
        approval_evaluator=evaluate_approval,
        jev=jev(scorer, enforce=True),
    )
    events = await run_script(harness)
    assert scorer.calls >= 1
    assert JEV_UNAVAILABLE in kinds(events)
    assert "tool.denied" not in kinds(events)


async def test_the_speculative_prefetch_cannot_outrun_the_gate(real_loop_harness) -> None:
    """읽기 전용 prefetch 는 **판정 전에 도구를 실행한다**.

    게이트가 켜져 있는데 그 경로가 남아 있으면, Jev 가 막았을 호출이 이미
    돌아 버린다. 샌드박스가 켜져 있다고 승인을 생략하지 않는 것과 같은 규칙이다.
    """
    harness = await real_loop_harness(
        script=READ_SCRIPT,
        approval_evaluator=evaluate_approval,
        jev=jev(StubScorer(0.99), enforce=True),
    )
    events = await run_script(harness)
    assert "tool.denied" in kinds(events), kinds(events)


def two_read_turn() -> tuple[object, ...]:
    """한 턴에 읽기 전용 호출 **둘**. 이래야 배치 경로가 켜진다.

    `_leading_readonly_batch` 는 `len(remaining) < 2` 면 `None` 을 돌려준다 --
    호출 하나짜리 스크립트로는 그 경로를 지나지 않고, 그 위에서 통과하는
    테스트는 아무것도 증명하지 않는다.
    """
    return (
        ToolCallCompleted("t1", "read_file.v1", {"path": "calc.py"}),
        ToolCallCompleted("t2", "read_file.v1", {"path": "test_calc.py"}),
        ModelCompleted("tool_use", ModelUsage(1, 1)),
    )


BATCH_SCRIPT = [two_read_turn(), text_turn("done")]


async def test_a_readonly_batch_scores_each_call_once(real_loop_harness) -> None:
    """두 호출이면 점수도 둘이다."""
    harness = await real_loop_harness(
        script=BATCH_SCRIPT,
        approval_evaluator=evaluate_approval,
        jev=jev(StubScorer(0.1), enforce=False),
    )
    events = await run_script(harness)
    scored = [e for e in events if e.type == JEV_RISK_SCORED]
    assert len(scored) == 2, f"호출 2건에 점수가 {len(scored)} 건이다"


async def test_a_blocked_batch_does_not_rescore_the_same_call(real_loop_harness) -> None:
    """배치가 막히면 본 판정 경로로 떨어진다 -- 거기서 같은 호출을 또 잰다.

    중복의 위험이 가장 큰 자리이고, **밴딩이 실제로 좁힐 때만** 나타난다.
    한 건이 두 줄로 보이면 L3 을 켤지 보는 사람의 분모가 틀린다.
    """
    harness = await real_loop_harness(
        script=BATCH_SCRIPT,
        approval_evaluator=evaluate_approval,
        jev=jev(StubScorer(0.99), enforce=True),
    )
    events = await run_script(harness)
    scored = [e for e in events if e.type == JEV_RISK_SCORED]
    by_tool_call = [e.payload["tool_call_id"] for e in scored]
    assert len(by_tool_call) == len(set(by_tool_call)), (
        f"같은 호출이 여러 번 채점됐다: {by_tool_call}"
    )
    assert all(by_tool_call), "점수를 호출에 붙일 수 없다 -- tool_call_id 가 없다"
