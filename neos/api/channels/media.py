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
) -> bytes | None:
    if not _url_allowed(url, resolve_host=resolve_host):
        return None
    request_headers = dict(headers or {})
    try:
        if fetch is not None:
            status, body = await fetch(url, request_headers)
        else:
            status, body = await _default_fetch(url, request_headers)
    except Exception as exc:
        logger.info(
            "[channel-media] download failed url=%s err=%s",
            safe_url_for_log(url),
            exc,
        )
        return None
    if status != 200 or body is None:
        return None
    if len(body) > MAX_INBOUND_MEDIA_BYTES:
        return None
    return body


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


async def _default_fetch(url: str, headers: dict[str, str]) -> tuple[int, bytes]:
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
                body = response.read(MAX_INBOUND_MEDIA_BYTES + 1)
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


async def collect_discord_attachments(
    attachments: list[Any],
    *,
    fetch: FetchFn | None = None,
    resolve_host: ResolveFn | None = None,
) -> list[dict[str, Any]]:
    specs = []
    for item in attachments:
        specs.append(
            {
                "url": getattr(item, "url", None) or "",
                "name": getattr(item, "filename", None) or "file",
                "content_type": getattr(item, "content_type", None)
                or "application/octet-stream",
                "size": getattr(item, "size", None) or 0,
            }
        )
    return await collect_url_attachments(
        specs, fetch=fetch, resolve_host=resolve_host
    )


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
