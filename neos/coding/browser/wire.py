"""관리형 브라우저의 선 위 규약 -- 트랙 Q14c (docs/Q14_AGENT_BROWSER_DESIGN_261001.md §8).

호스트(`managed_driver.py`)와 샌드박스 안의 guest(`guest.py`)가 바이트 스트림 하나 위에서
주고받는 프레임. 프레임 모양(4바이트 길이 + JSON 객체, 16 MiB 상한)은 `neos-sandboxd` 의
것을 **그대로** 쓴다 -- 사본이 아니다.

방향은 셋이다:

- guest → 호스트, 맨 처음 한 번: ``{"hello": {"protocol": 1, "bundle_digest": "sha256:.."}}``
- 호스트 → guest 호출: ``{"call": n, "op": "goto", "args": {..}}``
  guest 의 답: ``{"reply": n, "ok": true, "result": .., "url": ".."}`` 또는
  ``{"reply": n, "ok": false, "error": "timeout" | "failed"}`` -- 오류는 **코드만**(W9)
- guest → 호스트 요청 하나: ``{"route": m, "request": {"url", "method", "headers", "body"}}``
  호스트의 답: ``{"route": m, "response": {"status", "headers", "body"}}`` 또는
  ``{"route": m, "abort": true}``. 본문은 base64.

Chromium 은 샌드박스 안에서도 **네트워크가 없다**(같은 `playwright_driver` 의 실행 인자). 페이지가
내는 모든 요청은 route 프레임으로 호스트에 와서 `web_fetch.v1` 판정과 IP 고정 한 홉을 지난다(W2).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import asyncio
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol

from neos.coding.browser.driver import InterceptedRequest, ServedResponse
from neos.coding.sandboxd.guest import (
    MAX_FRAME_BYTES,
    FrameError,
    decode_payload,
    encode_frame,
    frame_length,
)

__all__ = [
    "BODY_LIMIT_BYTES",
    "HEADER_BYTES",
    "OPS",
    "PROTOCOL_VERSION",
    "FrameError",
    "FrameStream",
    "WireInvalid",
    "decode_payload",
    "encode_frame",
    "frame_length",
    "guest_bundle_digest",
    "request_from_wire",
    "request_to_wire",
    "response_from_wire",
    "response_to_wire",
]

PROTOCOL_VERSION = 1
HEADER_BYTES = 4
#: 호스트가 부르는 동작 -- `driver.py` 의 메서드 하나씩(+ 컨텍스트 열기·닫기).
OPS = frozenset(
    {
        "open",
        "title",
        "goto",
        "snapshot",
        "password_values",
        "element_origin",
        "click",
        "fill",
        "press_enter",
        "close",
    }
)
#: base64(4/3) 와 머리를 더해도 프레임 상한(16 MiB) 안에 드는 본문 상한. 설정 검증이
#: 관리형 브라우저의 `max_response_bytes`·`max_request_body_bytes` 를 이것으로 막는다
#: (`neos.config.schema.MANAGED_BROWSER_MAX_BODY_BYTES` 와 같다 -- 테스트가 고정한다).
BODY_LIMIT_BYTES = 8 * 1024 * 1024
if BODY_LIMIT_BYTES * 4 // 3 + 64 * 1024 >= MAX_FRAME_BYTES:  # pragma: no cover
    raise RuntimeError("browser body limit does not fit a sandboxd frame")
_MAX_URL_CHARS = 16 * 1024
_MAX_HEADERS = 256
_MAX_HEADER_CHARS = 64 * 1024

#: guest bundle 을 이루는 파일. 하나라도 바뀌면 digest 가 바뀐다(sandboxd 의 bundle digest 와 같은 방식).
_BUNDLE = (
    "coding/browser/driver.py",
    "coding/browser/guest.py",
    "coding/browser/playwright_driver.py",
    "coding/browser/wire.py",
    "coding/sandboxd/guest.py",
)


class WireInvalid(Exception):
    """상대가 보낸 프레임의 모양이 틀렸다. 문구 없이 코드 하나."""


def guest_bundle_digest(root: str | None = None) -> str:
    """호스트가 고정하는 guest 의 digest -- `_BUNDLE` 파일의 바이트를 순서대로."""
    base = Path(root) if root else Path(__file__).resolve().parents[2]
    digest = hashlib.sha256()
    for name in _BUNDLE:
        data = (base / name).read_bytes()
        digest.update(name.encode() + b"\0" + len(data).to_bytes(8, "big") + data)
    return "sha256:" + digest.hexdigest()


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _unb64(value: object) -> bytes:
    if not isinstance(value, str):
        raise WireInvalid("body")
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        raise WireInvalid("body") from None


def _headers(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping) or len(value) > _MAX_HEADERS:
        raise WireInvalid("headers")
    out: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not isinstance(item, str):
            raise WireInvalid("headers")
        if len(key) + len(item) > _MAX_HEADER_CHARS:
            raise WireInvalid("headers")
        out[key] = item
    return out


def request_to_wire(request: InterceptedRequest) -> dict[str, Any]:
    return {
        "url": request.url,
        "method": request.method,
        "headers": dict(request.headers),
        "body": None if request.body is None else _b64(request.body),
    }


def request_from_wire(value: object) -> InterceptedRequest:
    """guest 가 보낸 요청. guest 는 페이지와 같은 신뢰 등급이다 -- 모양만 믿고 판정은 호스트가 한다."""
    if not isinstance(value, Mapping):
        raise WireInvalid("request")
    url = value.get("url")
    method = value.get("method")
    if not isinstance(url, str) or not url or len(url) > _MAX_URL_CHARS:
        raise WireInvalid("url")
    if not isinstance(method, str) or not method.isalpha() or len(method) > 16:
        raise WireInvalid("method")
    body = value.get("body")
    return InterceptedRequest(
        url=url,
        method=method,
        headers=_headers(value.get("headers", {})),
        body=None if body is None else _unb64(body),
    )


def response_to_wire(response: ServedResponse) -> dict[str, Any]:
    return {
        "status": response.status,
        "headers": dict(response.headers),
        "body": _b64(response.body),
    }


def response_from_wire(value: object) -> ServedResponse:
    if not isinstance(value, Mapping):
        raise WireInvalid("response")
    status = value.get("status")
    if not isinstance(status, int) or isinstance(status, bool) or not 100 <= status <= 599:
        raise WireInvalid("status")
    return ServedResponse(
        status=status, headers=_headers(value.get("headers", {})), body=_unb64(value.get("body"))
    )


class ByteChannel(Protocol):
    """`neos.coding.sandboxd.client.SandboxdChannel` 과 같은 모양 -- 벤더 exec 의 stdio 가 그대로 맞는다."""

    async def read_exactly(self, size: int) -> bytes: ...

    async def write(self, data: bytes) -> None: ...

    async def close(self) -> None: ...


class FrameStream:
    """바이트 채널 위의 프레임. 쓰기는 한 번에 하나(호출 답과 route 답이 섞이지 않게)."""

    def __init__(self, channel: ByteChannel) -> None:
        self._channel = channel
        self._write_lock = asyncio.Lock()

    async def read(self) -> dict:
        header = await self._channel.read_exactly(HEADER_BYTES)
        return decode_payload(await self._channel.read_exactly(frame_length(header)))

    async def write(self, message: dict) -> None:
        data = encode_frame(message)
        async with self._write_lock:
            await self._channel.write(data)

    async def close(self) -> None:
        await self._channel.close()
