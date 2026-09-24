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

## 그러나 **어느 모델이 무엇을 받는지는 모른다**

그것은 `ModelCapabilities.effort`(SDK 에 있다)가 말하는 것이고, 읽으려면
models API 를 불러야 한다 -- 키가 필요하다(K1b·K4b 와 같은 관문). 그래서
카탈로그의 기본값은 **"모른다"** 이고, 모르면 아무것도 보내지 않는다.
추측한 레벨을 보내면 미지원 모델에서 400 이고, 지원하더라도 우리가 재 본 적
없는 사고량으로 도는 것이다.
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


def test_no_catalog_model_claims_effort_support_yet() -> None:
    """**이것이 K5 의 정직한 출발점이다.**

    지원 여부는 models API 가 말하고 그것은 키를 요구한다. 지금 채워 넣으면
    재 본 적 없는 사고량을 사실로 적는 것이다 -- 이 저장소가 "확인 못 한
    모델은 추측 말고 은퇴시킨다" 로 정한 바로 그 자리.

    이 테스트는 값이 채워지는 날 **빨개져야 한다.** 그때 이 파일을 열고,
    무엇을 근거로 채웠는지 여기 적는다.
    """
    from neos.config.model_config import model_config

    claimed = {
        name: spec.effort_levels
        for name, spec in model_config.catalog.models.items()
        if spec.effort_levels
    }

    assert claimed == {}, (
        f"effort 지원을 선언한 모델이 생겼다: {sorted(claimed)} -- "
        "근거(models API 응답)를 이 테스트 옆에 적고 단언을 고칠 것."
    )


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
