from types import SimpleNamespace

from neos.config.schema import AdvisorConfig, PromptCachingConfig
from neos.providers.anthropic_features import (
    ADVISOR_BETA,
    build_cache_control,
    build_tool_policy,
    serialize_content_block,
)


def test_build_cache_control_respects_enabled_and_ttl():
    assert build_cache_control(PromptCachingConfig()) == {
        "type": "ephemeral",
        "ttl": "5m",
    }
    assert build_cache_control(PromptCachingConfig(enabled=False)) is None
    assert build_cache_control(PromptCachingConfig(ttl="1h"))["ttl"] == "1h"


def test_tool_policy_copies_tools_and_marks_last_stable_tool():
    original = [{"name": "search_tools", "input_schema": {"type": "object"}}]

    policy = build_tool_policy(
        original,
        executor_model="claude-sonnet-4-6",
        prompt_caching=PromptCachingConfig(),
        advisor=AdvisorConfig(enabled=False),
    )

    assert original[0].get("cache_control") is None
    assert policy.tools[0]["cache_control"] == {"type": "ephemeral", "ttl": "5m"}
    assert policy.use_beta is False
    assert policy.advisor.injected is False


def test_tool_policy_injects_advisor_only_for_compatible_pair():
    policy = build_tool_policy(
        [{"name": "search_tools", "input_schema": {"type": "object"}}],
        executor_model="claude-sonnet-4-6",
        prompt_caching=PromptCachingConfig(),
        advisor=AdvisorConfig(enabled=True, model="claude-opus-4-8"),
    )

    assert policy.use_beta is True
    assert policy.betas == [ADVISOR_BETA]
    assert policy.tools[-1]["type"] == "advisor_20260301"
    assert policy.tools[-1]["name"] == "advisor"
    assert policy.tools[-1]["max_tokens"] == 2048
    assert policy.tools[-1]["cache_control"]["type"] == "ephemeral"
    assert policy.advisor.injected is True


def test_tool_policy_skips_unknown_or_incompatible_executor():
    unknown = build_tool_policy(
        [],
        executor_model="claude-future-99",
        prompt_caching=PromptCachingConfig(),
        advisor=AdvisorConfig(enabled=True),
    )
    incompatible = build_tool_policy(
        [],
        executor_model="claude-sonnet-4-5-20250929",
        prompt_caching=PromptCachingConfig(),
        advisor=AdvisorConfig(enabled=True),
    )

    assert unknown.advisor.skip_reason == "unknown_executor_model"
    assert incompatible.advisor.skip_reason == "incompatible_model_pair"
    assert unknown.use_beta is False
    assert incompatible.use_beta is False


def test_serialize_content_block_preserves_beta_fields():
    block = SimpleNamespace(
        model_dump=lambda **_: {
            "type": "advisor_tool_result",
            "tool_use_id": "srv_1",
            "content": {"type": "advisor_result", "text": "internal guidance"},
        }
    )

    assert serialize_content_block(block)["content"]["text"] == "internal guidance"
