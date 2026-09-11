"""Telegram adapter admission gate — Phase 0."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from neos.api.channels.adapters.telegram import TelegramAdapter
from tests.api.channels.conftest import install_channel_settings

pytestmark = pytest.mark.no_db

BOT_ID = 999
BOT_USERNAME = "NeosBot"
ALLOWLISTED_USER_ID = 12345
GROUP_CHAT_ID = -100123


class FakeGateway:
    def __init__(self) -> None:
        self.calls: list[object] = []

    async def dispatch(self, message: object) -> str:
        self.calls.append(message)
        return "ok"


def _fake_update(
    *,
    text: str,
    user_id: int = ALLOWLISTED_USER_ID,
    chat_id: int = GROUP_CHAT_ID,
    chat_type: str = "supergroup",
    is_bot: bool = False,
    username: str = "alice",
) -> SimpleNamespace:
    chat = SimpleNamespace(
        id=chat_id,
        type=chat_type,
        send_action=AsyncMock(),
        send_message=AsyncMock(),
    )
    user = SimpleNamespace(id=user_id, is_bot=is_bot, username=username)
    message = SimpleNamespace(text=text, entities=[])
    return SimpleNamespace(
        effective_chat=chat,
        effective_user=user,
        effective_message=message,
    )


def _make_adapter(gateway: FakeGateway) -> TelegramAdapter:
    adapter = TelegramAdapter(token="test-token", gateway=gateway)
    adapter._app = SimpleNamespace(
        bot=SimpleNamespace(
            username=BOT_USERNAME,
            id=BOT_ID,
            send_message=AsyncMock(),
        )
    )
    return adapter


def _assert_silent(
    update: SimpleNamespace, gateway: FakeGateway, adapter: TelegramAdapter
) -> None:
    assert gateway.calls == []
    update.effective_chat.send_action.assert_not_called()
    update.effective_chat.send_message.assert_not_called()
    adapter._app.bot.send_message.assert_not_called()


async def test_mentioned_allowlisted_user_is_dispatched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_channel_settings(monkeypatch, allowed_users=[str(ALLOWLISTED_USER_ID)])
    gateway = FakeGateway()
    adapter = _make_adapter(gateway)
    text = f"hey @{BOT_USERNAME} help"
    update = _fake_update(text=text)

    await adapter._handle_message(update, None)

    assert len(gateway.calls) == 1
    assert gateway.calls[0].text == text
    assert gateway.calls[0].channel_id == str(GROUP_CHAT_ID)


async def test_channel_message_without_mention_is_silent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_channel_settings(
        monkeypatch,
        allowed_users=[str(ALLOWLISTED_USER_ID)],
        require_mention=True,
    )
    gateway = FakeGateway()
    adapter = _make_adapter(gateway)
    update = _fake_update(text="hello everyone")

    await adapter._handle_message(update, None)

    _assert_silent(update, gateway, adapter)


async def test_user_not_in_allowlist_is_silent(monkeypatch: pytest.MonkeyPatch) -> None:
    install_channel_settings(monkeypatch, allowed_users=[str(ALLOWLISTED_USER_ID)])
    gateway = FakeGateway()
    adapter = _make_adapter(gateway)
    update = _fake_update(
        text=f"hey @{BOT_USERNAME} help",
        user_id=77777,
    )

    await adapter._handle_message(update, None)

    _assert_silent(update, gateway, adapter)


async def test_empty_allowlist_is_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    install_channel_settings(monkeypatch, allowed_users=[])
    gateway = FakeGateway()
    adapter = _make_adapter(gateway)
    update = _fake_update(text=f"hey @{BOT_USERNAME} help")

    await adapter._handle_message(update, None)

    _assert_silent(update, gateway, adapter)


async def test_dm_without_mention_is_dispatched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_channel_settings(
        monkeypatch,
        allowed_users=[str(ALLOWLISTED_USER_ID)],
        require_mention=True,
    )
    gateway = FakeGateway()
    adapter = _make_adapter(gateway)
    update = _fake_update(
        text="hello",
        chat_id=ALLOWLISTED_USER_ID,
        chat_type="private",
    )

    await adapter._handle_message(update, None)

    assert len(gateway.calls) == 1
    assert gateway.calls[0].text == "hello"
    assert gateway.calls[0].channel_id == str(ALLOWLISTED_USER_ID)


async def test_bot_or_self_message_is_silent(monkeypatch: pytest.MonkeyPatch) -> None:
    install_channel_settings(monkeypatch, allowed_users=[str(ALLOWLISTED_USER_ID)])
    gateway = FakeGateway()
    adapter = _make_adapter(gateway)

    bot_update = _fake_update(
        text=f"hey @{BOT_USERNAME} help",
        user_id=88888,
        is_bot=True,
    )
    await adapter._handle_message(bot_update, None)
    _assert_silent(bot_update, gateway, adapter)

    self_update = _fake_update(
        text=f"hey @{BOT_USERNAME} help",
        user_id=BOT_ID,
        username=BOT_USERNAME,
    )
    await adapter._handle_message(self_update, None)
    _assert_silent(self_update, gateway, adapter)


async def test_ignored_channel_is_silent_even_if_mentioned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_channel_settings(
        monkeypatch,
        allowed_users=[str(ALLOWLISTED_USER_ID)],
        ignored_channels=[str(GROUP_CHAT_ID)],
    )
    gateway = FakeGateway()
    adapter = _make_adapter(gateway)
    update = _fake_update(text=f"hey @{BOT_USERNAME} help")

    await adapter._handle_message(update, None)

    _assert_silent(update, gateway, adapter)
