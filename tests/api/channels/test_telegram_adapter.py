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
        from neos.api.channels.session_bind import InMemoryChannelCodingBindStore

        self.binds = InMemoryChannelCodingBindStore()

    async def dispatch(self, message: object) -> str:
        self.calls.append(message)
        return "ok"

    async def get_binding(self, session_id: str) -> object:
        return await self.binds.get(session_id)

    async def bind_session(self, session_id: str, task_id: str, owner_id: str) -> None:
        await self.binds.bind(session_id, task_id, owner_id)


def _fake_callback(
    *,
    data: str,
    user_id: int = ALLOWLISTED_USER_ID,
    chat_id: int = GROUP_CHAT_ID,
    chat_type: str = "supergroup",
    message_id: int = 99,
    message_thread_id: int | None = None,
) -> SimpleNamespace:
    update = _fake_update(
        text="Started coding task ct_abc",
        user_id=user_id,
        chat_id=chat_id,
        chat_type=chat_type,
        message_id=message_id,
        message_thread_id=message_thread_id,
    )
    query = SimpleNamespace(
        data=data,
        id="cbq-1",
        answer=AsyncMock(),
        from_user=update.effective_user,
        message=update.effective_message,
    )
    update.callback_query = query
    return update


def _keyboard_callback_data(markup: object) -> list[str]:
    rows = getattr(markup, "inline_keyboard", None)
    if rows is None:
        rows = markup["inline_keyboard"]  # type: ignore[index]
    data: list[str] = []
    for button in rows[0]:
        if isinstance(button, dict):
            data.append(str(button["callback_data"]))
        else:
            data.append(str(button.callback_data))
    return data


def _fake_update(
    *,
    text: str,
    user_id: int = ALLOWLISTED_USER_ID,
    chat_id: int = GROUP_CHAT_ID,
    chat_type: str = "supergroup",
    is_bot: bool = False,
    username: str = "alice",
    message_id: int = 42,
    message_thread_id: int | None = None,
) -> SimpleNamespace:
    chat = SimpleNamespace(
        id=chat_id,
        type=chat_type,
        send_action=AsyncMock(),
        send_message=AsyncMock(),
    )
    user = SimpleNamespace(id=user_id, is_bot=is_bot, username=username)
    message = SimpleNamespace(
        text=text,
        entities=[],
        message_id=message_id,
        message_thread_id=message_thread_id,
    )
    return SimpleNamespace(
        effective_chat=chat,
        effective_user=user,
        effective_message=message,
        update_id=9001,
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


async def test_bound_session_without_mention_dispatches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_channel_settings(monkeypatch, allowed_users=[str(ALLOWLISTED_USER_ID)])
    gateway = FakeGateway()
    adapter = _make_adapter(gateway)
    await gateway.bind_session(
        f"v2:telegram:{GROUP_CHAT_ID}:{GROUP_CHAT_ID}:99", "ct_abc", "u_owner"
    )
    update = _fake_update(text="status please", message_thread_id=99)

    await adapter._handle_message(update, None)

    assert len(gateway.calls) == 1
    assert gateway.calls[0].text == "status please"
    assert gateway.calls[0].session_id == f"v2:telegram:{GROUP_CHAT_ID}:{GROUP_CHAT_ID}:99"


async def test_unbound_session_without_mention_is_silent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_channel_settings(
        monkeypatch,
        allowed_users=[str(ALLOWLISTED_USER_ID)],
        require_mention=True,
    )
    gateway = FakeGateway()
    adapter = _make_adapter(gateway)
    update = _fake_update(text="status please")

    await adapter._handle_message(update, None)

    _assert_silent(update, gateway, adapter)


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


async def test_receive_message_uses_bot_when_principals_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_channel_settings(
        monkeypatch,
        allowed_users=[str(ALLOWLISTED_USER_ID)],
        bot_user_id="bot-fallback",
    )
    adapter = _make_adapter(FakeGateway())
    message = await adapter.receive_message(
        _fake_update(text=f"hey @{BOT_USERNAME} help")
    )
    assert message.user_id == "bot-fallback"


async def test_receive_message_does_not_fall_back_to_bot_when_unmapped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from neos.config.schema import ChannelPrincipal

    install_channel_settings(
        monkeypatch,
        allowed_users=[str(ALLOWLISTED_USER_ID), "77777"],
        bot_user_id="bot-fallback",
        principals=[
            ChannelPrincipal(
                platform="telegram",
                platform_user_id=str(ALLOWLISTED_USER_ID),
                user_id="u_alice",
            )
        ],
    )
    adapter = _make_adapter(FakeGateway())
    mapped = await adapter.receive_message(
        _fake_update(text=f"hey @{BOT_USERNAME} help")
    )
    unmapped = await adapter.receive_message(
        _fake_update(text=f"hey @{BOT_USERNAME} help", user_id=77777)
    )
    assert mapped.user_id == "u_alice"
    assert unmapped.user_id == ""


async def test_coding_start_reply_includes_inline_keyboard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_channel_settings(monkeypatch, allowed_users=[str(ALLOWLISTED_USER_ID)])
    adapter = _make_adapter(FakeGateway())
    await adapter.send_response(str(GROUP_CHAT_ID), "Started coding task ct_abc")
    send = adapter._app.bot.send_message
    send.assert_awaited()
    kwargs = send.await_args.kwargs
    markup = kwargs.get("reply_markup")
    assert _keyboard_callback_data(markup) == [
        "neos_code_stop:ct_abc",
        "neos_code_status:ct_abc",
    ]


async def test_ask_user_keyboard_omits_approve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_channel_settings(monkeypatch, allowed_users=[str(ALLOWLISTED_USER_ID)])
    adapter = _make_adapter(FakeGateway())
    await adapter.send_response(
        str(GROUP_CHAT_ID), "ct_1 waiting_approval ca_9 ask_user.v1"
    )
    markup = adapter._app.bot.send_message.await_args.kwargs["reply_markup"]
    callback_data = _keyboard_callback_data(markup)
    assert callback_data == ["neos_code_stop:ct_1", "neos_code_deny:ca_9"]
    assert all("approve" not in item for item in callback_data)
    assert all(
        "always" not in item.lower() and "session" not in item.lower()
        for item in callback_data
    )


async def test_callback_stop_dispatches_after_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_channel_settings(monkeypatch, allowed_users=[str(ALLOWLISTED_USER_ID)])
    gateway = FakeGateway()
    adapter = _make_adapter(gateway)
    await gateway.bind_session(
        f"v2:telegram:{GROUP_CHAT_ID}:{GROUP_CHAT_ID}:-", "ct_abc", "u_owner"
    )
    update = _fake_callback(data="neos_code_stop:ct_abc")
    await adapter._handle_callback(update, None)
    assert len(gateway.calls) == 1
    assert gateway.calls[0].text == "/stop"
    assert gateway.calls[0].session_id == f"v2:telegram:{GROUP_CHAT_ID}:{GROUP_CHAT_ID}:-"
    assert gateway.calls[0].metadata["idempotency_key"] == "99:neos_code_stop:ct_abc"
    update.callback_query.answer.assert_awaited()


async def test_callback_unallowlisted_user_is_silent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_channel_settings(monkeypatch, allowed_users=[str(ALLOWLISTED_USER_ID)])
    gateway = FakeGateway()
    adapter = _make_adapter(gateway)
    update = _fake_callback(data="neos_code_stop:ct_abc", user_id=77777)
    await adapter._handle_callback(update, None)
    assert gateway.calls == []
    update.effective_chat.send_message.assert_not_called()


async def test_session_id_starts_with_v2_telegram_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_channel_settings(monkeypatch, allowed_users=[str(ALLOWLISTED_USER_ID)])
    gateway = FakeGateway()
    adapter = _make_adapter(gateway)
    update = _fake_update(text=f"hey @{BOT_USERNAME} help")

    await adapter._handle_message(update, None)

    assert len(gateway.calls) == 1
    assert gateway.calls[0].session_id.startswith("v2:telegram:")
    assert gateway.calls[0].metadata["idempotency_key"] == "9001"


@pytest.mark.parametrize(("chat_type", "expected"), [("private", True), ("supergroup", False), ("group", False)])
async def test_receive_message_carries_the_gates_dm_verdict(
    monkeypatch: pytest.MonkeyPatch, chat_type: str, expected: bool
) -> None:
    """Q8b: the gateway attaches only DMs to an agent thread; the adapter says which."""
    from neos.api.channels.adapters.telegram import telegram_chat_is_dm

    install_channel_settings(monkeypatch, allowed_users=[str(ALLOWLISTED_USER_ID)])
    adapter = _make_adapter(FakeGateway())
    update = _fake_update(text="hello", chat_type=chat_type)

    message = await adapter.receive_message(update)

    assert message.metadata["is_dm"] is expected
    assert telegram_chat_is_dm(update.effective_chat) is expected
