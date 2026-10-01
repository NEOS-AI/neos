"""Q4b: every adapter shows each message to the channel triggers before the chat gate.

The hook is a side effect (decision D5): a message the chat gate drops for
want of a mention still reaches the triggers, and the chat path is the same
with or without them. The hook itself is replaced by a spy here -- its own
rules are tested in tests/standing/test_channel_triggers.py.
"""

from __future__ import annotations

import pytest

import neos.standing.channel_triggers as hook
from tests.api.channels import test_discord_adapter as discord
from tests.api.channels import test_slack_adapter as slack
from tests.api.channels import test_telegram_adapter as telegram


@pytest.fixture
def seen(monkeypatch):
    calls = []

    async def spy(ctx, *, message_id, thread_id=None):
        calls.append((ctx.channel_type, ctx.channel_id, ctx.platform_user_id, ctx.text,
                      message_id, thread_id))

    monkeypatch.setattr(hook, "observe_channel_message", spy)
    return calls


async def test_slack_shows_an_unmentioned_message_and_still_drops_it(monkeypatch, seen) -> None:
    adapter, gateway, say = slack._make_adapter(monkeypatch, allowed_users=["U_alice"])

    await adapter._handle_message(
        slack._slack_message(text="deploy failed", ts="5.5", thread_ts="1.1"), say, client=None
    )

    assert seen == [("slack", "C_general", "U_alice", "deploy failed", "5.5", "1.1")]
    assert gateway.calls == []


async def test_slack_mentioned_message_reaches_both(monkeypatch, seen) -> None:
    adapter, gateway, say = slack._make_adapter(monkeypatch, allowed_users=["U_alice"])

    await adapter._handle_message(slack._slack_message(ts="6.6"), say, client=None)

    assert [call[4:] for call in seen] == [("6.6", None)]
    assert len(gateway.calls) == 1


async def test_discord_shows_an_unmentioned_message(monkeypatch, seen) -> None:
    channel = discord.FakeChannel(discord.CHANNEL_ID)
    gateway = await discord._handle(
        monkeypatch, discord._message(content="build red", channel=channel), channel,
        allowed_users=[str(discord.USER_ID)],
    )

    assert seen == [("discord", str(discord.CHANNEL_ID), str(discord.USER_ID), "build red",
                     str(discord.MESSAGE_ID), None)]
    assert gateway.calls == []


async def test_telegram_shows_an_unmentioned_message(monkeypatch, seen) -> None:
    from tests.api.channels.conftest import install_channel_settings

    install_channel_settings(monkeypatch, allowed_users=[str(telegram.ALLOWLISTED_USER_ID)])
    gateway = telegram.FakeGateway()
    adapter = telegram._make_adapter(gateway)

    await adapter._handle_message(
        telegram._fake_update(text="pager", message_id=77, message_thread_id=3), None
    )

    assert seen == [("telegram", str(telegram.GROUP_CHAT_ID), str(telegram.ALLOWLISTED_USER_ID),
                     "pager", "77", "3")]
    assert gateway.calls == []
