"""Cross-session search. user_id is required. No LLM summary."""

from __future__ import annotations

from typing import Any


async def search_user_sessions(
    user_id: str,
    query: str,
    *,
    limit: int = 5,
) -> list[dict[str, Any]]:
    if not (user_id or "").strip():
        raise ValueError("user_id is required")
    from neos.services.similarity_search_service import similarity_search_service

    return await similarity_search_service.find_similar_across_conversations(
        user_id=user_id.strip(),
        query=query,
        limit=limit,
    )
