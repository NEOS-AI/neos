"""모델 사고량(effort) 축 — 카탈로그 쪽 (로드맵 K5 / 스펙 R-05).

## DA 의 `Effort` 와 다른 축이다

`neos.workflow.deep_analysis.models.Effort`(scout·dig·synth·split)는 **조사
깊이**다. 여기 있는 effort 는 **모델의 사고량**이고, Anthropic 의
`output_config.effort` 로 나간다. 이름이 같아 섞이기 쉬우므로 둘이 만나는
곳이 없도록 어휘를 분리해 둔다.

## 레벨 이름은 지어내지 않았다

설치된 SDK 에서 읽은 사실이다 -- `anthropic.types.output_config_param.
OutputConfigParam.effort` 가 `Literal["low","medium","high","xhigh","max"]`
다. 카탈로그가 그 다섯을 그대로 쓴다.

## 어느 모델이 무엇을 받는지는 **재서** 적는다

그것은 `ModelCapabilities.effort`(models API)가 말한다. 2026-09-24 에 키로
실측해 채웠다 (`scripts/probe_anthropic_effort.py`, 아래 `ANTHROPIC_PROBED`).
OpenAI 는 공식 models 문서가 근거다. 재지 않은 모델은 여전히 "모른다" 이고,
모르면 아무것도 보내지 않는다.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.no_db

#: SDK 가 정한 다섯. 이 목록의 출처는 사람이 아니다.
SDK_EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")


def test_the_levels_come_from_the_installed_sdk() -> None:
    """목록을 손으로 적어 두면 SDK 가 늘어날 때 조용히 낡는다.

    `id_forms` 주석의 "날짜 접미사를 지어내지 않는다" 와 같은 규율이다 --
    프로바이더가 정한 어휘는 프로바이더에게 묻는다.
    """
    from typing import get_args, get_type_hints

    from anthropic.types.output_config_param import OutputConfigParam

    from neos.config.model_config import EFFORT_LEVELS

    # `__annotations__` 를 그대로 읽지 않는다 -- 그 모듈은
    # `from __future__ import annotations` 를 쓰므로 값이 **문자열**이고,
    # `get_args` 는 문자열에서 아무것도 못 꺼내 이 테스트가 조용히 통과한다.
    annotation = get_type_hints(OutputConfigParam)["effort"]
    # Optional[Literal[...]] 에서 Literal 을 꺼낸다.
    literal = next(arg for arg in get_args(annotation) if get_args(arg))
    levels = set(get_args(literal))

    # 대조 테스트가 덜 검사할 수 있다 -- 비면 아래 두 단언이 공허하다.
    assert len(levels) >= 5
    from neos.config.model_config import EFFORT_VOCABULARY

    assert set(EFFORT_VOCABULARY["anthropic"]) == levels
    assert set(EFFORT_LEVELS) == set(SDK_EFFORT_LEVELS)


def test_openai_levels_come_from_the_installed_sdk() -> None:
    from typing import get_args

    from openai.types.shared.reasoning_effort import ReasoningEffort

    from neos.config.model_config import EFFORT_VOCABULARY

    # ReasoningEffort = Optional[Literal[...]]
    literal = next(arg for arg in get_args(ReasoningEffort) if get_args(arg))
    levels = set(get_args(literal))
    assert len(levels) >= 7
    assert set(EFFORT_VOCABULARY["openai"]) == levels


def test_the_union_is_ordered_low_to_high() -> None:
    from neos.config.model_config import ALL_EFFORT_LEVELS, EFFORT_VOCABULARY

    assert ALL_EFFORT_LEVELS == (
        "none", "minimal", "low", "medium", "high", "xhigh", "max",
    )
    for vocab in EFFORT_VOCABULARY.values():
        assert set(vocab) <= set(ALL_EFFORT_LEVELS)


def test_an_openai_level_is_refused_on_an_anthropic_model() -> None:
    from neos.config.model_config import ModelSpec

    with pytest.raises(ValueError, match="effort"):
        ModelSpec(provider="anthropic", effort_levels=["none"])


def test_an_openai_model_takes_openai_levels() -> None:
    from neos.config.model_config import ModelSpec

    spec = ModelSpec(provider="openai", effort_levels=["high", "none", "low"])
    assert spec.effort_levels == ["none", "low", "high"]


def test_a_provider_without_a_vocabulary_takes_no_levels() -> None:
    from neos.config.model_config import ModelSpec

    with pytest.raises(ValueError, match="effort"):
        ModelSpec(provider="gemini", effort_levels=["low"])


#: 2026-09-24 `scripts/probe_anthropic_effort.py` 실호출 출력 (models API
#: `capabilities.effort`). 바꾸려면 다시 재고 출력을 여기에 붙인다.
#: claude-haiku-4-5-20251001 · claude-sonnet-4-5-20250929 는 `[]` 이었다 -- 적지 않는다.
ANTHROPIC_PROBED: dict[str, list[str]] = {
    "claude-sonnet-5": ["low", "medium", "high", "xhigh", "max"],
    "claude-opus-5-5": ["low", "medium", "high", "xhigh", "max"],
    "claude-fable-5-1": ["low", "medium", "high", "xhigh", "max"],
    "claude-opus-4-8": ["low", "medium", "high", "xhigh", "max"],
}

#: OpenAI 공식 models 문서 (developers.openai.com/api/docs/models, 2026-09-24):
#: "Supports none, low, medium, high, xhigh, and max levels"
OPENAI_DOCUMENTED: dict[str, list[str]] = {
    "gpt-6-sol": ["none", "low", "medium", "high", "xhigh", "max"],
    "gpt-6-luna": ["none", "low", "medium", "high", "xhigh", "max"],
}


def test_catalog_effort_levels_are_exactly_what_was_measured() -> None:
    """채운 값은 전부 근거가 있다 -- 이 표 밖의 선언은 추측이다."""
    from neos.config.model_config import model_config

    claimed = {
        name: spec.effort_levels
        for name, spec in model_config.catalog.models.items()
        if spec.effort_levels
    }
    assert claimed == {**ANTHROPIC_PROBED, **OPENAI_DOCUMENTED}


def test_an_unknown_model_supports_nothing() -> None:
    """`supports_vision` 과 같은 규율: 모르면 False 다.

    모른다는 뜻이지 못 한다는 뜻이 아니지만, 능력 게이트에서 안전한 쪽은
    보내지 않는 쪽이다 -- 틀린 effort 는 400 이다.
    """
    from neos.config.model_config import effort_levels_for, supports_effort

    assert supports_effort("존재하지-않는-모델") is False
    assert effort_levels_for("존재하지-않는-모델") == ()


def test_a_declared_model_reports_exactly_what_it_declared(monkeypatch) -> None:
    from neos.config.model_config import (
        effort_levels_for,
        model_config,
        supports_effort,
    )

    name = next(iter(model_config.catalog.models))
    spec = model_config.catalog.models[name]
    monkeypatch.setattr(spec, "effort_levels", ["low", "high"])

    assert supports_effort(name) is True
    assert effort_levels_for(name) == ("low", "high")


def test_a_level_outside_the_sdk_vocabulary_is_refused() -> None:
    """오타가 배포까지 가면 매 요청이 400 이다. 설정 검증에서 멈춘다."""
    from neos.config.model_config import ModelSpec

    with pytest.raises(ValueError, match="effort"):
        ModelSpec(provider="anthropic", effort_levels=["medium-ish"])


def test_the_declaration_keeps_the_sdk_order(monkeypatch) -> None:
    """레벨은 **순서가 있는 축**이다 (low < medium < high < xhigh < max).

    선언 순서를 그대로 두면 "이 모델의 가장 낮은 레벨" 같은 질문에 답할 때
    목록 순서와 사고량 순서가 어긋난다.
    """
    from neos.config.model_config import ModelSpec, effort_levels_for, model_config

    name = next(iter(model_config.catalog.models))
    monkeypatch.setitem(
        model_config.catalog.models,
        name,
        ModelSpec(provider="anthropic", effort_levels=["max", "low", "high"]),
    )

    assert effort_levels_for(name) == ("low", "high", "max")
