"""클램프는 추정하지 않는다 -- 예산과 같은 함수로 재고 줄인다."""

import pytest

from neos.workflow.deep_analysis.llm import prompt_input_bound
from neos.workflow.deep_analysis.prompt_clamp import (
    clamp_prompt,
    shrink_once,
)
from neos.workflow.deep_analysis.token_budget import conservative_input_bound


def _render(primary: list[str], secondary: list[str]) -> str:
    return "머리말\n" + "\n".join(primary) + "\n" + "\n".join(secondary)


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

    def huge_template(primary: list[str], secondary: list[str]) -> str:
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
        lambda primary, secondary: (primary, secondary),
    )

    result = prompt_clamp.clamp_prompt(
        model="m",
        allowance=1,
        render_prompt=_render,
        primary=["자식"],
        secondary=["미확인"],
    )

    assert result.exhausted is True
