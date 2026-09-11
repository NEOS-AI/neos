"""채널 어댑터 베이스 인터페이스 (Phase 1 — OpenClaw Channel Adapter Layer)

모든 채널 어댑터(Telegram, Discord, Slack, ...)는 이 인터페이스를 구현한다.
ChannelAdapterBase는 채널별 메시지 포맷 파싱과 응답 전송만 담당하고,
워크플로우 라우팅은 ChannelGateway에 위임한다.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar, Dict, Optional


@dataclass
class ChannelMessage:
    """채널에서 수신한 정규화된 메시지."""
    user_id: str                        # NEOS 내부 user_id (채널 사용자 → NEOS 계정 매핑)
    session_id: str                     # 채널 대화를 NEOS 세션으로 매핑한 ID
    text: str                           # 사용자 입력 텍스트
    channel_type: str                   # "telegram" | "discord" | "slack"
    channel_id: str                     # 외부 채널 식별자 (Telegram chat_id, Discord channel_id 등)
    raw_data: Any = None                # 원본 webhook/update 페이로드 (디버깅용)
    metadata: Dict[str, Any] = field(default_factory=dict)  # 채널별 추가 메타데이터


class ChannelAdapterBase(ABC):
    """
    채널 어댑터 공통 인터페이스

    구현체가 제공해야 할 것:
    - channel_type: ClassVar[str] — 채널 식별자 ("telegram", "discord", ...)
    - start(): 봇/폴링/WebSocket 등 채널 연결 시작
    - stop(): 채널 연결 종료 (graceful)
    - receive_message(): 원본 페이로드를 ChannelMessage로 변환
    - send_response(): 채널에 응답 전송

    내부 워크플로우 실행은 ChannelGateway에 위임한다 (HTTP 호출 불필요).
    """

    channel_type: ClassVar[str] = ""

    @abstractmethod
    async def start(self) -> None:
        """채널 연결을 시작한다 (봇 폴링, WebSocket 연결 등)."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """채널 연결을 종료한다. graceful shutdown을 보장해야 한다."""
        ...

    @abstractmethod
    async def receive_message(self, raw: Any) -> ChannelMessage:
        """
        원본 채널 페이로드를 정규화된 ChannelMessage로 변환한다.

        Args:
            raw: 채널별 원본 메시지 객체 (Telegram Update, Discord Message 등)

        Returns:
            정규화된 ChannelMessage
        """
        ...

    @abstractmethod
    async def send_response(
        self, channel_id: str, content: str, *, thread_id: str | None = None
    ) -> None:
        """
        채널에 응답 텍스트를 전송한다.

        Args:
            channel_id: 전송 대상 채널 ID
            content: 전송할 텍스트 (채널별 길이 제한 처리는 구현체 책임)
        """
        ...
