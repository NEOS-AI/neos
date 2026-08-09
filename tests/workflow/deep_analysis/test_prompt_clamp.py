"""클램프는 추정하지 않는다 -- 예산과 같은 함수로 재고 줄인다."""

import pytest

from neos.workflow.deep_analysis.llm import prompt_input_bound
from neos.workflow.deep_analysis.models import NodeSummary
from neos.workflow.deep_analysis.prompt_clamp import (
    clamp_prompt,
    shrink_once,
)
from neos.workflow.deep_analysis.synthesizer import Synthesizer
from neos.workflow.deep_analysis.token_budget import (
    FINALIZATION_STAGES,
    REPORT_STAGES,
    TokenBudgetExhausted,
    conservative_input_bound,
)


def _render(primary: list[str], secondary: list[str], anchor: str = "") -> str:
    return (
        "머리말\n"
        + anchor
        + "\n".join(primary)
        + "\n"
        + "\n".join(secondary)
    )


def test_prompt_input_bound_matches_what_reserve_would_charge():
    """자가 두 벌이면 클램프의 유일한 보장이 깨진다.

    call_llm 은 request={"model": m, "messages": [...], "tools": None} 로
    reserve() 를 부른다(llm.py:328). 헬퍼는 반드시 같은 모양이어야 한다.
    """
    prompt = "한국어 프롬프트 본문"
    expected = conservative_input_bound(
        {
            "model": "m",
            "messages": [{"role": "user", "content": prompt}],
            "tools": None,
        }
    )

    assert prompt_input_bound("m", prompt) == expected


def test_a_prompt_within_the_allowance_is_untouched():
    result = clamp_prompt(
        model="m",
        allowance=100_000,
        render_prompt=_render,
        primary=["자식 A", "자식 B"],
        secondary=["미확인: 1"],
    )

    assert result.clamped is False
    assert result.exhausted is False
    assert result.dropped_primary == 0
    assert result.dropped_secondary == 0
    assert result.prompt == _render(["자식 A", "자식 B"], ["미확인: 1"])


def test_an_oversized_prompt_is_forced_under_the_allowance():
    """조립이 574 run 동안 예약을 못 받은 이유가 입력 크기다."""
    primary = [f"- [q{i:04d}] {'가' * 400}" for i in range(12)]
    secondary = [f"미확인: {'나' * 200}" for _ in range(8)]
    allowance = 4_000

    assert prompt_input_bound("m", _render(primary, secondary)) > allowance

    result = clamp_prompt(
        model="m",
        allowance=allowance,
        render_prompt=_render,
        primary=primary,
        secondary=secondary,
    )

    assert prompt_input_bound("m", result.prompt) <= allowance
    assert result.clamped is True
    assert result.bound_after < result.bound_before


def test_secondary_is_spent_before_primary():
    """D-6: caveats -> 자식 꼬리 -> 자식 수. 본문 커버리지를 먼저 지킨다."""
    primary = ["- [q0001] 짧은 자식"]
    secondary = [f"미확인: {'나' * 300}" for _ in range(6)]

    result = clamp_prompt(
        model="m",
        allowance=prompt_input_bound("m", _render(primary, [])) + 32,
        render_prompt=_render,
        primary=primary,
        secondary=secondary,
    )

    assert result.dropped_secondary > 0
    assert result.dropped_primary == 0


def test_an_unshrinkable_prompt_reports_exhaustion_instead_of_looping():
    """가변 조각을 다 비워도 템플릿이 크면 더 줄일 것이 없다.

    포기하고 reserve() 에 판단을 넘긴다. 무한 루프를 만들지 않는다.
    """

    def huge_template(
        primary: list[str], secondary: list[str], anchor: str = ""
    ) -> str:
        return "머" * 5_000 + "\n".join(primary) + "\n".join(secondary)

    result = clamp_prompt(
        model="m",
        allowance=100,
        render_prompt=huge_template,
        primary=["자식"],
        secondary=["미확인"],
    )

    assert result.exhausted is True
    assert prompt_input_bound("m", result.prompt) > 100


def test_shrink_once_returns_none_when_nothing_is_left():
    assert shrink_once([], []) is None


def test_an_oversized_anchor_is_halved_instead_of_eating_every_child():
    """D54: 앵커가 클램프 밖에 있으면 나머지 전부가 그 값을 치른다.

    표본 #11 이 잰 끝 상태 -- 조립 클램프 12건이 **12/12 exhausted** 였고,
    자식 블록 전부와 caveats 전부를 버리고도 허용량을 못 맞췄다. 강등된 루트
    요약 하나가 허용량을 단독으로 넘었기 때문이다. 그 결과 리포트는 **인용할
    클레임이 프롬프트에 없는 채로** 쓰였다.
    """
    primary = ["- [q0001] 자식 A", "- [q0002] 자식 B"]
    anchor = "루" * 4_000
    allowance = 3_000

    result = clamp_prompt(
        model="m",
        allowance=allowance,
        render_prompt=_render,
        primary=primary,
        secondary=[],
        anchor=anchor,
    )

    assert prompt_input_bound("m", result.prompt) <= allowance
    assert result.exhausted is False
    # 자식은 하나도 잃지 않았다 -- 값을 치른 것은 앵커다.
    assert result.dropped_primary == 0
    assert result.anchor_clamped is True
    assert result.anchor_chars_after < result.anchor_chars_before
    for block in primary:
        assert block in result.prompt


def test_a_normally_sized_anchor_does_not_change_the_old_ordering():
    """앵커가 평범한 크기면 정책은 D-6 그대로여야 한다 -- 이 변경은 순위를
    뒤집는 것이 아니라 앵커가 무한할 수 없게 만드는 것이다."""
    primary = [f"- [q{i:04d}] {'가' * 400}" for i in range(6)]
    secondary = [f"미확인: {'나' * 200}" for _ in range(4)]
    anchor = "루트 요약"

    result = clamp_prompt(
        model="m",
        allowance=prompt_input_bound("m", _render(primary, [], anchor)) + 32,
        render_prompt=_render,
        primary=primary,
        secondary=secondary,
        anchor=anchor,
    )

    assert result.dropped_secondary > 0
    assert result.dropped_primary == 0
    assert result.anchor_clamped is False
    assert anchor in result.prompt


def test_shrink_once_never_drops_the_anchor_to_nothing():
    """앵커는 반토막이 나도 사라지지는 않는다 -- 루트 요약이 없는 리포트는
    짧은 리포트보다 나쁘다."""
    primary: list[str] = []
    anchor = "루" * 64
    steps = 0
    while (step := shrink_once(primary, [], anchor)) is not None:
        primary, _sec, anchor = step
        steps += 1
        assert steps < 100, "반토막이 수렴하지 않는다"
    # 더 줄일 것이 없다고 판단할 때까지 반토막이 났지만, 앵커는 남아 있다.
    assert anchor != ""
    assert len(anchor) == 1
    # 아무것도 없을 때만 None 이다.
    assert shrink_once([], [], "") is None


def test_clamp_terminates_even_if_the_policy_stops_making_progress(
    monkeypatch,
):
    """정책 함수가 손대지 않은 리스트를 돌려줘도 루프는 끝나야 한다.

    종료를 정책의 정확성에 걸지 않는다 -- 정책은 사람이 고치는 부분이다.
    """
    from neos.workflow.deep_analysis import prompt_clamp

    monkeypatch.setattr(
        prompt_clamp,
        "shrink_once",
        lambda primary, secondary, anchor="": (primary, secondary, anchor),
    )

    result = prompt_clamp.clamp_prompt(
        model="m",
        allowance=1,
        render_prompt=_render,
        primary=["자식"],
        secondary=["미확인"],
    )

    assert result.exhausted is True


def test_clamp_terminates_even_if_the_policy_cycles_between_two_states(
    monkeypatch,
):
    """정책이 고정점이 아니라 두 상태를 오가기만 해도 끝나야 한다.

    이전 종료 보장("새 상태 == 이전 상태")은 정확히 되돌아오는 스텝만 잡는다.
    두 상태를 번갈아 돌려주는 정책은 매 스텝 그 검사를 통과하면서도 절대
    줄어들지 않는다 -- 실제 리뷰에서 이 정책을 몽키패치했을 때 10초 타임아웃까지
    멈추지 않았다. 지금은 입력에서 유도한 반복 횟수 상한이 잡는다.
    """
    from neos.workflow.deep_analysis import prompt_clamp

    state_a = (["자식"], ["미확인"], "")
    state_b = (["다른"], ["다른 미확인"], "")
    calls = {"n": 0}

    def alternating(primary, secondary, anchor=""):
        calls["n"] += 1
        return state_b if calls["n"] % 2 else state_a

    monkeypatch.setattr(prompt_clamp, "shrink_once", alternating)

    result = prompt_clamp.clamp_prompt(
        model="m",
        allowance=1,
        render_prompt=_render,
        primary=list(state_a[0]),
        secondary=list(state_a[1]),
    )

    assert result.exhausted is True


class _Ledger:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict]] = []

    async def log(self, kind, qid, payload):
        self.events.append((kind, qid, payload))

    async def verified_claims(self, qid):
        return []

    def kinds(self) -> list[str]:
        return [kind for kind, _qid, _payload in self.events]

    def payload(self, kind: str) -> dict:
        return next(p for k, _q, p in self.events if k == kind)


class _Response:
    text = "## 요약\n본문"
    input_tokens = 10
    output_tokens = 20


@pytest.mark.asyncio
async def test_assemble_clamps_an_oversized_prompt_and_records_it():
    ledger = _Ledger()
    seen: dict[str, str] = {}

    async def llm_call(model, prompt, **kwargs):
        seen["model"] = model
        seen["prompt"] = prompt
        return _Response()

    synth = Synthesizer(
        ledger, llm_call=llm_call, synthesis_max_tokens=1_200
    )
    # 루트 요약은 절대 잘리지 않는다(D-6). 이 테스트는 자식·caveats 축소만
    # 보려는 것이므로 루트를 짧게 두어 허용량 대부분을 가변 조각에 남긴다.
    root = NodeSummary(
        question_id="q0000000",
        answer="루트 요약",
        key_claim_ids=[],
        confidence=0.8,
        caveats=[],
    )
    children = [
        NodeSummary(
            question_id=f"q{i:07d}",
            answer="가" * 900,
            key_claim_ids=[],
            confidence=0.5,
            caveats=[],
        )
        for i in range(10)
    ]

    await synth.assemble(root, children, ["미확인: " + "나" * 400])

    # 예약이 쓸 자와 같은 자로, 실제로 넘어간 모델명으로 잰다.
    assert (
        prompt_input_bound(seen["model"], seen["prompt"])
        <= synth.assembly_input_allowance
    )
    assert "finalization_prompt_clamped" in ledger.kinds()
    clamped = ledger.payload("finalization_prompt_clamped")
    assert clamped["stage"] == "report_assembly"
    assert clamped["bound_after"] < clamped["bound_before"]
    assert clamped["exhausted"] is False
    assert "synth_pass" in ledger.kinds()


@pytest.mark.asyncio
async def test_assemble_does_not_log_a_clamp_when_nothing_was_cut():
    """클램프 이벤트는 실제로 잘랐을 때만 나온다 -- 원장을 노이즈로 채우지 않는다."""
    ledger = _Ledger()

    async def llm_call(model, prompt, **kwargs):
        return _Response()

    synth = Synthesizer(
        ledger, llm_call=llm_call, synthesis_max_tokens=1_200
    )
    root = NodeSummary(
        question_id="q0000001",
        answer="짧은 답",
        key_claim_ids=[],
        confidence=0.9,
        caveats=[],
    )

    await synth.assemble(root, [], [])

    assert "finalization_prompt_clamped" not in ledger.kinds()
    assert "synth_pass" in ledger.kinds()


@pytest.mark.asyncio
async def test_assemble_reports_no_verified_claims_when_the_clamp_drops_every_child(
    monkeypatch,
):
    """F10: `has_content`는 클램프 *이후* 상태로 계산돼야 한다.

    루트 요약이 비어 있고 클램프가 모든 child 블록을 지워버리면, 캐비어 캡션은
    "(없음)"이 아니라 "검증된 클레임을 확보하지 못함"이어야 한다 -- 클램프 전
    `child_blocks`로 계산하면 실제로는 클레임이 하나도 안 남았는데도 (원래
    child가 있었다는 이유만으로) "(없음)"으로 보인다.
    """
    from neos.config.settings import settings

    monkeypatch.setattr(
        settings.config.deep_analysis, "assembly_input_ratio", 0.01
    )
    ledger = _Ledger()
    seen: dict[str, str] = {}

    async def llm_call(model, prompt, **kwargs):
        seen["prompt"] = prompt
        return _Response()

    synth = Synthesizer(
        ledger, llm_call=llm_call, synthesis_max_tokens=1_200
    )
    root = NodeSummary(
        question_id="q0000000",
        answer="",
        key_claim_ids=[],
        confidence=0.0,
        caveats=[],
    )
    children = [
        NodeSummary(
            question_id=f"q{i:07d}",
            answer="가" * 900,
            key_claim_ids=[],
            confidence=0.5,
            caveats=[],
        )
        for i in range(5)
    ]

    await synth.assemble(root, children, [])

    assert "검증된 클레임을 확보하지 못함" in seen["prompt"]
    assert "(없음)" not in seen["prompt"]


@pytest.mark.asyncio
async def test_a_degraded_join_is_bounded_by_the_answer_ceiling():
    """D54 근본 원인. 강등 요약은 자식 답을 이어붙이는데 그것이 무계였다.

    강등된 부모가 강등된 자식을 이어붙이므로 텍스트가 트리를 타고 누적된다.
    표본 #11 의 `7aa21c7f` 은 리덕션 12건이 강등됐고 **마지막이 루트**였다 --
    그 답이 서브트리 대부분이 되어 입력 5,800~12,200 토큰, 조립 허용량 6,000
    을 단독으로 넘었다.
    """
    ledger = _Ledger()

    async def json_call(model, prompt, **kwargs):
        raise TokenBudgetExhausted("budget")

    ceiling = 1_200
    synth = Synthesizer(
        ledger, json_call=json_call, synthesis_max_tokens=ceiling
    )

    class _Question:
        id = "q0000001"
        text = "질문"

    # 자식 넷이 각각 큰 답을 들고 있다 -- 강등 join 은 이것을 전부 잇는다.
    children = [
        NodeSummary(
            question_id=f"q000000{i}",
            answer="가" * 4_000,
            key_claim_ids=[],
            confidence=0.4,
            caveats=[],
        )
        for i in range(2, 6)
    ]

    summary = await synth.reduce_node(_Question(), children)

    # 잘리지 않았다면 16,000자 -- 실제 LLM 답이 결코 될 수 없는 크기다.
    assert len(summary.answer) < 16_000
    assert prompt_input_bound("m", summary.answer) <= ceiling
    degraded = ledger.payload("node_reduction_degraded")
    assert degraded["answer_truncated"] is True
    assert degraded["answer_chars"] > len(summary.answer)


@pytest.mark.asyncio
async def test_a_bounded_join_does_not_ship_half_a_citation_marker():
    """잘린 자리에 `[C:` 조각이 남으면 `_RAW_MARKER` 도 렌더러도 그것을 못
    알아본다 -- 인용이 있어야 할 자리에 문자 그대로 남는다."""
    ledger = _Ledger()

    async def json_call(model, prompt, **kwargs):
        raise TokenBudgetExhausted("budget")

    synth = Synthesizer(ledger, json_call=json_call, synthesis_max_tokens=400)

    class _Question:
        id = "q0000001"
        text = "질문"

    child = NodeSummary(
        question_id="q0000002",
        # 잘림이 마커 중간에 떨어지도록 마커를 촘촘히 깐다.
        answer=" ".join(f"[C:{i:08x}] 문장 {i}" for i in range(400)),
        key_claim_ids=[],
        confidence=0.4,
        caveats=[],
    )

    summary = await synth.reduce_node(_Question(), [child])

    import re

    assert not re.search(r"\[C:[0-9a-f]{0,7}$", summary.answer)
    # 남은 마커는 전부 온전하다.
    for fragment in summary.answer.split("[C:")[1:]:
        assert re.match(r"^[0-9a-f]{8}\]", fragment)


@pytest.mark.asyncio
async def test_a_degraded_reduction_leaves_a_trace():
    """W1 검증에 필수다.

    강등이 원장에 안 남으면 "리덕션은 강등됐지만 조립은 살았다"(설계 의도)와
    "리덕션이 전부 성공했다"를 구분할 수 없다.
    """
    ledger = _Ledger()

    async def json_call(model, prompt, **kwargs):
        raise TokenBudgetExhausted("budget")

    synth = Synthesizer(
        ledger, json_call=json_call, synthesis_max_tokens=1_200
    )

    class _Question:
        id = "q0000001"
        text = "질문"

    child = NodeSummary(
        question_id="q0000002",
        answer="자식 답",
        key_claim_ids=[],
        confidence=0.4,
        caveats=[],
    )

    summary = await synth.reduce_node(_Question(), [child])

    assert summary.caveats == ["token_budget_exhausted"]
    assert "node_reduction_degraded" in ledger.kinds()
    degraded = ledger.payload("node_reduction_degraded")
    assert degraded == {
        "question_id": "q0000001",
        "child_count": 1,
        "reason": "token_budget_exhausted",
        # D54: 강등 join 은 이제 유계다. 이 두 값이 없으면 강등된 루트가
        # 400자짜리 join 이었는지 40,000자짜리였는지 원장에서 구별되지 않고,
        # 조립을 망가뜨리는 것은 후자다.
        "answer_chars": 4,
        "answer_truncated": False,
    }


@pytest.mark.asyncio
async def test_assemble_and_reduce_node_pass_stage_literals_the_budget_recognizes():
    """`TokenBudget.reserve` matches `stage=` against REPORT_STAGES /
    FINALIZATION_STAGES by string equality (token_budget.py). A typo in
    either literal is invisible to type checkers and silently drops the
    call into the wrong tier -- `report_assembly` misspelled falls into the
    investigation branch and is refused on every run once the floor is in
    place.

    Asserted against the real imported constants, not a repeated string
    literal, so this fails if either side drifts -- a copy of the same
    literal in the test would pass right alongside the same typo.
    """
    ledger = _Ledger()
    captured: dict[str, dict] = {}

    async def llm_call(model, prompt, **kwargs):
        captured["assemble"] = kwargs
        return _Response()

    async def json_call(model, prompt, **kwargs):
        captured["reduce_node"] = kwargs
        return (
            {
                "answer": "요약",
                "confidence": 0.5,
                "key_claim_ids": [],
                "caveats": [],
                "conflicts": [],
            },
            _Response(),
        )

    synth = Synthesizer(
        ledger,
        llm_call=llm_call,
        json_call=json_call,
        synthesis_max_tokens=1_200,
    )
    root = NodeSummary(
        question_id="q0000000",
        answer="루트 요약",
        key_claim_ids=[],
        confidence=0.8,
        caveats=[],
    )

    await synth.assemble(root, [], [])

    class _Question:
        id = "q0000001"
        text = "질문"

    await synth.reduce_node(_Question(), [])

    assert captured["assemble"]["stage"] in REPORT_STAGES
    assert captured["reduce_node"]["stage"] in FINALIZATION_STAGES
    assert captured["reduce_node"]["stage"] not in REPORT_STAGES
