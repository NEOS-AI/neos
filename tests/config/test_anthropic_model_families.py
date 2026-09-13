"""CA12: Anthropic 세대 사실이 카탈로그 하나에서 나온다.

이 파일이 지키는 것은 값이 아니라 **소재지**다. 세대 접두사표·advisor
호환표·캐시 최소 길이는 `neos/providers/anthropic_features.py` 와
`anthropic_usage.py` 에 파이썬 리터럴로 있었다. 가격이 아니어서 카탈로그
config화(2026-07-27)의 병합 범위 밖이었고, 그래서 그 작업이 끝낸 드리프트가
**다른 이름으로 다시 시작됐다**. 지금은 `models.yaml` 이 답한다.
"""

import pytest

from neos.config.model_config import (
    DEFAULT_CACHE_MINIMUM_TOKENS,
    AnthropicFamily,
    ModelCatalog,
    advisor_targets,
    cache_minimum_tokens,
    canonical_model_family,
    model_config,
)
from neos.providers import anthropic_features, anthropic_usage

pytestmark = pytest.mark.no_db


def _anthropic_models() -> list[str]:
    return [
        name
        for name, spec in model_config.catalog.models.items()
        if spec.provider == "anthropic"
    ]


# 세대 사실이 **없는** Anthropic 카탈로그 모델. 비어 있어야 하는 목록이
# 아니라, 비어 있지 않다는 것을 보이게 만드는 목록이다 -- 표를 옮기면서
# 드러난 실제 상태이고, 값을 지어내는 것은 §4.3 의
# "확인 못 한 모델은 추측하지 않는다" 를 어기는 것이다.
#
# 🔴 `claude-opus-5` 가 여기 있는 것이 이 표의 존재 이유다. 하네스의
# `powerful` 워커(dig·synth)이고 피커의 `powerful` 티어인데, 코드에 있던
# 접두사표는 opus-4.5~4.8 만 알고 **5 세대를 배운 적이 없다.** 그래서
# advisor 를 켜면 `unknown_executor_model` 로 조용히 미주입되고, 캐시
# 하한은 확인되지 않은 기본값 1024 를 쓴다. 지금 잠들어 있어 무해하지만
# (`llm.advisor.enabled: false`), 이것이 정확히 CA12 가 추적하던 드리프트다.
_UNCOVERED = {
    "claude-opus-5",
    "claude-3-5-sonnet-20240620",
}

# 가족 항목은 있으나 **advisor 세대 이름이 없는** 모델. 공백이 아니라 의도다:
# 코드의 캐시 표에는 `claude-opus-4-5` 가 있었고 advisor 표에는 없었다. 두 표가
# 서로 다른 접두사 어휘를 쓰고 있었다는 사실 자체가 옮기면서 드러난 것이고,
# 하나로 합치면서 그 비대칭을 지우지 않고 표현했다.
_CACHE_ONLY = {"claude-opus-4-5-20251101"}


def test_every_anthropic_model_either_has_facts_or_is_a_recorded_gap():
    """새 Claude 모델을 등재하면 세대 사실도 정하게 만든다.

    양방향으로 고정한다 -- 새 공백도, 메워진 공백도 실패시킨다. 후자가
    실패하는 것은 의도다: 공백이 메워졌다면 이 목록이 낡은 것이고, 낡은
    목록은 §7 이 유령 백로그라 부른 것이다.
    """
    catalog = model_config.catalog
    uncovered = {
        name
        for name in _anthropic_models()
        if catalog._anthropic_family_for(name) is None
    }
    assert uncovered == _UNCOVERED


def test_cache_only_entries_are_named_rather_than_indistinguishable():
    """캐시 사실만 아는 세대와 아무것도 모르는 세대는 다른 상태다.

    둘 다 `canonical_model_family` 가 `None` 이라 그 함수만으로는 구별되지
    않는다 -- 구별을 아는 곳(카탈로그 항목의 유무)에서 물어야 한다.
    """
    catalog = model_config.catalog
    cache_only = {
        name
        for name in _anthropic_models()
        if catalog._anthropic_family_for(name) is not None
        and canonical_model_family(name) is None
    }
    assert cache_only == _CACHE_ONLY
    assert cache_minimum_tokens("claude-opus-4-5-20251101") == 4096


def test_a_model_without_family_facts_takes_the_documented_defaults():
    """공백은 조용한 오답이 아니라 **문서화된 기본값**이어야 한다."""
    assert canonical_model_family("claude-opus-5") is None
    assert cache_minimum_tokens("claude-opus-5") == DEFAULT_CACHE_MINIMUM_TOKENS
    assert advisor_targets("opus-5") == frozenset()


def test_dated_variants_inherit_their_generation():
    """접두사로 거는 이유. 카탈로그에 없는 날짜 변종도 같은 사실을 갖는다."""
    assert canonical_model_family("claude-opus-4-7-20260101") == "opus-4.7"
    assert cache_minimum_tokens("claude-opus-4-7-20260101") == 2048


def test_the_provider_modules_read_the_catalog_rather_than_their_own_table():
    """두 모듈이 카탈로그와 **같은 답**을 낸다.

    두 함수 이름은 그대로 남겼으므로(호출부 무변경) 이 단언이 없으면
    누군가 그 안에 표를 다시 심어도 아무것도 빨개지지 않는다.
    """
    for name in _anthropic_models():
        assert anthropic_features.canonical_model_family(
            name
        ) == canonical_model_family(name)
        assert anthropic_usage.cache_minimum_tokens(name) == cache_minimum_tokens(
            name
        )


def test_catalog_allows_a_prefix_nested_inside_another():
    """5.1 은 `claude-sonnet-5` 의 접두사 중첩이다. 가장 긴 접두사가 이긴다."""
    catalog = ModelCatalog.model_validate(
        {
            "anthropic_families": [
                {"prefix": "claude-sonnet-5", "family": "sonnet-5"},
                {"prefix": "claude-sonnet-5-1", "family": "sonnet-5.1"},
            ]
        }
    )

    assert catalog.canonical_model_family("claude-sonnet-5") == "sonnet-5"
    assert catalog.canonical_model_family("claude-sonnet-5-1") == "sonnet-5.1"
    assert (
        catalog.canonical_model_family("claude-sonnet-5-1-20260901") == "sonnet-5.1"
    )


def test_without_a_nested_prefix_the_parent_generation_matches():
    catalog = ModelCatalog.model_validate(
        {"anthropic_families": [{"prefix": "claude-sonnet-5", "family": "sonnet-5"}]}
    )

    assert catalog.canonical_model_family("claude-sonnet-5-1") == "sonnet-5"


def test_sonnet_4_5_does_not_match_sonnet_5():
    catalog = ModelCatalog.model_validate(
        {
            "anthropic_families": [
                {"prefix": "claude-sonnet-5", "family": "sonnet-5"},
                {"prefix": "claude-sonnet-4-5", "family": "sonnet-4.5"},
            ]
        }
    )

    assert catalog.canonical_model_family("claude-sonnet-4-5-20250929") == "sonnet-4.5"
    assert catalog.canonical_model_family("claude-sonnet-5") == "sonnet-5"


def test_catalog_still_rejects_duplicate_prefixes():
    with pytest.raises(ValueError, match="duplicate"):
        ModelCatalog.model_validate(
            {
                "anthropic_families": [
                    {"prefix": "claude-sonnet-5", "family": "sonnet-5"},
                    {"prefix": "claude-sonnet-5", "family": "sonnet-5-dup"},
                ]
            }
        )


def test_catalog_rejects_an_advisor_target_no_family_declares():
    """오타 하나가 advisor 를 조용히 미주입으로 되돌리는 것을 막는다."""
    with pytest.raises(ValueError, match="advisor targets"):
        ModelCatalog.model_validate(
            {
                "anthropic_families": [
                    {
                        "prefix": "claude-sonnet-5",
                        "family": "sonnet-5",
                        "advisor_targets": ["opus-4-8"],  # 점이 아니라 하이픈
                    }
                ]
            }
        )


def test_longest_prefix_wins_so_declaration_order_cannot_change_the_answer():
    """중첩을 허용해도 승자는 선언 순서가 아니라 접두사 길이다."""
    catalog = ModelCatalog(
        anthropic_families=[
            AnthropicFamily(prefix="claude-sonnet-5", family="sonnet-5"),
            AnthropicFamily(prefix="claude-sonnet-5-1", family="sonnet-5.1"),
            AnthropicFamily(prefix="claude-sonnet-4-5", family="sonnet-4.5"),
        ]
    )
    reversed_catalog = ModelCatalog(
        anthropic_families=list(reversed(catalog.anthropic_families))
    )
    for cat in (catalog, reversed_catalog):
        assert cat.canonical_model_family("claude-sonnet-5") == "sonnet-5"
        assert cat.canonical_model_family("claude-sonnet-5-1") == "sonnet-5.1"
        assert (
            cat.canonical_model_family("claude-sonnet-4-5-20250929")
            == "sonnet-4.5"
        )
