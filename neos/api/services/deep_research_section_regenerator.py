from __future__ import annotations

import re
from typing import Any, Callable

from langchain_core.messages import HumanMessage

from neos.utils.llm_factory import create_llm
from neos.utils.llm_wrapper import extract_text_from_response


class DeepResearchSectionRegenerator:
    """Source-constrained section repair for Direct Deep Research reports."""

    def __init__(self, *, llm_factory: Callable[[], Any] | None = None) -> None:
        self.llm_factory = llm_factory or _default_llm_factory
        self.last_metadata: dict[str, Any] = {"status": "idle"}

    async def regenerate(
        self,
        *,
        research_topic: str,
        section_title: str,
        current_content: str,
        sources: list[dict[str, Any]],
        failed_items: list[dict[str, Any]],
        action_type: str,
        language: str = "ko",
    ) -> str:
        if not sources:
            return self._fallback(
                current_content,
                reason="insufficient_sources",
                action_type=action_type,
            )

        prompt = _build_prompt(
            research_topic=research_topic,
            section_title=section_title,
            current_content=current_content,
            sources=sources,
            failed_items=failed_items,
            action_type=action_type,
            language=language,
        )
        try:
            response = await self.llm_factory().ainvoke([HumanMessage(content=prompt)])
            content = extract_text_from_response(response).strip()
        except Exception as exc:
            return self._fallback(
                current_content,
                reason="model_error",
                action_type=action_type,
                error=str(exc),
            )

        if not content:
            return self._fallback(
                current_content,
                reason="empty_model_response",
                action_type=action_type,
            )
        if _has_invalid_citation_markers(content):
            return self._fallback(
                current_content,
                reason="invalid_citation_markers",
                action_type=action_type,
            )

        self.last_metadata = {
            "status": "executed",
            "action_type": action_type,
            "source_count": len(sources),
        }
        return content

    def _fallback(
        self,
        current_content: str,
        *,
        reason: str,
        action_type: str,
        error: str | None = None,
    ) -> str:
        self.last_metadata = {
            "status": "fallback",
            "reason": reason,
            "action_type": action_type,
        }
        if error:
            self.last_metadata["error"] = error
        return (
            f"{current_content.rstrip()}\n\n"
            f"Repair note: Harness repair could not safely regenerate this section "
            f"({reason})."
        )


def _default_llm_factory() -> Any:
    return create_llm(temperature=0.2, max_tokens=4000)


def _build_prompt(
    *,
    research_topic: str,
    section_title: str,
    current_content: str,
    sources: list[dict[str, Any]],
    failed_items: list[dict[str, Any]],
    action_type: str,
    language: str,
) -> str:
    source_lines = []
    for index, source in enumerate(sources, 1):
        source_lines.append(
            "\n".join(
                [
                    f"[{index}] {source.get('title') or 'Untitled source'}",
                    f"URL: {source.get('url') or ''}",
                    f"Date: {source.get('published_at') or source.get('date') or ''}",
                    f"Snippet: {str(source.get('content') or source.get('snippet') or '')[:1000]}",
                ]
            )
        )
    return (
        "Repair one existing markdown report section using only the provided sources. "
        "Keep numeric citation markers like [1], [2]. Do not invent sources. "
        "Return only the repaired markdown section body, with no JSON wrapper.\n\n"
        f"Language: {language}\n"
        f"Research topic: {research_topic}\n"
        f"Section title: {section_title}\n"
        f"Repair action: {action_type}\n"
        f"Failed items: {failed_items}\n\n"
        f"Sources:\n{chr(10).join(source_lines)}\n\n"
        f"Current section:\n{current_content}"
    )


def _has_invalid_citation_markers(content: str) -> bool:
    for marker in re.findall(r"\[([^\]]+)\]", content):
        if marker.strip().isdigit():
            continue
        return True
    return False
