"""Telegram 채널 어댑터 (Phase 1 — OpenClaw Channel Adapter)

python-telegram-bot>=21.0 (asyncio-native) 사용.
uvicorn 이벤트 루프와 동일한 루프에서 asyncio.create_task()로 실행된다.

의존성 설치:
    uv add --optional channels "python-telegram-bot>=21.0"
    또는:
    pip install "python-telegram-bot>=21.0"
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import TYPE_CHECKING, Any, Optional

from neos.api.channels.authz import (
    GateContext,
    evaluate_channel_gate,
    policy_from_settings,
    telegram_text_mentions_bot,
)
from neos.api.channels.session_key import build_session_key

from ..base import ChannelAdapterBase, ChannelMessage

if TYPE_CHECKING:
    from ..gateway import ChannelGateway

logger = logging.getLogger(__name__)

# Telegram 단일 메시지 최대 길이 (HTML/Markdown 포함 시 4096)
_TELEGRAM_MAX_CHARS = 4096


def _telegram_update_mentions_bot(update: Any, text: str, bot: Any) -> bool:
    bot_username = getattr(bot, "username", None) or "" if bot is not None else ""
    if telegram_text_mentions_bot(text, bot_username):
        return True
    if bot is None:
        return False
    message = getattr(update, "effective_message", None)
    entities = getattr(message, "entities", None) or ()
    bot_id = getattr(bot, "id", None)
    username = bot_username.lstrip("@").lower()
    for entity in entities:
        etype = getattr(entity, "type", None)
        if etype == "text_mention":
            user = getattr(entity, "user", None)
            if bot_id is not None and user is not None and getattr(user, "id", None) == bot_id:
                return True
        elif etype == "mention" and username:
            offset = getattr(entity, "offset", 0)
            length = getattr(entity, "length", 0)
            token = text[offset : offset + length]
            if token.lstrip("@").lower() == username:
                return True
    return False


class TelegramAdapter(ChannelAdapterBase):
    """
    Telegram Bot API 어댑터

    start() 이후 봇이 메시지를 polling하며 수신한다.
    메시지를 받으면 ChannelGateway.dispatch()를 통해 NEOS 워크플로우를 실행하고
    결과를 해당 chat_id로 전송한다.

    이벤트 루프 전략:
        python-telegram-bot>=21.0은 asyncio-native이므로 run_polling()을
        asyncio.create_task()로 실행하면 uvicorn 루프와 공유된다.
        별도 스레드나 asyncio.run() 중첩이 불필요하다.

    채널 사용자 → NEOS user_id 매핑:
        현재는 settings.CHANNEL_BOT_USER_ID(서비스 계정)를 공유한다.
        향후 Telegram user_id → NEOS user_id 조회 테이블을 추가할 수 있다.
    """

    channel_type = "telegram"

    def __init__(self, token: str, gateway: "ChannelGateway") -> None:
        self._token = token
        self._gateway = gateway
        self._app: Optional[Any] = None       # telegram.ext.Application
        self._polling_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Telegram 봇 폴링을 시작한다."""
        try:
            from telegram.ext import Application, MessageHandler, filters
        except ImportError:
            logger.error(
                "[TelegramAdapter] python-telegram-bot 미설치. "
                "uv add --optional channels 'python-telegram-bot>=21.0' 를 실행하세요."
            )
            return

        if not self._token:
            logger.warning("[TelegramAdapter] CHANNEL_TELEGRAM_BOT_TOKEN이 설정되지 않았습니다. 시작 건너뜀.")
            return

        try:
            self._app = (
                Application.builder()
                .token(self._token)
                .build()
            )

            # 텍스트 메시지 핸들러 등록
            self._app.add_handler(
                MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message)
            )

            # 봇 초기화
            await self._app.initialize()
            await self._app.start()

            # polling 태스크 시작 (uvicorn 이벤트 루프와 공유)
            self._polling_task = asyncio.create_task(
                self._app.updater.start_polling(drop_pending_updates=True),
                name="telegram_polling",
            )

            def _on_polling_done(task: asyncio.Task) -> None:
                """polling task 종료 시 예외 여부를 확인하여 로깅한다."""
                if not task.cancelled():
                    exc = task.exception()
                    if exc:
                        logger.error(
                            f"[TelegramAdapter] Polling task failed unexpectedly: {exc}"
                        )

            self._polling_task.add_done_callback(_on_polling_done)
            logger.info("[TelegramAdapter] Telegram bot polling started.")
        except Exception as e:
            logger.error(f"[TelegramAdapter] Start failed: {e}")

    async def stop(self) -> None:
        """Telegram 봇 폴링을 종료한다."""
        if self._polling_task and not self._polling_task.done():
            self._polling_task.cancel()
            try:
                await self._polling_task
            except asyncio.CancelledError:
                pass

        if self._app:
            try:
                await self._app.updater.stop()
                await self._app.stop()
                await self._app.shutdown()
                logger.info("[TelegramAdapter] Telegram bot stopped.")
            except Exception as e:
                logger.warning(f"[TelegramAdapter] Stop error (non-critical): {e}")

    async def receive_message(self, raw: Any) -> ChannelMessage:
        """
        Telegram Update 객체를 ChannelMessage로 변환한다.

        Args:
            raw: telegram.Update 객체

        Returns:
            정규화된 ChannelMessage
        """
        from neos.config.settings import settings

        chat = raw.effective_chat
        message = raw.effective_message
        chat_id = str(chat.id)
        text = (message.text or "").strip()
        is_private = getattr(chat, "type", None) == "private"
        message_thread_id = getattr(message, "message_thread_id", None)
        message_id = getattr(message, "message_id", None)

        return ChannelMessage(
            user_id=settings.CHANNEL_BOT_USER_ID,
            session_id=build_session_key(
                "telegram",
                "dm" if is_private else chat_id,
                chat_id,
                str(message_thread_id) if message_thread_id else "-",
            ),
            text=text,
            channel_type=self.channel_type,
            channel_id=chat_id,
            raw_data=raw,
            metadata={
                "telegram_user_id": raw.effective_user.id if raw.effective_user else None,
                "telegram_username": (
                    raw.effective_user.username if raw.effective_user else None
                ),
                "thread_id": str(message_id) if message_id is not None else None,
            },
        )

    async def send_response(
        self, channel_id: str, content: str, *, thread_id: str | None = None
    ) -> None:
        """
        Telegram chat_id로 응답 텍스트를 전송한다.

        Telegram 단일 메시지 4096자 제한을 준수하기 위해
        필요 시 여러 메시지로 분할한다.

        Args:
            channel_id: Telegram chat_id
            content: 전송할 텍스트
            thread_id: 원본 message_id — 설정 시 해당 메시지에 reply
        """
        if not self._app:
            logger.warning("[TelegramAdapter] send_response called before start()")
            return

        if not content:
            return

        bot = self._app.bot
        # 4096자 초과 시 분할 전송
        chunks = [
            content[i : i + _TELEGRAM_MAX_CHARS]
            for i in range(0, len(content), _TELEGRAM_MAX_CHARS)
        ]
        send_kwargs: dict[str, Any] = {}
        if thread_id:
            send_kwargs["reply_to_message_id"] = int(thread_id)

        for chunk in chunks:
            try:
                await bot.send_message(chat_id=channel_id, text=chunk, **send_kwargs)
            except Exception as e:
                logger.error(f"[TelegramAdapter] send_message failed to {channel_id}: {e}")

    async def _handle_message(self, update: Any, context: Any) -> None:
        """
        python-telegram-bot MessageHandler 콜백.
        메시지를 ChannelMessage로 변환 후 ChannelGateway에 위임하고 응답을 전송한다.
        """
        if not update.effective_message or not update.effective_message.text:
            return

        effective_user = update.effective_user
        effective_chat = update.effective_chat
        text = update.effective_message.text or ""
        bot = getattr(self._app, "bot", None) if self._app is not None else None
        bot_id = getattr(bot, "id", None) if bot is not None else None
        ctx = GateContext(
            channel_type=self.channel_type,
            platform_user_id=str(effective_user.id) if effective_user is not None else "",
            channel_id=str(effective_chat.id) if effective_chat is not None else "",
            text=text,
            is_dm=bool(effective_chat is not None and effective_chat.type == "private"),
            is_bot=bool(getattr(effective_user, "is_bot", False)),
            is_self=bool(
                bot_id is not None
                and effective_user is not None
                and effective_user.id == bot_id
            ),
            mentioned=_telegram_update_mentions_bot(update, text, bot),
        )
        decision = evaluate_channel_gate(ctx, policy_from_settings(self.channel_type))
        if not decision.allowed:
            logger.info(
                "[TelegramAdapter] drop reason=%s channel=%s user=%s",
                decision.reason,
                ctx.channel_id,
                ctx.platform_user_id,
            )
            return

        try:
            channel_message = await self.receive_message(update)
            logger.info(
                f"[TelegramAdapter] Received: chat_id={channel_message.channel_id}, "
                f"text={channel_message.text[:50]!r}"
            )

            # 타이핑 인디케이터 (UX 개선 — 워크플로우 실행 중 표시)
            await update.effective_chat.send_action(action="typing")

            response = await self._gateway.dispatch(channel_message)
            await self.send_response(
                channel_message.channel_id,
                response,
                thread_id=channel_message.metadata.get("thread_id"),
            )

        except Exception as e:
            logger.error(f"[TelegramAdapter] _handle_message error: {e}")
            try:
                await update.effective_chat.send_message(
                    "죄송합니다. 오류가 발생했습니다. 잠시 후 다시 시도해주세요."
                )
            except Exception:
                pass
