"""트랙 L 설정 -- 로드맵 §12.4 · §9(매직넘버 금지) · §12.5.

핵심은 **임계값에 기본값이 없다**는 것이다. 쿡북의 `0.30/0.70` 을 기본값으로
한 번 적어 두면 아무도 그것이 실측인지 인용인지 다시 묻지 않는다. 그래서
임계값 없이 켜려고 하면 **기동이 실패한다** -- 조용히 도는 것보다 낫다.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from neos.config.loader import SECRET_ENV_KEYS
from neos.config.schema import JevConfig

pytestmark = pytest.mark.no_db


def test_every_jev_flag_is_off_by_default() -> None:
    """§12.5 "전부 플래그 off 로 착지한다"."""
    config = JevConfig()
    assert config.enabled is False
    assert config.tool_risk_shadow_enabled is False
    assert config.tool_risk_gate_enabled is False
    assert config.judge_shadow_enabled is False


def test_thresholds_have_no_default() -> None:
    config = JevConfig()
    assert config.low_below is None
    assert config.high_at_or_above is None


def test_shadow_without_thresholds_is_refused() -> None:
    """섀도도 밴드를 계산한다 -- 임계값 없이는 기록할 밴드가 없다."""
    with pytest.raises(ValidationError, match="low_below"):
        JevConfig(enabled=True, tool_risk_shadow_enabled=True)


def test_the_gate_without_thresholds_is_refused() -> None:
    with pytest.raises(ValidationError, match="low_below"):
        JevConfig(enabled=True, tool_risk_gate_enabled=True, high_at_or_above=0.7)


def test_inverted_thresholds_are_refused() -> None:
    with pytest.raises(ValidationError, match="high_at_or_above"):
        JevConfig(
            enabled=True,
            tool_risk_shadow_enabled=True,
            low_below=0.8,
            high_at_or_above=0.2,
        )


def test_the_gate_cannot_be_on_while_jev_is_off() -> None:
    """켤 수 없는 플래그가 켜져 있으면 **읽는 사람이 틀린다**."""
    with pytest.raises(ValidationError, match="jev.enabled"):
        JevConfig(
            enabled=False,
            tool_risk_gate_enabled=True,
            low_below=0.3,
            high_at_or_above=0.7,
        )


def test_the_model_is_pinned_not_an_alias() -> None:
    """`jev-latest` 를 프로덕션 경로에 쓰지 않는다(§12.5 L0).

    SDK 기본값이 `jev-latest` 이므로, 아무것도 적지 않으면 별칭이 실린다.
    별칭으로 돈 런은 어떤 모델이 답했는지 모른다 = 표본이 아니다.
    """
    with pytest.raises(ValidationError, match="latest"):
        JevConfig(model="jev-latest")


def test_the_typesafe_key_is_a_known_secret() -> None:
    """템플릿과 허용목록은 짝이다 -- 한쪽만 고치면 기동 검사가 문다."""
    assert "TYPESAFE_API_KEY" in SECRET_ENV_KEYS
