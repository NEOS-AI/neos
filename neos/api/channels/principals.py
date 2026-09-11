"""Map a platform user to a NEOS principal. Fail-closed when a map exists."""

from __future__ import annotations

from neos.api.channels.base import ChannelMessage
from neos.config.schema import ChannelConfig


_PLATFORM_META_KEYS = {
    "slack": "slack_user_id",
    "discord": "discord_user_id",
    "telegram": "telegram_user_id",
}


def platform_user_id_from_message(message: ChannelMessage) -> str:
    key = _PLATFORM_META_KEYS.get(message.channel_type)
    if key is None:
        return ""
    value = (message.metadata or {}).get(key)
    return str(value) if value else ""


def resolve_channel_principal(
    *,
    platform: str,
    platform_user_id: str,
    channels: ChannelConfig,
) -> str | None:
    if not platform or not platform_user_id:
        return None
    for item in channels.principals:
        if item.platform == platform and item.platform_user_id == platform_user_id:
            return item.user_id
    return None


def resolve_message_user_id(
    *,
    platform: str,
    platform_user_id: str,
    channels: ChannelConfig,
    bot_user_id: str,
) -> str:
    """Map a chat user. Fail-closed to "" when a principals map exists."""
    mapped = resolve_channel_principal(
        platform=platform,
        platform_user_id=platform_user_id,
        channels=channels,
    )
    if mapped:
        return mapped
    if channels.principals:
        return ""
    return bot_user_id


async def coding_action_actor_allowed(
    *,
    gateway: object,
    session_id: str,
    platform: str,
    platform_user_id: str,
    channels: ChannelConfig,
) -> bool:
    """Allowlist already ran. When a principal map exists, actor must be the task owner."""
    if not channels.principals:
        return True
    get_binding = getattr(gateway, "get_binding", None)
    if get_binding is None:
        return False
    binding = await get_binding(session_id)
    actor = resolve_channel_principal(
        platform=platform,
        platform_user_id=platform_user_id,
        channels=channels,
    )
    if binding is not None:
        return actor is not None and actor == binding.owner_id
    pending_owner_fn = getattr(gateway, "workflow_pending_owner", None)
    if pending_owner_fn is not None:
        pending_owner = await pending_owner_fn(session_id)
        if pending_owner:
            return actor is not None and actor == pending_owner
    return True


def resolve_coding_owner(
    *,
    message: ChannelMessage,
    channels: ChannelConfig,
) -> str | None:
    platform_user_id = platform_user_id_from_message(message)
    mapped = resolve_channel_principal(
        platform=message.channel_type,
        platform_user_id=platform_user_id,
        channels=channels,
    )
    if mapped:
        return mapped
    if channels.principals:
        return None
    return channels.coding_owner_user_id or None
