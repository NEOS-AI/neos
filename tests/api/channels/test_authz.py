"""Channel admission gate — Phase 0.

These tests define the contract adapters must use before calling
ChannelGateway.dispatch(). A missing feature must fail here first.
"""

from __future__ import annotations

import pytest

from neos.config.schema import ChannelConfig, DiscordChannelConfig, SlackChannelConfig
from neos.api.channels.authz import (
    ChannelGatePolicy,
    DropReason,
    GateContext,
    evaluate_channel_gate,
    resolve_channel_policy,
    slack_text_mentions_bot,
    telegram_text_mentions_bot,
)

pytestmark = pytest.mark.no_db


def _ctx(**overrides: object) -> GateContext:
    payload: dict[str, object] = {
        "channel_type": "slack",
        "platform_user_id": "U_alice",
        "channel_id": "C_general",
        "text": "hello <@U_BOT>",
        "is_dm": False,
        "is_bot": False,
        "is_self": False,
        "mentioned": True,
    }
    payload.update(overrides)
    return GateContext(**payload)  # type: ignore[arg-type]


def _policy(**overrides: object) -> ChannelGatePolicy:
    payload: dict[str, object] = {
        "require_mention": True,
        "allowed_users": frozenset({"U_alice"}),
        "allowed_channels": frozenset(),
        "ignored_channels": frozenset(),
    }
    payload.update(overrides)
    return ChannelGatePolicy(**payload)  # type: ignore[arg-type]


def test_bot_message_is_dropped_before_other_rules() -> None:
    decision = evaluate_channel_gate(
        _ctx(is_bot=True, mentioned=True, platform_user_id="U_alice"),
        _policy(allowed_users=frozenset()),
    )
    assert decision.allowed is False
    assert decision.reason is DropReason.SELF_OR_BOT


def test_self_message_is_dropped() -> None:
    decision = evaluate_channel_gate(_ctx(is_self=True), _policy())
    assert decision.allowed is False
    assert decision.reason is DropReason.SELF_OR_BOT


def test_empty_text_is_dropped() -> None:
    decision = evaluate_channel_gate(_ctx(text="   ", mentioned=True), _policy())
    assert decision.allowed is False
    assert decision.reason is DropReason.EMPTY_TEXT


def test_empty_text_with_attachment_is_not_dropped() -> None:
    decision = evaluate_channel_gate(
        _ctx(text="   ", mentioned=True, has_attachment=True),
        _policy(),
    )
    assert decision.allowed is True
    assert decision.reason is None


def test_ignored_channel_is_dropped_even_when_mentioned() -> None:
    decision = evaluate_channel_gate(
        _ctx(channel_id="C_noise", mentioned=True),
        _policy(ignored_channels=frozenset({"C_noise"})),
    )
    assert decision.allowed is False
    assert decision.reason is DropReason.IGNORED_CHANNEL


def test_allowed_channels_whitelist_drops_other_rooms() -> None:
    decision = evaluate_channel_gate(
        _ctx(channel_id="C_other", mentioned=True),
        _policy(allowed_channels=frozenset({"C_general"})),
    )
    assert decision.allowed is False
    assert decision.reason is DropReason.CHANNEL_NOT_ALLOWED


def test_allowed_channels_empty_means_any_room() -> None:
    decision = evaluate_channel_gate(
        _ctx(channel_id="C_random", mentioned=True),
        _policy(allowed_channels=frozenset()),
    )
    assert decision.allowed is True
    assert decision.reason is None


def test_channel_message_without_mention_is_dropped() -> None:
    decision = evaluate_channel_gate(_ctx(mentioned=False, is_dm=False), _policy())
    assert decision.allowed is False
    assert decision.reason is DropReason.MENTION_REQUIRED


def test_dm_skips_mention_requirement() -> None:
    decision = evaluate_channel_gate(
        _ctx(mentioned=False, is_dm=True, text="hello"),
        _policy(require_mention=True),
    )
    assert decision.allowed is True


def test_bound_session_skips_mention_requirement() -> None:
    decision = evaluate_channel_gate(
        _ctx(mentioned=False, is_dm=False, text="hello", bound_session=True),
        _policy(require_mention=True),
    )
    assert decision.allowed is True
    assert decision.reason is None


def test_bound_session_still_requires_allowlist() -> None:
    decision = evaluate_channel_gate(
        _ctx(
            mentioned=False,
            bound_session=True,
            platform_user_id="U_eve",
            text="hello",
        ),
        _policy(require_mention=True, allowed_users=frozenset({"U_alice"})),
    )
    assert decision.allowed is False
    assert decision.reason is DropReason.USER_NOT_ALLOWED


def test_bound_session_still_drops_ignored_channel() -> None:
    decision = evaluate_channel_gate(
        _ctx(
            mentioned=False,
            bound_session=True,
            channel_id="C_noise",
            text="hello",
        ),
        _policy(require_mention=True, ignored_channels=frozenset({"C_noise"})),
    )
    assert decision.allowed is False
    assert decision.reason is DropReason.IGNORED_CHANNEL


def test_unbound_session_still_requires_mention() -> None:
    decision = evaluate_channel_gate(
        _ctx(mentioned=False, is_dm=False, text="hello", bound_session=False),
        _policy(require_mention=True),
    )
    assert decision.allowed is False
    assert decision.reason is DropReason.MENTION_REQUIRED


def test_mention_not_required_when_disabled() -> None:
    decision = evaluate_channel_gate(
        _ctx(mentioned=False, is_dm=False, text="hello"),
        _policy(require_mention=False),
    )
    assert decision.allowed is True


def test_empty_allowlist_is_fail_closed() -> None:
    decision = evaluate_channel_gate(
        _ctx(mentioned=True),
        _policy(allowed_users=frozenset()),
    )
    assert decision.allowed is False
    assert decision.reason is DropReason.USER_NOT_ALLOWED


def test_user_outside_allowlist_is_silent() -> None:
    decision = evaluate_channel_gate(
        _ctx(platform_user_id="U_eve", mentioned=True),
        _policy(allowed_users=frozenset({"U_alice"})),
    )
    assert decision.allowed is False
    assert decision.reason is DropReason.USER_NOT_ALLOWED


def test_allowlisted_mentioned_user_is_admitted() -> None:
    decision = evaluate_channel_gate(_ctx(), _policy())
    assert decision.allowed is True
    assert decision.reason is None


def test_resolve_policy_uses_platform_lists_over_global() -> None:
    channels = ChannelConfig(
        allowed_users=["U_global"],
        require_mention=True,
        slack=SlackChannelConfig(
            enabled=True,
            allowed_users=["U_slack"],
            require_mention=False,
            ignored_channels=["C_noise"],
        ),
    )
    policy = resolve_channel_policy("slack", channels)
    assert policy.allowed_users == frozenset({"U_slack"})
    assert policy.require_mention is False
    assert "C_noise" in policy.ignored_channels


def test_resolve_policy_falls_back_to_global_when_platform_list_empty() -> None:
    channels = ChannelConfig(
        allowed_users=["U_global"],
        ignored_channels=["C_global"],
        discord=DiscordChannelConfig(enabled=True),
    )
    policy = resolve_channel_policy("discord", channels)
    assert policy.allowed_users == frozenset({"U_global"})
    assert policy.require_mention is True
    assert "C_global" in policy.ignored_channels


def test_slack_mention_token_detects_bot_user() -> None:
    assert slack_text_mentions_bot("hey <@U0BOT> please look", "U0BOT") is True
    assert slack_text_mentions_bot("hey <@U0BOT|neos> please look", "U0BOT") is True
    assert slack_text_mentions_bot("hey <@U_OTHER>", "U0BOT") is False
    assert slack_text_mentions_bot("", "U0BOT") is False
    assert slack_text_mentions_bot("<@U0BOT>", "") is False


def test_inbound_media_and_draft_streaming_default_off() -> None:
    channels = ChannelConfig()
    assert channels.inbound_media is False
    assert channels.draft_streaming is False
    assert channels.coding_invoke is False


def test_legacy_settings_expose_gate_fields() -> None:
    from neos.config.schema import AppConfig
    from neos.config.settings import Settings

    settings = Settings(config=AppConfig())
    assert settings.CHANNEL_REQUIRE_MENTION is True
    assert settings.CHANNEL_ALLOWED_USERS == []
    assert settings.CHANNEL_ALLOWED_CHANNELS == []
    assert settings.CHANNEL_IGNORED_CHANNELS == []


def test_telegram_at_mention_is_case_insensitive() -> None:
    assert telegram_text_mentions_bot("hi @NeosBot", "neosbot") is True
    assert telegram_text_mentions_bot("hi @neosbot please", "NeosBot") is True
    assert telegram_text_mentions_bot("email me@neosbot.com", "neosbot") is False
    assert telegram_text_mentions_bot("hi @otherbot", "neosbot") is False
