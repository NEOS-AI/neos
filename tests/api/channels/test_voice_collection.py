"""Q15b — 채널 음성 수집(설계 `docs/Q15_VOICE_DESIGN_261005.md` §6).

실제 어댑터의 `_handle_message` 로 돈다: 게이트 → `receive_message`(수집) → 게이트웨이.
다운로드는 가짜 `fetch`/`get_file`/`att.read()` 이고, 호출 기록으로 "내려받지 않았다"를 확인한다.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from neos.api.channels.media import (
    MAX_INBOUND_MEDIA_BYTES,
    TELEGRAM_DOWNLOAD_MAX_BYTES,
    download_inbound_media,
)
from neos.config.schema import ChannelVoiceConfig
from tests.api.channels.conftest import install_channel_settings

pytestmark = pytest.mark.no_db

_VOICE_ON = ChannelVoiceConfig(enabled=True)


def _voice(**overrides: Any) -> ChannelVoiceConfig:
    return ChannelVoiceConfig(enabled=True, **overrides)


class _Fetch:
    def __init__(self, body: bytes = b"audio-bytes", status: int = 200) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []
        self._body = body
        self._status = status

    async def __call__(self, url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        self.calls.append((url, headers))
        return self._status, self._body


# ---------------------------------------------------------------- download limit


async def test_download_default_limit_is_unchanged() -> None:
    fetch = _Fetch(body=b"x" * (MAX_INBOUND_MEDIA_BYTES + 1))

    data = await download_inbound_media(
        "https://files.slack.com/x", fetch=fetch, resolve_host=lambda _h: ["1.2.3.4"]
    )

    assert data is None


async def test_download_limit_argument_raises_the_cap() -> None:
    body = b"x" * (MAX_INBOUND_MEDIA_BYTES + 1)
    fetch = _Fetch(body=body)

    data = await download_inbound_media(
        "https://files.slack.com/x",
        fetch=fetch,
        resolve_host=lambda _h: ["1.2.3.4"],
        limit=MAX_INBOUND_MEDIA_BYTES * 2,
    )

    assert data == body


async def test_download_limit_argument_lowers_the_cap() -> None:
    fetch = _Fetch(body=b"x" * 11)

    data = await download_inbound_media(
        "https://files.slack.com/x", fetch=fetch, resolve_host=lambda _h: ["1.2.3.4"], limit=10
    )

    assert data is None


# ---------------------------------------------------------------- Telegram


def _telegram(monkeypatch: pytest.MonkeyPatch, *, voice: ChannelVoiceConfig, inbound_media: bool = False):
    from tests.api.channels.test_telegram_adapter import (
        ALLOWLISTED_USER_ID,
        FakeGateway,
        _make_adapter,
    )

    install_channel_settings(
        monkeypatch,
        allowed_users=[str(ALLOWLISTED_USER_ID)],
        inbound_media=inbound_media,
        require_mention=False,
        voice=voice,
    )
    gateway = FakeGateway()
    adapter = _make_adapter(gateway)
    fetch = _Fetch(body=b"ogg-bytes")
    adapter._media_fetch = fetch  # type: ignore[attr-defined]
    adapter._media_resolve = lambda _host: ["1.2.3.4"]  # type: ignore[attr-defined]
    get_file = AsyncMock(return_value=SimpleNamespace(file_path="voice/file_1.oga"))
    adapter._app.bot.get_file = get_file
    adapter._app.bot.token = "test-token"
    return adapter, gateway, fetch, get_file


def _telegram_update(*, caption: str | None = None, voice: Any = None, audio: Any = None):
    from tests.api.channels.test_telegram_adapter import _fake_update

    update = _fake_update(text="", chat_type="private", chat_id=12345)
    message = update.effective_message
    message.text = None
    message.caption = caption
    message.photo = None
    message.document = None
    message.video = None
    message.voice = voice
    message.audio = audio
    return update


def _tg_voice(**overrides: Any) -> SimpleNamespace:
    fields = {"file_id": "voice1", "duration": 3, "mime_type": "audio/ogg", "file_size": 9}
    fields.update(overrides)
    return SimpleNamespace(**fields)


async def test_telegram_voice_is_collected_with_inbound_media_off(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter, gateway, fetch, get_file = _telegram(monkeypatch, voice=_VOICE_ON, inbound_media=False)

    await adapter._handle_message(_telegram_update(voice=_tg_voice()), None)

    assert len(gateway.calls) == 1
    message = gateway.calls[0]
    assert message.metadata["voice"] == {
        "bytes": b"ogg-bytes",
        "filename": "voice.ogg",
        "content_type": "audio/ogg",
        "duration_seconds": 3.0,
        "refused": None,
    }
    assert "attachments" not in message.metadata
    get_file.assert_awaited_once_with("voice1")
    assert fetch.calls[0][0] == "https://api.telegram.org/file/bottest-token/voice/file_1.oga"


async def test_telegram_audio_is_collected_when_there_is_no_voice(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter, gateway, _fetch, get_file = _telegram(monkeypatch, voice=_VOICE_ON)
    audio = SimpleNamespace(
        file_id="aud1", duration=40, mime_type="audio/mpeg", file_size=9, file_name="memo.mp3"
    )

    await adapter._handle_message(_telegram_update(audio=audio, caption="listen"), None)

    voice = gateway.calls[0].metadata["voice"]
    assert voice["filename"] == "memo.mp3"
    assert voice["content_type"] == "audio/mpeg"
    assert voice["duration_seconds"] == 40.0
    assert gateway.calls[0].text == "listen"
    get_file.assert_awaited_once_with("aud1")


async def test_telegram_voice_wins_over_audio(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter, gateway, _fetch, get_file = _telegram(monkeypatch, voice=_VOICE_ON)
    audio = SimpleNamespace(file_id="aud1", duration=4, mime_type="audio/mpeg", file_size=9, file_name="a.mp3")

    await adapter._handle_message(_telegram_update(voice=_tg_voice(), audio=audio), None)

    get_file.assert_awaited_once_with("voice1")
    assert gateway.calls[0].metadata["voice"]["filename"] == "voice.ogg"


async def test_telegram_voice_without_mime_defaults_to_ogg(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter, gateway, _fetch, _get_file = _telegram(monkeypatch, voice=_VOICE_ON)

    await adapter._handle_message(_telegram_update(voice=_tg_voice(mime_type=None)), None)

    voice = gateway.calls[0].metadata["voice"]
    assert voice["filename"] == "voice.ogg"
    assert voice["content_type"] == "audio/ogg"


async def test_telegram_flag_off_drops_a_voice_only_message(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter, gateway, fetch, get_file = _telegram(
        monkeypatch, voice=ChannelVoiceConfig(enabled=False), inbound_media=True
    )

    await adapter._handle_message(_telegram_update(voice=_tg_voice()), None)

    assert gateway.calls == []
    get_file.assert_not_awaited()
    assert fetch.calls == []


async def test_telegram_flag_off_with_caption_dispatches_the_caption_only(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter, gateway, fetch, get_file = _telegram(monkeypatch, voice=ChannelVoiceConfig(enabled=False))

    await adapter._handle_message(_telegram_update(voice=_tg_voice(), caption="hi"), None)

    assert len(gateway.calls) == 1
    assert gateway.calls[0].text == "hi"
    assert "voice" not in gateway.calls[0].metadata
    get_file.assert_not_awaited()
    assert fetch.calls == []


async def test_telegram_known_size_over_limit_is_refused_before_download(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter, gateway, fetch, get_file = _telegram(monkeypatch, voice=_voice(max_bytes=8))

    await adapter._handle_message(_telegram_update(voice=_tg_voice(file_size=9)), None)

    voice = gateway.calls[0].metadata["voice"]
    assert voice["refused"] == "too_large"
    assert voice["bytes"] is None
    get_file.assert_not_awaited()
    assert fetch.calls == []


async def test_telegram_platform_limit_wins_over_a_larger_max_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter, gateway, fetch, get_file = _telegram(monkeypatch, voice=_voice(max_bytes=25_000_000))

    await adapter._handle_message(
        _telegram_update(voice=_tg_voice(file_size=TELEGRAM_DOWNLOAD_MAX_BYTES + 1)), None
    )

    assert TELEGRAM_DOWNLOAD_MAX_BYTES == 20_000_000
    assert gateway.calls[0].metadata["voice"]["refused"] == "too_large"
    get_file.assert_not_awaited()
    assert fetch.calls == []


async def test_telegram_known_duration_over_limit_is_refused_before_download(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter, gateway, fetch, get_file = _telegram(monkeypatch, voice=_voice(max_seconds=60))

    await adapter._handle_message(_telegram_update(voice=_tg_voice(duration=61)), None)

    voice = gateway.calls[0].metadata["voice"]
    assert voice["refused"] == "too_long"
    assert voice["bytes"] is None
    assert voice["duration_seconds"] == 61.0
    get_file.assert_not_awaited()
    assert fetch.calls == []


async def test_telegram_unknown_size_over_limit_after_download_is_too_large(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter, gateway, fetch, _get_file = _telegram(monkeypatch, voice=_voice(max_bytes=4))

    await adapter._handle_message(_telegram_update(voice=_tg_voice(file_size=None)), None)

    voice = gateway.calls[0].metadata["voice"]
    assert len(fetch.calls) == 1
    assert voice["refused"] == "too_large"
    assert voice["bytes"] is None


async def test_telegram_get_file_failure_is_download_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter, gateway, fetch, get_file = _telegram(monkeypatch, voice=_VOICE_ON)
    get_file.side_effect = RuntimeError("telegram down")

    await adapter._handle_message(_telegram_update(voice=_tg_voice()), None)

    voice = gateway.calls[0].metadata["voice"]
    assert voice["refused"] == "download_failed"
    assert voice["bytes"] is None
    assert fetch.calls == []


async def test_telegram_http_failure_is_download_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter, gateway, fetch, _get_file = _telegram(monkeypatch, voice=_VOICE_ON)
    fetch._status = 404

    await adapter._handle_message(_telegram_update(voice=_tg_voice()), None)

    assert gateway.calls[0].metadata["voice"]["refused"] == "download_failed"


def test_telegram_inbound_filters_include_voice_and_audio() -> None:
    from neos.api.channels.adapters.telegram import telegram_inbound_filters

    voice, audio = object(), object()
    filters = SimpleNamespace(
        TEXT="text",
        PHOTO="photo",
        Document=SimpleNamespace(ALL="docs"),
        CAPTION="caption",
        VIDEO="video",
        VOICE=voice,
        AUDIO=audio,
    )

    inbound = telegram_inbound_filters(filters)

    assert voice in inbound
    assert audio in inbound


# ---------------------------------------------------------------- Slack


def _slack(
    monkeypatch: pytest.MonkeyPatch,
    *,
    voice: ChannelVoiceConfig,
    inbound_media: bool = False,
    ignored_channels: list[str] | None = None,
):
    from tests.api.channels.test_slack_adapter import FakeGateway, FakeSay
    from neos.api.channels.adapters.slack import SlackAdapter

    install_channel_settings(
        monkeypatch,
        allowed_users=["U_alice"],
        require_mention=False,
        inbound_media=inbound_media,
        ignored_channels=ignored_channels,
        voice=voice,
    )
    gateway = FakeGateway()
    adapter = SlackAdapter(token="xoxb-test", gateway=gateway)
    adapter._bot_user_id = "U_BOT"
    fetch = _Fetch(body=b"webm-bytes")
    adapter._media_fetch = fetch
    adapter._media_resolve = lambda _host: ["1.2.3.4"]
    adapter._users_info = AsyncMock(return_value=None)
    return adapter, gateway, fetch, FakeSay()


def _slack_file(file_id: str, mimetype: str, name: str, size: int = 10) -> dict[str, object]:
    return {
        "id": file_id,
        "mimetype": mimetype,
        "name": name,
        "size": size,
        "url_private": f"https://files.slack.com/files-pri/T/{file_id}",
    }


def _slack_event(files: list[dict[str, object]], *, text: str = "", **overrides: object) -> dict[str, object]:
    event: dict[str, object] = {
        "user": "U_alice",
        "channel": "D_alice",
        "channel_type": "im",
        "text": text,
        "ts": "100.000",
        "subtype": "file_share",
        "files": files,
    }
    event.update(overrides)
    return event


async def test_slack_audio_file_is_collected_with_inbound_media_off(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter, gateway, fetch, say = _slack(monkeypatch, voice=_VOICE_ON)

    await adapter._handle_message(
        _slack_event([_slack_file("F1", "audio/webm", "clip.webm")]), say, client=None
    )

    assert len(gateway.calls) == 1
    assert gateway.calls[0].metadata["voice"] == {
        "bytes": b"webm-bytes",
        "filename": "clip.webm",
        "content_type": "audio/webm",
        "duration_seconds": None,
        "refused": None,
    }
    assert "attachments" not in gateway.calls[0].metadata
    url, headers = fetch.calls[0]
    assert url == "https://files.slack.com/files-pri/T/F1"
    assert headers == {"Authorization": "Bearer xoxb-test"}


async def test_slack_first_audio_is_voice_and_stays_out_of_attachments(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter, gateway, fetch, say = _slack(monkeypatch, voice=_VOICE_ON, inbound_media=True)
    files = [
        _slack_file("F0", "image/png", "a.png"),
        _slack_file("F1", "audio/mp4", "first.m4a"),
        _slack_file("F2", "audio/mpeg", "second.mp3"),
    ]

    await adapter._handle_message(_slack_event(files), say, client=None)

    metadata = gateway.calls[0].metadata
    assert metadata["voice"]["filename"] == "first.m4a"
    names = [item["name"] for item in metadata["attachments"]]
    assert names == ["a.png", "second.mp3"]
    fetched = [url for url, _ in fetch.calls]
    assert fetched.count("https://files.slack.com/files-pri/T/F1") == 1


async def test_slack_audio_stays_an_attachment_when_voice_is_off(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter, gateway, _fetch, say = _slack(
        monkeypatch, voice=ChannelVoiceConfig(enabled=False), inbound_media=True
    )

    await adapter._handle_message(
        _slack_event([_slack_file("F1", "audio/webm", "clip.webm")]), say, client=None
    )

    metadata = gateway.calls[0].metadata
    assert "voice" not in metadata
    assert [item["name"] for item in metadata["attachments"]] == ["clip.webm"]


async def test_slack_known_size_over_limit_is_refused_before_download(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter, gateway, fetch, say = _slack(monkeypatch, voice=_voice(max_bytes=9))

    await adapter._handle_message(
        _slack_event([_slack_file("F1", "audio/webm", "clip.webm", size=10)]), say, client=None
    )

    voice = gateway.calls[0].metadata["voice"]
    assert voice["refused"] == "too_large"
    assert voice["bytes"] is None
    assert fetch.calls == []


async def test_slack_known_size_at_the_limit_is_downloaded(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter, gateway, fetch, say = _slack(monkeypatch, voice=_voice(max_bytes=10))

    await adapter._handle_message(
        _slack_event([_slack_file("F1", "audio/webm", "clip.webm", size=10)]), say, client=None
    )

    voice = gateway.calls[0].metadata["voice"]
    assert voice["refused"] is None
    assert voice["bytes"] == b"webm-bytes"
    assert len(fetch.calls) == 1


async def test_slack_flag_off_drops_an_audio_only_message(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter, gateway, fetch, say = _slack(monkeypatch, voice=ChannelVoiceConfig(enabled=False))

    await adapter._handle_message(
        _slack_event([_slack_file("F1", "audio/webm", "clip.webm")]), say, client=None
    )

    assert gateway.calls == []
    assert fetch.calls == []


async def test_slack_non_audio_file_is_not_voice(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter, gateway, fetch, say = _slack(monkeypatch, voice=_VOICE_ON)

    await adapter._handle_message(
        _slack_event([_slack_file("F1", "video/mp4", "clip.mp4")]), say, client=None
    )

    assert gateway.calls == []
    assert fetch.calls == []


async def test_slack_ignored_channel_voice_is_not_downloaded(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter, gateway, fetch, say = _slack(monkeypatch, voice=_VOICE_ON, ignored_channels=["D_alice"])

    await adapter._handle_message(
        _slack_event([_slack_file("F1", "audio/webm", "clip.webm")]), say, client=None
    )

    assert gateway.calls == []
    assert fetch.calls == []


async def test_slack_bot_voice_is_not_downloaded(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter, gateway, fetch, say = _slack(monkeypatch, voice=_VOICE_ON)

    await adapter._handle_message(
        _slack_event([_slack_file("F1", "audio/webm", "clip.webm")], bot_id="B1"), say, client=None
    )

    assert gateway.calls == []
    assert fetch.calls == []


# ---------------------------------------------------------------- Discord


class _DiscordAttachment:
    def __init__(
        self,
        *,
        filename: str = "voice-message.ogg",
        content_type: str | None = "audio/ogg",
        size: int = 10,
        duration: float | None = 2.5,
        data: bytes = b"opus-bytes",
        error: BaseException | None = None,
    ) -> None:
        self.filename = filename
        self.content_type = content_type
        self.size = size
        self.duration = duration
        self._data = data
        self._error = error
        self.reads = 0

    async def read(self) -> bytes:
        self.reads += 1
        if self._error is not None:
            raise self._error
        return self._data


async def _discord(
    monkeypatch: pytest.MonkeyPatch,
    attachments: list[_DiscordAttachment],
    *,
    voice: ChannelVoiceConfig,
    inbound_media: bool = False,
    content: str = "",
    bot: bool = False,
):
    from tests.api.channels.test_discord_adapter import (
        CHANNEL_ID,
        USER_ID,
        FakeChannel,
        FakeGateway,
        _adapter,
        _author,
        _message,
    )

    install_channel_settings(
        monkeypatch,
        allowed_users=[str(USER_ID)],
        require_mention=False,
        inbound_media=inbound_media,
        voice=voice,
    )
    channel = FakeChannel(CHANNEL_ID)
    gateway = FakeGateway()
    adapter = _adapter(gateway, channel)
    message = _message(content=content, channel=channel, guild=None, author=_author(bot=bot))
    message.attachments = attachments
    message.add_reaction = AsyncMock()
    await adapter._handle_message(message)
    return gateway, channel


async def test_discord_voice_message_is_collected_with_inbound_media_off(monkeypatch: pytest.MonkeyPatch) -> None:
    attachment = _DiscordAttachment()

    gateway, _channel = await _discord(monkeypatch, [attachment], voice=_VOICE_ON)

    assert len(gateway.calls) == 1
    assert gateway.calls[0].metadata["voice"] == {
        "bytes": b"opus-bytes",
        "filename": "voice-message.ogg",
        "content_type": "audio/ogg",
        "duration_seconds": 2.5,
        "refused": None,
    }
    assert attachment.reads == 1


async def test_discord_first_audio_is_voice_and_stays_out_of_attachments(monkeypatch: pytest.MonkeyPatch) -> None:
    image = _DiscordAttachment(filename="a.png", content_type="image/png", duration=None, data=b"png")
    first = _DiscordAttachment(filename="first.mp3", content_type="audio/mpeg", duration=None, data=b"mp3")
    second = _DiscordAttachment(filename="second.ogg", content_type="audio/ogg", duration=None, data=b"ogg")

    gateway, _channel = await _discord(
        monkeypatch, [image, first, second], voice=_VOICE_ON, inbound_media=True
    )

    metadata = gateway.calls[0].metadata
    assert metadata["voice"]["filename"] == "first.mp3"
    assert metadata["voice"]["duration_seconds"] is None
    assert [item["name"] for item in metadata["attachments"]] == ["a.png", "second.ogg"]
    assert first.reads == 1


async def test_discord_known_size_over_limit_is_refused_before_read(monkeypatch: pytest.MonkeyPatch) -> None:
    attachment = _DiscordAttachment(size=11)

    gateway, _channel = await _discord(monkeypatch, [attachment], voice=_voice(max_bytes=10))

    voice = gateway.calls[0].metadata["voice"]
    assert voice["refused"] == "too_large"
    assert voice["bytes"] is None
    assert attachment.reads == 0


async def test_discord_known_duration_over_limit_is_refused_before_read(monkeypatch: pytest.MonkeyPatch) -> None:
    attachment = _DiscordAttachment(duration=601.0)

    gateway, _channel = await _discord(monkeypatch, [attachment], voice=_voice(max_seconds=600))

    assert gateway.calls[0].metadata["voice"]["refused"] == "too_long"
    assert attachment.reads == 0


async def test_discord_read_failure_is_download_failed_not_an_attachment_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attachment = _DiscordAttachment(error=RuntimeError("cdn"))

    gateway, channel = await _discord(monkeypatch, [attachment], voice=_VOICE_ON)

    metadata = gateway.calls[0].metadata
    assert metadata["voice"]["refused"] == "download_failed"
    assert metadata["voice"]["bytes"] is None
    assert "attachments_error" not in metadata
    assert channel.sent == ["ok"]


async def test_discord_flag_off_drops_a_voice_only_message(monkeypatch: pytest.MonkeyPatch) -> None:
    attachment = _DiscordAttachment()

    gateway, _channel = await _discord(
        monkeypatch, [attachment], voice=ChannelVoiceConfig(enabled=False), inbound_media=False
    )

    assert gateway.calls == []
    assert attachment.reads == 0


async def test_discord_flag_off_with_text_dispatches_without_voice(monkeypatch: pytest.MonkeyPatch) -> None:
    attachment = _DiscordAttachment()

    gateway, _channel = await _discord(
        monkeypatch, [attachment], voice=ChannelVoiceConfig(enabled=False), content="hello"
    )

    assert len(gateway.calls) == 1
    assert "voice" not in gateway.calls[0].metadata
    assert attachment.reads == 0


async def test_discord_bot_voice_is_not_read(monkeypatch: pytest.MonkeyPatch) -> None:
    attachment = _DiscordAttachment()

    gateway, _channel = await _discord(monkeypatch, [attachment], voice=_VOICE_ON, bot=True)

    assert gateway.calls == []
    assert attachment.reads == 0
