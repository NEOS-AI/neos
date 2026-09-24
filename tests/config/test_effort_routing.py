"""사고량(effort)은 모델과 **같은 사슬**을 탄다 (로드맵 K5).

로드맵 §원칙: "effort 는 모델과 같은 해석 사슬을 탄다 -- 따로 사슬을 만들면
'고침은 한 호출부에만'이 재발한다." 그래서 우선순위도 어휘도
`resolve_model` 의 것을 그대로 쓴다: user → conversation → feature override
→ role default, 그리고 `ResolutionSource`.

## 모델에 없는 단계가 하나 더 있다

해석된 레벨을 **그 모델이 받는가**. 안 받으면 보내지 않는다 -- 틀린 effort 는
매 요청 400 이고, 카탈로그가 비어 있는 동안(K5 의 출발점)은 그것이 모든
모델이다.

그 게이트가 두 곳에 생기면 한쪽만 고쳐지는 날이 온다. 그래서 해석과 게이트를
한 함수가 한다.

## 거절은 조용하지 않다

운영자가 `high` 를 적었는데 아무 일도 안 일어나면 설정이 틀렸는지 코드가
틀렸는지 알 수 없다. `refused` 가 이유를 들고 다닌다.
"""

from __future__ import annotations

import pytest

from neos.config.model_routing import ResolutionSource

pytestmark = pytest.mark.no_db

_KNOWN = "claude-opus-5-5"


def _resolve(**kwargs):
    from neos.config.model_routing import resolve_effort

    base = {
        "model": _KNOWN,
        "role": "powerful",
        "role_default": None,
        "supported_levels": ("low", "medium", "high"),
    }
    base.update(kwargs)
    return resolve_effort(**base)


# ---- 우선순위는 모델과 같다 -------------------------------------------------------


def test_the_user_wins_over_everything() -> None:
    resolution = _resolve(
        user_effort="low",
        conversation_effort="medium",
        feature_override="high",
        role_default="max",
    )

    assert resolution.effort == "low"
    assert resolution.source is ResolutionSource.USER


def test_the_conversation_wins_over_the_feature_and_the_default() -> None:
    resolution = _resolve(
        conversation_effort="medium", feature_override="high", role_default="low"
    )

    assert resolution.effort == "medium"
    assert resolution.source is ResolutionSource.CONVERSATION


def test_the_feature_override_wins_over_the_role_default() -> None:
    resolution = _resolve(feature_override="high", role_default="low")

    assert resolution.effort == "high"
    assert resolution.source is ResolutionSource.FEATURE_OVERRIDE


def test_the_role_default_is_the_floor() -> None:
    resolution = _resolve(role_default="medium")

    assert resolution.effort == "medium"
    assert resolution.source is ResolutionSource.ROLE_DEFAULT


def test_nothing_asked_means_nothing_sent() -> None:
    """**K5 의 기본 상태다.** 아무도 값을 정하지 않았으면 요청은 예전과 같다.

    이것이 필드를 넣는 커밋을 표본 경계가 아니게 만든다(로드맵 §경계 10).
    """
    resolution = _resolve()

    assert resolution.effort is None
    assert resolution.source is None
    assert resolution.refused == ""


# ---- 모델이 받지 않으면 보내지 않는다 ---------------------------------------------


def test_a_model_that_declares_nothing_gets_nothing() -> None:
    """카탈로그가 비어 있는 동안은 **모든 모델**이 여기 해당한다.

    조용히 떨어뜨리지 않는다 -- 운영자가 `high` 를 적었는데 아무 일도 안
    일어나면 설정이 틀렸는지 코드가 틀렸는지 알 수 없다.
    """
    resolution = _resolve(feature_override="high", supported_levels=())

    assert resolution.effort is None
    assert resolution.refused == "model_declares_no_effort"


def test_a_level_the_model_does_not_take_is_refused() -> None:
    """`xhigh` 를 받는 모델과 안 받는 모델이 있다(SDK 의 `xhigh` 는 Optional).

    가장 가까운 레벨로 **낮춰 보내지 않는다.** 그러면 운영자가 적은 것과
    실제로 돈 것이 달라지고, 그 차이는 어디에도 남지 않는다.
    """
    resolution = _resolve(feature_override="xhigh")

    assert resolution.effort is None
    assert resolution.refused == "level_not_supported"


def test_a_supported_level_passes_the_gate() -> None:
    resolution = _resolve(feature_override="high")

    assert resolution.effort == "high"
    assert resolution.refused == ""


# ---- 어휘 밖의 값 ---------------------------------------------------------------


def test_a_level_outside_the_sdk_vocabulary_is_refused() -> None:
    """설정 검증을 우회해 들어온 값(예: DB 의 옛 행)도 여기서 걸린다."""
    resolution = _resolve(user_effort="turbo")

    assert resolution.effort is None
    assert resolution.refused == "unknown_level"


def test_the_refusal_names_the_level_it_refused() -> None:
    """무엇을 고쳐야 하는지 말하지 않는 거절은 절반만 유용하다."""
    resolution = _resolve(user_effort="turbo")

    assert "turbo" in resolution.detail


def test_a_refusal_still_reports_where_the_value_came_from() -> None:
    """user 가 적은 것이 틀렸는지 역할 기본값이 틀렸는지 갈린다."""
    resolution = _resolve(feature_override="xhigh")

    assert resolution.source is ResolutionSource.FEATURE_OVERRIDE
