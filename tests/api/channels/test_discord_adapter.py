"""Discord adapter admission gate — Phase 0."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from neos.api.channels.adapters.discord import DiscordAdapter
from tests.api.channels.conftest import install_channel_settings

pytestmark = pytest.mark.no_db

BOT_ID = 9001
USER_ID = 1001
OTHER_USER_ID = 1002
CHANNEL_ID = 2001
IGNORED_CHANNEL_ID = 2002
GUILD_ID = 3001
MESSAGE_ID = 4001


class FakeGateway:
    def __init__(self) -> None:
        self.calls: list[Any] = []

    async def dispatch(self, message: Any) -> str:
        self.calls.append(message)
        return "ok"


class _Typing:
    def __init__(self, channel: "FakeChannel") -> None:
        self._channel = channel

    async def __aenter__(self) -> "_Typing":
        self._channel.typing_started = True
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False


class FakeChannel:
    def __init__(self, channel_id: int) -> None:
        self.id = channel_id
        self.sent: list[str] = []
        self.typing_started = False

    def typing(self) -> _Typing:
        return _Typing(self)

    async def send(self, content: str) -> None:
        self.sent.append(content)


def _bot_user() -> SimpleNamespace:
    return SimpleNamespace(id=BOT_ID)


def _author(*, user_id: int = USER_ID, bot: bool = False) -> SimpleNamespace:
    return SimpleNamespace(id=user_id, bot=bot)


def _mentioned_content() -> str:
    return f"please look <@!{BOT_ID}>"


def _bot_mention() -> SimpleNamespace:
    return SimpleNamespace(id=BOT_ID)


def _message(
    *,
    author: SimpleNamespace | None = None,
    content: str = "hello",
    channel: FakeChannel | None = None,
    guild: object | None = ...,
    mentions: list[Any] | None = None,
    message_id: int = MESSAGE_ID,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=message_id,
        author=author or _author(),
        content=content,
        channel=channel or FakeChannel(CHANNEL_ID),
        guild=SimpleNamespace(id=GUILD_ID) if guild is ... else guild,
        mentions=list(mentions or []),
    )


def _adapter(gateway: FakeGateway, channel: FakeChannel) -> DiscordAdapter:
    adapter = DiscordAdapter(token="test-token", gateway=gateway)

    def get_channel(channel_id: int) -> FakeChannel | None:
        if int(channel_id) == int(channel.id):
            return channel
        return None

    adapter._client = SimpleNamespace(user=_bot_user(), get_channel=get_channel)
    return adapter


async def _handle(
    monkeypatch: pytest.MonkeyPatch,
    message: SimpleNamespace,
    channel: FakeChannel,
    *,
    allowed_users: list[str],
    require_mention: bool = True,
    ignored_channels: list[str] | None = None,
) -> FakeGateway:
    install_channel_settings(
        monkeypatch,
        allowed_users=allowed_users,
        require_mention=require_mention,
        ignored_channels=ignored_channels,
    )
    gateway = FakeGateway()
    adapter = _adapter(gateway, channel)
    await adapter._handle_message(message)
    return gateway


async def test_mentioned_allowlisted_user_is_dispatched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    channel = FakeChannel(CHANNEL_ID)
    message = _message(
        content=_mentioned_content(),
        channel=channel,
        mentions=[_bot_mention()],
    )
    gateway = await _handle(
        monkeypatch,
        message,
        channel,
        allowed_users=[str(USER_ID)],
    )
    assert len(gateway.calls) == 1
    dispatched = gateway.calls[0]
    assert dispatched.session_id == f"v2:discord:{GUILD_ID}:{CHANNEL_ID}:-"
    assert dispatched.channel_id == str(CHANNEL_ID)
    assert dispatched.text == _mentioned_content()
    assert dispatched.metadata["thread_id"] == str(MESSAGE_ID)


async def test_channel_message_without_mention_is_silent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    channel = FakeChannel(CHANNEL_ID)
    message = _message(content="hello everyone", channel=channel, mentions=[])
    gateway = await _handle(
        monkeypatch,
        message,
        channel,
        allowed_users=[str(USER_ID)],
        require_mention=True,
    )
    assert gateway.calls == []
    assert channel.sent == []
    assert channel.typing_started is False


async def test_user_not_in_allowlist_is_silent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    channel = FakeChannel(CHANNEL_ID)
    message = _message(
        author=_author(user_id=OTHER_USER_ID),
        content=_mentioned_content(),
        channel=channel,
        mentions=[_bot_mention()],
    )
    gateway = await _handle(
        monkeypatch,
        message,
        channel,
        allowed_users=[str(USER_ID)],
    )
    assert gateway.calls == []
    assert channel.sent == []
    assert channel.typing_started is False


async def test_empty_allowlist_is_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    channel = FakeChannel(CHANNEL_ID)
    message = _message(
        content=_mentioned_content(),
        channel=channel,
        mentions=[_bot_mention()],
    )
    gateway = await _handle(
        monkeypatch,
        message,
        channel,
        allowed_users=[],
    )
    assert gateway.calls == []
    assert channel.sent == []
    assert channel.typing_started is False


async def test_dm_without_mention_is_dispatched_for_allowlisted_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    channel = FakeChannel(CHANNEL_ID)
    message = _message(
        content="hello in dm",
        channel=channel,
        guild=None,
        mentions=[],
    )
    gateway = await _handle(
        monkeypatch,
        message,
        channel,
        allowed_users=[str(USER_ID)],
        require_mention=True,
    )
    assert len(gateway.calls) == 1
    assert gateway.calls[0].session_id == f"v2:discord:dm:{CHANNEL_ID}:-"


async def test_bot_or_self_message_is_dropped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_channel_settings(monkeypatch, allowed_users=[str(USER_ID)])
    gateway = FakeGateway()
    channel = FakeChannel(CHANNEL_ID)
    adapter = _adapter(gateway, channel)

    bot_message = _message(
        author=_author(user_id=OTHER_USER_ID, bot=True),
        content=_mentioned_content(),
        channel=channel,
        mentions=[_bot_mention()],
    )
    await adapter._handle_message(bot_message)
    assert gateway.calls == []
    assert channel.sent == []
    assert channel.typing_started is False

    self_channel = FakeChannel(CHANNEL_ID)
    adapter = _adapter(gateway, self_channel)
    self_message = _message(
        author=adapter._client.user,
        content=_mentioned_content(),
        channel=self_channel,
        mentions=[_bot_mention()],
    )
    await adapter._handle_message(self_message)
    assert gateway.calls == []
    assert self_channel.sent == []
    assert self_channel.typing_started is False


async def test_ignored_channel_is_dropped_even_when_mentioned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    channel = FakeChannel(IGNORED_CHANNEL_ID)
    message = _message(
        content=_mentioned_content(),
        channel=channel,
        mentions=[_bot_mention()],
    )
    gateway = await _handle(
        monkeypatch,
        message,
        channel,
        allowed_users=[str(USER_ID)],
        ignored_channels=[str(IGNORED_CHANNEL_ID)],
    )
    assert gateway.calls == []
    assert channel.sent == []
    assert channel.typing_started is False


async def test_session_id_starts_with_v2_discord(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    channel = FakeChannel(CHANNEL_ID)
    message = _message(
        content=_mentioned_content(),
        channel=channel,
        mentions=[_bot_mention()],
    )
    gateway = await _handle(
        monkeypatch,
        message,
        channel,
        allowed_users=[str(USER_ID)],
    )
    assert len(gateway.calls) == 1
    assert gateway.calls[0].session_id.startswith("v2:discord:")
