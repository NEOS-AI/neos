"""Discord 채널 어댑터 스텁 (Phase 1 — 향후 구현 예정)

인터페이스 시그니처만 정의. 실제 구현은 discord.py>=2.3.0 사용 예정.

의존성 설치 (구현 시):
    uv add --optional channels "discord.py>=2.3.0"
"""

from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from ..base import ChannelAdapterBase, ChannelMessage

if TYPE_CHECKING:
    from ..gateway import ChannelGateway

logger = logging.getLogger(__name__)


class DiscordAdapter(ChannelAdapterBase):
    """
    Discord Bot 어댑터 (스텁)

    TODO: discord.py Client 기반으로 구현
    - on_message 이벤트 핸들러 → ChannelGateway.dispatch()
    - send_response: channel.send()
    """

    channel_type = "discord"

    def __init__(self, token: str, gateway: "ChannelGateway") -> None:
        self._token = token
        self._gateway = gateway

    async def start(self) -> None:
        logger.warning(
            "[DiscordAdapter] Discord 어댑터는 아직 구현되지 않았습니다. "
            "CHANNEL_DISCORD_ENABLED=false로 설정하세요."
        )

    async def stop(self) -> None:
        pass

    async def receive_message(self, raw: Any) -> ChannelMessage:
        raise NotImplementedError("DiscordAdapter.receive_message() is not implemented yet.")

    async def send_response(self, channel_id: str, content: str) -> None:
        raise NotImplementedError("DiscordAdapter.send_response() is not implemented yet.")
