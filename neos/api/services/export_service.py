"""
Export Service (Phase 3.4)

연구 세션 데이터를 가져와 다양한 포맷으로 export합니다.
"""

import logging
from typing import Optional
from datetime import datetime

from neos.exporters import (
    MarkdownExporter,
    HTMLExporter,
    PDFExporter,
    ExportFormat,
    ResearchReport,
)
from neos.database.connection import get_session_ctx

logger = logging.getLogger(__name__)


class ExportService:
    """연구 리포트 export 서비스"""

    def __init__(self):
        self.exporters = {
            ExportFormat.MARKDOWN: MarkdownExporter(),
            ExportFormat.HTML: HTMLExporter(),
            ExportFormat.PDF: PDFExporter(),
        }

    async def export_research_session(
        self,
        session_id: str,
        format: ExportFormat,
        user_id: str,
        **options,
    ) -> bytes:
        """연구 세션을 지정 포맷으로 export"""

        report = await self._build_report(session_id, user_id)
        if not report:
            raise ValueError(f"Session not found: {session_id}")

        exporter = self.exporters.get(format)
        if not exporter:
            raise ValueError(f"Unsupported format: {format}")

        return await exporter.export(report, **options)

    async def _build_report(
        self, session_id: str, user_id: str
    ) -> Optional[ResearchReport]:
        """DB에서 세션 데이터를 가져와 ResearchReport 구성"""
        try:
            from sqlalchemy import text

            async with get_session_ctx() as session:
                # episodic_memories 테이블에서 세션 데이터 조회
                result = await session.execute(
                    text("""
                        SELECT
                            session_id, query, key_findings,
                            sources_used, quality_score,
                            metadata, created_at
                        FROM episodic_memories
                        WHERE session_id = :session_id AND user_id = :user_id
                        ORDER BY created_at DESC
                        LIMIT 1
                    """),
                    {"session_id": session_id, "user_id": user_id},
                )
                row = result.fetchone()

                if not row:
                    # research_sessions 테이블에서도 시도
                    result = await session.execute(
                        text("""
                            SELECT
                                session_id, query, '' as key_findings,
                                '[]'::jsonb as sources_used, NULL as quality_score,
                                metadata, created_at
                            FROM research_sessions
                            WHERE session_id = :session_id AND user_id = :user_id
                            ORDER BY created_at DESC
                            LIMIT 1
                        """),
                        {"session_id": session_id, "user_id": user_id},
                    )
                    row = result.fetchone()

                if not row:
                    return None

                search_results = row[3] if isinstance(row[3], list) else []
                citations = self._extract_citations(search_results)

                return ResearchReport(
                    session_id=row[0],
                    query=row[1] or "",
                    response=row[2] or "",
                    search_results=search_results,
                    citations=citations,
                    quality_score=row[4],
                    metadata=row[5] if isinstance(row[5], dict) else {},
                    created_at=row[6] if isinstance(row[6], datetime) else datetime.now(),
                )

        except Exception as e:
            logger.error(f"Failed to build report: {e}", exc_info=True)
            return None

    @staticmethod
    def _extract_citations(search_results: list) -> list:
        """검색 결과에서 인용 목록 추출"""
        return [
            {
                "title": r.get("title"),
                "url": r.get("url"),
                "source": r.get("source"),
            }
            for r in (search_results or [])
            if r.get("url")
        ]


export_service = ExportService()
