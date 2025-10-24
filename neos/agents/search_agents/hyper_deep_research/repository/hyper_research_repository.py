"""Repository pattern implementation for HyperDeepResearch database operations.

This module implements the Repository pattern to separate database access logic
from business logic, making the code more maintainable and testable.
"""

import json
import uuid
from typing import Dict, List, Any, Optional
from neos.database.connection import db_manager


class HyperResearchRepository:
    """Repository for HyperDeepResearch database operations.

    Implements the Repository pattern to encapsulate all database
    operations related to hyper research reports, sections, and data collection.
    """

    # ==================== Table Management ====================

    @staticmethod
    async def ensure_tables_exist() -> None:
        """Ensure all required tables exist, create if missing."""
        try:
            # Check if tables exist
            check_query = "SELECT 1 FROM hyper_research_reports LIMIT 1"
            await db_manager.fetch_one(check_query)
        except Exception:
            # Tables don't exist, create them
            await HyperResearchRepository._create_tables()

    @staticmethod
    async def _create_tables() -> None:
        """Create all HyperDeepResearch tables."""
        print("[INFO] Creating HyperDeepResearch tables...")

        try:
            # Reports table
            await db_manager.execute("""
                CREATE TABLE IF NOT EXISTS hyper_research_reports (
                    id SERIAL PRIMARY KEY,
                    report_id VARCHAR(255) UNIQUE NOT NULL,
                    user_id VARCHAR(255) NOT NULL,
                    session_id VARCHAR(255) NOT NULL,
                    research_topic TEXT NOT NULL,
                    research_plan JSONB,
                    research_status VARCHAR(50) DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    started_at TIMESTAMP,
                    completed_at TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    total_sections INTEGER DEFAULT 0,
                    total_sources INTEGER DEFAULT 0,
                    total_queries INTEGER DEFAULT 0,
                    processing_time_ms INTEGER,
                    quality_score FLOAT,
                    completeness_score FLOAT,
                    metadata JSONB DEFAULT '{}'
                )
            """)

            # Sections table
            await db_manager.execute("""
                CREATE TABLE IF NOT EXISTS hyper_research_sections (
                    id SERIAL PRIMARY KEY,
                    section_id VARCHAR(255) UNIQUE NOT NULL,
                    report_id VARCHAR(255) NOT NULL,
                    section_order INTEGER NOT NULL,
                    section_level INTEGER DEFAULT 1,
                    parent_section_id VARCHAR(255),
                    section_type VARCHAR(100) NOT NULL,
                    section_title TEXT NOT NULL,
                    section_content TEXT,
                    section_summary TEXT,
                    section_status VARCHAR(50) DEFAULT 'pending',
                    sources_count INTEGER DEFAULT 0,
                    sources JSONB DEFAULT '[]',
                    queries JSONB DEFAULT '[]',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    started_at TIMESTAMP,
                    completed_at TIMESTAMP,
                    processing_time_ms INTEGER,
                    metadata JSONB DEFAULT '{}'
                )
            """)

            # Data collection table
            await db_manager.execute("""
                CREATE TABLE IF NOT EXISTS hyper_research_data_collection (
                    id SERIAL PRIMARY KEY,
                    collection_id VARCHAR(255) UNIQUE NOT NULL,
                    report_id VARCHAR(255) NOT NULL,
                    section_id VARCHAR(255),
                    query_text TEXT NOT NULL,
                    query_type VARCHAR(50),
                    search_phase INTEGER,
                    results_count INTEGER DEFAULT 0,
                    results JSONB DEFAULT '[]',
                    executed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    execution_time_ms INTEGER,
                    metadata JSONB DEFAULT '{}'
                )
            """)

            # Criticism feedback table
            await db_manager.execute("""
                CREATE TABLE IF NOT EXISTS hyper_research_criticism_feedback (
                    id SERIAL PRIMARY KEY,
                    feedback_id VARCHAR(255) UNIQUE NOT NULL,
                    report_id VARCHAR(255) NOT NULL,
                    section_type VARCHAR(100) NOT NULL,
                    section_title TEXT NOT NULL,
                    severity VARCHAR(50) DEFAULT 'none',
                    has_issues BOOLEAN DEFAULT FALSE,
                    feedback_text TEXT,
                    suggested_queries JSONB DEFAULT '[]',
                    missing_perspectives JSONB DEFAULT '[]',
                    redirect_suggestion TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    metadata JSONB DEFAULT '{}'
                )
            """)

            print("[INFO] HyperDeepResearch tables created successfully")

        except Exception as e:
            print(f"[WARNING] Failed to create tables: {e}")
            print("[INFO] Will continue without DB storage")

    # ==================== Report Operations ====================

    @staticmethod
    async def create_report(
        report_id: str,
        user_id: str,
        session_id: str,
        topic: str,
        research_plan: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Create a new research report.

        Args:
            report_id: Unique report identifier
            user_id: User ID
            session_id: Session ID
            topic: Research topic
            research_plan: Optional research plan dictionary

        Returns:
            True if successful, False otherwise
        """
        try:
            plan_json = json.dumps(research_plan) if research_plan else json.dumps({
                "phases": [
                    "topic_analysis", "methodology", "multi_query_collection",
                    "deep_analysis", "gap_analysis", "validation",
                    "critical_thinking", "synthesis"
                ]
            })

            query = """
                INSERT INTO hyper_research_reports
                (report_id, user_id, session_id, research_topic, research_status, research_plan)
                VALUES ($1, $2, $3, $4, $5, $6)
            """

            await db_manager.execute(
                query, report_id, user_id, session_id, topic, "pending", plan_json
            )

            print(f"[DEBUG] Created report in DB: {report_id}")
            return True

        except Exception as e:
            print(f"[ERROR] Failed to create report: {e}")
            return False

    @staticmethod
    async def update_report_status(
        report_id: str,
        status: str,
        timestamp_field: Optional[str] = None,
        quality_score: Optional[float] = None
    ) -> bool:
        """Update report status.

        Args:
            report_id: Report identifier
            status: New status
            timestamp_field: Optional timestamp field to update
            quality_score: Optional quality score

        Returns:
            True if successful, False otherwise
        """
        try:
            updates = [f"research_status = '{status}'"]

            if timestamp_field:
                updates.append(f"{timestamp_field} = CURRENT_TIMESTAMP")

            if quality_score is not None:
                updates.append(f"quality_score = {quality_score}")

            query = f"""
                UPDATE hyper_research_reports
                SET {', '.join(updates)}
                WHERE report_id = $1
            """

            await db_manager.execute(query, report_id)
            print(f"[DEBUG] Updated report status to: {status}")
            return True

        except Exception as e:
            print(f"[ERROR] Failed to update report status: {e}")
            return False

    @staticmethod
    async def update_report_metadata(
        report_id: str,
        total_sections: int,
        total_sources: int,
        total_queries: int,
        metadata: Dict[str, Any]
    ) -> bool:
        """Update report metadata.

        Args:
            report_id: Report identifier
            total_sections: Total number of sections
            total_sources: Total number of sources
            total_queries: Total number of queries
            metadata: Additional metadata dictionary

        Returns:
            True if successful, False otherwise
        """
        try:
            query = """
                UPDATE hyper_research_reports
                SET total_sections = $1,
                    total_sources = $2,
                    total_queries = $3,
                    metadata = $4
                WHERE report_id = $5
            """

            await db_manager.execute(
                query,
                total_sections,
                total_sources,
                total_queries,
                json.dumps(metadata),
                report_id
            )

            return True

        except Exception as e:
            print(f"[ERROR] Failed to update report metadata: {e}")
            return False

    # ==================== Section Operations ====================

    @staticmethod
    async def create_section(
        report_id: str,
        section_type: str,
        section_order: int,
        title: str,
        content: str,
        status: str,
        sources_count: int = 0
    ) -> str:
        """Create a new report section.

        Args:
            report_id: Parent report ID
            section_type: Type of section
            section_order: Order number
            title: Section title
            content: Section content
            status: Section status
            sources_count: Number of sources

        Returns:
            Section ID if successful, empty string otherwise
        """
        try:
            section_id = f"section_{uuid.uuid4()}"

            query = """
                INSERT INTO hyper_research_sections
                (section_id, report_id, section_order, section_type,
                 section_title, section_content, section_status, sources_count)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """

            await db_manager.execute(
                query, section_id, report_id, section_order, section_type,
                title, content, status, sources_count
            )

            print(f"[DEBUG] Created section in DB: {title}")
            return section_id

        except Exception as e:
            print(f"[ERROR] Failed to create section: {e}")
            return ""

    # ==================== Data Collection Operations ====================

    @staticmethod
    async def record_data_collection(
        report_id: str,
        query_text: str,
        query_type: str,
        phase: int,
        results: List[Dict[str, Any]],
        section_id: Optional[str] = None
    ) -> bool:
        """Record data collection activity.

        Args:
            report_id: Parent report ID
            query_text: Search query
            query_type: Type of query
            phase: Search phase number
            results: Search results
            section_id: Optional section ID

        Returns:
            True if successful, False otherwise
        """
        try:
            collection_id = f"collection_{uuid.uuid4()}"

            query = """
                INSERT INTO hyper_research_data_collection
                (collection_id, report_id, section_id, query_text,
                 query_type, search_phase, results_count, results)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """

            await db_manager.execute(
                query,
                collection_id,
                report_id,
                section_id,
                query_text,
                query_type,
                phase,
                len(results),
                json.dumps(results[:5])  # Store only first 5 for space
            )

            return True

        except Exception as e:
            print(f"[ERROR] Failed to record data collection: {e}")
            return False

    # ==================== Criticism Feedback Operations ====================

    @staticmethod
    async def record_criticism_feedback(
        report_id: str,
        section_type: str,
        section_title: str,
        feedback: Dict[str, Any]
    ) -> bool:
        """Record criticism feedback.

        Args:
            report_id: Parent report ID
            section_type: Type of section reviewed
            section_title: Title of section reviewed
            feedback: Feedback dictionary

        Returns:
            True if successful, False otherwise
        """
        try:
            feedback_id = f"feedback_{uuid.uuid4()}"

            query = """
                INSERT INTO hyper_research_criticism_feedback
                (feedback_id, report_id, section_type, section_title,
                 severity, has_issues, feedback_text, suggested_queries,
                 missing_perspectives, redirect_suggestion)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            """

            await db_manager.execute(
                query,
                feedback_id,
                report_id,
                section_type,
                section_title,
                feedback.get("severity", "none"),
                feedback.get("has_issues", False),
                feedback.get("feedback", ""),
                json.dumps(feedback.get("suggested_queries", [])),
                json.dumps(feedback.get("missing_perspectives", [])),
                feedback.get("redirect_suggestion", "")
            )

            print(f"[DEBUG] Recorded criticism feedback: {feedback_id}")
            return True

        except Exception as e:
            print(f"[ERROR] Failed to record criticism feedback: {e}")
            return False
