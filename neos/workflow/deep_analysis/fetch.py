"""HTTP retrieval that returns immutable, content-addressed blob proposals."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable
from dataclasses import asdict
from html.parser import HTMLParser

import httpx
import trafilatura

from neos.config.settings import settings

from .models import ProposedBlob
from .pdf_text import pdf_bytes_to_text
from .text_norm import normalize_evidence_text

#: 다시 걸면 답이 **달라질 수 있는** 상태들 (트랙 A D2).
#:
#: 설정이 아니라 상수인 이유: 이것은 배포가 고르는 값이 아니라 HTTP 의
#: 의미다. 429 는 "지금 말고 나중에", 503 은 "지금 서버가 못 한다" 이고,
#: 둘 다 같은 요청이 나중에 성공할 수 있다고 프로토콜이 말한다. 몇 번·얼마나
#: 기다릴지는 배포 정책이라 그쪽은 설정에 있다.
#:
#: 🔴 **403 은 여기 없고, 그것이 의도다.** 403 은 "이 클라이언트에게는 안
#: 준다" 이므로 같은 요청을 다시 보내면 같은 답이 온다. 재시도는 답을 바꾸지
#: 못하면서 상대 서버에는 봇이 우기는 것으로 보인다 -- `fetch_user_agent` 가
#: 브라우저를 흉내내지 않기로 한 것과 같은 판단이다. 대신 **센다**: 403 이
#: 얼마나 남아 있는지가 D2 가 묻는 것이고, 세지 않으면 답할 수 없다.
RETRYABLE_STATUSES = frozenset({429, 503})


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() in {"script", "style"}:
            self._ignored_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style"} and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    return normalize_evidence_text(" ".join(parser.parts))


def extract_article_text(html: str) -> str:
    """Article body text, falling back to whole-page text.

    ``html_to_text`` concatenates every text node, so navigation, headers,
    footers and cookie banners arrive as evidence next to the article. That
    buried real article text deeply enough that workers reported pages as
    containing only navigation. trafilatura strips the boilerplate.

    ``include_comments=False`` matches the existing trafilatura call in
    ``neos/agents/analysis_agents.py`` — without it, reader comments are
    extracted as if they were article prose and become indistinguishable
    from body text once normalized to a single line, so a worker could quote
    a commenter's claim and have it graded as if the source asserted it.
    ``include_tables=True`` is trafilatura's own default and is passed
    explicitly for the same reason: it recovers in-content fact tables
    (e.g. Wikipedia-style ``<table class="infobox">`` markup) without
    pulling in out-of-content tables such as nav menus, since boilerplate
    removal excludes those containers regardless of this flag.

    It returns nothing on roughly 3% of pages, so those fall back to
    ``html_to_text`` — that fallback path is exactly today's behaviour, which
    keeps this change from making any page worse *on the fallback path*. On
    the success path, trafilatura can still drop content ``html_to_text``
    would have kept — e.g. a headline in a ``<header>`` outside the main
    content container, or a key-facts box marked up as ``<aside>`` (trafilatura
    treats ``<aside>`` as a sidebar and strips it, table settings included).
    Neither of those causes a false verdict (a worker can only quote what it
    sees), but both cost recall on fact-dense pages. If recall drops in a
    later baseline, this is a plausible contributing cause, not something
    this function rules out.
    """
    try:
        extracted = trafilatura.extract(
            html, include_comments=False, include_tables=True
        )
    except Exception:  # noqa: BLE001 - extractor must never break a fetch
        extracted = None
    if extracted and extracted.strip():
        return normalize_evidence_text(extracted)
    return html_to_text(html)


def _content_hash(raw_text: str) -> str:
    return hashlib.sha256(raw_text.encode("utf-8")).hexdigest()[:16]


def _blob_hash(raw_text: str, url: str, status: int) -> str:
    """Content address for a fetched blob.

    Non-empty bodies address by content (identical text from mirror URLs
    dedups to one blob — the intended cross-verification behavior). But an
    *empty* extraction (every non-2xx response, plus 2xx pages that yield no
    text) would otherwise collapse every distinct source onto
    ``sha256("")``; ``Ledger._store_blob`` keeps only the first, so a live
    200-but-empty page could inherit an earlier dead 404's ``http_status``
    and be mis-graded ``E_SOURCE_DEAD`` (and vice-versa). Disambiguate empty
    bodies by ``url``+``status`` so each real source keeps its own blob row.
    """
    if raw_text:
        return _content_hash(raw_text)
    return _content_hash(f"\x00EMPTY\x00{status}\x00{url}")


def _is_pdf_response(response) -> bool:
    headers = getattr(response, "headers", {}) or {}
    normalized_headers = {
        str(key).lower(): value for key, value in headers.items()
    }
    media_type = (
        str(normalized_headers.get("content-type", ""))
        .split(";", 1)[0]
        .strip()
        .lower()
    )
    content = getattr(response, "content", b"") or b""
    return media_type == "application/pdf" or bytes(content).lstrip().startswith(
        b"%PDF-"
    )


def _build_fetch_client():
    """The HTTP client ``fetch_url`` uses when the caller supplies none.

    The User-Agent is descriptive rather than browser-like on purpose — see
    ``DeepAnalysisConfig.fetch_user_agent``.
    """
    config = settings.config.deep_analysis
    return httpx.AsyncClient(
        timeout=config.fetch_timeout_seconds,
        follow_redirects=True,
        headers={"User-Agent": config.fetch_user_agent},
    )


def _retry_after_seconds(response, cap: float) -> float | None:
    """`Retry-After` 헤더의 초 단위 값, 상한을 씌워서.

    서버가 준 수를 **선호한다** -- 지수 백오프는 서버가 말이 없을 때 쓰는
    추측이고, 말했으면 추측보다 낫다. 날짜 형식(RFC 7231 이 허용한다)은
    파싱하지 않고 `None` 을 돌려 지수 백오프로 떨어진다: 시계 스큐를 다루는
    비용이 이 경로가 사는 값어치보다 크다.
    """
    headers = getattr(response, "headers", {}) or {}
    raw = None
    for key, value in headers.items():
        if str(key).lower() == "retry-after":
            raw = value
            break
    if raw is None:
        return None
    try:
        seconds = float(str(raw).strip())
    except (TypeError, ValueError):
        return None
    if seconds < 0:
        return None
    return min(seconds, cap)


async def fetch_url(
    url: str,
    *,
    client=None,
    cassette=None,
    on_attempt: Callable[[int, str], None] | None = None,
    sleep=asyncio.sleep,
) -> ProposedBlob:
    """URL 하나를 가져와 내용 주소가 붙은 blob 제안으로 돌려준다.

    재시도는 `RETRYABLE_STATUSES` 와 전송 오류에만 건다 (트랙 A D2). 이전에는
    재시도가 한 줄도 없어서 429 한 번이 그 출처를 **영구히** 잃게 만들었고 --
    `raw_text=""` 로 blob 이 만들어지고 워커는 그것을 빈 페이지와 구별하지
    못한다 -- 원장에는 그런 일이 있었다는 흔적조차 없었다.

    `on_attempt(status, outcome)` 은 시도마다 불린다. `fetch_url` 이 스스로
    원장에 쓰지 않는 이유는 P2 다: 워커가 세고 오케스트레이터가 쓴다. 카세트
    재생 경로에서는 불리지 않으며 그것이 옳다 -- 재생된 fetch 는 HTTP 요청을
    한 적이 없으므로 재시도 수를 보고하면 거짓말이 된다.
    """
    config = settings.config.deep_analysis
    max_attempts = max(1, config.fetch_max_attempts)
    cap = config.fetch_retry_max_sleep_seconds

    def report(status: int, outcome: str) -> None:
        if on_attempt is not None:
            on_attempt(status, outcome)

    async def produce() -> dict:
        owns_client = client is None
        resolved_client = client
        if owns_client:
            resolved_client = _build_fetch_client()
        try:
            for attempt in range(max_attempts):
                last = attempt == max_attempts - 1
                try:
                    response = await resolved_client.get(url)
                except httpx.HTTPError:
                    # 전송 오류(타임아웃·연결 리셋)는 재시도 가능하다. 마지막
                    # 시도에서까지 실패하면 던진다 -- 여기서 삼켜 빈 blob 을
                    # 만들면 "가져왔는데 비었다" 와 "못 가져왔다" 가 원장에서
                    # 같은 모양이 되고, 그것이 §3.2 의 조용한 실패다.
                    report(0, "transport_error")
                    if last:
                        raise
                    await sleep(config.fetch_retry_base_seconds * (2**attempt))
                    continue

                status = int(response.status_code)
                if status in RETRYABLE_STATUSES and not last:
                    report(status, "retrying")
                    delay = _retry_after_seconds(response, cap)
                    if delay is None:
                        delay = min(
                            config.fetch_retry_base_seconds * (2**attempt), cap
                        )
                    await sleep(delay)
                    continue

                if 200 <= status < 300:
                    report(status, "ok")
                elif status in RETRYABLE_STATUSES:
                    report(status, "exhausted")
                else:
                    # 403 이 도착하는 곳. 재시도하지 않고 세기만 한다.
                    report(status, "refused")

                if not 200 <= status < 300:
                    raw_text = ""
                elif _is_pdf_response(response):
                    raw_text = pdf_bytes_to_text(bytes(response.content))
                else:
                    raw_text = extract_article_text(response.text)

                return asdict(
                    ProposedBlob(
                        content_hash=_blob_hash(raw_text, url, status),
                        source_url=url,
                        http_status=status,
                        raw_text=raw_text,
                    )
                )
            # `max_attempts >= 1` 이므로 루프는 반드시 반환하거나 던진다.
            raise AssertionError("unreachable: retry loop neither returned nor raised")
        finally:
            if owns_client:
                await resolved_client.aclose()

    if cassette is None:
        return ProposedBlob(**(await produce()))

    recorded = await cassette.remember("fetch", {"url": url}, produce)
    return ProposedBlob(**recorded)
