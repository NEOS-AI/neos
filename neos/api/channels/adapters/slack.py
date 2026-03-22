"""Slack 채널 어댑터 스텁 (Phase 1 — 향후 구현 예정)

인터페이스 시그니처만 정의. 실제 구현은 slack-bolt>=1.18.0 사용 예정.
AsyncSocketModeHandler를 사용하면 추가 HTTP 포트 없이 구현 가능.

의존성 설치 (구현 시):
    uv add --optional channels "slack-bolt>=1.18.0"
"""

from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from ..base import ChannelAdapterBase, ChannelMessage

if TYPE_CHECKING:
    from ..gateway import ChannelGateway

logger = logging.getLogger(__name__)


class SlackAdapter(ChannelAdapterBase):
    """
    Slack Bot 어댑터 (스텁)

    TODO: slack-bolt AsyncApp + AsyncSocketModeHandler 기반으로 구현
    - @app.message() 핸들러 → ChannelGateway.dispatch()
    - send_response: client.chat_postMessage()
    - CHANNEL_SLACK_APP_TOKEN 필요 (Socket Mode용)
    """

    channel_type = "slack"

    def __init__(self, token: str, gateway: "ChannelGateway") -> None:
        self._token = token
        self._gateway = gateway

    async def start(self) -> None:
        logger.warning(
            "[SlackAdapter] Slack 어댑터는 아직 구현되지 않았습니다. "
            "CHANNEL_SLACK_ENABLED=false로 설정하세요."
        )

    async def stop(self) -> None:
        pass

    async def receive_message(self, raw: Any) -> ChannelMessage:
        raise NotImplementedError("SlackAdapter.receive_message() is not implemented yet.")

    async def send_response(self, channel_id: str, content: str) -> None:
        raise NotImplementedError("SlackAdapter.send_response() is not implemented yet.")
