from __future__ import annotations

import asyncio
import concurrent.futures
import re
from typing import Any, Callable

from tavily import TavilyClient

from neos.api.repositories.deep_research_repair_repository import (
    DeepResearchRepairRepository,
)
from neos.api.services.deep_research_repair_sources import (
    dedupe_sources,
    dominant_domains_from_sources,
    normalize_repair_source,
    sources_for_section,
)
from neos.api.services.deep_research_section_regenerator import (
    DeepResearchSectionRegenerator,
)
from neos.config.settings import settings
from neos.workflow.harness.models import HarnessRepairAction


SearchExecutor = Callable[..., Any]


class DirectDeepResearchRepairExecutor:
    """Execute bounded Direct Deep Research harness repair actions."""

    def __init__(
        self,
        *,
        repository: DeepResearchRepairRepository | None = None,
        searcher: SearchExecutor | None = None,
        regenerator: DeepResearchSectionRegenerator | None = None,
        section_source_limit: int = 12,
    ) -> None:
        self.repository = repository or DeepResearchRepairRepository()
        self.searcher = searcher or _default_tavily_search
        self.regenerator = regenerator or DeepResearchSectionRegenerator()
        self.section_source_limit = section_source_limit

    async def __call__(
        self,
        *,
        report_id: str,
        action: HarnessRepairAction,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        repair_context = await self.repository.fetch_repair_context(report_id)
        action_type = action.action_type
        if action_type in {
            "request_more_sources",
            "search_independent_domains",
            "date_constrained_freshness_search",
        }:
            return await self._execute_search_action(
                report_id=report_id,
                action=action,
                context=context,
                repair_context=repair_context,
            )
        if action_type == "rebuild_citation_map":
            return await self._rebuild_citation_map(
                report_id=report_id,
                action=action,
                context=context,
                repair_context=repair_context,
            )
        if action_type in {
            "regenerate_cited_sections",
            "regenerate_unsupported_claims",
            "add_perspective_balancing_sources",
        }:
            return await self._regenerate_sections(
                report_id=report_id,
                action=action,
                context=context,
                repair_context=repair_context,
            )
        return {"status": "skipped", "reason": "unsupported_action"}

    async def _execute_search_action(
        self,
        *,
        report_id: str,
        action: HarnessRepairAction,
        context: dict[str, Any],
        repair_context: dict[str, Any],
    ) -> dict[str, Any]:
        query = _query_for_action(action, context)
        avoid_domains = set(action.params.get("avoid_domains") or [])
        if action.action_type == "search_independent_domains" and not avoid_domains:
            avoid_domains = set(dominant_domains_from_sources(_all_sources(repair_context)))

        raw_results = await _maybe_await(
            self.searcher(
                query,
                action_type=action.action_type,
                avoid_domains=sorted(avoid_domains),
                freshness_window_days=action.params.get("freshness_window_days"),
            )
        )
        normalized = [
            normalize_repair_source(raw, index=index, action_type=action.action_type)
            for index, raw in enumerate(raw_results or [], 1)
            if isinstance(raw, dict)
        ]
        if avoid_domains:
            normalized = [source for source in normalized if source.get("domain") not in avoid_domains]
        unique_sources = _new_sources_only(_all_sources(repair_context), normalized)
        if not unique_sources:
            return {
                "status": "skipped",
                "reason": "no_repair_sources_found",
                "added_sources": 0,
            }

        repair_event = _repair_event(action, context, added_sources=len(unique_sources))
        await self.repository.record_repair_collection(
            report_id=report_id,
            query_text=query,
            action_type=action.action_type,
            results=unique_sources,
            section_id=_first_section_id(repair_context),
            metadata=repair_event,
        )
        await self.repository.append_report_repair_metadata(report_id, repair_event)
        return {
            "status": "executed",
            "added_sources": len(unique_sources),
            "source_domains": dominant_domains_from_sources(unique_sources),
        }

    async def _rebuild_citation_map(
        self,
        *,
        report_id: str,
        action: HarnessRepairAction,
        context: dict[str, Any],
        repair_context: dict[str, Any],
    ) -> dict[str, Any]:
        updated_sections: list[str] = []
        for section in _select_sections(repair_context, action.params.get("failed_items") or []):
            sources = _section_sources(section)
            if not sources:
                continue
            content = str(section.get("section_content") or "")
            repaired = _rewrite_invalid_numeric_citations(content, len(sources))
            if repaired == content:
                continue
            await self.repository.update_section_after_repair(
                section_id=section["section_id"],
                content=repaired,
                sources=sources,
                metadata={"repair_event": _repair_event(action, context)},
            )
            updated_sections.append(section["section_id"])

        if not updated_sections:
            return {"status": "skipped", "reason": "no_deterministic_citation_mapping"}
        await self.repository.append_report_repair_metadata(
            report_id,
            _repair_event(action, context, updated_sections=updated_sections),
        )
        return {"status": "executed", "updated_sections": updated_sections}

    async def _regenerate_sections(
        self,
        *,
        report_id: str,
        action: HarnessRepairAction,
        context: dict[str, Any],
        repair_context: dict[str, Any],
    ) -> dict[str, Any]:
        failed_items = action.params.get("failed_items") or []
        new_sources: list[dict[str, Any]] = []
        if action.action_type == "add_perspective_balancing_sources":
            raw_results = await _maybe_await(
                self.searcher(
                    f"{context.get('research_topic') or context.get('original_query') or ''} counter perspective stakeholders",
                    action_type=action.action_type,
                )
            )
            new_sources = [
                normalize_repair_source(raw, index=index, action_type=action.action_type)
                for index, raw in enumerate(raw_results or [], 1)
                if isinstance(raw, dict)
            ]
            if new_sources:
                await self.repository.record_repair_collection(
                    report_id=report_id,
                    query_text=str(context.get("research_topic") or context.get("original_query") or ""),
                    action_type=action.action_type,
                    results=new_sources,
                    section_id=_first_section_id(repair_context),
                    metadata=_repair_event(action, context, added_sources=len(new_sources)),
                )

        selected_sections = _select_sections(repair_context, failed_items)
        if not selected_sections:
            return {"status": "skipped", "reason": "no_matching_sections"}

        updated_sections: list[str] = []
        for section in selected_sections:
            section_sources = sources_for_section(
                _section_sources(section),
                new_sources,
                self.section_source_limit,
            )
            if not section_sources:
                continue
            repaired = await self.regenerator.regenerate(
                research_topic=str(context.get("research_topic") or context.get("original_query") or ""),
                section_title=str(section.get("section_title") or "Untitled"),
                current_content=str(section.get("section_content") or ""),
                sources=section_sources,
                failed_items=failed_items,
                action_type=action.action_type,
                language=str(context.get("language") or "ko"),
            )
            await self.repository.update_section_after_repair(
                section_id=section["section_id"],
                content=repaired,
                sources=section_sources,
                metadata={
                    "repair_event": _repair_event(
                        action,
                        context,
                        regenerator_metadata=getattr(self.regenerator, "last_metadata", {}),
                    )
                },
            )
            updated_sections.append(section["section_id"])

        if not updated_sections:
            return {"status": "skipped", "reason": "no_section_sources_available"}
        await self.repository.append_report_repair_metadata(
            report_id,
            _repair_event(action, context, updated_sections=updated_sections),
        )
        return {
            "status": "executed",
            "updated_sections": updated_sections,
            "added_sources": len(new_sources),
        }


async def _default_tavily_search(query: str, **kwargs: Any) -> list[dict[str, Any]]:
    if not settings.TAVILY_API_KEY:
        return []
    client = TavilyClient(api_key=settings.TAVILY_API_KEY)

    def run_search() -> list[dict[str, Any]]:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                client.search,
                query=query,
                search_depth="advanced",
                max_results=5,
                include_answer=True,
                include_raw_content=True,
            )
            response = future.result(timeout=20)
        return response.get("results", []) if isinstance(response, dict) else []

    try:
        return await asyncio.wait_for(asyncio.to_thread(run_search), timeout=25)
    except Exception:
        return []


def _query_for_action(action: HarnessRepairAction, context: dict[str, Any]) -> str:
    query = str(action.params.get("query") or context.get("original_query") or context.get("research_topic") or "")
    if action.action_type == "date_constrained_freshness_search":
        window = action.params.get("freshness_window_days")
        if window:
            query = f"{query} latest recent published within {window} days"
    return query.strip()


def _all_sources(repair_context: dict[str, Any]) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    for section in repair_context.get("sections") or []:
        sources.extend(_section_sources(section))
    for row in repair_context.get("collection_rows") or []:
        sources.extend([source for source in row.get("results") or [] if isinstance(source, dict)])
    return sources


def _new_sources_only(
    existing_sources: list[dict[str, Any]],
    new_sources: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    existing_count = len(dedupe_sources(existing_sources, []))
    return dedupe_sources(existing_sources, new_sources)[existing_count:]


def _section_sources(section: dict[str, Any]) -> list[dict[str, Any]]:
    return [source for source in section.get("sources") or [] if isinstance(source, dict)]


def _select_sections(
    repair_context: dict[str, Any],
    failed_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    sections = list(repair_context.get("sections") or [])
    if not failed_items:
        return [
            section
            for section in sections
            if str(section.get("section_type") or "").lower() not in {"appendix", "data_collection"}
        ] or sections[:1]
    hints = {
        str(item.get("section") or item.get("section_title") or item.get("title") or "").lower()
        for item in failed_items
        if isinstance(item, dict)
    }
    hints = {hint for hint in hints if hint}
    if not hints:
        return sections[:1]
    matched = []
    for section in sections:
        title = str(section.get("section_title") or "").lower()
        section_type = str(section.get("section_type") or "").lower()
        if any(hint in title or hint in section_type for hint in hints):
            matched.append(section)
    return matched


def _rewrite_invalid_numeric_citations(content: str, source_count: int) -> str:
    if source_count <= 0:
        return content

    def replace(match: re.Match[str]) -> str:
        marker = int(match.group(1))
        if 1 <= marker <= source_count:
            return match.group(0)
        return f"[{source_count}]"

    return re.sub(r"\[(\d+)\]", replace, content)


def _first_section_id(repair_context: dict[str, Any]) -> str | None:
    sections = repair_context.get("sections") or []
    return sections[0].get("section_id") if sections else None


def _repair_event(
    action: HarnessRepairAction,
    context: dict[str, Any],
    **extra: Any,
) -> dict[str, Any]:
    return {
        "attempt": context.get("attempt"),
        "action_type": action.action_type,
        "target_check": action.target_check,
        "reason": action.reason,
        **extra,
    }


async def _maybe_await(value: Any) -> Any:
    if asyncio.iscoroutine(value) or hasattr(value, "__await__"):
        return await value
    return value
