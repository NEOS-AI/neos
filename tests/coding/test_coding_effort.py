"""코딩 루프의 사고량 (로드맵 K5 ④ -- 코딩 절반).

DA 절반(2026-09-24)과 같은 모양이다: 해석은 `resolve_effort` 사슬 한 곳,
결과는 `ModelLimits.effort` 로 요청에 실린다. 코딩에는 셋이 있다 -- durable
루프의 턴, 컴팩션 요약, 자식. 하나라도 빠지면 그 호출만 조용히 기본
사고량으로 돈다.

## 값은 아무것도 정하지 않는다

`coding_model.effort` 의 기본값은 None 이고, 배포 설정의 `model_routing.effort`
도 비어 있다. 그래서 이 커밋은 요청 바이트를 움직이지 않는다 -- **경계가
아니다.** 값을 정하는 날이 코딩 에이전트 지표의 경계다(§경계 10).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import neos.utils.anthropic_client as anthropic_client_module
from neos.coding import runtime as runtime_module
from neos.config.coding_selection import CodingModelSelection, resolve_coding_effort
from neos.config.model_config import effort_levels_for, model_config
from neos.config.schema import AppConfig, CodingModelConfig, ModelRoutingConfig
from neos.config.settings import settings

pytestmark = pytest.mark.no_db

_MODEL = model_config.catalog.role_aliases["sonnet-5"].current


def _selection(model: str = _MODEL) -> CodingModelSelection:
    return CodingModelSelection(provider="anthropic", model=model, source="catalog")


def _routing(**effort) -> ModelRoutingConfig:
    return ModelRoutingConfig.model_validate({"effort": effort})


def test_the_deployed_coding_loop_asks_for_no_effort_yet() -> None:
    """**이 테스트는 값이 정해지는 날 빨개져야 한다.** 그때 §경계 10 에 행을 더한다."""
    config = settings.config
    selection = runtime_module.resolve_coding_selection_from_app(config)

    resolution = resolve_coding_effort(
        coding=config.coding_model, routing=config.model_routing, selection=selection
    )

    assert config.coding_model.effort is None
    assert resolution.effort is None
    assert resolution.refused == ""


def test_the_coding_override_is_the_feature_override_slot() -> None:
    """Beats the per-model default, as `deep_analysis.model_effort` does."""
    levels = effort_levels_for(_MODEL)
    assert len(levels) >= 2
    resolution = resolve_coding_effort(
        coding=CodingModelConfig(effort=levels[0]),
        routing=_routing(models={_MODEL: levels[1]}),
        selection=_selection(),
    )

    assert resolution.effort == levels[0]
    assert resolution.source == "feature_override"


def test_the_per_model_default_reaches_coding_too() -> None:
    """The operator's `claude-...: high` is one default per model -- chat, DA
    and now coding. Mutation: drop `model_default=` -> None here."""
    level = effort_levels_for(_MODEL)[-1]
    resolution = resolve_coding_effort(
        coding=CodingModelConfig(),
        routing=_routing(models={_MODEL: level}),
        selection=_selection(),
    )

    assert resolution.effort == level
    assert resolution.source == "model_default"


def test_a_level_the_model_does_not_take_is_refused_not_lowered() -> None:
    resolution = resolve_coding_effort(
        coding=CodingModelConfig(effort="max"),
        routing=_routing(),
        selection=_selection("claude-manual-not-in-catalog"),
    )

    assert resolution.effort is None
    assert resolution.refused == "model_declares_no_effort"


# ---- 세 호출 자리 --------------------------------------------------------------


def _loop_config(**kwargs):
    from neos.coding.loop.anthropic import AnthropicLoopConfig

    return AnthropicLoopConfig(model="claude-test", system="code", **kwargs)


def test_a_loop_turn_carries_the_effort() -> None:
    """Mutation: drop `effort=` from `_model_limits` -> ''."""
    from tests.coding.loop.support import harness

    h = harness([], config=_loop_config(effort="high"))

    limits = h.loop._model_limits(SimpleNamespace(output_token_escalations=0))

    assert limits.effort == "high"


def test_no_effort_means_the_turn_sends_none() -> None:
    from tests.coding.loop.support import harness

    h = harness([], config=_loop_config())

    assert h.loop._model_limits(SimpleNamespace(output_token_escalations=0)).effort == ""


@pytest.mark.parametrize(("preserving", "expected"), [(True, "high"), (False, "")])
def test_compaction_carries_it_only_on_the_preserving_summary(preserving, expected) -> None:
    """The legacy summary is capped at 512 tokens; raising the effort inside
    that cap would spend the summary on thinking. Mutation: drop `effort=`
    from the preserving branch, or add it to the legacy one."""
    from tests.coding.loop.support import harness

    h = harness(
        [],
        config=_loop_config(effort="high", compaction_preserving_summary=preserving),
    )

    request, _ = h.loop._compaction_request("summarize")

    assert request.limits.effort == expected


def test_a_child_gets_the_effort_only_on_the_model_it_was_resolved_for() -> None:
    """A level valid for the parent's model can be a 400 on another one.
    Mutation: drop the model check -> the aliased child gets 'high'."""
    from neos.subagent.stepper import ChildStepper

    stepper = ChildStepper(
        model=object(), tools=object(), effort="high", effort_model="claude-a"
    )

    assert stepper._effort_for("claude-a") == "high"
    assert stepper._effort_for("claude-b") == ""
    assert ChildStepper(model=object(), tools=object())._effort_for("claude-a") == ""


# ---- 런타임 경계 --------------------------------------------------------------


def test_the_runtime_resolves_it_once_and_hands_it_to_loop_and_children(
    monkeypatch,
) -> None:
    """Mutation: drop `effort=` from the loop config or from
    `_build_subagent_runtime` -> one of the two goes empty."""
    level = effort_levels_for(_MODEL)[0]
    config = AppConfig.model_validate(
        {
            "coding_model": {
                "enabled": True,
                "effort": level,
                "input_cost_micros_per_million": 1,
                "output_cost_micros_per_million": 1,
            },
            "sandbox": {"enabled": True},
            "secrets": {"anthropic_api_key": "test"},
        }
    )
    monkeypatch.setattr(
        anthropic_client_module, "AsyncAnthropic", lambda **kwargs: object()
    )

    loop = runtime_module._prepare_real_coding_loop(config=config)(object())
    stepper = loop._subagents._stepper

    assert loop._config.model == _MODEL
    assert loop._config.effort == level
    assert (stepper._effort, stepper._effort_model) == (level, _MODEL)


def test_a_refused_level_is_logged_not_dropped_silently(monkeypatch, caplog) -> None:
    config = AppConfig.model_validate(
        {
            "coding_model": {
                "enabled": True,
                "model": "claude-manual",
                "effort": "max",
                "input_cost_micros_per_million": 1,
                "output_cost_micros_per_million": 1,
            },
            "sandbox": {"enabled": True},
            "secrets": {"anthropic_api_key": "test"},
        }
    )
    monkeypatch.setattr(
        anthropic_client_module, "AsyncAnthropic", lambda **kwargs: object()
    )

    with caplog.at_level("WARNING"):
        loop = runtime_module._prepare_real_coding_loop(config=config)(object())

    assert loop._config.effort == ""
    assert "model_declares_no_effort" in caplog.text
