"""Skills as discovery sources: (skill, query) -> [{url, title, snippet}].

D6 확장 — 탐색(discovery)만 담당한다. 검색(retrieval)은 fetch.py 독점이며,
여기서 반환한 URL은 반드시 fetch를 거쳐 원문 대조로 검증된다(P3).
URL을 주지 못하는 항목은 검증 사슬에 들어갈 수 없으므로 버린다.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# 순서가 곧 우선순위다. fetch.py는 content-type 분기 없이 html_to_text를 돌리므로
# (fetch.py:64) PDF URL은 쓰레기 텍스트가 되어 E_QUOTE_MISMATCH로 기각된다.
# 따라서 HTML 랜딩/초록 페이지를 항상 PDF보다 먼저 고른다.
_URL_KEYS = (
    "url",  # semantic-scholar, sec-edgar, wikipedia, news-api, google-scholar
    "entry_url",  # arxiv 초록 페이지 (HTML)
    "pubmed_url",  # pubmed 초록 페이지 (HTML)
    "landing_page_url",  # openalex 랜딩 페이지 (HTML)
    "homepage_url",  # openalex 대체
    "link",  # google-scholar 대체
    "html_url",
    "href",
    # 최후 수단. PDF만 있는 항목은 현재 검증을 통과하지 못하지만, 버리면
    # fetch.py가 PDF를 지원하게 됐을 때 조용히 누락된다.
    "pdf_url",
)
_TITLE_KEYS = ("title", "name", "headline")
_SNIPPET_KEYS = ("snippet", "summary", "abstract", "content", "description", "text")


def _first_str(item: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def normalize_discovery_items(data: Any) -> list[dict[str, str]]:
    if not isinstance(data, list):
        return []

    items: list[dict[str, str]] = []
    for raw in data:
        if not isinstance(raw, dict):
            continue
        url = _first_str(raw, _URL_KEYS)
        if not url:
            continue
        items.append(
            {
                "url": url,
                "title": _first_str(raw, _TITLE_KEYS),
                "snippet": _first_str(raw, _SNIPPET_KEYS),
            }
        )
    return items


async def skill_search(
    skill,
    query: str,
    k: int,
    *,
    cassette=None,
) -> list[dict[str, str]]:
    async def produce() -> list[dict[str, str]]:
        try:
            if not await skill.initialize():
                logger.warning(
                    "[deep_analysis] skill %s failed to initialize", skill.name
                )
                return []
            result = await skill.execute(
                {"query": query, "action": "search", "max_results": k}
            )
            if not getattr(result, "success", False):
                return []
            return normalize_discovery_items(getattr(result, "data", None))
        except Exception as exc:  # noqa: BLE001 — 스킬 장애가 워커를 죽이면 안 된다
            logger.warning("[deep_analysis] skill %s raised: %s", skill.name, exc)
            return []
        finally:
            try:
                await skill.cleanup()
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "[deep_analysis] skill %s cleanup failed: %s", skill.name, exc
                )

    if cassette is None:
        return await produce()
    return await cassette.remember(
        "skill",
        {"skill": skill.name, "query": query, "limit": k},
        produce,
    )
