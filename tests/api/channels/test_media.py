"""Inbound media download — default-off, SSRF fail-closed."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from neos.api.channels.media import (
    MAX_INBOUND_MEDIA_BYTES,
    download_inbound_media,
    is_blocked_ip,
    next_media_url,
    safe_url_for_log,
)
from tests.api.channels.conftest import install_channel_settings

pytestmark = pytest.mark.no_db


async def test_download_blocks_private_and_metadata_ips() -> None:
    fetched: list[str] = []

    async def fetch(url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        fetched.append(url)
        return 200, b"secret"

    for ip in ("169.254.169.254", "10.0.0.1", "127.0.0.1", "192.168.1.8", "172.16.0.1"):
        data = await download_inbound_media(
            "https://files.slack.com/files-pri/T/download/x",
            fetch=fetch,
            resolve_host=lambda _host, _ip=ip: [_ip],
        )
        assert data is None
    assert fetched == []


async def test_download_blocks_non_allowlisted_host() -> None:
    async def fetch(url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        return 200, b"nope"

    data = await download_inbound_media(
        "https://evil.example/image.png",
        fetch=fetch,
        resolve_host=lambda _host: ["1.2.3.4"],
    )
    assert data is None


async def test_download_blocks_http_and_literal_private_host() -> None:
    async def fetch(url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        raise AssertionError("must not fetch")

    assert (
        await download_inbound_media(
            "http://files.slack.com/x",
            fetch=fetch,
            resolve_host=lambda _host: ["1.2.3.4"],
        )
        is None
    )
    assert is_blocked_ip("169.254.169.254") is True
    assert is_blocked_ip("8.8.8.8") is False


async def test_download_respects_size_cap() -> None:
    async def fetch(url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        return 200, b"x" * (MAX_INBOUND_MEDIA_BYTES + 1)

    data = await download_inbound_media(
        "https://files.slack.com/files-pri/T/download/x",
        fetch=fetch,
        resolve_host=lambda _host: ["1.2.3.4"],
    )
    assert data is None


def test_redirect_to_private_ip_is_rejected() -> None:
    assert (
        next_media_url(
            "https://files.slack.com/files-pri/T/download/x",
            "https://169.254.169.254/latest/meta-data/",
        )
        is None
    )


def test_telegram_bot_token_is_redacted_in_logs() -> None:
    raw = "https://api.telegram.org/file/bot123:secret/photos/x"
    assert "secret" not in safe_url_for_log(raw)
    assert "bot***" in safe_url_for_log(raw)


async def test_download_allowlisted_public_host() -> None:
    async def fetch(url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        return 200, b"png-bytes"

    data = await download_inbound_media(
        "https://files.slack.com/files-pri/T/download/x",
        fetch=fetch,
        resolve_host=lambda _host: ["1.2.3.4"],
    )
    assert data == b"png-bytes"


async def test_slack_empty_file_is_dropped_when_media_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.api.channels.test_slack_adapter import _make_adapter

    adapter, gateway, say = _make_adapter(monkeypatch, allowed_users=["U_alice"])
    await adapter._handle_message(
        {
            "user": "U_alice",
            "channel": "C_general",
            "text": "",
            "channel_type": "channel",
            "files": [
                {
                    "name": "shot.png",
                    "mimetype": "image/png",
                    "url_private": "https://files.slack.com/files-pri/T/shot.png",
                    "size": 12,
                }
            ],
        },
        say,
        client=None,
    )
    assert gateway.calls == []
    assert say.calls == []


async def test_slack_empty_file_dispatches_when_media_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.api.channels.test_slack_adapter import _make_adapter, _slack_message

    adapter, gateway, say = _make_adapter(monkeypatch, allowed_users=["U_alice"])
    install_channel_settings(
        monkeypatch,
        allowed_users=["U_alice"],
        inbound_media=True,
        require_mention=False,
    )

    async def fetch(url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        return 200, b"png-bytes"

    adapter._media_fetch = fetch  # type: ignore[attr-defined]
    adapter._media_resolve = lambda _host: ["1.2.3.4"]  # type: ignore[attr-defined]

    await adapter._handle_message(
        _slack_message(
            text="",
            files=[
                {
                    "id": "F1",
                    "name": "shot.png",
                    "mimetype": "image/png",
                    "url_private": "https://files.slack.com/files-pri/T/shot.png",
                    "size": 9,
                }
            ],
        ),
        say,
        client=None,
    )
    assert len(gateway.calls) == 1
    attachments = gateway.calls[0].metadata["attachments"]
    assert attachments[0]["name"] == "shot.png"
    assert attachments[0]["bytes"] == b"png-bytes"


def _discord_attachment(
    *,
    filename: str = "a.png",
    content_type: str = "image/png",
    url: str = "https://cdn.discordapp.com/attachments/1/a.png",
    size: int = 3,
    data: bytes | None = b"img",
    error: BaseException | None = None,
    omit_read: bool = False,
) -> SimpleNamespace:
    attachment = SimpleNamespace(
        filename=filename,
        content_type=content_type,
        url=url,
        size=size,
    )
    if omit_read:
        return attachment

    async def read() -> bytes:
        if error is not None:
            raise error
        assert data is not None
        return data

    attachment.read = read
    return attachment


async def test_discord_empty_file_dispatches_when_media_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.api.channels.test_discord_adapter import (
        CHANNEL_ID,
        USER_ID,
        FakeChannel,
        FakeGateway,
        _adapter,
        _message,
        _bot_mention,
    )

    install_channel_settings(
        monkeypatch, allowed_users=[str(USER_ID)], inbound_media=True
    )
    channel = FakeChannel(CHANNEL_ID)
    gateway = FakeGateway()
    adapter = _adapter(gateway, channel)
    fetched: list[str] = []

    async def fetch(url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        fetched.append(url)
        return 200, b"cdn-should-not-run"

    adapter._media_fetch = fetch  # type: ignore[attr-defined]
    adapter._media_resolve = lambda _host: ["1.2.3.4"]  # type: ignore[attr-defined]
    message = _message(
        content="",
        channel=channel,
        mentions=[_bot_mention()],
    )
    message.attachments = [_discord_attachment()]
    await adapter._handle_message(message)
    assert len(gateway.calls) == 1
    assert gateway.calls[0].metadata["attachments"][0]["bytes"] == b"img"
    assert fetched == []


async def test_discord_att_read_uses_authenticated_bytes() -> None:
    from neos.api.channels.media import collect_discord_attachments

    attachments = await collect_discord_attachments(
        [_discord_attachment(data=b"from-read")]
    )
    assert attachments[0]["bytes"] == b"from-read"
    assert attachments[0]["name"] == "a.png"


async def test_discord_att_read_403_is_refused() -> None:
    from neos.api.channels.media import (
        DiscordAttachmentRefused,
        collect_discord_attachments,
    )

    with pytest.raises(DiscordAttachmentRefused) as exc_info:
        await collect_discord_attachments(
            [_discord_attachment(error=OSError("HTTP 403"))]
        )
    assert exc_info.value.reason == "read_failed"


async def test_discord_missing_read_is_refused() -> None:
    from neos.api.channels.media import (
        DiscordAttachmentRefused,
        collect_discord_attachments,
    )

    with pytest.raises(DiscordAttachmentRefused) as exc_info:
        await collect_discord_attachments([_discord_attachment(omit_read=True)])
    assert exc_info.value.reason == "missing_read"


async def test_discord_oversized_attachment_is_skipped() -> None:
    from neos.api.channels.media import (
        MAX_INBOUND_MEDIA_BYTES,
        collect_discord_attachments,
    )

    attachments = await collect_discord_attachments(
        [
            _discord_attachment(
                filename="huge.bin",
                size=MAX_INBOUND_MEDIA_BYTES + 1,
                data=b"x",
            ),
            _discord_attachment(filename="ok.png", data=b"ok"),
        ]
    )
    assert [item["name"] for item in attachments] == ["ok.png"]
    assert attachments[0]["bytes"] == b"ok"


async def test_discord_partial_read_failure_refuses_all() -> None:
    from neos.api.channels.media import (
        DiscordAttachmentRefused,
        collect_discord_attachments,
    )

    with pytest.raises(DiscordAttachmentRefused):
        await collect_discord_attachments(
            [
                _discord_attachment(filename="ok.png", data=b"ok"),
                _discord_attachment(
                    filename="bad.png", error=OSError("HTTP 403")
                ),
            ]
        )


async def test_discord_read_failure_does_not_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.api.channels.test_discord_adapter import (
        CHANNEL_ID,
        USER_ID,
        FakeChannel,
        FakeGateway,
        _adapter,
        _message,
        _bot_mention,
    )

    install_channel_settings(
        monkeypatch, allowed_users=[str(USER_ID)], inbound_media=True
    )
    channel = FakeChannel(CHANNEL_ID)
    gateway = FakeGateway()
    adapter = _adapter(gateway, channel)
    fetched: list[str] = []

    async def fetch(url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        fetched.append(url)
        return 200, b"cdn"

    adapter._media_fetch = fetch  # type: ignore[attr-defined]
    adapter._media_resolve = lambda _host: ["1.2.3.4"]  # type: ignore[attr-defined]
    message = _message(
        content="look at this",
        channel=channel,
        mentions=[_bot_mention()],
    )
    message.attachments = [_discord_attachment(error=OSError("HTTP 403"))]
    await adapter._handle_message(message)
    assert gateway.calls == []
    assert fetched == []
    assert channel.sent == ["Could not read the attached file."]


async def test_telegram_empty_photo_dispatches_when_media_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.api.channels.test_telegram_adapter import (
        ALLOWLISTED_USER_ID,
        BOT_USERNAME,
        FakeGateway,
        _fake_update,
        _make_adapter,
    )

    install_channel_settings(
        monkeypatch,
        allowed_users=[str(ALLOWLISTED_USER_ID)],
        inbound_media=True,
        require_mention=False,
    )
    gateway = FakeGateway()
    adapter = _make_adapter(gateway)

    async def fetch(url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        return 200, b"photo"

    adapter._media_fetch = fetch  # type: ignore[attr-defined]
    adapter._media_resolve = lambda _host: ["1.2.3.4"]  # type: ignore[attr-defined]

    async def get_file(file_id: str) -> SimpleNamespace:
        return SimpleNamespace(file_path="photos/a.jpg")

    adapter._app.bot.get_file = get_file
    adapter._app.bot.token = "test-token"
    update = _fake_update(text="")
    update.effective_message.text = None
    update.effective_message.caption = None
    update.effective_message.photo = [SimpleNamespace(file_id="ph1", file_size=5)]
    update.effective_message.document = None
    await adapter._handle_message(update, None)
    assert len(gateway.calls) == 1
    assert gateway.calls[0].metadata["attachments"][0]["bytes"] == b"photo"


def _telegram_video_update():
    from tests.api.channels.test_telegram_adapter import _fake_update

    update = _fake_update(text="")
    update.effective_message.text = None
    update.effective_message.caption = None
    update.effective_message.photo = None
    update.effective_message.document = None
    update.effective_message.video = SimpleNamespace(
        file_id="vid1",
        file_name="clip.mp4",
        mime_type="video/mp4",
        file_size=11,
    )
    return update


async def test_telegram_video_is_ignored_when_inbound_media_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.api.channels.test_telegram_adapter import (
        ALLOWLISTED_USER_ID,
        FakeGateway,
        _make_adapter,
    )

    install_channel_settings(
        monkeypatch,
        allowed_users=[str(ALLOWLISTED_USER_ID)],
        inbound_media=False,
        require_mention=False,
    )
    gateway = FakeGateway()
    adapter = _make_adapter(gateway)
    fetched: list[str] = []

    async def fetch(url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        fetched.append(url)
        return 200, b"video-bytes"

    adapter._media_fetch = fetch  # type: ignore[attr-defined]
    adapter._media_resolve = lambda _host: ["1.2.3.4"]  # type: ignore[attr-defined]
    update = _telegram_video_update()
    await adapter._handle_message(update, None)
    assert gateway.calls == []
    assert fetched == []


async def test_telegram_video_downloads_when_inbound_media_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.api.channels.test_telegram_adapter import (
        ALLOWLISTED_USER_ID,
        FakeGateway,
        _make_adapter,
    )

    install_channel_settings(
        monkeypatch,
        allowed_users=[str(ALLOWLISTED_USER_ID)],
        inbound_media=True,
        require_mention=False,
    )
    gateway = FakeGateway()
    adapter = _make_adapter(gateway)

    async def fetch(url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        return 200, b"video-bytes"

    adapter._media_fetch = fetch  # type: ignore[attr-defined]
    adapter._media_resolve = lambda _host: ["1.2.3.4"]  # type: ignore[attr-defined]

    async def get_file(file_id: str) -> SimpleNamespace:
        assert file_id == "vid1"
        return SimpleNamespace(file_path="videos/clip.mp4")

    adapter._app.bot.get_file = get_file
    adapter._app.bot.token = "test-token"
    update = _telegram_video_update()
    await adapter._handle_message(update, None)
    assert len(gateway.calls) == 1
    attachment = gateway.calls[0].metadata["attachments"][0]
    assert attachment["name"] == "clip.mp4"
    assert attachment["content_type"] == "video/mp4"
    assert attachment["bytes"] == b"video-bytes"


def test_telegram_inbound_filters_include_video() -> None:
    from neos.api.channels.adapters.telegram import telegram_inbound_filters

    video = object()
    filters = SimpleNamespace(
        TEXT="text",
        PHOTO="photo",
        Document=SimpleNamespace(ALL="docs"),
        CAPTION="caption",
        VIDEO=video,
    )
    inbound = telegram_inbound_filters(filters)
    assert video in inbound
