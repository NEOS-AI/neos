"""스킬 결과 → `SearchResult` 변환 헬퍼 (spec 2026-10-11 §3.5).

결과 모양을 아는 것은 스킬 자신이다 -- 각 스킬이 `to_search_results()` 에서 이
헬퍼로 자기 항목을 옮긴다. 여기에는 모양을 모르는 공통 부분만 둔다.
"""

from __future__ import annotations

from typing import Any

from neos.workflow.state import SearchResult

__all__ = ["SKILL_EXECUTOR_VIA", "SearchResult", "collect_items", "join_text", "make_result"]

#: 공통 실행 노드가 낸 결과의 `metadata["via"]`. 직접 응답이 이것으로 스킬 출처를 고른다.
SKILL_EXECUTOR_VIA = "skill_executor"


def collect_items(data: Any, *list_keys: str) -> list[dict[str, Any]]:
    """`data` 에서 처음 발견되는 목록 키의 dict 항목을 꺼낸다.

    단건 조회(`get_by_id` 등)는 `data` 자체가 항목이라 목록 키가 없다 -- 그때는
    `title`/`name` 이 있으면 `[data]` 다.
    """
    if not isinstance(data, dict):
        return []
    for key in list_keys:
        value = data.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if value is not None:
            return []
    if data.get("title") or data.get("name"):
        return [data]
    return []


def join_text(*parts: Any) -> str:
    return "\n".join(str(part) for part in parts if part)


def make_result(
    source: str,
    *,
    title: Any,
    content: Any,
    url: Any = None,
    score: float = 0.8,
    metadata: dict[str, Any] | None = None,
) -> SearchResult:
    return SearchResult(
        source=source,
        title=str(title or ""),
        content=str(content or ""),
        url=str(url) if url else None,
        score=score,
        metadata=dict(metadata or {}),
    )
