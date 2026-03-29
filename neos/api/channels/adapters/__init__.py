"""채널 어댑터 구현체 패키지

현재 구현:
- TelegramAdapter: python-telegram-bot>=21.0 사용 (완전 구현)

스텁 (인터페이스만, 향후 구현):
- DiscordAdapter
- SlackAdapter
"""

from .telegram import TelegramAdapter
from .discord import DiscordAdapter
from .slack import SlackAdapter

__all__ = ["TelegramAdapter", "DiscordAdapter", "SlackAdapter"]
