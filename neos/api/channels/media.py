"""Inbound channel media download. Default-off at config; SSRF fail-closed."""

from __future__ import annotations

import ipaddress
import logging
import re
import socket
import urllib.error
import urllib.request
from typing import Any, Awaitable, Callable, Mapping
from urllib.parse import urljoin, urlparse

logger = logging.getLogger(__name__)

MAX_INBOUND_MEDIA_BYTES = 5 * 1024 * 1024

_ALLOWED_HOSTS = frozenset(
    {
        "files.slack.com",
        "files-origin.slack.com",
        "cdn.discordapp.com",
        "media.discordapp.net",
        "api.telegram.org",
    }
)

FetchFn = Callable[[str, dict[str, str]], Awaitable[tuple[int, bytes]]]
ResolveFn = Callable[[str], list[str]]


def is_blocked_ip(value: str) -> bool:
    try:
        addr = ipaddress.ip_address(value)
    except ValueError:
        return True
    return bool(
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    )


def _host_allowed(host: str) -> bool:
    host = (host or "").lower().rstrip(".")
    if not host:
        return False
    if host in _ALLOWED_HOSTS:
        return True
    return any(host.endswith("." + allowed) for allowed in _ALLOWED_HOSTS)


def _resolve_host(host: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError:
        return []
    ips: list[str] = []
    for info in infos:
        sockaddr = info[4]
        if sockaddr:
            ips.append(str(sockaddr[0]))
    return ips


def _url_allowed(url: str, *, resolve_host: ResolveFn | None = None) -> bool:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        return False
    if parsed.username or parsed.password:
        return False
    if parsed.port not in (None, 443):
        return False
    host = parsed.hostname or ""
    if not _host_allowed(host):
        return False
    resolver = resolve_host or _resolve_host
    ips = resolver(host)
    if not ips:
        return False
    return all(not is_blocked_ip(ip) for ip in ips)


async def download_inbound_media(
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    fetch: FetchFn | None = None,
    resolve_host: ResolveFn | None = None,
    limit: int = MAX_INBOUND_MEDIA_BYTES,
) -> bytes | None:
    data, _reason = await _download(
        url, headers=headers, fetch=fetch, resolve_host=resolve_host, limit=limit
    )
    return data


async def _download(
    url: str,
    *,
    headers: Mapping[str, str] | None,
    fetch: FetchFn | None,
    resolve_host: ResolveFn | None,
    limit: int,
) -> tuple[bytes | None, str | None]:
    """(본문, None) 또는 (None, "too_large" | "download_failed")."""
    if not _url_allowed(url, resolve_host=resolve_host):
        return None, "download_failed"
    request_headers = dict(headers or {})
    try:
        if fetch is not None:
            status, body = await fetch(url, request_headers)
        else:
            status, body = await _default_fetch(url, request_headers, limit=limit)
    except Exception as exc:
        logger.info(
            "[channel-media] download failed url=%s err=%s",
            safe_url_for_log(url),
            exc,
        )
        return None, "download_failed"
    if status != 200 or body is None:
        return None, "download_failed"
    if len(body) > limit:
        return None, "too_large"
    return body, None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def safe_url_for_log(url: str) -> str:
    return re.sub(r"/bot[^/]+/", "/bot***/", url or "")


def next_media_url(current: str, location: str) -> str | None:
    if not location:
        return None
    nxt = urljoin(current, location)
    if not _url_allowed(nxt):
        return None
    return nxt


async def _default_fetch(
    url: str, headers: dict[str, str], *, limit: int = MAX_INBOUND_MEDIA_BYTES
) -> tuple[int, bytes]:
    current = url
    for _ in range(4):
        if not _url_allowed(current):
            raise OSError("blocked media url")
        request = urllib.request.Request(current, headers=headers, method="GET")
        opener = urllib.request.build_opener(
            urllib.request.HTTPHandler,
            urllib.request.HTTPSHandler,
            _NoRedirect,
        )
        try:
            with opener.open(request, timeout=10) as response:
                status = int(getattr(response, "status", 200) or 200)
                body = response.read(limit + 1)
            return status, body
        except urllib.error.HTTPError as error:
            if error.code not in {301, 302, 303, 307, 308}:
                raise
            nxt = next_media_url(current, error.headers.get("Location") or "")
            if nxt is None:
                raise OSError("blocked media redirect")
            current = nxt
    raise OSError("too many media redirects")


def _attachment(
    *,
    name: str,
    content_type: str,
    data: bytes,
) -> dict[str, Any]:
    return {
        "name": name,
        "content_type": content_type,
        "bytes": data,
        "size": len(data),
    }


async def collect_url_attachments(
    specs: list[Mapping[str, Any]],
    *,
    headers: Mapping[str, str] | None = None,
    fetch: FetchFn | None = None,
    resolve_host: ResolveFn | None = None,
) -> list[dict[str, Any]]:
    attachments: list[dict[str, Any]] = []
    for spec in specs:
        url = str(spec.get("url") or "")
        size = int(spec.get("size") or 0)
        if size > MAX_INBOUND_MEDIA_BYTES:
            continue
        data = await download_inbound_media(
            url, headers=headers, fetch=fetch, resolve_host=resolve_host
        )
        if data is None:
            continue
        attachments.append(
            _attachment(
                name=str(spec.get("name") or "file"),
                content_type=str(spec.get("content_type") or "application/octet-stream"),
                data=data,
            )
        )
    return attachments


async def collect_slack_attachments(
    files: list[Mapping[str, Any]],
    *,
    token: str = "",
    fetch: FetchFn | None = None,
    resolve_host: ResolveFn | None = None,
) -> list[dict[str, Any]]:
    specs = []
    for item in files:
        url = str(item.get("url_private") or item.get("url_private_download") or "")
        if not url:
            continue
        specs.append(
            {
                "url": url,
                "name": item.get("name") or "file",
                "content_type": item.get("mimetype") or "application/octet-stream",
                "size": item.get("size") or 0,
            }
        )
    headers = {"Authorization": f"Bearer {token}"} if token else None
    return await collect_url_attachments(
        specs, headers=headers, fetch=fetch, resolve_host=resolve_host
    )


class DiscordAttachmentRefused(Exception):
    """Attachment present but att.read() failed. CDN URL fallback is forbidden."""

    def __init__(self, reason: str, *, name: str = "file") -> None:
        self.reason = reason
        self.name = name
        super().__init__(reason)


class _DiscordAttachmentSkip(Exception):
    def __init__(self, reason: str, *, name: str = "file") -> None:
        self.reason = reason
        self.name = name
        super().__init__(reason)


async def _read_discord_attachment_bytes(item: Any) -> bytes:
    name = str(getattr(item, "filename", None) or "file")
    try:
        size = int(getattr(item, "size", None) or 0)
    except (TypeError, ValueError):
        size = 0
    if size > MAX_INBOUND_MEDIA_BYTES:
        raise _DiscordAttachmentSkip("too_large", name=name)
    reader = getattr(item, "read", None)
    if not callable(reader):
        logger.info(
            "[channel-media] discord attachment missing read(); refusing CDN fallback name=%s",
            name,
        )
        raise DiscordAttachmentRefused("missing_read", name=name)
    try:
        data = await reader()
    except DiscordAttachmentRefused:
        raise
    except Exception as exc:
        logger.info(
            "[channel-media] discord att.read() failed name=%s err=%s",
            name,
            exc,
        )
        raise DiscordAttachmentRefused("read_failed", name=name) from exc
    if data is None:
        raise DiscordAttachmentRefused("read_failed", name=name)
    raw = bytes(data)
    if len(raw) > MAX_INBOUND_MEDIA_BYTES:
        raise _DiscordAttachmentSkip("too_large", name=name)
    return raw


async def collect_discord_attachments(
    attachments: list[Any],
) -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []
    for item in attachments:
        try:
            data = await _read_discord_attachment_bytes(item)
        except _DiscordAttachmentSkip:
            continue
        collected.append(
            _attachment(
                name=str(getattr(item, "filename", None) or "file"),
                content_type=str(getattr(item, "content_type", None)
                or "application/octet-stream"),
                data=data,
            )
        )
    return collected


async def collect_telegram_attachments(
    message: Any,
    *,
    bot: Any = None,
    fetch: FetchFn | None = None,
    resolve_host: ResolveFn | None = None,
) -> list[dict[str, Any]]:
    file_id = ""
    name = "file"
    content_type = "application/octet-stream"
    size = 0
    document = getattr(message, "document", None)
    photo = getattr(message, "photo", None) or ()
    video = getattr(message, "video", None)
    if document is not None:
        file_id = str(getattr(document, "file_id", "") or "")
        name = str(getattr(document, "file_name", None) or "file")
        content_type = str(
            getattr(document, "mime_type", None) or "application/octet-stream"
        )
        size = int(getattr(document, "file_size", None) or 0)
    elif photo:
        largest = photo[-1]
        file_id = str(getattr(largest, "file_id", "") or "")
        name = "photo.jpg"
        content_type = "image/jpeg"
        size = int(getattr(largest, "file_size", None) or 0)
    elif video is not None:
        file_id = str(getattr(video, "file_id", "") or "")
        name = str(getattr(video, "file_name", None) or "video.mp4")
        content_type = str(getattr(video, "mime_type", None) or "video/mp4")
        size = int(getattr(video, "file_size", None) or 0)
    if not file_id or bot is None:
        return []
    if size > MAX_INBOUND_MEDIA_BYTES:
        return []
    get_file = getattr(bot, "get_file", None)
    if get_file is None:
        return []
    try:
        remote = await get_file(file_id)
    except Exception as exc:
        logger.info("[channel-media] telegram get_file failed: %s", exc)
        return []
    file_path = str(getattr(remote, "file_path", "") or "")
    if not file_path:
        return []
    if file_path.startswith("https://"):
        url = file_path
    else:
        token = str(getattr(bot, "token", "") or "")
        url = f"https://api.telegram.org/file/bot{token}/{file_path.lstrip('/')}"
    data = await download_inbound_media(
        url, fetch=fetch, resolve_host=resolve_host
    )
    if data is None:
        return []
    return [_attachment(name=name, content_type=content_type, data=data)]


# ---------------------------------------------------------------- 음성 (Q15b)
#
# 설계 docs/Q15_VOICE_DESIGN_261005.md §6. `channels.voice.enabled` 일 때만, `inbound_media` 와
# 별개로 메시지당 오디오 **하나**를 `metadata["voice"]` 로 모은다. 크기·길이를 플랫폼이 알려 주면
# 상한을 **내려받기 전에** 보고, 넘으면 바이트 없이 `refused` 를 싣는다 — 문구는 게이트웨이가
# 낸다(Q15c). 어댑터의 게이트("오디오 있음")와 수집이 아래 판정 함수를 함께 쓴다.

#: Bot API getFile: "For the moment, bots can download files of up to 20MB in size."
#: https://core.telegram.org/bots/api#getfile (2026-10-05 조회). 단위를 밝히지 않아 작은 쪽(10진).
TELEGRAM_DOWNLOAD_MAX_BYTES = 20_000_000

_VOICE_EXTENSION_BY_MIME = {
    "audio/ogg": "ogg",
    "audio/opus": "ogg",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/mp4": "m4a",
    "audio/m4a": "m4a",
    "audio/x-m4a": "m4a",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/webm": "webm",
    "audio/flac": "flac",
}


def is_audio_content_type(content_type: Any) -> bool:
    mime = str(content_type or "").split(";", 1)[0].strip().lower()
    return mime.startswith("audio/")


def _voice_filename(name: Any, content_type: str, stem: str) -> str:
    given = str(name or "").strip()
    if given:
        return given
    mime = content_type.split(";", 1)[0].strip().lower()
    ext = _VOICE_EXTENSION_BY_MIME.get(mime)
    return f"{stem}.{ext}" if ext else stem


def _voice_entry(
    *,
    data: bytes | None,
    filename: str,
    content_type: str,
    duration_seconds: float | None,
    refused: str | None,
) -> dict[str, Any]:
    return {
        "bytes": data,
        "filename": filename,
        "content_type": content_type,
        "duration_seconds": duration_seconds,
        "refused": refused,
    }


def _as_seconds(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _as_size(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _refuse_before_download(
    *, size: int, duration_seconds: float | None, limit: int, max_seconds: int
) -> str | None:
    """플랫폼이 알려 준 값만으로 거절할 수 있으면 그 이유. 모르는 값(0·None)은 보지 않는다."""
    if size > limit:
        return "too_large"
    if duration_seconds is not None and duration_seconds > max_seconds:
        return "too_long"
    return None


def slack_voice_file(files: list[Any]) -> Mapping[str, Any] | None:
    """Slack 메시지의 첫 오디오 파일(`mimetype` 이 `audio/*`)."""
    for item in files or []:
        if isinstance(item, Mapping) and is_audio_content_type(item.get("mimetype")):
            return item
    return None


def discord_voice_attachment(attachments: list[Any]) -> Any | None:
    """Discord 메시지의 첫 오디오 첨부(음성 메시지 포함 — `content_type` 이 `audio/*`)."""
    for item in attachments or []:
        if is_audio_content_type(getattr(item, "content_type", None)):
            return item
    return None


def telegram_voice_media(message: Any) -> tuple[Any, str] | None:
    """Telegram 의 `voice`(음성 노트) → `audio`(오디오 파일). `document` 는 음성이 아니다."""
    voice = getattr(message, "voice", None)
    if voice is not None:
        return voice, "voice"
    audio = getattr(message, "audio", None)
    if audio is not None:
        return audio, "audio"
    return None


async def collect_slack_voice(
    item: Mapping[str, Any],
    *,
    config: Any,
    token: str = "",
    fetch: FetchFn | None = None,
    resolve_host: ResolveFn | None = None,
) -> dict[str, Any]:
    content_type = str(item.get("mimetype") or "application/octet-stream")
    filename = _voice_filename(item.get("name"), content_type, "audio")
    limit = int(config.max_bytes)
    # Slack 파일 객체에는 길이가 없다(설계 §5) — 크기만 본다.
    refused = _refuse_before_download(
        size=_as_size(item.get("size")),
        duration_seconds=None,
        limit=limit,
        max_seconds=config.max_seconds,
    )
    data: bytes | None = None
    if refused is None:
        url = str(item.get("url_private") or item.get("url_private_download") or "")
        headers = {"Authorization": f"Bearer {token}"} if token else None
        if url:
            data, refused = await _download(
                url, headers=headers, fetch=fetch, resolve_host=resolve_host, limit=limit
            )
        else:
            refused = "download_failed"
    return _voice_entry(
        data=data,
        filename=filename,
        content_type=content_type,
        duration_seconds=None,
        refused=refused,
    )


async def collect_discord_voice(item: Any, *, config: Any) -> dict[str, Any]:
    content_type = str(getattr(item, "content_type", None) or "application/octet-stream")
    filename = _voice_filename(getattr(item, "filename", None), content_type, "voice")
    duration = _as_seconds(getattr(item, "duration", None))
    limit = int(config.max_bytes)
    refused = _refuse_before_download(
        size=_as_size(getattr(item, "size", None)),
        duration_seconds=duration,
        limit=limit,
        max_seconds=config.max_seconds,
    )
    data: bytes | None = None
    if refused is None:
        reader = getattr(item, "read", None)
        raw: Any = None
        if callable(reader):  # CDN URL 로 대체하지 않는다(첨부 경로와 같은 규칙).
            try:
                raw = await reader()
            except Exception as exc:
                logger.info("[channel-media] discord voice read failed: %s", exc)
        if raw is None:
            refused = "download_failed"
        elif len(raw) > limit:
            refused = "too_large"
        else:
            data = bytes(raw)
    return _voice_entry(
        data=data,
        filename=filename,
        content_type=content_type,
        duration_seconds=duration,
        refused=refused,
    )


async def collect_telegram_voice(
    message: Any,
    *,
    config: Any,
    bot: Any = None,
    fetch: FetchFn | None = None,
    resolve_host: ResolveFn | None = None,
) -> dict[str, Any] | None:
    found = telegram_voice_media(message)
    if found is None:
        return None
    media, kind = found
    default_type = "audio/ogg" if kind == "voice" else "audio/mpeg"
    content_type = str(getattr(media, "mime_type", None) or default_type)
    filename = _voice_filename(getattr(media, "file_name", None), content_type, kind)
    duration = _as_seconds(getattr(media, "duration", None))
    limit = min(int(config.max_bytes), TELEGRAM_DOWNLOAD_MAX_BYTES)
    refused = _refuse_before_download(
        size=_as_size(getattr(media, "file_size", None)),
        duration_seconds=duration,
        limit=limit,
        max_seconds=config.max_seconds,
    )
    data: bytes | None = None
    if refused is None:
        data, refused = await _download_telegram_file(
            str(getattr(media, "file_id", "") or ""),
            bot=bot,
            fetch=fetch,
            resolve_host=resolve_host,
            limit=limit,
        )
    return _voice_entry(
        data=data,
        filename=filename,
        content_type=content_type,
        duration_seconds=duration,
        refused=refused,
    )


async def _download_telegram_file(
    file_id: str,
    *,
    bot: Any,
    fetch: FetchFn | None,
    resolve_host: ResolveFn | None,
    limit: int,
) -> tuple[bytes | None, str | None]:
    get_file = getattr(bot, "get_file", None) if bot is not None else None
    if not file_id or get_file is None:
        return None, "download_failed"
    try:
        remote = await get_file(file_id)
    except Exception as exc:
        logger.info("[channel-media] telegram voice get_file failed: %s", exc)
        return None, "download_failed"
    file_path = str(getattr(remote, "file_path", "") or "")
    if not file_path:
        return None, "download_failed"
    if file_path.startswith("https://"):
        url = file_path
    else:
        token = str(getattr(bot, "token", "") or "")
        url = f"https://api.telegram.org/file/bot{token}/{file_path.lstrip('/')}"
    return await _download(
        url, headers=None, fetch=fetch, resolve_host=resolve_host, limit=limit
    )
