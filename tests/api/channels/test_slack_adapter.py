"""Slack adapter admission gate — Phase 0.

Dropped messages must be silent: no ChannelGateway.dispatch, no say().
"""

from __future__ import annotations

from typing import Any

import pytest

from neos.api.channels.adapters.slack import SlackAdapter
from tests.api.channels.conftest import install_channel_settings

pytestmark = pytest.mark.no_db


class FakeGateway:
    def __init__(self) -> None:
        self.calls: list[Any] = []

    async def dispatch(self, message: Any) -> str:
        self.calls.append(message)
        return "ok"


class FakeSay:
    def __init__(self) -> None:
        self.calls: list[Any] = []

    async def __call__(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append((args, kwargs))


def _slack_message(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "user": "U_alice",
        "channel": "C_general",
        "text": "hello <@U_BOT>",
        "channel_type": "channel",
    }
    payload.update(overrides)
    return payload


def _make_adapter(
    monkeypatch: pytest.MonkeyPatch,
    *,
    allowed_users: list[str],
    require_mention: bool = True,
    ignored_channels: list[str] | None = None,
) -> tuple[SlackAdapter, FakeGateway, FakeSay]:
    install_channel_settings(
        monkeypatch,
        allowed_users=allowed_users,
        require_mention=require_mention,
        ignored_channels=ignored_channels,
    )
    gateway = FakeGateway()
    adapter = SlackAdapter(token="xoxb-test", gateway=gateway)
    adapter._bot_user_id = "U_BOT"
    return adapter, gateway, FakeSay()


async def test_mentioned_allowlisted_user_dispatches_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, gateway, say = _make_adapter(monkeypatch, allowed_users=["U_alice"])

    await adapter._handle_message(_slack_message(), say, client=None)

    assert len(gateway.calls) == 1
    assert gateway.calls[0].text == "hello <@U_BOT>"
    assert gateway.calls[0].channel_id == "C_general"
    assert say.calls == []


async def test_channel_message_without_mention_is_silent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, gateway, say = _make_adapter(monkeypatch, allowed_users=["U_alice"])

    await adapter._handle_message(
        _slack_message(text="hello everyone"),
        say,
        client=None,
    )

    assert gateway.calls == []
    assert say.calls == []


async def test_user_not_in_allowlist_is_silent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, gateway, say = _make_adapter(monkeypatch, allowed_users=["U_alice"])

    await adapter._handle_message(
        _slack_message(user="U_eve"),
        say,
        client=None,
    )

    assert gateway.calls == []
    assert say.calls == []


async def test_empty_allowlist_is_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, gateway, say = _make_adapter(monkeypatch, allowed_users=[])

    await adapter._handle_message(_slack_message(), say, client=None)

    assert gateway.calls == []
    assert say.calls == []


async def test_dm_without_mention_dispatches_when_allowlisted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, gateway, say = _make_adapter(monkeypatch, allowed_users=["U_alice"])

    await adapter._handle_message(
        _slack_message(text="hello", channel_type="im", channel="D_alice"),
        say,
        client=None,
    )

    assert len(gateway.calls) == 1
    assert gateway.calls[0].text == "hello"
    assert gateway.calls[0].channel_id == "D_alice"
    assert say.calls == []


async def test_bot_or_self_message_is_dropped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, gateway, say = _make_adapter(monkeypatch, allowed_users=["U_alice", "U_BOT"])

    await adapter._handle_message(
        _slack_message(bot_id="B123", user="U_BOT"),
        say,
        client=None,
    )
    await adapter._handle_message(
        _slack_message(subtype="bot_message", user="B_OTHER"),
        say,
        client=None,
    )
    await adapter._handle_message(
        _slack_message(user="U_BOT"),
        say,
        client=None,
    )

    assert gateway.calls == []
    assert say.calls == []


async def test_ignored_channel_is_dropped_even_when_mentioned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, gateway, say = _make_adapter(
        monkeypatch,
        allowed_users=["U_alice"],
        ignored_channels=["C_noise"],
    )

    await adapter._handle_message(
        _slack_message(channel="C_noise"),
        say,
        client=None,
    )

    assert gateway.calls == []
    assert say.calls == []
