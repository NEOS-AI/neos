"""브라우저의 모든 요청을 호스트가 대신 받는다 -- 트랙 Q14a (W2).

Chromium 에는 네트워크가 없다(이름 풀이를 막고 죽은 프록시를 건다, `playwright_driver`).
페이지가 내는 요청은 하위 리소스·리다이렉트·폼 제출까지 전부 `context.route` 로 여기 와서
`web_fetch.v1` 과 **같은 판정 함수**를 거친다(사본이 아니다 -- 고침이 한쪽에만 닿지 않게):
허용 호스트 · 사용자 정보 금지 · 비밀 이름 질의 금지 · 풀린 주소가 전부 공개 IP.
통과하면 호스트가 IP 를 고정해 **한 홉만** 가져와 `route.fulfill` 로 돌려준다. 3xx 는
따라가지 않고 브라우저에 그대로 준다 -- 브라우저가 낸 다음 요청이 다시 여기서 판정받는다.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from urllib.parse import quote, quote_plus, unquote, unquote_plus, urlsplit

from neos.coding.browser.driver import InterceptedRequest, ServedResponse
from neos.coding.tools.executor import (
    _NoRedirect,
    _PinnedHTTPSHandler,
    _web_fetch_ip_blocked,
    _web_fetch_resolve,
    _web_fetch_safety_reason,
)

#: GET·HEAD·POST 만. 로그인 폼은 POST 다. 나머지(PUT·DELETE…)는 Q14a 에서 닫는다(W5).
ALLOWED_METHODS = frozenset({"GET", "HEAD", "POST"})
#: 호스트가 다시 정하는 것 -- 브라우저가 보낸 값을 믿지 않는다.
_REQUEST_HEADER_DROP = frozenset(
    {
        "host",
        "connection",
        "proxy-connection",
        "proxy-authorization",
        "keep-alive",
        "transfer-encoding",
        "te",
        "upgrade",
        "accept-encoding",
        "content-length",
    }
)
#: 본문은 풀린 채(identity)로 받고 길이는 fulfill 이 다시 단다.
_RESPONSE_HEADER_DROP = frozenset(
    {"content-encoding", "content-length", "transfer-encoding", "connection", "keep-alive"}
)


class EgressRefused(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class TypedSecret:
    """이 세션이 페이지에 입력한 비밀. 컨텍스트가 닫힐 때까지 **프로세스 메모리에만** 산다(W7)."""

    name: str
    origin: str
    value: str = field(repr=False)


def request_origin(url: str) -> str | None:
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return None
    host = (parts.hostname or "").rstrip(".").lower()
    if not parts.scheme or not host:
        return None
    default = {"https": 443, "http": 80}.get(parts.scheme)
    suffix = "" if port in {None, default} else f":{port}"
    return f"{parts.scheme}://{host}{suffix}"


def _variants(value: str) -> tuple[str, ...]:
    import json

    return tuple(
        {value, quote(value, safe=""), quote_plus(value), quote(value), json.dumps(value)[1:-1]}
    )


def carries_secret_elsewhere(
    request: InterceptedRequest, typed: Mapping[str, TypedSecret]
) -> bool:
    """입력한 비밀이 **그 비밀의 출처가 아닌 곳**으로 나가는가 (W8).

    URL(원문·디코딩)과 본문을 본다. 같은 출처로의 폼 제출은 막지 않는다.
    """
    if not typed:
        return False
    origin = request_origin(request.url)
    haystacks = [request.url, unquote(request.url)]
    if request.body:
        text = request.body.decode("utf-8", "replace")
        haystacks += [text, unquote_plus(text)]
    for secret in typed.values():
        if origin == secret.origin:
            continue
        for variant in _variants(secret.value):
            if any(variant in hay for hay in haystacks):
                return True
    return False


def egress_refusal(
    request: InterceptedRequest,
    *,
    allowlist: tuple[str, ...],
    typed: Mapping[str, TypedSecret],
    max_request_body_bytes: int,
) -> str | None:
    """이 요청을 내보내면 안 되는 이유. `None` 이면 내보낸다."""
    if urlsplit(request.url).scheme != "https":
        return "browser_scheme_denied"
    if request.method.upper() not in ALLOWED_METHODS:
        return "browser_method_denied"
    if request.body is not None and len(request.body) > max_request_body_bytes:
        return "browser_request_too_large"
    if carries_secret_elsewhere(request, typed):
        return "browser_secret_egress_denied"
    return _web_fetch_safety_reason(request.url, allowlist)


def _response_headers(message) -> dict[str, str]:
    merged: dict[str, list[str]] = {}
    for key, value in message.items():
        lowered = key.lower()
        if lowered in _RESPONSE_HEADER_DROP:
            continue
        merged.setdefault(lowered, []).append(str(value))
    # fulfill 은 이름당 값 하나다. 여러 Set-Cookie 는 줄바꿈으로 잇는다.
    return {
        key: ("\n" if key == "set-cookie" else ", ").join(values)
        for key, values in merged.items()
    }


def fetch_one_hop(
    request: InterceptedRequest, *, timeout_sec: float, max_response_bytes: int
) -> ServedResponse:
    """판정을 통과한 요청 하나를 고정한 IP 로 보낸다. 리다이렉트는 따라가지 않는다."""
    host = urlsplit(request.url).hostname or ""
    try:
        addresses = [a for a in _web_fetch_resolve(host) if not _web_fetch_ip_blocked(a)]
    except OSError as error:
        raise EgressRefused("web_fetch_ssrf") from error
    if not addresses:
        raise EgressRefused("web_fetch_ssrf")
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _NoRedirect(),
        _PinnedHTTPSHandler(addresses[0]),
    )
    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in _REQUEST_HEADER_DROP and not key.startswith(":")
    }
    headers["Accept-Encoding"] = "identity"
    method = request.method.upper()
    outgoing = urllib.request.Request(
        request.url,
        data=request.body if method == "POST" else None,
        method=method,
        headers=headers,
    )
    try:
        response = opener.open(outgoing, timeout=timeout_sec)
    except urllib.error.HTTPError as error:
        response = error  # 3xx·4xx·5xx 도 페이지가 받을 응답이다
    except (urllib.error.URLError, OSError) as error:
        raise EgressRefused("browser_fetch_failed") from error
    try:
        body = response.read(max_response_bytes + 1)
        if len(body) > max_response_bytes:
            raise EgressRefused("browser_response_too_large")
        status = int(getattr(response, "status", None) or response.getcode() or 502)
        return ServedResponse(status, _response_headers(response.headers), body)
    except (urllib.error.URLError, OSError) as error:
        raise EgressRefused("browser_fetch_failed") from error
    finally:
        response.close()


Fetcher = Callable[[InterceptedRequest], ServedResponse]
