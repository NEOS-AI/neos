from __future__ import annotations

from typing import Any


def combine_deep_research_sections(sections: list[dict[str, Any]]) -> str:
    ordered = sorted(sections, key=lambda item: int(item.get("section_order") or 0))
    parts: list[str] = []
    for section in ordered:
        title = str(section.get("section_title") or "Untitled")
        content = str(section.get("section_content") or "").strip()
        if not content:
            continue
        parts.append(f"## {title}\n\n{content}")
    return "\n\n".join(parts).strip()


def extract_deep_research_sources(
    sections: list[dict[str, Any]],
    collection_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    raw_sources: list[dict[str, Any]] = []
    for section in sections:
        raw_sources.extend(_as_list(section.get("sources")))
    for row in collection_rows:
        raw_sources.extend(_as_list(row.get("results")))

    seen: set[str] = set()
    sources: list[dict[str, Any]] = []
    for raw in raw_sources:
        if not isinstance(raw, dict):
            continue
        identity = str(raw.get("url") or raw.get("source") or raw.get("title") or "")
        if not identity or identity in seen:
            continue
        seen.add(identity)
        source = dict(raw)
        source["id"] = str(len(sources) + 1)
        sources.append(source)
    return sources


def build_deep_research_contract_state(
    *,
    research_topic: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = dict(metadata or {})
    return {
        "original_query": research_topic,
        "query_intent": "deep_research",
        "query_classification": {"complexity_score": 1.0},
        "harness_mode": "gate",
        "metadata": metadata,
        "harness_config": {
            "required_checks": metadata.get(
                "required_checks",
                ["source_count", "citation_validity", "citation_coverage"],
            )
        },
    }


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]
