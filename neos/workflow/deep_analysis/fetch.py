"""HTTP retrieval that returns immutable, content-addressed blob proposals."""

from __future__ import annotations

import hashlib
from dataclasses import asdict
from html.parser import HTMLParser

import httpx
import trafilatura

from neos.config.settings import settings

from .models import ProposedBlob
from .pdf_text import pdf_bytes_to_text
from .text_norm import normalize_evidence_text


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


async def fetch_url(
    url: str,
    *,
    client=None,
    cassette=None,
) -> ProposedBlob:
    async def produce() -> dict:
        owns_client = client is None
        resolved_client = client
        if owns_client:
            resolved_client = _build_fetch_client()
        try:
            response = await resolved_client.get(url)
            status = int(response.status_code)
            if not 200 <= status < 300:
                raw_text = ""
            elif _is_pdf_response(response):
                raw_text = pdf_bytes_to_text(bytes(response.content))
            else:
                raw_text = extract_article_text(response.text)
        finally:
            if owns_client:
                await resolved_client.aclose()

        return asdict(
            ProposedBlob(
                content_hash=_blob_hash(raw_text, url, status),
                source_url=url,
                http_status=status,
                raw_text=raw_text,
            )
        )

    if cassette is None:
        return ProposedBlob(**(await produce()))

    recorded = await cassette.remember("fetch", {"url": url}, produce)
    return ProposedBlob(**recorded)
