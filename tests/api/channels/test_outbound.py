from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from neos.api.channels.outbound import validate_outbound_path
from tests.api.channels.conftest import install_channel_settings
from tests.api.channels.test_slack_adapter import _make_adapter

pytestmark = pytest.mark.no_db


def test_validate_outbound_denies_empty_allow_dirs(tmp_path: Path) -> None:
    target = tmp_path / "a.txt"
    target.write_text("x")
    assert validate_outbound_path(str(target), []) is None
    assert validate_outbound_path(str(target), None) is None


def test_validate_outbound_allows_path_inside_allow_dir(tmp_path: Path) -> None:
    allow = tmp_path / "out"
    allow.mkdir()
    target = allow / "ok.txt"
    target.write_text("yes")
    assert validate_outbound_path(str(target), [str(allow)]) == target.resolve()


def test_validate_outbound_denies_dotdot_escape(tmp_path: Path) -> None:
    allow = tmp_path / "out"
    allow.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("no")
    escaped = allow / ".." / "secret.txt"
    assert validate_outbound_path(str(escaped), [str(allow)]) is None
    assert validate_outbound_path(str(allow / ".." / ".." / "etc" / "passwd"), [str(allow)]) is None


def test_validate_outbound_denies_sibling_prefix_trick(tmp_path: Path) -> None:
    allow = tmp_path / "out"
    allow.mkdir()
    sibling = tmp_path / "out_evil"
    sibling.mkdir()
    target = sibling / "secret.txt"
    target.write_text("no")
    assert validate_outbound_path(str(target), [str(allow)]) is None


async def test_slack_send_file_uploads_v2_when_flag_on(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    allow = tmp_path / "out"
    allow.mkdir()
    ok = allow / "ok.txt"
    ok.write_text("yes")
    adapter, _gateway, _say = _make_adapter(monkeypatch, allowed_users=["U_alice"])
    install_channel_settings(
        monkeypatch, allowed_users=["U_alice"], outbound_files=True
    )
    uploaded: list[dict[str, object]] = []

    async def _upload_v2(*_args: object, **kwargs: object) -> None:
        uploaded.append(dict(kwargs))

    adapter._app = type(
        "App", (), {"client": type("C", (), {"files_upload_v2": _upload_v2})()}
    )()
    await adapter.send_file("C_general", str(ok), allow_dirs=[str(allow)])
    assert len(uploaded) == 1
    assert uploaded[0]["channel"] == "C_general"
    assert uploaded[0]["file"] == str(ok.resolve())


async def test_discord_send_file_uses_discord_file_when_flag_on(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from neos.api.channels.adapters.discord import DiscordAdapter
    from tests.api.channels.test_discord_adapter import CHANNEL_ID, FakeChannel, FakeGateway

    allow = tmp_path / "out"
    allow.mkdir()
    ok = allow / "note.txt"
    ok.write_text("hi")
    install_channel_settings(
        monkeypatch, allowed_users=["1001"], outbound_files=True
    )
    channel = FakeChannel(CHANNEL_ID)
    sent_files: list[Any] = []

    async def _send(*_args: object, **kwargs: object) -> None:
        sent_files.append(kwargs.get("file"))

    channel.send = _send  # type: ignore[method-assign]
    adapter = DiscordAdapter(token="test-token", gateway=FakeGateway())

    class _Client:
        def get_channel(self, channel_id: int) -> FakeChannel | None:
            return channel if int(channel_id) == CHANNEL_ID else None

        async def fetch_channel(self, channel_id: int) -> FakeChannel:
            return channel

    adapter._client = _Client()
    fake_file = SimpleNamespace(name="note.txt")

    class _FakeDiscordMod:
        class File:
            def __init__(self, path: object, **_kwargs: object) -> None:
                del path
                self.marker = fake_file

    monkeypatch.setitem(__import__("sys").modules, "discord", _FakeDiscordMod)
    await adapter.send_file(str(CHANNEL_ID), str(ok), allow_dirs=[str(allow)])
    assert sent_files
    assert getattr(sent_files[0], "marker", sent_files[0]) is fake_file


async def test_telegram_send_file_sends_document_when_flag_on(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from tests.api.channels.test_telegram_adapter import FakeGateway
    from neos.api.channels.adapters.telegram import TelegramAdapter

    allow = tmp_path / "out"
    allow.mkdir()
    ok = allow / "doc.txt"
    ok.write_text("doc")
    install_channel_settings(
        monkeypatch, allowed_users=["12345"], outbound_files=True
    )
    adapter = TelegramAdapter(token="test-token", gateway=FakeGateway())
    sent: list[dict[str, object]] = []

    async def _send_document(*_args: object, **kwargs: object) -> None:
        sent.append(dict(kwargs))

    adapter._app = type(
        "App", (), {"bot": type("B", (), {"send_document": _send_document})()}
    )()
    await adapter.send_file("-100123", str(ok), allow_dirs=[str(allow)])
    assert len(sent) == 1
    assert sent[0]["chat_id"] == "-100123"
    document = sent[0]["document"]
    assert getattr(document, "name", None) == str(ok.resolve()) or str(document) == str(
        ok.resolve()
    )


async def test_send_file_is_noop_when_flag_off_or_escape(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    allow = tmp_path / "out"
    allow.mkdir()
    ok = allow / "ok.txt"
    ok.write_text("yes")
    adapter, _gateway, _say = _make_adapter(monkeypatch, allowed_users=["U_alice"])
    sent: list[str] = []

    async def _upload(*_args: object, **_kwargs: object) -> None:
        sent.append("uploaded")

    adapter._app = type("App", (), {"client": type("C", (), {"files_upload": _upload})()})()
    await adapter.send_file("C_general", str(ok), allow_dirs=[str(allow)])
    assert sent == []

    install_channel_settings(
        monkeypatch, allowed_users=["U_alice"], outbound_files=True
    )
    escaped = allow / ".." / "secret.txt"
    escaped.write_text("no")
    await adapter.send_file("C_general", str(escaped), allow_dirs=[str(allow)])
    assert sent == []
