"""Learning policy: fail-closed writes, no imperative memory."""

from __future__ import annotations

import re

from neos.config.settings import settings

_IMPERATIVE = re.compile(
    r"^\s*(always|never|you must|do not|don't|must always)\b",
    re.IGNORECASE,
)

PROTECTED_SKILL_NAMES = frozenset(
    {
        "arxiv",
        "canvas",
        "cron",
        "docx",
        "github-search",
        "google-scholar",
        "news-api",
        "openalex",
        "pdf",
        "pubmed",
        "reddit",
        "research-assistant",
        "sec-edgar",
        "semantic-scholar",
        "wikipedia",
    }
)


def is_imperative(text: str) -> bool:
    return bool(text and _IMPERATIVE.search(text))


def namespace(owner_id: str, workspace_id: str | None = None) -> str:
    owner = (owner_id or "").strip() or "unknown"
    if workspace_id and workspace_id.strip():
        return f"owner:{owner}:ws:{workspace_id.strip()}"
    return f"owner:{owner}"


def is_protected_name(name: str) -> bool:
    return name in PROTECTED_SKILL_NAMES


def write_approval_required() -> bool:
    return bool(settings.config.learn.write_approval)


def max_knowledge_chars() -> int:
    return int(settings.config.learn.max_knowledge_chars)


def clip_knowledge(text: str) -> str:
    limit = max_knowledge_chars()
    body = text.strip()
    if len(body) <= limit:
        return body
    return body[:limit]
