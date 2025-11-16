"""Query Repository - 쿼리 히스토리 및 HyperResearch 데이터 접근 레이어

이 모듈은 Repository 패턴을 구현하여 쿼리 히스토리 및 HyperDeepResearch 보고서
관련 모든 데이터베이스 쿼리를 캡슐화합니다.
"""

from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime
from dataclasses import dataclass

from neos.database.connection import db_manager


@dataclass
class HyperResearchReport:
    """HyperResearch 보고서 데이터 클래스"""
    report_id: str
    user_id: str
    session_id: str
    research_topic: str
    research_status: str
    created_at: datetime
    completed_at: Optional[datetime]
    total_sections: int
    total_sources: int
    total_queries: int
    quality_score: Optional[float]
    metadata: Dict[str, Any]


@dataclass
class HyperResearchSection:
    """HyperResearch 섹션 데이터 클래스"""
    section_id: str
    section_order: int
    section_type: str
    section_title: str
    section_content: Optional[str]
    section_summary: Optional[str]
    sources_count: int
    created_at: datetime
    completed_at: Optional[datetime]


class QueryRepository:
    """쿼리 및 HyperResearch 데이터 리포지토리"""

    # ==================== HyperResearch 보고서 조회 ====================

    @staticmethod
    async def get_hyper_research_report(report_id: str) -> Optional[HyperResearchReport]:
        """HyperResearch 보고서 메타데이터 조회

        Args:
            report_id: 보고서 ID

        Returns:
            보고서 데이터 또는 None
        """
        query = """
        SELECT
            report_id,
            user_id,
            session_id,
            research_topic,
            research_status,
            created_at,
            completed_at,
            total_sections,
            total_sources,
            total_queries,
            quality_score,
            metadata
        FROM hyper_research_reports
        WHERE report_id = $1 AND deleted_at IS NULL
        """

        row = await db_manager.fetch_one(query, report_id)

        if not row:
            return None

        return HyperResearchReport(
            report_id=row[0],
            user_id=row[1],
            session_id=row[2],
            research_topic=row[3],
            research_status=row[4],
            created_at=row[5],
            completed_at=row[6],
            total_sections=row[7] or 0,
            total_sources=row[8] or 0,
            total_queries=row[9] or 0,
            quality_score=row[10],
            metadata=row[11] if row[11] else {}
        )

    @staticmethod
    async def get_hyper_research_sections(report_id: str) -> List[HyperResearchSection]:
        """HyperResearch 보고서의 섹션 목록 조회

        Args:
            report_id: 보고서 ID

        Returns:
            섹션 목록
        """
        query = """
        SELECT
            section_id,
            section_order,
            section_type,
            section_title,
            section_content,
            section_summary,
            sources_count,
            created_at,
            completed_at
        FROM hyper_research_sections
        WHERE report_id = $1
        ORDER BY section_order ASC
        """

        rows = await db_manager.fetch_all(query, report_id)

        return [
            HyperResearchSection(
                section_id=row[0],
                section_order=row[1],
                section_type=row[2],
                section_title=row[3],
                section_content=row[4],
                section_summary=row[5],
                sources_count=row[6] or 0,
                created_at=row[7],
                completed_at=row[8]
            )
            for row in rows
        ]

    @staticmethod
    async def list_hyper_research_reports(
        user_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> Tuple[List[HyperResearchReport], int]:
        """HyperResearch 보고서 목록 조회

        Args:
            user_id: 사용자 ID 필터 (선택)
            status: 상태 필터 (선택)
            limit: 최대 결과 수
            offset: 오프셋

        Returns:
            (보고서 목록, 전체 개수)
        """
        # WHERE 절 구성
        where_clauses = ["deleted_at IS NULL"]
        params = []
        param_idx = 1

        if user_id:
            where_clauses.append(f"user_id = ${param_idx}")
            params.append(user_id)
            param_idx += 1

        if status:
            where_clauses.append(f"research_status = ${param_idx}")
            params.append(status)
            param_idx += 1

        where_sql = " AND ".join(where_clauses)

        # 보고서 목록 조회
        list_query = f"""
        SELECT
            report_id,
            user_id,
            session_id,
            research_topic,
            research_status,
            created_at,
            completed_at,
            total_sections,
            total_sources,
            total_queries,
            quality_score,
            metadata
        FROM hyper_research_reports
        WHERE {where_sql}
        ORDER BY created_at DESC
        LIMIT ${param_idx} OFFSET ${param_idx + 1}
        """

        params.extend([limit, offset])
        rows = await db_manager.fetch_all(list_query, *params)

        # 전체 개수 조회
        count_query = f"""
        SELECT COUNT(*)
        FROM hyper_research_reports
        WHERE {where_sql}
        """

        # limit, offset 제외한 파라미터만 사용
        count_params = params[:-2]
        count_result = await db_manager.fetch_one(count_query, *count_params)
        total_count = count_result[0] if count_result else 0

        # 데이터 변환
        reports = [
            HyperResearchReport(
                report_id=row[0],
                user_id=row[1],
                session_id=row[2],
                research_topic=row[3],
                research_status=row[4],
                created_at=row[5],
                completed_at=row[6],
                total_sections=row[7] or 0,
                total_sources=row[8] or 0,
                total_queries=row[9] or 0,
                quality_score=row[10],
                metadata=row[11] if row[11] else {}
            )
            for row in rows
        ]

        return reports, total_count
