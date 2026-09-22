"""설정 -> 실제 클라이언트. 조립은 한 곳에서만 한다.

루프는 설정을 읽지 않는다(`JevToolRiskGate` 가 `None` 이면 off). 그래서
"켜졌는가"를 판단하는 자리는 이 팩토리 하나다 -- 판단하는 자리가 둘이 되면
"켜졌다고 믿는 자리"와 "실제로 켜진 자리"가 갈라진다.
"""

from __future__ import annotations

import pytest

from neos.config.schema import JevConfig
from neos.jev.assembly import MisconfiguredJev, build_tool_risk_gate

pytestmark = pytest.mark.no_db


def config(**overrides) -> JevConfig:
    base = {
        "enabled": True,
        "tool_risk_shadow_enabled": True,
        "model": "jev-1.13.0",
        "low_below": 0.3,
        "high_at_or_above": 0.7,
    }
    base.update(overrides)
    return JevConfig(**base)


def test_a_disabled_config_builds_nothing() -> None:
    """`None` 이 off 다. 꺼진 게이트 객체를 만들어 들고 다니지 않는다."""
    assert build_tool_risk_gate(JevConfig(), api_key="k") is None


def test_enabled_but_no_banding_builds_nothing() -> None:
    """`jev.enabled` 만으로는 도구 위험 밴딩이 켜지지 않는다 -- L5 도 있다."""
    built = build_tool_risk_gate(
        JevConfig(enabled=True, judge_shadow_enabled=True), api_key="k"
    )
    assert built is None


def test_shadow_builds_a_non_enforcing_gate() -> None:
    gate = build_tool_risk_gate(config(), api_key="k")
    assert gate is not None
    assert gate.enforce is False
    assert gate.thresholds.low_below == 0.3


def test_the_gate_flag_makes_it_enforce() -> None:
    gate = build_tool_risk_gate(
        config(tool_risk_gate_enabled=True), api_key="k"
    )
    assert gate is not None
    assert gate.enforce is True


def test_a_missing_key_fails_loudly() -> None:
    """빈 자격증명을 "통과"로 읽으면 게이트가 조용히 사라진다.

    D-L1 의 폴백은 **런타임에 Jev 가 대답하지 않을 때**의 이야기다. 키를 넣지
    않은 것은 오설정이고, 오설정이 조용히 "게이트 off" 가 되면 안 된다.
    """
    with pytest.raises(MisconfiguredJev, match="TYPESAFE_API_KEY"):
        build_tool_risk_gate(config(), api_key="")


def test_an_unpinned_model_is_refused_at_assembly() -> None:
    """모델을 안 적으면 SDK 기본값(`jev-latest`)으로 돈다 -- 별칭이다."""
    with pytest.raises(MisconfiguredJev, match="jev.model"):
        build_tool_risk_gate(config(model=None), api_key="k")


def test_the_built_scorer_carries_the_rubric_digest() -> None:
    from neos.jev.rubric import load_rubric

    gate = build_tool_risk_gate(config(), api_key="k")
    assert gate is not None
    assert gate.scorer._rubric.digest == load_rubric("tool_risk").digest
