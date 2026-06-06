from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse


def normalize_repair_source(
    raw: dict[str, Any],
    index: int,
    action_type: str,
    *,
    retrieved_at: datetime | None = None,
) -> dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    metadata = dict(raw.get("metadata") or {}) if isinstance(raw.get("metadata"), dict) else {}
    url = str(raw.get("url") or raw.get("link") or raw.get("source_url") or "")
    domain = str(raw.get("domain") or _domain_from_url(url))
    published_at = _first_present(
        raw,
        metadata,
        ("published_at", "published_date", "date", "timestamp", "last_updated"),
    )
    retrieved = retrieved_at or datetime.now(timezone.utc)
    provider_score = raw.get("score")
    if provider_score is not None:
        metadata["provider_score"] = provider_score
    if not published_at:
        metadata["date_missing"] = True

    return {
        "id": f"repair_{action_type}_{index}",
        "title": str(raw.get("title") or raw.get("source") or f"Repair source {index}"),
        "url": url,
        "content": str(raw.get("content") or raw.get("snippet") or raw.get("raw_content") or raw.get("summary") or ""),
        "domain": domain,
        "published_at": published_at,
        "retrieved_at": retrieved.isoformat(),
        "repair_action": action_type,
        "metadata": metadata,
    }


def dedupe_sources(
    existing: list[dict[str, Any]],
    new: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in [*existing, *new]:
        if not isinstance(source, dict):
            continue
        identity = _source_identity(source)
        if identity in seen:
            continue
        seen.add(identity)
        sources.append(source)
    return sources


def sources_for_section(
    existing_sources: list[dict[str, Any]],
    new_sources: list[dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    if limit <= 0:
        return []
    return dedupe_sources(existing_sources, new_sources)[:limit]


def dominant_domains_from_sources(sources: list[dict[str, Any]]) -> list[str]:
    counts = Counter()
    for source in sources:
        if not isinstance(source, dict):
            continue
        domain = str(source.get("domain") or _domain_from_url(str(source.get("url") or "")))
        if domain:
            counts[domain] += 1
    return [domain for domain, _ in counts.most_common()]


def _source_identity(source: dict[str, Any]) -> str:
    url = str(source.get("url") or "").strip().rstrip("/").lower()
    if url:
        return f"url:{url}"
    title = str(source.get("title") or "").strip().lower()
    domain = str(source.get("domain") or _domain_from_url(str(source.get("url") or ""))).lower()
    return f"title-domain:{title}:{domain}"


def _domain_from_url(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    return parsed.netloc.lower()


def _first_present(
    raw: dict[str, Any],
    metadata: dict[str, Any],
    keys: tuple[str, ...],
) -> Any:
    for source in (raw, metadata):
        for key in keys:
            value = source.get(key)
            if value:
                return value.isoformat() if isinstance(value, datetime) else value
    return None
