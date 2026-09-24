"""DA 역할별 사고량 (로드맵 K5 / 스펙 R-05: "DA 역할 scout/dig/synth/judge 각각").

`resolve_harness_model` 과 **짝**이다. 그 함수가 "이 역할이 실제로 어떤
모델로 도는가" 를 말하는 유일한 지점이듯, 여기도 "이 역할이 어떤 사고량으로
도는가" 의 유일한 지점이어야 한다 -- 사본이 생기면 매니페스트(H1)가 실제로
돈 것과 다른 값을 싣는다.

## 이름을 `model_effort` 로 둔 이유

`deep_analysis.effort` 는 **이미 있다** -- scout/dig/synth 의 `token_cap` 과
`wall_clock_cap`, 즉 **조사 깊이**다. 같은 트리에서 `effort` 가 두 축을
가리키면 설정을 읽는 사람이 어느 쪽인지 알 수 없다.

## 기본값은 전부 비어 있다

값을 정하는 것은 **표본 경계**다(로드맵 §경계 10: "effort 변경마다 행을
더한다"). 그래서 이 커밋은 배선만 넣고 아무 값도 정하지 않는다.
"""

from __future__ import annotations

import pytest

from neos.config.model_routing import ResolutionSource
from neos.config.settings import settings

pytestmark = pytest.mark.no_db


def test_no_role_asks_for_effort_yet() -> None:
    """**이 테스트는 값이 정해지는 날 빨개져야 한다.**

    그때 무엇을 측정하고 정했는지 로드맵 §경계 10 의 표에 행을 더한다.
    """
    overrides = settings.config.deep_analysis.model_effort
    asked = {
        role: value
        for role, value in overrides.model_dump().items()
        if value is not None
    }
    defaults = settings.config.model_routing.effort
    asked_defaults = {
        role: value
        for role, value in defaults.model_dump().items()
        if value is not None
    }

    assert asked == {}, f"DA 역할이 사고량을 요구한다: {asked} -- 경계 행을 더할 것"
    assert asked_defaults == {}, (
        f"역할 기본값이 사고량을 요구한다: {asked_defaults} -- 경계 행을 더할 것"
    )


def test_every_harness_role_can_be_asked() -> None:
    """네 역할 전부다. 하나가 빠지면 그 역할만 조용히 기본값으로 돈다."""
    from neos.workflow.deep_analysis.model_roles import (
        HARNESS_ROLES,
        resolve_harness_effort,
    )

    for name in HARNESS_ROLES:
        assert resolve_harness_effort(name).effort is None


def test_nothing_configured_means_nothing_sent() -> None:
    """K5 의 기본 상태 -- 요청은 예전과 바이트가 같다."""
    from neos.workflow.deep_analysis.model_roles import resolve_harness_effort

    resolution = resolve_harness_effort("dig")

    assert resolution.effort is None
    assert resolution.source is None
    assert resolution.refused == ""


def test_a_da_override_reaches_the_chain_as_a_feature_override(monkeypatch) -> None:
    """DA 의 역할별 값은 사슬의 **feature override** 칸이다.

    `deep_analysis.models.dig` 가 모델의 feature override 인 것과 같은 자리다.
    """
    from neos.workflow.deep_analysis import model_roles

    monkeypatch.setattr(
        settings.config.deep_analysis.model_effort, "dig", "high", raising=False
    )
    monkeypatch.setattr(
        model_roles, "_supported_levels", lambda model: ("low", "high")
    )

    resolution = model_roles.resolve_harness_effort("dig")

    assert resolution.effort == "high"
    assert resolution.source is ResolutionSource.FEATURE_OVERRIDE


def test_a_role_default_is_read_from_model_routing(monkeypatch) -> None:
    """역할 기본값은 `model_routing.effort` 에 있다 -- 모델 기본값 옆이다."""
    from neos.workflow.deep_analysis import model_roles

    monkeypatch.setattr(
        settings.config.model_routing.effort, "powerful", "medium", raising=False
    )
    monkeypatch.setattr(
        model_roles, "_supported_levels", lambda model: ("low", "medium")
    )

    # dig 는 powerful 역할이다 (HARNESS_ROLES).
    resolution = model_roles.resolve_harness_effort("dig")

    assert resolution.effort == "medium"
    assert resolution.source is ResolutionSource.ROLE_DEFAULT


def test_an_unsupported_level_is_refused_not_downgraded(monkeypatch) -> None:
    """모델이 받지 않는 레벨은 가장 가까운 레벨로 낮추지 않고 거절한다.

    카탈로그가 비어 있던 동안은 모든 역할이 `model_declares_no_effort` 였다.
    2026-09-24 에 실측 레벨이 채워졌으므로 일부만 받는 모델을 세워 둔다.
    """
    from neos.workflow.deep_analysis import model_roles

    monkeypatch.setattr(model_roles, "_supported_levels", lambda model: ("low", "high"))
    monkeypatch.setattr(
        settings.config.deep_analysis.model_effort, "judge", "max", raising=False
    )

    resolution = model_roles.resolve_harness_effort("judge")

    assert resolution.effort is None
    assert resolution.refused == "level_not_supported"


def test_a_model_that_declares_nothing_is_refused(monkeypatch) -> None:
    from neos.workflow.deep_analysis import model_roles

    monkeypatch.setattr(model_roles, "_supported_levels", lambda model: ())
    monkeypatch.setattr(
        settings.config.deep_analysis.model_effort, "judge", "max", raising=False
    )

    resolution = model_roles.resolve_harness_effort("judge")

    assert resolution.refused == "model_declares_no_effort"
