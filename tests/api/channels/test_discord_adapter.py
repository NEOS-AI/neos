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
        from neos.api.channels.session_bind import InMemoryChannelCodingBindStore

        self.binds = InMemoryChannelCodingBindStore()

    async def dispatch(self, message: Any) -> str:
        self.calls.append(message)
        return "ok"

    async def get_binding(self, session_id: str) -> Any:
        return await self.binds.get(session_id)

    async def bind_session(self, session_id: str, task_id: str, owner_id: str) -> None:
        await self.binds.bind(session_id, task_id, owner_id)


class _Typing:
    def __init__(self, channel: "FakeChannel") -> None:
        self._channel = channel

    async def __aenter__(self) -> "_Typing":
        self._channel.typing_started = True
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False


class FakeChannel:
    def __init__(
        self,
        channel_id: int,
        *,
        parent_id: int | None = None,
        type_name: str = "text",
    ) -> None:
        self.id = channel_id
        self.parent_id = parent_id
        self.type = SimpleNamespace(name=type_name)
        self.sent: list[str] = []
        self.sent_payloads: list[dict[str, Any]] = []
        self.typing_started = False
        self.threads: list["FakeChannel"] = []
        self.name = ""

    def typing(self) -> _Typing:
        return _Typing(self)

    async def send(self, content: str, **kwargs: Any) -> None:
        self.sent.append(content)
        self.sent_payloads.append({"content": content, **kwargs})


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
    registry = {int(channel.id): channel}

    def get_channel(channel_id: int) -> FakeChannel | None:
        found = registry.get(int(channel_id))
        if found is not None:
            return found
        for known in list(registry.values()):
            for thread in known.threads:
                registry[int(thread.id)] = thread
                if int(thread.id) == int(channel_id):
                    return thread
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
    assert dispatched.metadata["idempotency_key"] == str(MESSAGE_ID)


async def test_bound_session_without_mention_dispatches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    thread = FakeChannel(MESSAGE_ID, parent_id=CHANNEL_ID, type_name="public_thread")
    message = _message(content="status please", channel=thread, mentions=[])
    install_channel_settings(monkeypatch, allowed_users=[str(USER_ID)])
    gateway = FakeGateway()
    await gateway.bind_session(
        f"v2:discord:{GUILD_ID}:{CHANNEL_ID}:{MESSAGE_ID}", "ct_abc", "u_owner"
    )
    adapter = _adapter(gateway, thread)
    await adapter._handle_message(message)
    assert len(gateway.calls) == 1
    assert gateway.calls[0].text == "status please"
    assert gateway.calls[0].session_id == f"v2:discord:{GUILD_ID}:{CHANNEL_ID}:{MESSAGE_ID}"


async def test_unbound_session_without_mention_is_silent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    channel = FakeChannel(CHANNEL_ID)
    message = _message(content="status please", channel=channel, mentions=[])
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


async def test_category_parent_is_not_treated_as_a_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    channel = FakeChannel(CHANNEL_ID, parent_id=5555, type_name="text")
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
    assert gateway.calls[0].session_id == f"v2:discord:{GUILD_ID}:{CHANNEL_ID}:-"


async def test_real_thread_uses_parent_as_chat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    channel = FakeChannel(CHANNEL_ID, parent_id=5555, type_name="public_thread")
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
    assert gateway.calls[0].session_id == f"v2:discord:{GUILD_ID}:5555:{CHANNEL_ID}"


THREAD_ID = 5001


class CodingFakeGateway(FakeGateway):
    def __init__(self, reply: str = "Started coding task ct_abc") -> None:
        super().__init__()
        self.reply = reply
        from neos.api.channels.session_bind import InMemoryChannelCodingBindStore

        self.binds = InMemoryChannelCodingBindStore()

    async def dispatch(self, message: Any) -> str:
        self.calls.append(message)
        from neos.api.channels.commands import ChannelCommandKind, parse_channel_command

        command = parse_channel_command(message.text)
        if command.kind is ChannelCommandKind.CODE and command.rest:
            await self.binds.bind(message.session_id, "ct_abc", "u_owner")
            return self.reply
        return "ok"

    async def bind_session(self, session_id: str, task_id: str, owner_id: str) -> None:
        await self.binds.bind(session_id, task_id, owner_id)

    async def get_binding(self, session_id: str) -> Any:
        return await self.binds.get(session_id)


def _code_content() -> str:
    return f"<@{BOT_ID}> /code fix the tests"


def _attach_create_thread(
    message: SimpleNamespace,
    channel: FakeChannel,
    *,
    error: Exception | None = None,
    thread_id: int = THREAD_ID,
) -> list[FakeChannel]:
    created: list[FakeChannel] = []

    async def create_thread(name: str, **_kwargs: Any) -> FakeChannel:
        if error is not None:
            raise error
        thread = FakeChannel(thread_id, parent_id=channel.id, type_name="public_thread")
        thread.name = name
        channel.threads.append(thread)
        created.append(thread)
        return thread

    message.create_thread = create_thread
    message.created_threads = created
    return created


async def _handle_code(
    monkeypatch: pytest.MonkeyPatch,
    message: SimpleNamespace,
    channel: FakeChannel,
    *,
    allowed_users: list[str],
    require_mention: bool = True,
    gateway: FakeGateway | None = None,
) -> FakeGateway:
    install_channel_settings(
        monkeypatch,
        allowed_users=allowed_users,
        require_mention=require_mention,
        coding_invoke=True,
        coding_owner_user_id="u_owner",
    )
    gateway = gateway or CodingFakeGateway()
    adapter = _adapter(gateway, channel)
    await adapter._handle_message(message)
    return gateway


async def test_guild_code_creates_thread_and_replies_there(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    channel = FakeChannel(CHANNEL_ID)
    message = _message(
        content=_code_content(),
        channel=channel,
        mentions=[_bot_mention()],
    )
    created = _attach_create_thread(message, channel)

    gateway = await _handle_code(
        monkeypatch, message, channel, allowed_users=[str(USER_ID)]
    )

    assert len(gateway.calls) == 1
    assert len(created) == 1
    thread = created[0]
    assert thread.name == "code ct_abc"
    assert thread.sent == ["Started coding task ct_abc"]
    assert channel.sent == []
    thread_bind = await gateway.get_binding(
        f"v2:discord:{GUILD_ID}:{CHANNEL_ID}:{THREAD_ID}"
    )
    parent_bind = await gateway.get_binding(f"v2:discord:{GUILD_ID}:{CHANNEL_ID}:-")
    assert parent_bind is not None
    assert thread_bind is not None
    assert thread_bind.task_id == parent_bind.task_id == "ct_abc"


async def test_code_already_in_thread_does_not_create_another(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    channel = FakeChannel(CHANNEL_ID, parent_id=5555, type_name="public_thread")
    message = _message(
        content=_code_content(),
        channel=channel,
        mentions=[_bot_mention()],
    )
    created = _attach_create_thread(message, channel)

    await _handle_code(monkeypatch, message, channel, allowed_users=[str(USER_ID)])

    assert created == []
    assert channel.sent == ["Started coding task ct_abc"]


async def test_dm_code_does_not_create_a_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    channel = FakeChannel(CHANNEL_ID)
    message = _message(
        content="/code fix the tests",
        channel=channel,
        guild=None,
        mentions=[],
    )
    created = _attach_create_thread(message, channel)

    await _handle_code(
        monkeypatch,
        message,
        channel,
        allowed_users=[str(USER_ID)],
        require_mention=True,
    )

    assert created == []
    assert channel.sent == ["Started coding task ct_abc"]


async def test_thread_create_failure_replies_in_parent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    channel = FakeChannel(CHANNEL_ID)
    message = _message(
        content=_code_content(),
        channel=channel,
        mentions=[_bot_mention()],
    )
    created = _attach_create_thread(message, channel, error=RuntimeError("no threads"))

    gateway = await _handle_code(
        monkeypatch, message, channel, allowed_users=[str(USER_ID)]
    )

    assert created == []
    assert channel.sent == ["Started coding task ct_abc"]
    assert len(gateway.calls) == 1


async def test_receive_message_uses_bot_when_principals_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_channel_settings(
        monkeypatch, allowed_users=[str(USER_ID)], bot_user_id="bot-fallback"
    )
    channel = FakeChannel(CHANNEL_ID)
    adapter = _adapter(FakeGateway(), channel)
    message = await adapter.receive_message(
        _message(content=_mentioned_content(), channel=channel, mentions=[_bot_mention()])
    )
    assert message.user_id == "bot-fallback"


async def test_receive_message_does_not_fall_back_to_bot_when_unmapped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from neos.config.schema import ChannelPrincipal

    install_channel_settings(
        monkeypatch,
        allowed_users=[str(USER_ID), str(OTHER_USER_ID)],
        bot_user_id="bot-fallback",
        principals=[
            ChannelPrincipal(
                platform="discord",
                platform_user_id=str(USER_ID),
                user_id="u_alice",
            )
        ],
    )
    channel = FakeChannel(CHANNEL_ID)
    adapter = _adapter(FakeGateway(), channel)
    mapped = await adapter.receive_message(
        _message(content=_mentioned_content(), channel=channel, mentions=[_bot_mention()])
    )
    unmapped = await adapter.receive_message(
        _message(
            author=_author(user_id=OTHER_USER_ID),
            content=_mentioned_content(),
            channel=channel,
            mentions=[_bot_mention()],
        )
    )
    assert mapped.user_id == "u_alice"
    assert unmapped.user_id == ""


def _view_custom_ids(channel: FakeChannel) -> list[str]:
    if not channel.sent_payloads:
        return []
    view = channel.sent_payloads[-1].get("view")
    if view is None:
        return []
    buttons = getattr(view, "buttons", None)
    if buttons is None:
        buttons = getattr(view, "children", None) or []
    ids: list[str] = []
    for button in buttons:
        if isinstance(button, dict):
            ids.append(str(button.get("custom_id") or ""))
        else:
            ids.append(str(getattr(button, "custom_id", "") or ""))
    return ids


async def test_coding_start_reply_includes_stop_status_buttons(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    channel = FakeChannel(CHANNEL_ID)
    message = _message(
        content=_code_content(),
        channel=channel,
        mentions=[_bot_mention()],
    )
    created = _attach_create_thread(message, channel)
    await _handle_code(monkeypatch, message, channel, allowed_users=[str(USER_ID)])
    assert _view_custom_ids(created[0]) == [
        "neos_code_stop:ct_abc",
        "neos_code_status:ct_abc",
    ]


async def test_ask_user_view_omits_approve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_channel_settings(monkeypatch, allowed_users=[str(USER_ID)])
    channel = FakeChannel(CHANNEL_ID)
    adapter = _adapter(FakeGateway(), channel)
    await adapter.send_response(
        str(CHANNEL_ID), "ct_1 waiting_approval ca_9 ask_user.v1"
    )
    assert _view_custom_ids(channel) == [
        "neos_code_stop:ct_1",
        "neos_code_deny:ca_9",
    ]
    mentions = channel.sent_payloads[-1].get("allowed_mentions")
    assert mentions is not None
    assert getattr(mentions, "everyone", True) is False


async def test_button_stop_dispatches_after_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_channel_settings(monkeypatch, allowed_users=[str(USER_ID)])
    channel = FakeChannel(CHANNEL_ID, parent_id=5555, type_name="public_thread")
    gateway = FakeGateway()
    await gateway.bind_session(
        f"v2:discord:{GUILD_ID}:5555:{CHANNEL_ID}", "ct_abc", "u_owner"
    )
    adapter = _adapter(gateway, channel)
    await adapter._handle_code_action(
        user_id=str(USER_ID),
        channel=channel,
        guild_id=str(GUILD_ID),
        custom_id="neos_code_stop:ct_abc",
        is_dm=False,
        is_bot=False,
    )
    assert len(gateway.calls) == 1
    assert gateway.calls[0].text == "/stop"
    assert gateway.calls[0].session_id == f"v2:discord:{GUILD_ID}:5555:{CHANNEL_ID}"
    assert gateway.calls[0].metadata["idempotency_key"] == "neos_code_stop:ct_abc"


async def test_button_unallowlisted_user_is_silent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_channel_settings(monkeypatch, allowed_users=[str(USER_ID)])
    channel = FakeChannel(CHANNEL_ID)
    gateway = FakeGateway()
    adapter = _adapter(gateway, channel)
    await adapter._handle_code_action(
        user_id=str(OTHER_USER_ID),
        channel=channel,
        guild_id=str(GUILD_ID),
        custom_id="neos_code_stop:ct_abc",
        is_dm=False,
        is_bot=False,
    )
    assert gateway.calls == []
    assert channel.sent == []


async def test_stop_in_autothread_resolves_bind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from neos.api.channels.gateway import ChannelGateway
    from tests.api.channels.test_gateway_router import FakeCoding, FakeWorkflow

    install_channel_settings(
        monkeypatch,
        allowed_users=[str(USER_ID)],
        coding_invoke=True,
        coding_owner_user_id="u_owner",
    )
    coding = FakeCoding()
    gateway = ChannelGateway(FakeWorkflow(), coding=coding)
    channel = FakeChannel(CHANNEL_ID)
    start = _message(
        content=_code_content(),
        channel=channel,
        mentions=[_bot_mention()],
    )
    created = _attach_create_thread(start, channel)
    adapter = _adapter(gateway, channel)

    await adapter._handle_message(start)
    assert created
    thread = created[0]
    await adapter._handle_message(
        _message(
            content=f"<@{BOT_ID}> /stop",
            channel=thread,
            mentions=[_bot_mention()],
        )
    )

    assert coding.stopped == ["ct_channel"]
    assert thread.sent[-1] == "Stopped ct_channel"
