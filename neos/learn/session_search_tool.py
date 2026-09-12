"""Chat/research tool for prior-session snippets. Not a coding tool. No LLM."""

from __future__ import annotations

from typing import Any, Mapping

from neos.config.settings import settings
from neos.learn.session_search import (
    clip_session_text,
    is_hidden_session_row,
    search_user_sessions,
)

SEARCH_USER_SESSIONS_NAME = "search_user_sessions"
_DEFAULT_LIMIT = 5
_MAX_LIMIT = 10

SEARCH_USER_SESSIONS_TOOL: dict[str, Any] = {
    "name": SEARCH_USER_SESSIONS_NAME,
    "description": (
        "Search this user's earlier chat sessions for relevant snippets. "
        "Use when the current question may have been discussed before. "
        "Returns short snippets only — do not expect a summary."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "What to look for in prior sessions.",
            },
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": _MAX_LIMIT,
                "description": f"Maximum snippets to return (1-{_MAX_LIMIT}).",
            },
            "exclude_conversation_id": {
                "type": "string",
                "description": "Conversation to omit (usually the live thread).",
            },
        },
        "required": ["query"],
    },
}


def is_session_search_tool(name: str) -> bool:
    return name == SEARCH_USER_SESSIONS_NAME


def list_chat_research_tools() -> list[dict[str, Any]]:
    if not settings.config.learn.session_search_tool:
        return []
    return [SEARCH_USER_SESSIONS_TOOL]


def _clamp_limit(raw: Any) -> int:
    try:
        limit = int(raw)
    except (TypeError, ValueError):
        return _DEFAULT_LIMIT
    return max(1, min(limit, _MAX_LIMIT))


def _reject_model_user_id(tool_input: Mapping[str, Any], user_id: str) -> None:
    """Ignore model-supplied user ids; only the authenticated user may search."""
    supplied = tool_input.get("user_id")
    if supplied is None:
        return
    other = str(supplied).strip()
    if other and other != user_id:
        raise ValueError("user_id cannot be supplied by the model")


def _optional_conversation_id(raw: Any) -> str | None:
    if raw is None:
        return None
    value = str(raw).strip()
    return value or None


def _snippets(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    snippets: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict) or is_hidden_session_row(row):
            continue
        snippets.append(
            {
                "message_id": row.get("message_id"),
                "conversation_id": row.get("conversation_id"),
                "conversation_title": row.get("conversation_title"),
                "snippet": clip_session_text(row),
                "role": row.get("role"),
                "similarity_score": row.get("similarity_score"),
            }
        )
    return snippets


async def handle_search_user_sessions(
    tool_input: Mapping[str, Any] | None,
    *,
    user_id: str,
    exclude_conversation_id: str | None = None,
) -> dict[str, Any]:
    """Run search as the authenticated/workflow user. Ignore model user ids."""
    owner = (user_id or "").strip()
    if not owner:
        raise ValueError("user_id is required")
    payload = tool_input or {}
    _reject_model_user_id(payload, owner)
    query = str(payload.get("query") or "")
    limit = _clamp_limit(payload.get("limit", _DEFAULT_LIMIT))
    excluded = _optional_conversation_id(exclude_conversation_id)
    if excluded is None:
        excluded = _optional_conversation_id(payload.get("exclude_conversation_id"))
    rows = await search_user_sessions(
        owner,
        query,
        limit=limit,
        exclude_conversation_id=excluded,
    )
    return {"type": "tool_result", "snippets": _snippets(rows)}
