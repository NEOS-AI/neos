"""멀티채널 어댑터 레이어 (Phase 1 — OpenClaw Channel Adapter)

외부 메신저(Telegram, Discord, Slack 등)에서 NEOS 워크플로우를 직접 트리거한다.
채널 어댑터는 ChannelGateway를 통해 multi_agent_workflow.execute_workflow()를
HTTP 없이 직접 호출한다 (같은 프로세스 내 함수 호출).
"""

from .base import ChannelAdapterBase, ChannelMessage
from .gateway import ChannelGateway

__all__ = ["ChannelAdapterBase", "ChannelMessage", "ChannelGateway"]
