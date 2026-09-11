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
        from neos.api.channels.session_bind import InMemoryChannelCodingBindStore

        self.binds = InMemoryChannelCodingBindStore()

    async def dispatch(self, message: Any) -> str:
        self.calls.append(message)
        return "ok"

    async def get_binding(self, session_id: str) -> Any:
        return await self.binds.get(session_id)

    async def bind_session(self, session_id: str, task_id: str, owner_id: str) -> None:
        await self.binds.bind(session_id, task_id, owner_id)


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
    inbound_media: bool = False,
) -> tuple[SlackAdapter, FakeGateway, FakeSay]:
    install_channel_settings(
        monkeypatch,
        allowed_users=allowed_users,
        require_mention=require_mention,
        ignored_channels=ignored_channels,
        inbound_media=inbound_media,
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


async def test_bound_session_without_mention_dispatches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, gateway, say = _make_adapter(monkeypatch, allowed_users=["U_alice"])
    await gateway.bind_session("v2:slack:T1:C_general:111.222", "ct_abc", "u_owner")

    await adapter._handle_message(
        _slack_message(
            text="status please",
            team="T1",
            ts="999.000",
            thread_ts="111.222",
        ),
        say,
        client=None,
    )

    assert len(gateway.calls) == 1
    assert gateway.calls[0].text == "status please"
    assert gateway.calls[0].session_id == "v2:slack:T1:C_general:111.222"
    assert say.calls == []


async def test_unbound_session_without_mention_is_silent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, gateway, say = _make_adapter(monkeypatch, allowed_users=["U_alice"])

    await adapter._handle_message(
        _slack_message(text="status please", team="T1", ts="111.222"),
        say,
        client=None,
    )

    assert gateway.calls == []
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


async def test_idempotency_key_is_slack_ts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, gateway, say = _make_adapter(monkeypatch, allowed_users=["U_alice"])
    await adapter._handle_message(
        _slack_message(team="T_workspace", ts="123.456"),
        say,
        client=None,
    )
    assert gateway.calls[0].metadata["idempotency_key"] == "123.456"


async def test_session_id_is_v2_slack_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, gateway, say = _make_adapter(monkeypatch, allowed_users=["U_alice"])

    await adapter._handle_message(
        _slack_message(team="T_workspace", ts="123.456"),
        say,
        client=None,
    )

    assert len(gateway.calls) == 1
    assert gateway.calls[0].session_id == "v2:slack:T_workspace:C_general:123.456"
    assert gateway.calls[0].metadata["thread_id"] == "123.456"


async def test_session_id_uses_thread_ts_not_message_ts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, gateway, say = _make_adapter(monkeypatch, allowed_users=["U_alice"])

    await adapter._handle_message(
        _slack_message(team="T1", ts="999.000", thread_ts="111.222"),
        say,
        client=None,
    )

    assert gateway.calls[0].session_id == "v2:slack:T1:C_general:111.222"
    assert gateway.calls[0].metadata["thread_id"] == "111.222"


async def test_follow_up_in_bot_started_thread_keeps_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, gateway, say = _make_adapter(monkeypatch, allowed_users=["U_alice"])
    await adapter._handle_message(
        _slack_message(team="T1", ts="123.456"),
        say,
        client=None,
    )
    await adapter._handle_message(
        _slack_message(team="T1", ts="123.789", thread_ts="123.456"),
        say,
        client=None,
    )
    assert gateway.calls[0].session_id == gateway.calls[1].session_id
    assert gateway.calls[0].session_id == "v2:slack:T1:C_general:123.456"


async def test_send_response_is_called_with_thread_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, gateway, say = _make_adapter(monkeypatch, allowed_users=["U_alice"])
    sent: list[dict[str, Any]] = []

    async def _record(
        channel_id: str, content: str, *, thread_id: str | None = None
    ) -> None:
        sent.append(
            {"channel_id": channel_id, "content": content, "thread_id": thread_id}
        )

    adapter.send_response = _record  # type: ignore[method-assign]

    await adapter._handle_message(
        _slack_message(ts="123.456"),
        say,
        client=None,
    )

    assert sent == [
        {"channel_id": "C_general", "content": "ok", "thread_id": "123.456"}
    ]


class FakeSlackClient:
    def __init__(self, *, fail_blocks: bool = False) -> None:
        self.posted: list[dict[str, Any]] = []
        self.updated: list[dict[str, Any]] = []
        self._fail_blocks = fail_blocks

    async def chat_postMessage(self, **kwargs: Any) -> None:
        if self._fail_blocks and kwargs.get("blocks"):
            raise RuntimeError("invalid_blocks")
        self.posted.append(kwargs)

    async def chat_update(self, **kwargs: Any) -> None:
        self.updated.append(kwargs)


def _action_ids(blocks: list[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    for block in blocks:
        for element in block.get("elements") or []:
            action_id = element.get("action_id")
            if action_id:
                ids.append(str(action_id))
    return ids


def _attach_slack_client(
    adapter: SlackAdapter, *, fail_blocks: bool = False
) -> FakeSlackClient:
    client = FakeSlackClient(fail_blocks=fail_blocks)
    adapter._app = type("FakeApp", (), {"client": client})()
    return client


async def test_send_draft_is_noop_when_flag_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, _gateway, _say = _make_adapter(monkeypatch, allowed_users=["U_alice"])
    client = _attach_slack_client(adapter)
    await adapter.send_draft("C_general", "thinking...")
    assert client.posted == []
    assert client.updated == []


async def test_send_draft_may_edit_when_flag_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, _gateway, _say = _make_adapter(monkeypatch, allowed_users=["U_alice"])
    install_channel_settings(
        monkeypatch, allowed_users=["U_alice"], draft_streaming=True
    )
    client = _attach_slack_client(adapter)
    await adapter.send_draft("C_general", "thinking...", thread_id="123.456")
    assert client.updated or client.posted


async def test_coding_start_reply_includes_stop_and_status_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, _gateway, _say = _make_adapter(monkeypatch, allowed_users=["U_alice"])
    client = _attach_slack_client(adapter)

    await adapter.send_response("C_general", "Started coding task ct_abc")

    assert len(client.posted) == 1
    payload = client.posted[0]
    assert payload["text"] == "Started coding task ct_abc"
    assert payload["channel"] == "C_general"
    blocks = payload["blocks"]
    assert _action_ids(blocks) == ["neos_code_stop", "neos_code_status"]
    values = [
        element.get("value")
        for block in blocks
        for element in block.get("elements") or []
        if element.get("action_id")
    ]
    assert values == ["ct_abc", "ct_abc"]


async def test_block_action_matches_code_session_when_message_omits_team(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, gateway, say = _make_adapter(monkeypatch, allowed_users=["U_alice"])
    adapter._team_id = "T1"

    await adapter._handle_message(
        _slack_message(text="<@U_BOT> /code fix it", ts="111.222"),
        say,
        client=None,
    )
    await adapter._handle_block_action(
        {
            "user": {"id": "U_alice"},
            "channel": {"id": "C_general"},
            "team": {"id": "T1"},
            "message": {"ts": "999.000", "thread_ts": "111.222"},
            "actions": [
                {"action_id": "neos_code_stop", "value": "ct_abc", "type": "button"}
            ],
        }
    )

    assert [call.session_id for call in gateway.calls] == [
        "v2:slack:T1:C_general:111.222",
        "v2:slack:T1:C_general:111.222",
    ]


async def test_block_action_stop_dispatches_stop_same_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, gateway, _say = _make_adapter(monkeypatch, allowed_users=["U_alice"])

    await adapter._handle_block_action(
        {
            "user": {"id": "U_alice"},
            "channel": {"id": "C_general"},
            "team": {"id": "T1"},
            "message": {"ts": "999.000", "thread_ts": "111.222"},
            "actions": [
                {"action_id": "neos_code_stop", "value": "ct_abc", "type": "button"}
            ],
        }
    )

    assert len(gateway.calls) == 1
    dispatched = gateway.calls[0]
    assert dispatched.text == "/stop"
    assert dispatched.session_id == "v2:slack:T1:C_general:111.222"
    assert dispatched.metadata["thread_id"] == "111.222"
    assert dispatched.channel_id == "C_general"


async def test_non_coding_chat_reply_has_no_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, _gateway, _say = _make_adapter(monkeypatch, allowed_users=["U_alice"])
    client = _attach_slack_client(adapter)

    await adapter.send_response("C_general", "ok")

    assert len(client.posted) == 1
    assert client.posted[0]["text"] == "ok"
    assert "blocks" not in client.posted[0]


async def test_block_action_unallowlisted_user_is_silent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, gateway, say = _make_adapter(monkeypatch, allowed_users=["U_alice"])

    await adapter._handle_block_action(
        {
            "user": {"id": "U_eve"},
            "channel": {"id": "C_general"},
            "team": {"id": "T1"},
            "message": {"ts": "123.456"},
            "actions": [
                {"action_id": "neos_code_stop", "value": "ct_abc", "type": "button"}
            ],
        }
    )

    assert gateway.calls == []
    assert say.calls == []


async def test_block_kit_post_falls_back_to_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, _gateway, _say = _make_adapter(monkeypatch, allowed_users=["U_alice"])
    client = _attach_slack_client(adapter, fail_blocks=True)

    await adapter.send_response("C_general", "Started coding task ct_abc")

    assert len(client.posted) == 1
    assert client.posted[0]["text"] == "Started coding task ct_abc"
    assert "blocks" not in client.posted[0]


async def test_status_card_includes_stop_until_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, _gateway, _say = _make_adapter(monkeypatch, allowed_users=["U_alice"])
    client = _attach_slack_client(adapter)

    await adapter.send_response("C_general", "ct_abc queued")
    await adapter.send_response("C_general", "ct_abc completed")

    assert _action_ids(client.posted[0]["blocks"]) == ["neos_code_stop"]
    assert client.posted[1]["blocks"][0]["type"] == "section"
    assert _action_ids(client.posted[1]["blocks"]) == []


async def test_receive_message_uses_bot_when_principals_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, _gateway, _say = _make_adapter(monkeypatch, allowed_users=["U_alice"])
    install_channel_settings(
        monkeypatch, allowed_users=["U_alice"], bot_user_id="bot-fallback"
    )
    message = await adapter.receive_message(_slack_message(user="U_alice"))
    assert message.user_id == "bot-fallback"


async def test_receive_message_does_not_fall_back_to_bot_when_unmapped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from neos.config.schema import ChannelPrincipal

    adapter, _gateway, _say = _make_adapter(monkeypatch, allowed_users=["U_alice"])
    install_channel_settings(
        monkeypatch,
        allowed_users=["U_alice", "U_eve"],
        bot_user_id="bot-fallback",
        principals=[
            ChannelPrincipal(
                platform="slack",
                platform_user_id="U_alice",
                user_id="u_alice",
            )
        ],
    )
    mapped = await adapter.receive_message(_slack_message(user="U_alice"))
    unmapped = await adapter.receive_message(_slack_message(user="U_eve"))
    assert mapped.user_id == "u_alice"
    assert unmapped.user_id == ""


async def test_block_action_status_and_approve_dispatch_commands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, gateway, _say = _make_adapter(monkeypatch, allowed_users=["U_alice"])
    body = {
        "user": {"id": "U_alice"},
        "channel": {"id": "C_general"},
        "team": {"id": "T1"},
        "message": {"ts": "123.456", "thread_ts": "111.222"},
    }

    await adapter._handle_block_action(
        {**body, "actions": [{"action_id": "neos_code_status", "value": "ct_abc"}]}
    )
    await adapter._handle_block_action(
        {
            **body,
            "actions": [{"action_id": "neos_code_approve", "value": "ca_1"}],
        }
    )
    await adapter._handle_block_action(
        {**body, "actions": [{"action_id": "neos_code_deny", "value": "ca_1"}]}
    )

    assert [call.text for call in gateway.calls] == [
        "/status",
        "/approve ca_1",
        "/deny ca_1",
    ]
    assert [call.metadata["idempotency_key"] for call in gateway.calls] == [
        "123.456:neos_code_status",
        "123.456:neos_code_approve",
        "123.456:neos_code_deny",
    ]
    assert all(call.session_id == "v2:slack:T1:C_general:111.222" for call in gateway.calls)


async def test_users_info_display_name_is_prefixed(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter, gateway, say = _make_adapter(monkeypatch, allowed_users=["U_alice"])

    async def users_info(user_id: str) -> dict[str, object]:
        assert user_id == "U_alice"
        return {"user": {"profile": {"display_name": "Alice"}}}

    adapter._users_info = users_info
    await adapter._handle_message(_slack_message(team="T1"), say, client=None)

    assert gateway.calls[0].metadata["slack_user_name"] == "Alice"


def _slack_video_file(
    *,
    channel_id: str = "C_general",
    ts: str = "999.000",
    thread_ts: str | None = "111.222",
    file_id: str = "F123",
) -> dict[str, object]:
    share: dict[str, object] = {"ts": ts}
    if thread_ts is not None:
        share["thread_ts"] = thread_ts
    bucket = "private" if channel_id.startswith("D") else "public"
    return {
        "file": {
            "id": file_id,
            "mimetype": "video/mp4",
            "url_private": f"https://files.slack.com/files-pri/T/{file_id}",
            "name": "clip.mp4",
            "size": 12,
            "timestamp": "555.000",
            "shares": {bucket: {channel_id: [share]}},
        }
    }


def _install_slack_video_file(
    adapter: SlackAdapter, info: dict[str, object] | None = None
) -> None:
    payload = info or _slack_video_file()
    file_obj = payload["file"]
    assert isinstance(file_obj, dict)

    async def files_info(file_id: str) -> dict[str, object]:
        assert file_id == file_obj["id"]
        return payload

    async def fetch(url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        del url, headers
        return 200, b"video-bytes"

    adapter._files_info = files_info
    adapter._media_fetch = fetch
    adapter._media_resolve = lambda _host: ["1.2.3.4"]


async def test_file_shared_video_dispatches_when_media_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, gateway, _say = _make_adapter(
        monkeypatch,
        allowed_users=["U_alice"],
        require_mention=False,
        inbound_media=True,
    )
    _install_slack_video_file(adapter)

    await adapter._handle_file_shared(
        {
            "file_id": "F123",
            "channel_id": "C_general",
            "user_id": "U_alice",
            "team_id": "T1",
        }
    )

    assert len(gateway.calls) == 1
    dispatched = gateway.calls[0]
    assert dispatched.session_id == "v2:slack:T1:C_general:111.222"
    assert dispatched.metadata["thread_id"] == "111.222"
    assert dispatched.metadata["slack_message_ts"] == "999.000"
    attachments = dispatched.metadata.get("attachments") or []
    assert attachments[0]["name"] == "clip.mp4"
    assert attachments[0]["bytes"] == b"video-bytes"


async def test_file_shared_video_wakes_bound_thread_without_mention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, gateway, say = _make_adapter(
        monkeypatch, allowed_users=["U_alice"], inbound_media=True
    )
    await gateway.bind_session("v2:slack:T1:C_general:111.222", "ct_abc", "u_owner")
    _install_slack_video_file(adapter)

    await adapter._handle_file_shared(
        {
            "file_id": "F123",
            "channel_id": "C_general",
            "user_id": "U_alice",
            "team_id": "T1",
        }
    )

    assert len(gateway.calls) == 1
    assert gateway.calls[0].session_id == "v2:slack:T1:C_general:111.222"
    assert say.calls == []


async def test_file_shared_video_dm_dispatches_without_mention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, gateway, say = _make_adapter(
        monkeypatch, allowed_users=["U_alice"], inbound_media=True
    )
    _install_slack_video_file(adapter, _slack_video_file(channel_id="D_alice"))

    await adapter._handle_file_shared(
        {
            "file_id": "F123",
            "channel_id": "D_alice",
            "user_id": "U_alice",
            "team_id": "T1",
        }
    )

    assert len(gateway.calls) == 1
    assert gateway.calls[0].channel_id == "D_alice"
    assert say.calls == []


async def test_file_shared_uses_context_team_when_event_omits_team(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, gateway, _say = _make_adapter(
        monkeypatch,
        allowed_users=["U_alice"],
        require_mention=False,
        inbound_media=True,
    )
    _install_slack_video_file(adapter)

    await adapter._handle_file_shared(
        {
            "file_id": "F123",
            "channel_id": "C_general",
            "user_id": "U_alice",
        },
        context={"team_id": "T_from_bolt"},
    )

    assert len(gateway.calls) == 1
    assert gateway.calls[0].session_id == "v2:slack:T_from_bolt:C_general:111.222"


async def test_file_shared_image_is_ignored_as_message_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, gateway, _say = _make_adapter(
        monkeypatch,
        allowed_users=["U_alice"],
        require_mention=False,
        inbound_media=True,
    )

    async def files_info(file_id: str) -> dict[str, object]:
        return {"file": {"id": file_id, "mimetype": "image/png"}}

    adapter._files_info = files_info
    await adapter._handle_file_shared(
        {"file_id": "Fimg", "channel_id": "C_general", "user_id": "U_alice"}
    )
    assert gateway.calls == []
