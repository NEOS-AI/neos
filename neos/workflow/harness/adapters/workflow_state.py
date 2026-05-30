from __future__ import annotations

from typing import Any


def _get_value(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def extract_report_text(state: dict[str, Any]) -> str:
    if state.get("final_response"):
        return str(state["final_response"])
    if state.get("search_synthesis"):
        return str(state["search_synthesis"])

    parts: list[str] = []
    for result in state.get("generation_results") or []:
        content = _get_value(result, "content")
        if content:
            parts.append(str(content))
    for result in state.get("analysis_results") or []:
        insights = _get_value(result, "insights")
        if isinstance(insights, list):
            parts.extend(str(item) for item in insights)
        elif insights:
            parts.append(str(insights))

    integrated = state.get("integrated_results") or {}
    if not parts and integrated:
        parts.append(str(integrated))

    return "\n\n".join(part for part in parts if part)


def extract_sources(state: dict[str, Any]) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    for index, result in enumerate(state.get("search_results") or [], start=1):
        metadata = _get_value(result, "metadata") or {}
        source = {
            "id": str(index),
            "source": _get_value(result, "source"),
            "title": _get_value(result, "title"),
            "content": _get_value(result, "content"),
            "url": _get_value(result, "url"),
            "score": _get_value(result, "score"),
            "metadata": metadata,
        }
        if isinstance(metadata, dict):
            for key in ("published_at", "published_date", "date", "timestamp"):
                if metadata.get(key) is not None:
                    source[key] = metadata[key]
        sources.append(source)
    return sources


def extract_context(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "errors": state.get("errors") or [],
        "fact_check_result": state.get("fact_check_result") or {},
        "quality_score": state.get("quality_score"),
        "quality_feedback": state.get("quality_feedback"),
        "execution_steps": state.get("execution_steps") or [],
    }

