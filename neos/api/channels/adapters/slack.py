"""Slack 채널 어댑터 (Phase 1 — OpenClaw Channel Adapter)

slack-bolt>=1.18.0 (AsyncApp + AsyncSocketModeHandler) 사용.
Socket Mode를 사용하므로 추가 HTTP 포트가 불필요하다.

필요 환경변수:
    CHANNEL_SLACK_ENABLED=true
    CHANNEL_SLACK_BOT_TOKEN    - xoxb- 접두사 Bot Token
    CHANNEL_SLACK_APP_TOKEN    - xapp- 접두사 App-Level Token (Socket Mode용)

Slack App 설정:
    Settings > Socket Mode 활성화
    Event Subscriptions > Bot Events: message.channels, message.im 추가
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import TYPE_CHECKING, Any, Optional

from ..base import ChannelAdapterBase, ChannelMessage
from ..cards import ACTION_PREFIX, coding_blocks, command_for_action
from ..session_key import build_session_key

if TYPE_CHECKING:
    from ..gateway import ChannelGateway

logger = logging.getLogger(__name__)

_SLACK_MAX_CHARS = 3000  # Slack 단일 메시지 안전 길이 (공식 4000자 제한)


class SlackAdapter(ChannelAdapterBase):
    """Slack Bot 어댑터 (Socket Mode).

    AsyncApp + AsyncSocketModeHandler로 uvicorn 루프에서 실행.
    @app.message() 핸들러를 통해 메시지 수신.
    """

    channel_type = "slack"

    def __init__(self, token: str, gateway: "ChannelGateway") -> None:
        self._bot_token = token           # xoxb- 토큰
        self._gateway = gateway
        self._app: Optional[Any] = None  # AsyncApp
        self._handler: Optional[Any] = None  # AsyncSocketModeHandler
        self._handler_task: Optional[asyncio.Task] = None
        self._bot_user_id: Optional[str] = None
        self._team_id: Optional[str] = None

    async def start(self) -> None:
        """Slack Socket Mode 핸들러를 시작한다."""
        try:
            from slack_bolt.async_app import AsyncApp
            from slack_bolt.adapter.socket_mode.async_handler import (
                AsyncSocketModeHandler,
            )
        except ImportError:
            logger.error(
                "[SlackAdapter] slack-bolt 미설치. "
                "pip install 'slack-bolt>=1.18.0' 를 실행하세요."
            )
            return

        from neos.config.settings import settings

        if not self._bot_token:
            logger.warning(
                "[SlackAdapter] CHANNEL_SLACK_BOT_TOKEN이 설정되지 않았습니다. "
                "시작 건너뜀."
            )
            return

        app_token = settings.CHANNEL_SLACK_APP_TOKEN
        if not app_token:
            logger.warning(
                "[SlackAdapter] CHANNEL_SLACK_APP_TOKEN이 설정되지 않았습니다. "
                "Socket Mode를 사용하려면 xapp- 토큰이 필요합니다. 시작 건너뜀."
            )
            return

        try:
            self._app = AsyncApp(token=self._bot_token)
            try:
                auth = await self._app.client.auth_test()
                self._bot_user_id = auth.get("user_id")
                team_id = auth.get("team_id")
                if team_id:
                    self._team_id = str(team_id)
            except Exception as e:
                logger.warning("[SlackAdapter] auth_test failed (non-critical): %s", e)

            self._register_handlers()

            self._handler = AsyncSocketModeHandler(self._app, app_token)
            self._handler_task = asyncio.create_task(
                self._handler.start_async(),
                name="slack_socket_mode",
            )

            def _on_handler_done(task: asyncio.Task) -> None:
                if task.cancelled():
                    return
                exc = task.exception()
                if exc:
                    logger.error(
                        "[SlackAdapter] Socket mode handler failed: %s", exc
                    )

            self._handler_task.add_done_callback(_on_handler_done)
            logger.info("[SlackAdapter] Slack Socket Mode handler started.")
        except Exception as e:
            logger.error("[SlackAdapter] Start failed: %s", e)

    async def stop(self) -> None:
        """Slack Socket Mode 핸들러를 종료한다."""
        if self._handler_task and not self._handler_task.done():
            self._handler_task.cancel()
            try:
                await self._handler_task
            except asyncio.CancelledError:
                pass

        if self._handler:
            try:
                await self._handler.close_async()
                logger.info("[SlackAdapter] Slack handler closed.")
            except Exception as e:
                logger.warning("[SlackAdapter] Stop error (non-critical): %s", e)

    async def receive_message(self, raw: Any) -> ChannelMessage:
        """Slack message 이벤트 딕셔너리를 ChannelMessage로 변환한다."""
        from neos.config.settings import settings

        channel_id = str(raw.get("channel", ""))
        text = (raw.get("text") or "").strip()
        slack_user_id = str(raw.get("user", ""))
        raw_ts = raw.get("ts")
        thread_id = self._thread_id(raw)
        session_id = self._session_id(raw)

        from neos.api.channels.principals import resolve_message_user_id

        user_id = resolve_message_user_id(
            platform="slack",
            platform_user_id=slack_user_id,
            channels=settings.config.channels,
            bot_user_id=settings.CHANNEL_BOT_USER_ID,
        )
        metadata: dict[str, Any] = {
            "slack_user_id": slack_user_id,
            "slack_message_ts": raw_ts or "",
            "thread_id": thread_id,
            "idempotency_key": str(raw_ts or ""),
        }
        if settings.config.channels.inbound_media:
            from neos.api.channels.media import collect_slack_attachments

            attachments = await collect_slack_attachments(
                list(raw.get("files") or []),
                token=self._bot_token,
                fetch=getattr(self, "_media_fetch", None),
                resolve_host=getattr(self, "_media_resolve", None),
            )
            if attachments:
                metadata["attachments"] = attachments
        return ChannelMessage(
            user_id=user_id,
            session_id=session_id,
            text=text,
            channel_type=self.channel_type,
            channel_id=channel_id,
            raw_data=raw,
            metadata=metadata,
        )

    async def send_response(
        self, channel_id: str, content: str, *, thread_id: str | None = None
    ) -> None:
        """Slack channel_id로 응답을 전송한다. 3000자 제한 준수."""
        if not self._app:
            logger.warning("[SlackAdapter] send_response called before start()")
            return
        if not content:
            return

        chunks = [
            content[i : i + _SLACK_MAX_CHARS]
            for i in range(0, len(content), _SLACK_MAX_CHARS)
        ]
        post_kwargs: dict[str, Any] = {}
        if thread_id:
            post_kwargs["thread_ts"] = thread_id
        blocks = coding_blocks(content) if len(chunks) == 1 else None
        for chunk in chunks:
            posted = False
            if blocks:
                try:
                    await self._app.client.chat_postMessage(
                        channel=channel_id,
                        text=chunk,
                        blocks=blocks,
                        **post_kwargs,
                    )
                    posted = True
                except Exception as e:
                    logger.warning(
                        "[SlackAdapter] Block Kit post failed to %s: %s",
                        channel_id,
                        e,
                    )
            if not posted:
                try:
                    await self._app.client.chat_postMessage(
                        channel=channel_id,
                        text=chunk,
                        **post_kwargs,
                    )
                except Exception as e:
                    logger.error(
                        "[SlackAdapter] chat_postMessage failed to %s: %s",
                        channel_id,
                        e,
                    )

    async def send_draft(
        self, channel_id: str, content: str, *, thread_id: str | None = None
    ) -> None:
        from neos.config.settings import settings

        if not settings.config.channels.draft_streaming:
            return
        if not self._app or not content:
            return
        try:
            if thread_id:
                await self._app.client.chat_update(
                    channel=channel_id, ts=thread_id, text=content
                )
            else:
                await self._app.client.chat_postMessage(
                    channel=channel_id, text=content
                )
        except Exception as e:
            logger.warning("[SlackAdapter] send_draft failed to %s: %s", channel_id, e)

    async def send_file(
        self,
        channel_id: str,
        path: str,
        *,
        allow_dirs: list[str] | None = None,
        thread_id: str | None = None,
    ) -> None:
        from neos.api.channels.outbound import resolve_outbound_file

        if resolve_outbound_file(path, allow_dirs) is None:
            return

    def _register_handlers(self) -> None:
        if self._app is None:
            return

        @self._app.message()
        async def handle_message(
            message: dict, say: Any, client: Any, context: Any = None
        ) -> None:
            team_id = _context_team_id(context)
            if team_id and not message.get("team") and not message.get("team_id"):
                message = {**message, "team": team_id}
            await self._handle_message(message, say, client)

        @self._app.action(re.compile(rf"^{re.escape(ACTION_PREFIX)}"))
        async def handle_code_action(ack: Any, body: dict) -> None:
            await ack()
            await self._handle_block_action(body)

    async def _handle_block_action(self, body: dict) -> None:
        actions = body.get("actions") or []
        if not actions:
            return
        action = actions[0]
        text = command_for_action(
            str(action.get("action_id") or ""),
            str(action.get("value") or ""),
        )
        if not text:
            return

        from neos.api.channels.authz import (
            GateContext,
            evaluate_channel_gate,
            policy_from_settings,
        )

        user = body.get("user") or {}
        channel = body.get("channel") or {}
        team = body.get("team") or {}
        message = body.get("message") or {}
        user_id = str(user.get("id") or "")
        channel_id = str(channel.get("id") or "")
        thread_ts = str(message.get("thread_ts") or message.get("ts") or "")
        raw = {
            "user": user_id,
            "channel": channel_id,
            "text": text,
            "team": team.get("id") or self._team_id,
            "thread_ts": thread_ts or None,
            "ts": message.get("ts") or thread_ts,
        }
        from neos.api.channels.session_bind import session_wakes_without_mention

        bound = await session_wakes_without_mention(
            self._gateway, self._session_id(raw)
        )
        ctx = GateContext(
            channel_type=self.channel_type,
            platform_user_id=user_id,
            channel_id=channel_id,
            text=text,
            is_dm=channel_id.startswith("D"),
            is_bot=False,
            is_self=bool(self._bot_user_id) and user_id == self._bot_user_id,
            mentioned=True,
            bound_session=bound,
        )
        decision = evaluate_channel_gate(ctx, policy_from_settings(self.channel_type))
        if not decision.allowed:
            logger.info(
                "[SlackAdapter] drop reason=%s channel=%s user=%s",
                decision.reason,
                ctx.channel_id,
                ctx.platform_user_id,
            )
            return
        from neos.api.channels.principals import coding_action_actor_allowed
        from neos.config.settings import settings

        if not await coding_action_actor_allowed(
            gateway=self._gateway,
            session_id=self._session_id(raw),
            platform="slack",
            platform_user_id=user_id,
            channels=settings.config.channels,
        ):
            logger.info(
                "[SlackAdapter] drop action: not task owner channel=%s user=%s",
                ctx.channel_id,
                user_id,
            )
            return

        channel_message = await self.receive_message(
            {
                "user": user_id,
                "channel": channel_id,
                "text": text,
                "team": team.get("id") or self._team_id,
                "thread_ts": thread_ts or None,
                "ts": message.get("ts") or thread_ts,
            }
        )
        response = await self._gateway.dispatch(channel_message)
        await self.send_response(
            channel_message.channel_id,
            response,
            thread_id=channel_message.metadata.get("thread_id"),
        )

    async def _add_reaction(
        self, client: Any, channel_id: str, timestamp: str, name: str
    ) -> None:
        if client is None or not timestamp:
            return
        try:
            await client.reactions_add(
                channel=channel_id,
                timestamp=timestamp,
                name=name,
            )
        except Exception:
            pass

    def _thread_id(self, raw: Any) -> str:
        if not isinstance(raw, dict):
            return ""
        return str(raw.get("thread_ts") or raw.get("ts") or "")

    def _session_id(self, raw: Any) -> str:
        channel_id = ""
        if isinstance(raw, dict):
            channel_id = str(raw.get("channel") or "")
        thread_id = self._thread_id(raw)
        return build_session_key(
            "slack",
            self._team_scope(raw),
            channel_id,
            thread_id or "-",
        )

    def _team_scope(self, raw: Any) -> str:
        team = None
        if isinstance(raw, dict):
            team = raw.get("team")
            if team is None:
                team = raw.get("team_id")
        if isinstance(team, dict):
            team = team.get("id")
        team_id = str(team or "").strip()
        if team_id:
            return team_id
        if self._team_id:
            return self._team_id
        return "dm"

    async def _handle_message(self, message: dict, say: Any, client: Any) -> None:
        """@app.message() 핸들러."""
        # bot_id가 있는 메시지 = 봇이 보낸 메시지 — 무시
        if message.get("bot_id"):
            return

        from neos.config.settings import settings
        from neos.api.channels.authz import (
            GateContext,
            evaluate_channel_gate,
            policy_from_settings,
            slack_text_mentions_bot,
        )

        text = message.get("text") or ""
        files = list(message.get("files") or [])
        has_attachment = bool(settings.config.channels.inbound_media and files)
        if not text.strip() and not has_attachment:
            return
        from neos.api.channels.session_bind import session_wakes_without_mention

        bound = await session_wakes_without_mention(
            self._gateway, self._session_id(message)
        )
        ctx = GateContext(
            channel_type=self.channel_type,
            platform_user_id=str(message.get("user") or ""),
            channel_id=str(message.get("channel") or ""),
            text=text,
            is_dm=message.get("channel_type") == "im",
            is_bot=bool(message.get("bot_id")) or message.get("subtype") == "bot_message",
            is_self=bool(self._bot_user_id)
            and str(message.get("user")) == self._bot_user_id,
            mentioned=slack_text_mentions_bot(text, self._bot_user_id or ""),
            bound_session=bound,
            has_attachment=has_attachment,
        )
        decision = evaluate_channel_gate(ctx, policy_from_settings(self.channel_type))
        if not decision.allowed:
            logger.info(
                "[SlackAdapter] drop reason=%s channel=%s user=%s",
                decision.reason,
                ctx.channel_id,
                ctx.platform_user_id,
            )
            return

        try:
            channel_message = await self.receive_message(message)
            logger.info(
                "[SlackAdapter] Received: channel_id=%s text=%r",
                channel_message.channel_id,
                channel_message.text[:50],
            )
            ts = str(message.get("ts") or "")
            await self._add_reaction(client, channel_message.channel_id, ts, "eyes")
            response = await self._gateway.dispatch(channel_message)
            await self.send_response(
                channel_message.channel_id,
                response,
                thread_id=channel_message.metadata.get("thread_id"),
            )
            await self._add_reaction(
                client, channel_message.channel_id, ts, "white_check_mark"
            )
        except Exception as e:
            logger.error("[SlackAdapter] _handle_message error: %s", e)
            await self._add_reaction(
                client,
                str(message.get("channel") or ""),
                str(message.get("ts") or ""),
                "x",
            )
            try:
                await say("죄송합니다. 오류가 발생했습니다. 잠시 후 다시 시도해주세요.")
            except Exception:
                pass


def _context_team_id(context: Any) -> str:
    if context is None:
        return ""
    team_id = getattr(context, "team_id", None)
    if not team_id and isinstance(context, dict):
        team_id = context.get("team_id")
    return str(team_id or "").strip()
