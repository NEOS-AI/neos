"""클램프는 추정하지 않는다 -- 예산과 같은 함수로 재고 줄인다."""

import re

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


def test_compaction_sheds_uncited_prose_before_cited_sentences():
    """D62. 같은 글자 예산에서 **어느 글자를 남기는가**만 바꾼다.

    `halve` 는 문자 오프셋에서 자르고 그 뒤를 전부 버린다. 그래서 인용이
    글자보다 빨리 사라진다 -- 표본 #14·#15 의 조립 클램프는 글자를 36% /
    33% 남기면서 고유 클레임은 9% / 15% 로 떨어뜨렸다. 잃은 산문은 회복
    가능하지만 **작성자에게 도달하지 못한 클레임은 인용될 수 없다**(표본
    #15 에서 6개 중 5개가 각주 = 잔존 클레임으로 정확히 일치).
    """
    from neos.workflow.deep_analysis.prompt_clamp import halve
    from neos.workflow.deep_analysis.synthesizer import compact_keeping_claims

    text = " ".join(
        f"[C:{i:08x}] 인용 있는 문장 {i}. 인용 없는 서술 {'가' * 60}."
        for i in range(6)
    )
    marker = re.compile(r"\[C:[0-9a-f]{8}\]")

    kept = compact_keeping_claims(text)
    halved = halve(text)

    # 예산은 같다 -- 절반 이하.
    assert len(kept) <= len(text) // 2
    # 그런데 클레임은 훨씬 많이 남는다.
    assert len(marker.findall(kept)) > len(marker.findall(halved))


def test_compaction_never_strands_half_a_marker():
    """세그먼트 경계는 문장 부호와 개행이고 마커에는 그런 문자가 없다 --
    자르는 자리가 마커 한가운데로 떨어질 수 없다. 반쪽 마커는 `_RAW_MARKER`
    도 렌더러도 못 알아보므로 인용 자리에 문자 그대로 남는다."""
    from neos.workflow.deep_analysis.synthesizer import compact_keeping_claims

    text = " ".join(
        f"[C:{i:08x}] 문장 {i} 입니다. 뒤따르는 설명 {'나' * 30}."
        for i in range(8)
    )

    kept = compact_keeping_claims(text)

    assert not re.search(r"\[C:[0-9a-f]{0,7}$", kept)
    for fragment in kept.split("[C:")[1:]:
        assert re.match(r"^[0-9a-f]{8}\]", fragment)


def test_compaction_falls_back_to_halving_when_it_cannot_do_better():
    """세그먼트가 하나뿐이면 고를 것이 없다. 그래도 **반드시 줄어야** 한다 --
    `clamp_prompt` 의 수렴이 거기 걸려 있다."""
    from neos.workflow.deep_analysis.prompt_clamp import halve
    from neos.workflow.deep_analysis.synthesizer import compact_keeping_claims

    single = "가" * 400  # 문장 부호도 개행도 없다

    assert compact_keeping_claims(single) == halve(single)
    assert len(compact_keeping_claims(single)) < len(single)


def test_a_compactor_that_refuses_to_shrink_cannot_stall_the_clamp():
    """정책이 주입 가능해진 이상 수렴을 정책의 선의에 걸 수 없다(D62).

    반복 상한이 잡기는 하지만, 그때 `exhausted` 로 보고되는 프롬프트는
    **줄일 수 있었는데 안 줄인** 것이다. 그래서 한 걸음마다 진전을 강제한다.
    """
    result = clamp_prompt(
        model="m",
        allowance=1_500,
        render_prompt=_render,
        primary=[f"- [q{i:04d}] {'가' * 500}" for i in range(4)],
        secondary=[],
        compact=lambda text: text + "더 붙인다",  # 줄이기는커녕 늘린다
    )

    assert prompt_input_bound("m", result.prompt) <= 1_500
    assert result.exhausted is False


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
        lambda primary, secondary, anchor="", *_a, **_k: (
            primary,
            secondary,
            anchor,
        ),
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

    def alternating(primary, secondary, anchor="", *_a, **_k):
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


def test_halving_a_primary_block_is_visible_without_dropping_it():
    """D58. `dropped_primary` 는 **항목 수**만 센다.

    `shrink_once` 는 버리기 전에 반토막부터 낸다. 그래서 자식 블록 일곱 개를
    전부 유지하면서 각각을 8분의 1로 자른 클램프가 `dropped_primary=0` 으로
    기록되고 손대지 않은 것처럼 보인다 -- 표본 #13 이 정확히 그 모양이었다.
    앵커는 절반만 줄고 자식은 하나도 안 버려졌는데 프롬프트는 3분의 1이 됐고,
    그 토큰이 어디로 갔는지 원장에 답이 없었다.
    """
    primary = [f"- [q{i:04d}] {'가' * 800}" for i in range(4)]

    result = clamp_prompt(
        model="m",
        allowance=2_000,
        render_prompt=_render,
        primary=primary,
        secondary=[],
    )

    assert result.dropped_primary == 0  # 아무것도 버리지 않았는데
    assert result.primary_clamped is True  # 실제로는 크게 잘렸다
    assert result.primary_chars_after < result.primary_chars_before // 2
    assert result.primary_chars_before == sum(len(b) for b in primary)


async def _claims_for(claim):
    """`ledger.verified_claims` 가 돌려주는 (claim, evidence rows) 짝."""
    return [(claim, [])]


def _echo_synth(ledger, **kw):
    async def llm_call(model, prompt, **kwargs):
        class R:
            text = "## 요약\n본문"
            input_tokens = 1
            output_tokens = 1

        return R()

    return Synthesizer(ledger, llm_call=llm_call, **kw)


@pytest.mark.asyncio
async def test_assembly_records_how_many_distinct_claims_survived_the_clamp():
    """D58 의 도메인 절반. 클램프는 크기만 알고, 그 글자들이 `[C:...]` 주소를
    나른다는 것은 호출자만 안다.

    프롬프트에 살아남은 클레임 수가 리포트가 가질 수 있는 인용의 **상한**이다.
    표본 #13 은 배달 리포트의 각주가 12 -> 7 -> 2 -> 2 로 떨어졌는데 마커가
    작성자에게 도달하기는 했는지조차 원장이 답하지 못했다.
    """
    ledger = _Ledger()
    synth = _echo_synth(ledger, synthesis_max_tokens=200)
    root = NodeSummary(
        question_id="q0000001",
        answer="[C:aaaaaaaa] 루트 " + "루" * 2_000,
        key_claim_ids=[],
        confidence=0.5,
        caveats=[],
    )
    children = [
        NodeSummary(
            question_id=f"q000000{i}",
            answer=f"[C:{i:08x}] 자식 답 " + "가" * 800,
            key_claim_ids=[],
            confidence=0.5,
            caveats=[],
        )
        for i in range(2, 7)
    ]

    await synth.assemble(root, children, [])

    clamp = ledger.payload("finalization_prompt_clamped")
    # 자식 5개 + 루트 1개 = 고유 클레임 6개가 들어갔다.
    assert clamp["distinct_claims_before"] == 6
    # 살아남은 수는 프롬프트에서 직접 센 것이고, 절삭됐으므로 더 적다.
    assert clamp["distinct_claims_after"] < clamp["distinct_claims_before"]
    # 그리고 크기 쪽 계측이 그 손실이 어느 슬롯에서 났는지 말해준다.
    assert clamp["primary_chars_before"] > clamp["primary_chars_after"]
    assert clamp["anchor_chars_before"] > clamp["anchor_chars_after"]


@pytest.mark.asyncio
async def test_assembly_keeps_more_claims_than_blind_halving_would():
    """D62 를 조립 경로 끝까지 -- 압축기가 실제로 배선돼 있는가.

    단위 테스트는 `compact_keeping_claims` 가 옳다는 것만 보인다. 이 테스트는
    `assemble` 이 그것을 clamp 에 **넘긴다**는 것을 보인다. 넘기지 않으면
    기본값 `halve` 로 돌아가고 아무것도 달라지지 않는다.
    """
    from neos.workflow.deep_analysis.prompt_clamp import halve

    def build(compact_arg):
        ledger = _Ledger()
        synth = _echo_synth(ledger, synthesis_max_tokens=2_000)
        return ledger, synth

    children = [
        NodeSummary(
            question_id=f"q{i:07d}",
            answer=" ".join(
                f"[C:{i * 5 + j:08x}] 근거 {j} 입니다. "
                f"인용 없는 서술 {'가' * 60}."
                for j in range(5)
            ),
            key_claim_ids=[],
            confidence=0.5,
            caveats=[],
        )
        for i in range(6)
    ]
    root = NodeSummary(
        question_id="q0000000",
        answer="루트 요약 " + "루" * 400,
        key_claim_ids=[],
        confidence=0.5,
        caveats=[],
    )

    ledger, synth = build(None)
    await synth.assemble(root, children, [])
    with_compactor = ledger.payload("finalization_prompt_clamped")

    # 대조군: 같은 입력을 기본 `halve` 로 클램프했을 때의 잔존 클레임.
    import neos.workflow.deep_analysis.synthesizer as synth_mod

    blind_ledger, blind_synth = build(None)
    original = synth_mod.compact_keeping_claims
    synth_mod.compact_keeping_claims = halve
    try:
        await blind_synth.assemble(root, children, [])
    finally:
        synth_mod.compact_keeping_claims = original
    blind = blind_ledger.payload("finalization_prompt_clamped")

    assert (
        with_compactor["distinct_claims_after"]
        > blind["distinct_claims_after"]
    ), (with_compactor, blind)


@pytest.mark.asyncio
async def test_a_claim_cited_in_two_slots_is_counted_once():
    """D59(2). 각주는 클레임당 하나다 -- `CitationRenderer` 가 몇 번 인용되든
    하나로 묶는다. 출현 횟수를 세면 다른 질문에 답하게 되고, 같은 클레임이
    자식 블록과 그것을 요약한 루트 답에 함께 나오는 것은 예외가 아니라 상례다.
    """
    ledger = _Ledger()
    synth = _echo_synth(ledger, synthesis_max_tokens=200)
    root = NodeSummary(
        question_id="q0000001",
        # 자식이 인용한 바로 그 클레임을 루트도 인용한다.
        answer="[C:0000002a] 루트 요약 " + "루" * 3_000,
        key_claim_ids=[],
        confidence=0.5,
        caveats=[],
    )
    child = NodeSummary(
        question_id="q0000002",
        answer="[C:0000002a] 자식 답 " + "가" * 3_000,
        key_claim_ids=[],
        confidence=0.5,
        caveats=[],
    )

    await synth.assemble(root, [child], [])

    clamp = ledger.payload("finalization_prompt_clamped")
    assert clamp["distinct_claims_before"] == 1


@pytest.mark.asyncio
async def test_before_counts_every_slot_the_prompt_will_contain():
    """D59(1). `before` 는 프롬프트가 담게 될 **모든** 슬롯을 세야 한다.

    `node_reduction` 의 `before` 가 `child_lines` 를 빠뜨려 표본 #14 에서
    합계가 35 -> 90 으로 나왔다 -- `after` 가 `before` 보다 컸고, 그 한 가지
    사실이 리덕션 층 계측 전체를 무효로 만들었다. 조립 쪽에는 같은 함정이
    `caveats` 에 있다: 프롬프트에 들어가고, 노드 요약은 자기 caveat 에도
    마커를 단다(D44 가 표본 #7 의 30건 중 3건에서 관측).

    `after <= before` 라는 불변식으로 잡으려 했으나 **잡지 못한다**:
    `shrink_once` 는 secondary 를 가장 먼저 버리므로 자식 줄의 마커가
    `after` 에 남지 못하는 경우가 많고, 그러면 빠뜨린 `before` 로도 부등식이
    성립한다. 그래서 의도를 직접 주장한다.
    """
    ledger = _Ledger()
    synth = _echo_synth(ledger, synthesis_max_tokens=200)

    class _Q:
        id = "q0000001"
        text = "질문"

    class _Claim:
        id = "0000000a"
        text = "노드 자신의 클레임"
        confidence = 0.5

    # 노드 자신의 클레임은 **짧게**. 그래야 `shrink_once` 가 긴 쪽(자식 줄)을
    # 치고, 두 슬롯의 마커가 **둘 다 프롬프트에 살아남는다** -- 양쪽이 0 이
    # 되어버리면 `after <= before` 는 버그가 있어도 성립해서 아무것도 잡지
    # 못한다(이 테스트를 처음 썼을 때 실제로 그랬다).
    ledger.verified_claims = lambda qid: _claims_for(_Claim())
    child = NodeSummary(
        question_id="q0000002",
        # 마커를 맨 앞에 둔다. 반토막은 앞을 남기므로 여러 번 잘려도 남는다.
        answer="[C:0000000b] " + "가" * 3_000,
        key_claim_ids=[],
        confidence=0.5,
        caveats=[],
    )

    async def json_call(model, prompt, **kwargs):
        return {"answer": "요약", "caveats": [], "conflicts": []}, type(
            "R", (), {"input_tokens": 1, "output_tokens": 1}
        )()

    synth.json_call = json_call
    await synth.reduce_node(_Q(), [child])

    # (2) 조립 -- caveat 에만 있는 마커. `caveats` 도 프롬프트에 들어가고
    # 노드 요약은 자기 caveat 에도 마커를 단다(D44).
    root = NodeSummary(
        question_id="q0000001",
        answer="[C:0000000d] " + "루" * 3_000,
        key_claim_ids=[],
        confidence=0.5,
        caveats=[],
    )
    await synth.assemble(root, [child], ["[C:0000000c] 미확인: 확인 실패"])

    by_stage = {
        payload["stage"]: payload
        for kind, _qid, payload in ledger.events
        if kind == "finalization_prompt_clamped"
        and "distinct_claims_before" in payload
    }

    # 리덕션: 노드 자신의 클레임 1 + 자식 줄의 클레임 1 = 2.
    # `child_lines` 를 빠뜨리면 1 이 된다.
    assert by_stage["node_reduction"]["distinct_claims_before"] == 2
    # 조립: 자식 블록 1 + 루트 답 1 + caveat 1 = 3.
    # `caveats` 를 빠뜨리면 2 가 된다.
    assert by_stage["report_assembly"]["distinct_claims_before"] == 3

    # 부등식은 이 데이터에서 저 두 결함을 잡지 못하지만(독스트링 참조),
    # 성립하기는 해야 한다.
    for payload in by_stage.values():
        assert (
            payload["distinct_claims_after"]
            <= payload["distinct_claims_before"]
        ), payload


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
