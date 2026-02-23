"""
Refinement Service (Phase 3.8)

사용자의 mid-session 연구 조정 요청을 처리합니다.
"""

import logging
from typing import Dict, Any, List

from neos.database.connection import db_manager
from neos.config.settings import settings

logger = logging.getLogger(__name__)


class RefinementService:
    """Interactive Research Refinement 서비스"""

    async def reject_source(
        self, user_id: str, session_id: str, source_url: str, reason: str = ""
    ) -> Dict[str, Any]:
        """소스를 블랙리스트에 추가"""
        try:
            pool = await db_manager.get_pool()
            async with pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO user_source_preferences (
                        user_id, source_url, action, reason, session_id
                    ) VALUES ($1, $2, 'blacklist', $3, $4)
                    ON CONFLICT (user_id, source_url, action) DO UPDATE SET
                        reason = EXCLUDED.reason
                """, user_id, source_url, reason, session_id)

            logger.info(f"[Refinement] Source blacklisted: {source_url}")
            return {"status": "blacklisted", "source_url": source_url}

        except Exception as e:
            logger.error(f"[Refinement] reject_source failed: {e}")
            raise

    async def adjust_trust(
        self, user_id: str, session_id: str, source_url: str, adjustment: float
    ) -> Dict[str, Any]:
        """소스 신뢰도 조정 (-1.0 ~ +1.0)"""
        adjustment = max(-1.0, min(1.0, adjustment))

        try:
            pool = await db_manager.get_pool()
            async with pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO user_source_preferences (
                        user_id, source_url, action, trust_adjustment, session_id
                    ) VALUES ($1, $2, 'trust_adjust', $3, $4)
                    ON CONFLICT (user_id, source_url, action) DO UPDATE SET
                        trust_adjustment = EXCLUDED.trust_adjustment
                """, user_id, source_url, adjustment, session_id)

            logger.info(f"[Refinement] Trust adjusted: {source_url} ({adjustment:+.2f})")
            return {"status": "adjusted", "source_url": source_url, "adjustment": adjustment}

        except Exception as e:
            logger.error(f"[Refinement] adjust_trust failed: {e}")
            raise

    async def get_user_blacklist(self, user_id: str) -> List[str]:
        """사용자의 블랙리스트 소스 URL 목록"""
        try:
            pool = await db_manager.get_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT source_url FROM user_source_preferences
                    WHERE user_id = $1 AND action = 'blacklist'
                """, user_id)
                return [row["source_url"] for row in rows]
        except Exception as e:
            logger.error(f"[Refinement] get_blacklist failed: {e}")
            return []

    async def get_trust_adjustments(self, user_id: str) -> Dict[str, float]:
        """사용자의 소스별 신뢰도 조정값"""
        try:
            pool = await db_manager.get_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT source_url, trust_adjustment FROM user_source_preferences
                    WHERE user_id = $1 AND action = 'trust_adjust'
                """, user_id)
                return {row["source_url"]: row["trust_adjustment"] for row in rows}
        except Exception as e:
            logger.error(f"[Refinement] get_trust_adjustments failed: {e}")
            return {}

    async def investigate_claim(
        self, user_id: str, session_id: str, claim_text: str, depth: str = "medium"
    ) -> Dict[str, Any]:
        """특정 주장에 대해 추가 검색 — 워크플로우 재실행으로 위임"""
        refined_query = f"Investigate and verify: {claim_text}"

        # 깊이에 따라 intent 힌트 조정
        intent_hint = {
            "shallow": "information_seeking",
            "medium": "deep_research",
            "deep": "hyper_deep_research",
        }.get(depth, "deep_research")

        return {
            "status": "submitted",
            "refined_query": refined_query,
            "intent_hint": intent_hint,
            "original_claim": claim_text,
        }

    async def redirect_research(
        self, user_id: str, session_id: str, new_direction: str,
        keep_existing: bool = True,
    ) -> Dict[str, Any]:
        """연구 방향 변경"""
        return {
            "status": "redirected",
            "new_direction": new_direction,
            "keep_existing": keep_existing,
            "session_id": session_id,
        }

    async def request_more_detail(
        self, user_id: str, session_id: str, topic: str
    ) -> Dict[str, Any]:
        """특정 토픽에 대한 상세 연구 요청"""
        refined_query = f"Provide detailed analysis on: {topic}"
        return {
            "status": "submitted",
            "refined_query": refined_query,
            "topic": topic,
        }


refinement_service = RefinementService()
