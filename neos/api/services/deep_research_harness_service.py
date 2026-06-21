from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from neos.database.connection import db_manager
from neos.workflow.harness.adapters.deep_research_report import (
    build_deep_research_contract_state,
    combine_deep_research_sections,
    extract_deep_research_sources,
)
from neos.workflow.harness.contract_builder import build_harness_contract
from neos.workflow.harness.models import HarnessContract, HarnessRun
from neos.workflow.harness.runner import HarnessRunner


@dataclass
class DeepResearchHarnessValidation:
    run: HarnessRun
    contract: HarnessContract
    report: str
    sources: list[dict[str, Any]]


class DeepResearchHarnessService:
    def __init__(self, runner: HarnessRunner | None = None) -> None:
        self.runner = runner or HarnessRunner()

    async def validate_report(
        self,
        *,
        report_id: str,
        research_topic: str,
        metadata: dict[str, Any] | None = None,
        event_callback: object | None = None,
        repair_attempts: int = 0,
    ) -> DeepResearchHarnessValidation:
        sections = await self._fetch_sections(report_id)
        collection_rows = await self._fetch_collection_rows(report_id)
        report = combine_deep_research_sections(sections)
        sources = extract_deep_research_sources(sections, collection_rows)
        state = build_deep_research_contract_state(
            research_topic=research_topic,
            metadata=metadata,
        )
        contract = build_harness_contract(state)
        run = await self.runner.arun(
            report=report,
            sources=sources,
            contract=contract,
            context={
                "report_id": report_id,
                "research_topic": research_topic,
                "metadata": metadata or {},
                "processing_time_ms": (metadata or {}).get("processing_time_ms"),
                "total_queries": (metadata or {}).get("total_queries"),
                "total_sources": (metadata or {}).get("total_sources"),
            },
            event_callback=event_callback,
            repair_attempts=repair_attempts,
        )
        return DeepResearchHarnessValidation(
            run=run,
            contract=contract,
            report=report,
            sources=sources,
        )

    async def _fetch_sections(self, report_id: str) -> list[dict[str, Any]]:
        query = """
            SELECT section_order, section_title, section_content, sources
            FROM hyper_research_sections
            WHERE report_id = $1
            ORDER BY section_order ASC
        """
        rows = await db_manager.fetch_all(query, report_id)
        return [
            {
                "section_order": row[0],
                "section_title": row[1],
                "section_content": row[2],
                "sources": row[3],
            }
            for row in rows
        ]

    async def _fetch_collection_rows(self, report_id: str) -> list[dict[str, Any]]:
        query = """
            SELECT results
            FROM hyper_research_data_collection
            WHERE report_id = $1
            ORDER BY executed_at ASC
        """
        rows = await db_manager.fetch_all(query, report_id)
        return [{"results": row[0]} for row in rows]
