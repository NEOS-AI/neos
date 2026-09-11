"""Discord 채널 어댑터 (Phase 1 — OpenClaw Channel Adapter)

discord.py>=2.3.0 사용.
uvicorn 이벤트 루프와 동일한 루프에서 asyncio.create_task()로 실행된다.

필요 환경변수:
    CHANNEL_DISCORD_ENABLED=true
    CHANNEL_DISCORD_BOT_TOKEN=<bot token>

Discord Developer Portal 설정:
    Bot > Privileged Gateway Intents > Message Content Intent 활성화 필요.
"""
from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, Optional

from neos.api.channels.authz import (
    GateContext,
    evaluate_channel_gate,
    policy_from_settings,
)
from neos.api.channels.cards import (
    ACTION_PREFIX,
    command_for_action,
    discord_buttons,
    parse_action_payload,
    started_task_id,
)
from neos.api.channels.commands import ChannelCommandKind, parse_channel_command
from neos.api.channels.session_key import build_session_key

from ..base import ChannelAdapterBase, ChannelMessage

if TYPE_CHECKING:
    from ..gateway import ChannelGateway

logger = logging.getLogger(__name__)

_DISCORD_MAX_CHARS = 2000  # Discord 단일 메시지 최대 길이


class DiscordAdapter(ChannelAdapterBase):
    """Discord Bot 어댑터.

    start() 이후 봇이 on_message 이벤트로 메시지를 수신한다.
    메시지 수신 → ChannelGateway.dispatch() → send_response() 흐름.
    """

    channel_type = "discord"

    def __init__(self, token: str, gateway: "ChannelGateway") -> None:
        self._token = token
        self._gateway = gateway
        self._client: Optional[Any] = None   # discord.Client
        self._bot_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Discord 봇을 시작한다."""
        try:
            import discord
        except ImportError:
            logger.error(
                "[DiscordAdapter] discord.py 미설치. "
                "pip install 'discord.py>=2.3.0' 를 실행하세요."
            )
            return

        if not self._token:
            logger.warning(
                "[DiscordAdapter] CHANNEL_DISCORD_BOT_TOKEN이 설정되지 않았습니다. "
                "시작 건너뜀."
            )
            return

        try:
            intents = discord.Intents.default()
            intents.message_content = True  # Developer Portal에서 활성화 필요

            self._client = discord.Client(intents=intents)

            @self._client.event
            async def on_ready() -> None:
                logger.info(
                    "[DiscordAdapter] Discord bot logged in as %s",
                    self._client.user,
                )

            @self._client.event
            async def on_message(message: discord.Message) -> None:
                await self._handle_message(message)

            @self._client.event
            async def on_interaction(interaction: discord.Interaction) -> None:
                await self._handle_interaction(interaction)

            self._bot_task = asyncio.create_task(
                self._client.start(self._token),
                name="discord_bot",
            )

            def _on_bot_done(task: asyncio.Task) -> None:
                if not task.cancelled():
                    exc = task.exception()
                    if exc:
                        logger.error(
                            "[DiscordAdapter] Bot task failed unexpectedly: %s", exc
                        )

            self._bot_task.add_done_callback(_on_bot_done)
            logger.info("[DiscordAdapter] Discord bot task started.")
        except Exception as e:
            logger.error("[DiscordAdapter] Start failed: %s", e)

    async def stop(self) -> None:
        """Discord 봇을 종료한다."""
        if self._bot_task and not self._bot_task.done():
            self._bot_task.cancel()
            try:
                await self._bot_task
            except asyncio.CancelledError:
                pass

        if self._client:
            try:
                await self._client.close()
                logger.info("[DiscordAdapter] Discord bot closed.")
            except Exception as e:
                logger.warning("[DiscordAdapter] Stop error (non-critical): %s", e)

    async def receive_message(self, raw: Any) -> ChannelMessage:
        """discord.Message를 ChannelMessage로 변환한다."""
        from neos.config.settings import settings

        channel = raw.channel
        channel_id = str(channel.id)
        text = (raw.content or "").strip()

        from neos.api.channels.principals import resolve_message_user_id

        platform_user_id = str(raw.author.id)
        user_id = resolve_message_user_id(
            platform="discord",
            platform_user_id=platform_user_id,
            channels=settings.config.channels,
            bot_user_id=settings.CHANNEL_BOT_USER_ID,
        )
        metadata: dict[str, Any] = {
            "discord_user_id": str(raw.author.id),
            "discord_username": str(raw.author),
            "discord_guild_id": str(raw.guild.id) if raw.guild else None,
            "thread_id": str(raw.id),
            "idempotency_key": str(raw.id),
        }
        if settings.config.channels.inbound_media:
            from neos.api.channels.media import collect_discord_attachments

            attachments = await collect_discord_attachments(
                list(getattr(raw, "attachments", None) or []),
                fetch=getattr(self, "_media_fetch", None),
                resolve_host=getattr(self, "_media_resolve", None),
            )
            if attachments:
                metadata["attachments"] = attachments
        return ChannelMessage(
            user_id=user_id,
            session_id=_discord_session_id(raw),
            text=text,
            channel_type=self.channel_type,
            channel_id=channel_id,
            raw_data=raw,
            metadata=metadata,
        )

    async def send_response(
        self, channel_id: str, content: str, *, thread_id: str | None = None
    ) -> None:
        """Discord channel_id로 응답을 전송한다. 2000자 제한 준수."""
        if not self._client:
            logger.warning("[DiscordAdapter] send_response called before start()")
            return
        if not content:
            return

        channel = self._client.get_channel(int(channel_id))
        if channel is None:
            try:
                channel = await self._client.fetch_channel(int(channel_id))
            except Exception as e:
                logger.error(
                    "[DiscordAdapter] fetch_channel(%s) failed: %s", channel_id, e
                )
                return

        chunks = [
            content[i : i + _DISCORD_MAX_CHARS]
            for i in range(0, len(content), _DISCORD_MAX_CHARS)
        ]
        reply_to = await _fetch_reply_target(channel, thread_id)
        view = _coding_discord_view(content) if len(chunks) == 1 else None
        send_kwargs: dict[str, Any] = {}
        if view is not None:
            send_kwargs["view"] = view
        for chunk in chunks:
            try:
                if reply_to is not None:
                    await reply_to.reply(chunk, **send_kwargs)
                else:
                    await channel.send(chunk, **send_kwargs)
            except Exception as e:
                logger.error(
                    "[DiscordAdapter] send failed to %s: %s", channel_id, e
                )

    async def send_draft(
        self, channel_id: str, content: str, *, thread_id: str | None = None
    ) -> None:
        from neos.config.settings import settings

        if not settings.config.channels.draft_streaming:
            return
        if not self._client or not content:
            return
        try:
            channel = self._client.get_channel(int(channel_id))
            if channel is None:
                channel = await self._client.fetch_channel(int(channel_id))
            target = await _fetch_reply_target(channel, thread_id)
            if target is not None and callable(getattr(target, "edit", None)):
                await target.edit(content=content)
            elif channel is not None:
                await channel.send(content)
        except Exception as e:
            logger.warning("[DiscordAdapter] send_draft failed to %s: %s", channel_id, e)

    async def _handle_message(self, message: Any) -> None:
        """on_message 이벤트 핸들러."""
        from neos.config.settings import settings
        from neos.api.channels.session_bind import session_is_bound

        bot_user = self._client.user if self._client is not None else None
        bound = await session_is_bound(self._gateway, _discord_session_id(message))
        attachments = list(getattr(message, "attachments", None) or [])
        has_attachment = bool(settings.config.channels.inbound_media and attachments)
        ctx = GateContext(
            channel_type=self.channel_type,
            platform_user_id=str(getattr(message.author, "id", "")),
            channel_id=str(message.channel.id),
            text=message.content or "",
            is_dm=getattr(message, "guild", None) is None,
            is_bot=bool(getattr(message.author, "bot", False)),
            is_self=self._client is not None and message.author == self._client.user,
            mentioned=_message_mentions_bot(message, bot_user),
            bound_session=bound,
            has_attachment=has_attachment,
        )
        decision = evaluate_channel_gate(ctx, policy_from_settings(self.channel_type))
        if not decision.allowed:
            logger.info(
                "[DiscordAdapter] drop reason=%s channel=%s user=%s",
                decision.reason,
                ctx.channel_id,
                ctx.platform_user_id,
            )
            return

        try:
            channel_message = await self.receive_message(message)
            logger.info(
                "[DiscordAdapter] Received: channel_id=%s text=%r",
                channel_message.channel_id,
                channel_message.text[:50],
            )
            await _add_reaction_safe(message, "👀")
            try:
                async with message.channel.typing():
                    response = await self._gateway.dispatch(channel_message)
                    reply_channel_id, reply_thread_id = await self._maybe_autothread(
                        message, channel_message, response
                    )
                    await self.send_response(
                        reply_channel_id,
                        response,
                        thread_id=reply_thread_id,
                    )
            except Exception:
                await _add_reaction_safe(message, "❌")
                raise
            await _add_reaction_safe(message, "✅")
        except Exception as e:
            logger.error("[DiscordAdapter] _handle_message error: %s", e)
            try:
                await message.channel.send(
                    "죄송합니다. 오류가 발생했습니다. 잠시 후 다시 시도해주세요."
                )
            except Exception:
                pass

    async def _maybe_autothread(
        self, message: Any, channel_message: ChannelMessage, response: str
    ) -> tuple[str, str | None]:
        channel_id = channel_message.channel_id
        thread_id = channel_message.metadata.get("thread_id")
        if not _should_create_code_thread(message, channel_message, response):
            return channel_id, thread_id
        task_id = started_task_id(response)
        create_thread = getattr(message, "create_thread", None)
        if task_id is None or create_thread is None:
            return channel_id, thread_id
        try:
            thread = await create_thread(name=_code_thread_name(task_id))
        except Exception as e:
            logger.warning("[DiscordAdapter] create_thread failed: %s", e)
            return channel_id, thread_id
        await self._bind_autothread(channel_message, thread, task_id)
        return str(thread.id), None

    async def _bind_autothread(
        self, channel_message: ChannelMessage, thread: Any, task_id: str
    ) -> None:
        bind_session = getattr(self._gateway, "bind_session", None)
        if bind_session is None:
            return
        guild_id = channel_message.metadata.get("discord_guild_id") or "dm"
        parent_id = str(
            getattr(thread, "parent_id", None) or channel_message.channel_id
        )
        thread_session = build_session_key(
            "discord", str(guild_id), parent_id, str(thread.id)
        )
        owner_id = None
        bound_task_id = task_id
        get_binding = getattr(self._gateway, "get_binding", None)
        if get_binding is not None:
            parent = await get_binding(channel_message.session_id)
            if parent is not None:
                bound_task_id = parent.task_id
                owner_id = parent.owner_id
        if not owner_id:
            from neos.config.settings import settings

            owner_id = settings.config.channels.coding_owner_user_id
        if bound_task_id and owner_id:
            await bind_session(thread_session, bound_task_id, owner_id)

    async def _handle_code_action(
        self,
        *,
        user_id: str,
        channel: Any,
        guild_id: str | None,
        custom_id: str,
        is_dm: bool,
        is_bot: bool,
    ) -> None:
        parsed = parse_action_payload(custom_id)
        if parsed is None:
            return
        text = command_for_action(parsed[0], parsed[1])
        if not text:
            return

        from neos.api.channels.session_bind import session_is_bound

        channel_id = str(getattr(channel, "id", "") or "")
        shim = SimpleNamespace(
            channel=channel,
            guild=SimpleNamespace(id=guild_id) if guild_id and not is_dm else None,
            author=SimpleNamespace(id=user_id, bot=is_bot),
            content=text,
            id=getattr(channel, "id", ""),
        )
        bound = await session_is_bound(self._gateway, _discord_session_id(shim))
        bot_user = self._client.user if self._client is not None else None
        ctx = GateContext(
            channel_type=self.channel_type,
            platform_user_id=str(user_id),
            channel_id=channel_id,
            text=text,
            is_dm=is_dm,
            is_bot=is_bot,
            is_self=bool(
                bot_user is not None and str(getattr(bot_user, "id", "")) == str(user_id)
            ),
            mentioned=True,
            bound_session=bound,
        )
        decision = evaluate_channel_gate(ctx, policy_from_settings(self.channel_type))
        if not decision.allowed:
            logger.info(
                "[DiscordAdapter] drop action reason=%s channel=%s user=%s",
                decision.reason,
                ctx.channel_id,
                ctx.platform_user_id,
            )
            return

        channel_message = await self.receive_message(shim)
        response = await self._gateway.dispatch(channel_message)
        await self.send_response(channel_id, response)

    async def _handle_interaction(self, interaction: Any) -> None:
        data = getattr(interaction, "data", None) or {}
        custom_id = ""
        if isinstance(data, dict):
            custom_id = str(data.get("custom_id") or "")
        else:
            custom_id = str(getattr(data, "custom_id", "") or "")
        if not custom_id.startswith(ACTION_PREFIX):
            return
        user = getattr(interaction, "user", None) or getattr(interaction, "author", None)
        channel = getattr(interaction, "channel", None)
        guild = getattr(interaction, "guild", None)
        await self._handle_code_action(
            user_id=str(getattr(user, "id", "") or ""),
            channel=channel,
            guild_id=str(guild.id) if guild is not None else None,
            custom_id=custom_id,
            is_dm=guild is None,
            is_bot=bool(getattr(user, "bot", False)),
        )


def _should_create_code_thread(
    message: Any, channel_message: ChannelMessage, response: str
) -> bool:
    if started_task_id(response) is None:
        return False
    if parse_channel_command(channel_message.text).kind is not ChannelCommandKind.CODE:
        return False
    if getattr(message, "guild", None) is None:
        return False
    return not _is_discord_thread(getattr(message, "channel", None))


def _code_thread_name(task_id: str) -> str:
    return f"code {task_id}"[:100]


async def _fetch_reply_target(channel: Any, thread_id: str | None) -> Any | None:
    if not thread_id or channel is None:
        return None
    fetch_message = getattr(channel, "fetch_message", None)
    if fetch_message is None:
        return None
    try:
        target = await fetch_message(int(thread_id))
    except Exception:
        return None
    if target is not None and callable(getattr(target, "reply", None)):
        return target
    return None


async def _add_reaction_safe(message: Any, emoji: str) -> None:
    add_reaction = getattr(message, "add_reaction", None)
    if add_reaction is None:
        return
    try:
        await add_reaction(emoji)
    except Exception:
        pass


def _coding_discord_view(text: str) -> Any | None:
    buttons = discord_buttons(text)
    if not buttons:
        return None
    try:
        import discord

        view = discord.ui.View()
        for button in buttons:
            style = (
                discord.ButtonStyle.danger
                if button.get("style") == "danger"
                else discord.ButtonStyle.secondary
            )
            view.add_item(
                discord.ui.Button(
                    label=button["label"],
                    custom_id=button["custom_id"],
                    style=style,
                )
            )
        return view
    except Exception:
        return SimpleNamespace(buttons=buttons, children=buttons)


def _discord_session_id(raw: Any) -> str:
    channel = getattr(raw, "channel", None)
    channel_id = str(getattr(channel, "id", "") or "")
    guild = getattr(raw, "guild", None)
    guild_id = str(guild.id) if guild is not None else None
    if _is_discord_thread(channel):
        chat = str(getattr(channel, "parent_id", None) or channel_id)
        thread = channel_id
    else:
        chat = channel_id
        thread = "-"
    return build_session_key("discord", guild_id or "dm", chat, thread)


def _is_discord_thread(channel: Any) -> bool:
    type_name = getattr(getattr(channel, "type", None), "name", "") or ""
    if type_name.endswith("thread"):
        return True
    return type(channel).__name__ == "Thread"


def _message_mentions_bot(message: Any, bot_user: Any) -> bool:
    if bot_user is None:
        return False
    bot_id = getattr(bot_user, "id", None)
    if bot_id is None:
        return False
    for mentioned in getattr(message, "mentions", []) or []:
        if getattr(mentioned, "id", None) == bot_id:
            return True
    content = getattr(message, "content", None) or ""
    bot_id_s = str(bot_id)
    return f"<@{bot_id_s}>" in content or f"<@!{bot_id_s}>" in content
