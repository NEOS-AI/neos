"""Channel admission gate (Phase 0).

Adapters MUST call `evaluate_channel_gate` before `ChannelGateway.dispatch`.
A dropped message is silent — no workflow, no error reply.

Order: self/bot → empty text → ignored channel → allowed-channel
whitelist → mention (DMs exempt) → user allowlist (empty = fail-closed).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from neos.config.schema import ChannelConfig


class DropReason(StrEnum):
    SELF_OR_BOT = "self_or_bot"
    EMPTY_TEXT = "empty_text"
    IGNORED_CHANNEL = "ignored_channel"
    CHANNEL_NOT_ALLOWED = "channel_not_allowed"
    MENTION_REQUIRED = "mention_required"
    USER_NOT_ALLOWED = "user_not_allowed"


@dataclass(frozen=True, slots=True)
class GateContext:
    channel_type: str
    platform_user_id: str
    channel_id: str
    text: str
    is_dm: bool = False
    is_bot: bool = False
    is_self: bool = False
    mentioned: bool = False
    bound_session: bool = False
    has_attachment: bool = False


@dataclass(frozen=True, slots=True)
class ChannelGatePolicy:
    require_mention: bool = True
    allowed_users: frozenset[str] = field(default_factory=frozenset)
    allowed_channels: frozenset[str] = field(default_factory=frozenset)
    ignored_channels: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True, slots=True)
class GateDecision:
    allowed: bool
    reason: DropReason | None = None


def evaluate_channel_gate(ctx: GateContext, policy: ChannelGatePolicy) -> GateDecision:
    if ctx.is_bot or ctx.is_self:
        return GateDecision(False, DropReason.SELF_OR_BOT)
    if not ctx.text.strip() and not ctx.has_attachment:
        return GateDecision(False, DropReason.EMPTY_TEXT)
    if ctx.channel_id in policy.ignored_channels:
        return GateDecision(False, DropReason.IGNORED_CHANNEL)
    if policy.allowed_channels and ctx.channel_id not in policy.allowed_channels:
        return GateDecision(False, DropReason.CHANNEL_NOT_ALLOWED)
    if (
        policy.require_mention
        and not ctx.is_dm
        and not ctx.mentioned
        and not ctx.bound_session
    ):
        return GateDecision(False, DropReason.MENTION_REQUIRED)
    if ctx.platform_user_id not in policy.allowed_users:
        return GateDecision(False, DropReason.USER_NOT_ALLOWED)
    return GateDecision(True, None)


def policy_from_settings(channel_type: str) -> ChannelGatePolicy:
    from neos.config.settings import settings

    return resolve_channel_policy(channel_type, settings.config.channels)


def resolve_channel_policy(channel_type: str, channels: ChannelConfig) -> ChannelGatePolicy:
    platform = getattr(channels, channel_type)
    allowed_users = platform.allowed_users or channels.allowed_users
    allowed_channels = platform.allowed_channels or channels.allowed_channels
    ignored = frozenset(platform.ignored_channels) | frozenset(channels.ignored_channels)
    require_mention = (
        channels.require_mention
        if platform.require_mention is None
        else platform.require_mention
    )
    return ChannelGatePolicy(
        require_mention=require_mention,
        allowed_users=frozenset(allowed_users),
        allowed_channels=frozenset(allowed_channels),
        ignored_channels=ignored,
    )


def slack_text_mentions_bot(text: str, bot_user_id: str) -> bool:
    if not text or not bot_user_id:
        return False
    pattern = rf"<@{re.escape(bot_user_id)}(?:\|[^>]+)?>"
    return re.search(pattern, text) is not None


def telegram_text_mentions_bot(text: str, bot_username: str) -> bool:
    if not text or not bot_username:
        return False
    username = bot_username.lstrip("@")
    if not username:
        return False
    pattern = rf"(?<![A-Za-z0-9_])@{re.escape(username)}\b"
    return re.search(pattern, text, flags=re.IGNORECASE) is not None
