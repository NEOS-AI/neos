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
from typing import TYPE_CHECKING, Any, Optional

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
        if self._client:
            try:
                await self._client.close()
                logger.info("[DiscordAdapter] Discord bot closed.")
            except Exception as e:
                logger.warning("[DiscordAdapter] Stop error (non-critical): %s", e)

        if self._bot_task and not self._bot_task.done():
            self._bot_task.cancel()
            try:
                await self._bot_task
            except asyncio.CancelledError:
                pass

    async def receive_message(self, raw: Any) -> ChannelMessage:
        """discord.Message를 ChannelMessage로 변환한다."""
        from neos.config.settings import settings

        channel_id = str(raw.channel.id)
        text = (raw.content or "").strip()

        return ChannelMessage(
            user_id=settings.CHANNEL_BOT_USER_ID,
            session_id=f"discord_{channel_id}",
            text=text,
            channel_type=self.channel_type,
            channel_id=channel_id,
            raw_data=raw,
            metadata={
                "discord_user_id": raw.author.id,
                "discord_username": str(raw.author),
                "discord_guild_id": raw.guild.id if raw.guild else None,
            },
        )

    async def send_response(self, channel_id: str, content: str) -> None:
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
        for chunk in chunks:
            try:
                await channel.send(chunk)
            except Exception as e:
                logger.error(
                    "[DiscordAdapter] channel.send() failed to %s: %s", channel_id, e
                )

    async def _handle_message(self, message: Any) -> None:
        """on_message 이벤트 핸들러."""
        # 봇 자신의 메시지 무시 (무한 루프 방지)
        if message.author == self._client.user:
            return
        if not message.content:
            return

        try:
            channel_message = await self.receive_message(message)
            logger.info(
                "[DiscordAdapter] Received: channel_id=%s text=%r",
                channel_message.channel_id,
                channel_message.text[:50],
            )
            async with message.channel.typing():
                response = await self._gateway.dispatch(channel_message)
            await self.send_response(channel_message.channel_id, response)
        except Exception as e:
            logger.error("[DiscordAdapter] _handle_message error: %s", e)
            try:
                await message.channel.send(
                    "죄송합니다. 오류가 발생했습니다. 잠시 후 다시 시도해주세요."
                )
            except Exception:
                pass
