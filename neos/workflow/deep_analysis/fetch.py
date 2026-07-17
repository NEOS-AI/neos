"""HTTP retrieval that returns immutable, content-addressed blob proposals."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import asdict
from html.parser import HTMLParser

from neos.config.settings import settings

from .models import ProposedBlob


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
    collapsed = re.sub(r"\s+", " ", " ".join(parser.parts)).strip()
    return unicodedata.normalize("NFC", collapsed)


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
            import httpx

            resolved_client = httpx.AsyncClient(
                timeout=settings.config.deep_analysis.fetch_timeout_seconds,
                follow_redirects=True,
            )
        try:
            response = await resolved_client.get(url)
            status = int(response.status_code)
            raw_text = (
                html_to_text(response.text)
                if 200 <= status < 300
                else ""
            )
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
