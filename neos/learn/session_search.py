"""Cross-session search. user_id is required. No LLM summary."""

from __future__ import annotations

from typing import Any

HIDDEN_SESSION_ORIGINS = frozenset(
    {"cron", "subagent", "subrun", "tool", "kanban", "scheduler"}
)
SNIPPET_MAX_CHARS = 240
_ORIGIN_KEYS = ("origin", "source", "mode", "channel_source")


def _as_origin_token(value: object) -> str | None:
    if value is None:
        return None
    token = str(value).strip().lower()
    return token or None


def _origin_tokens(row: dict[str, Any]) -> set[str]:
    tokens: set[str] = set()
    for key in _ORIGIN_KEYS:
        token = _as_origin_token(row.get(key))
        if token:
            tokens.add(token)
    conversation = row.get("conversation")
    if isinstance(conversation, dict):
        for key in _ORIGIN_KEYS:
            token = _as_origin_token(conversation.get(key))
            if token:
                tokens.add(token)
    metadata = row.get("metadata")
    if isinstance(metadata, dict):
        for key in _ORIGIN_KEYS:
            token = _as_origin_token(metadata.get(key))
            if token:
                tokens.add(token)
    return tokens


def is_hidden_session_row(row: dict[str, Any]) -> bool:
    return bool(_origin_tokens(row) & HIDDEN_SESSION_ORIGINS)


def clip_session_text(row: dict[str, Any]) -> str:
    snippet = row.get("snippet")
    content = row.get("content")
    snippet_text = str(snippet) if snippet else ""
    content_text = str(content) if content else ""
    if snippet_text and content_text:
        if len(snippet_text) <= len(content_text):
            return snippet_text
        return content_text[:SNIPPET_MAX_CHARS]
    if snippet_text:
        return snippet_text
    if content_text:
        return content_text[:SNIPPET_MAX_CHARS]
    return ""


def apply_session_row_hygiene(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    snippet = out.get("snippet")
    content = out.get("content")
    if not snippet and not content:
        return out
    text = clip_session_text(out)
    out["snippet"] = text
    if content and snippet and len(str(snippet)) < len(str(content)):
        out.pop("content", None)
    elif content:
        out["content"] = text
    return out


def filter_session_rows(
    rows: list[dict[str, Any]],
    *,
    exclude_conversation_id: str | None = None,
) -> list[dict[str, Any]]:
    excluded = (exclude_conversation_id or "").strip() or None
    cleaned: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if is_hidden_session_row(row):
            continue
        if excluded and str(row.get("conversation_id") or "") == excluded:
            continue
        cleaned.append(apply_session_row_hygiene(row))
    return cleaned


async def search_user_sessions(
    user_id: str,
    query: str,
    *,
    limit: int = 5,
    exclude_conversation_id: str | None = None,
) -> list[dict[str, Any]]:
    if not (user_id or "").strip():
        raise ValueError("user_id is required")
    from neos.services.similarity_search_service import similarity_search_service

    rows = await similarity_search_service.find_similar_across_conversations(
        user_id=user_id.strip(),
        query=query,
        limit=limit,
    )
    return filter_session_rows(rows, exclude_conversation_id=exclude_conversation_id)
