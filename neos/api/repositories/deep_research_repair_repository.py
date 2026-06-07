from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from typing import Any

from neos.database.connection import db_manager


class DeepResearchRepairRepository:
    """Database boundary for Direct Deep Research harness repair mutations."""

    def __init__(self, *, db: Any | None = None) -> None:
        self.db = db or db_manager

    async def fetch_repair_context(self, report_id: str) -> dict[str, Any]:
        sections_query = """
            SELECT
                section_id, section_order, section_type, section_title,
                section_content, sources, metadata
            FROM hyper_research_sections
            WHERE report_id = $1
            ORDER BY section_order ASC
        """
        collection_query = """
            SELECT collection_id, query_text, results, metadata
            FROM hyper_research_data_collection
            WHERE report_id = $1
            ORDER BY executed_at ASC
        """
        report_query = """
            SELECT metadata, total_sections, total_sources, total_queries
            FROM hyper_research_reports
            WHERE report_id = $1
        """
        section_rows = await self.db.fetch_all(sections_query, report_id)
        collection_rows = await self.db.fetch_all(collection_query, report_id)
        report_row = await self.db.fetch_one(report_query, report_id)

        return {
            "report_id": report_id,
            "sections": [
                {
                    "section_id": row[0],
                    "section_order": row[1],
                    "section_type": row[2],
                    "section_title": row[3],
                    "section_content": row[4],
                    "sources": _as_list(row[5]),
                    "metadata": _as_dict(row[6]),
                }
                for row in section_rows
            ],
            "collection_rows": [
                {
                    "collection_id": row[0],
                    "query_text": row[1],
                    "results": _as_list(row[2]),
                    "metadata": _as_dict(row[3]),
                }
                for row in collection_rows
            ],
            "report_metadata": _as_dict(report_row[0]) if report_row else {},
            "totals": {
                "total_sections": int(report_row[1] or 0) if report_row else 0,
                "total_sources": int(report_row[2] or 0) if report_row else 0,
                "total_queries": int(report_row[3] or 0) if report_row else 0,
            },
        }

    async def record_repair_collection(
        self,
        *,
        report_id: str,
        query_text: str,
        action_type: str,
        results: list[dict[str, Any]],
        section_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        query = """
            INSERT INTO hyper_research_data_collection (
                collection_id, report_id, section_id, query_text,
                query_type, search_phase, results_count, results, metadata
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        """
        repair_metadata = {
            "repair_action": action_type,
            **_as_dict(metadata),
        }
        await self.db.execute(
            query,
            f"repair_collection_{uuid.uuid4()}",
            report_id,
            section_id,
            _strip_nulls(query_text),
            "harness_repair",
            0,
            len(results),
            json.dumps(_json_safe(results), ensure_ascii=False),
            json.dumps(_json_safe(repair_metadata), ensure_ascii=False),
        )

    async def update_section_after_repair(
        self,
        *,
        section_id: str,
        content: str,
        sources: list[dict[str, Any]],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        current_query = """
            SELECT metadata
            FROM hyper_research_sections
            WHERE section_id = $1
        """
        row = await self.db.fetch_one(current_query, section_id)
        current_metadata = _as_dict(row[0]) if row else {}
        update_metadata = _as_dict(metadata)
        repair_event = update_metadata.pop("repair_event", None)
        events = list(current_metadata.get("harness_repair_events") or [])
        if repair_event:
            events.append(_json_safe(repair_event))
        merged_metadata = {
            **current_metadata,
            **update_metadata,
            "harness_repair_events": events,
        }

        query = """
            UPDATE hyper_research_sections
            SET
                section_content = $1,
                sources = $2,
                sources_count = $3,
                metadata = $4,
                section_status = 'completed',
                completed_at = CURRENT_TIMESTAMP
            WHERE section_id = $5
        """
        await self.db.execute(
            query,
            _strip_nulls(content),
            json.dumps(_json_safe(sources), ensure_ascii=False),
            len(sources),
            json.dumps(_json_safe(merged_metadata), ensure_ascii=False),
            section_id,
        )

    async def append_report_repair_metadata(
        self,
        report_id: str,
        repair_event: dict[str, Any],
    ) -> None:
        current_query = """
            SELECT metadata
            FROM hyper_research_reports
            WHERE report_id = $1
        """
        row = await self.db.fetch_one(current_query, report_id)
        current_metadata = _as_dict(row[0]) if row else {}
        events = list(current_metadata.get("harness_repair_events") or [])
        events.append(_json_safe(repair_event))
        query = """
            UPDATE hyper_research_reports
            SET metadata = $2, updated_at = CURRENT_TIMESTAMP
            WHERE report_id = $1
        """
        await self.db.execute(
            query,
            report_id,
            json.dumps(
                _json_safe({**current_metadata, "harness_repair_events": events}),
                ensure_ascii=False,
            ),
        )

    async def refresh_report_totals(self, report_id: str) -> dict[str, int]:
        totals_query = """
            SELECT
                COALESCE((SELECT COUNT(*) FROM hyper_research_sections WHERE report_id = $1), 0),
                COALESCE((SELECT SUM(sources_count) FROM hyper_research_sections WHERE report_id = $1), 0),
                COALESCE((SELECT COUNT(*) FROM hyper_research_data_collection WHERE report_id = $1), 0),
                COALESCE((
                    SELECT SUM(results_count)
                    FROM hyper_research_data_collection
                    WHERE report_id = $1 AND query_type = 'harness_repair'
                ), 0)
        """
        row = await self.db.fetch_one(totals_query, report_id)
        section_sources = int(row[1] or 0) if row else 0
        repair_collection_sources = int(row[3] or 0) if row and len(row) > 3 else 0
        totals = {
            "total_sections": int(row[0] or 0) if row else 0,
            "total_sources": section_sources + repair_collection_sources,
            "total_queries": int(row[2] or 0) if row else 0,
        }
        update_query = """
            UPDATE hyper_research_reports
            SET
                total_sections = $2,
                total_sources = $3,
                total_queries = $4,
                updated_at = CURRENT_TIMESTAMP
            WHERE report_id = $1
        """
        await self.db.execute(
            update_query,
            report_id,
            totals["total_sections"],
            totals["total_sources"],
            totals["total_queries"],
        )
        return totals


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else [parsed]
    return [value]


def _json_safe(value: Any) -> Any:
    if isinstance(value, str):
        return _strip_nulls(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(_strip_nulls(key)): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    try:
        json.dumps(value)
    except TypeError:
        return str(value)
    return value


def _strip_nulls(value: Any) -> str:
    return str(value or "").replace("\x00", "").replace("\u0000", "")
