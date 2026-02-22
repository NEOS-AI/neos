"""
Research Session Service

연구 세션의 CRUD 작업을 담당합니다.
독립적인 research_sessions 테이블을 사용하여 세션 메타데이터를 관리합니다.

Note: 이전 구현은 langgraph_checkpoints 내부 스키마에 직접 의존했으나,
LangGraph 버전 업데이트 시 스키마가 변경될 수 있어 독립 테이블로 전환함.
(P1 코드 리뷰 이슈 M-6 해결)
"""

import uuid
import logging
from typing import Dict, Any, List, Optional

from neos.database.connection import db_manager

logger = logging.getLogger(__name__)


class ResearchSessionService:
    """연구 세션 관리 서비스

    research_sessions 테이블을 사용하여 LangGraph 내부 스키마 의존을 제거.
    세션 생성은 워크플로우 시작 시 create_session()을 호출하여 수행한다.
    """

    async def create_session(
        self,
        thread_id: str,
        user_id: str,
        original_query: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """새로운 연구 세션을 생성합니다.

        워크플로우 시작 시 호출되어 세션 메타데이터를 독립 테이블에 기록합니다.

        Returns:
            생성된 session_id (UUID)
        """
        session_id = str(uuid.uuid4())
        try:
            query = """
            INSERT INTO research_sessions
            (session_id, thread_id, user_id, original_query, status, metadata)
            VALUES ($1::uuid, $2, $3, $4, 'active', $5::jsonb)
            ON CONFLICT (thread_id) DO UPDATE SET
                original_query = EXCLUDED.original_query,
                updated_at = NOW()
            RETURNING session_id
            """
            import json
            metadata_json = json.dumps(metadata or {})
            rows = await db_manager.fetch_all(
                query, session_id, thread_id, user_id, original_query, metadata_json
            )
            result_id = str(rows[0][0]) if rows else session_id
            logger.info(
                f"[ResearchSession] Session created: thread={thread_id}, "
                f"session={result_id}"
            )
            return result_id
        except Exception as e:
            logger.error(f"[ResearchSession] Failed to create session: {e}")
            raise

    async def update_session_status(
        self,
        thread_id: str,
        status: str,
        metadata_updates: Optional[Dict[str, Any]] = None,
    ) -> None:
        """세션 상태를 업데이트합니다.

        워크플로우 완료/실패 시 호출됩니다.

        Args:
            thread_id: LangGraph thread_id
            status: 새 상태 ('active', 'completed', 'failed')
            metadata_updates: 추가 메타데이터 (quality_score 등)
        """
        try:
            if metadata_updates:
                import json
                query = """
                UPDATE research_sessions
                SET status = $1,
                    metadata = metadata || $2::jsonb,
                    updated_at = NOW()
                WHERE thread_id = $3
                """
                await db_manager.execute(
                    query, status, json.dumps(metadata_updates), thread_id
                )
            else:
                query = """
                UPDATE research_sessions
                SET status = $1, updated_at = NOW()
                WHERE thread_id = $2
                """
                await db_manager.execute(query, status, thread_id)

            logger.debug(f"[ResearchSession] Session updated: thread={thread_id}, status={status}")
        except Exception as e:
            logger.error(f"[ResearchSession] Failed to update session {thread_id}: {e}")

    async def list_sessions(
        self,
        user_id: str,
        limit: int = 20,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """사용자의 연구 세션 목록을 조회합니다."""
        try:
            query = """
            SELECT session_id, thread_id, original_query, status, metadata, created_at
            FROM research_sessions
            WHERE user_id = $1
            ORDER BY created_at DESC
            LIMIT $2 OFFSET $3
            """
            rows = await db_manager.fetch_all(query, user_id, limit, offset)

            sessions = []
            for row in rows:
                sessions.append({
                    "session_id": str(row[0]),
                    "thread_id": row[1],
                    "query": row[2] or "",
                    "user_id": user_id,
                    "status": row[3],
                    "metadata": row[4] or {},
                    "created_at": str(row[5]) if row[5] else None,
                })

            count_query = """
            SELECT COUNT(*) FROM research_sessions WHERE user_id = $1
            """
            count_result = await db_manager.fetch_all(count_query, user_id)
            total = count_result[0][0] if count_result else 0

            return {"sessions": sessions, "total": total}

        except Exception as e:
            logger.error(f"[ResearchSession] Failed to list sessions: {e}")
            return {"sessions": [], "total": 0}

    async def get_session(
        self,
        session_id: str,
        user_id: str,
    ) -> Optional[Dict[str, Any]]:
        """특정 연구 세션을 조회합니다."""
        try:
            query = """
            SELECT session_id, thread_id, original_query, status, metadata,
                   created_at, updated_at
            FROM research_sessions
            WHERE (session_id::text = $1 OR thread_id = $1)
              AND user_id = $2
            """
            rows = await db_manager.fetch_all(query, session_id, user_id)

            if not rows:
                return None

            row = rows[0]
            metadata = row[4] or {}

            return {
                "session_id": str(row[0]),
                "thread_id": row[1],
                "original_query": row[2],
                "status": row[3],
                "metadata": metadata,
                "created_at": str(row[5]) if row[5] else None,
                "updated_at": str(row[6]) if row[6] else None,
                "summary": {
                    "query": row[2] or "",
                    "quality_score": metadata.get("quality_score"),
                    "search_results_count": metadata.get("search_results_count", 0),
                    "errors": metadata.get("errors", []),
                },
            }

        except Exception as e:
            logger.error(f"[ResearchSession] Failed to get session {session_id}: {e}")
            return None

    async def branch_session(
        self,
        parent_session_id: str,
        branch_query: str,
        user_id: str,
        title: Optional[str] = None,
    ) -> str:
        """기존 세션에서 분기하여 새 세션을 생성합니다."""
        new_session_id = str(uuid.uuid4())

        try:
            insert_query = """
            INSERT INTO research_session_branches
            (branch_session_id, parent_session_id, user_id, branch_query, title, created_at)
            VALUES ($1, $2, $3, $4, $5, NOW())
            """
            await db_manager.execute(
                insert_query,
                new_session_id, parent_session_id, user_id, branch_query, title
            )
            logger.info(
                f"[ResearchSession] Branched session: {parent_session_id} → {new_session_id}"
            )
        except Exception as e:
            logger.error(f"[ResearchSession] Failed to branch session: {e}")
            raise

        return new_session_id

    async def list_branches(
        self,
        parent_session_id: str,
        user_id: str,
    ) -> List[Dict[str, Any]]:
        """특정 세션의 분기 목록을 조회합니다."""
        try:
            query = """
            SELECT branch_session_id, branch_query, title, created_at
            FROM research_session_branches
            WHERE parent_session_id = $1 AND user_id = $2
            ORDER BY created_at DESC
            """
            rows = await db_manager.fetch_all(query, parent_session_id, user_id)

            return [
                {
                    "branch_session_id": row[0],
                    "branch_query": row[1],
                    "title": row[2],
                    "created_at": str(row[3]) if row[3] else None,
                }
                for row in rows
            ]
        except Exception as e:
            logger.error(f"[ResearchSession] Failed to list branches: {e}")
            return []


# 싱글톤 인스턴스
research_session_service = ResearchSessionService()
