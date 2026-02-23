"""
Persistent Evidence Graph Service (Phase 3.2)

FactChecker의 Claim/Contradiction을 DB에 영구 저장하고,
크로스 세션 증거를 조회하는 서비스.
"""

import logging
from typing import Dict, Any, List, Optional

from neos.database.connection import db_manager
from neos.utils.embeddings import embedding_manager
from neos.config.settings import settings

logger = logging.getLogger(__name__)


class EvidenceGraphService:
    """증거 그래프 서비스 — 주장, 소스, 모순의 영구 저장/조회"""

    async def persist_claim(
        self,
        claim_text: str,
        claim_type: str,
        confidence: float,
        verification_status: str,
        user_id: str,
        session_id: str,
        source_url: Optional[str] = None,
        source_title: Optional[str] = None,
    ) -> Optional[int]:
        """주장을 DB에 저장하고 claim_id 반환"""
        try:
            embedding = await embedding_manager.get_embedding(claim_text)
            pool = await db_manager.get_pool()
            async with pool.acquire() as conn:
                row = await conn.fetchrow("""
                    INSERT INTO evidence_claims (
                        claim_text, claim_type, confidence, verification_status,
                        embedding, user_id, session_id
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7)
                    RETURNING claim_id
                """,
                    claim_text, claim_type, confidence, verification_status,
                    str(embedding) if embedding else None, user_id, session_id,
                )
                claim_id = row["claim_id"]

                # 소스도 함께 저장
                if source_url:
                    await self._link_source(
                        conn, claim_id, source_url, source_title or "", "supporting"
                    )

                return claim_id
        except Exception as e:
            logger.error(f"[EvidenceGraph] Claim 저장 실패: {e}")
            return None

    async def _link_source(
        self, conn, claim_id: int, source_url: str, source_title: str,
        evidence_type: str,
    ) -> None:
        """주장과 소스를 연결"""
        # 소스 upsert
        row = await conn.fetchrow("""
            INSERT INTO evidence_sources (source_url, source_title)
            VALUES ($1, $2)
            ON CONFLICT (source_url) DO UPDATE SET source_title = EXCLUDED.source_title
            RETURNING source_id
        """, source_url, source_title)
        source_id = row["source_id"]

        # 체인 생성
        await conn.execute("""
            INSERT INTO evidence_chains (claim_id, source_id, evidence_type)
            VALUES ($1, $2, $3)
            ON CONFLICT (claim_id, source_id, evidence_type) DO NOTHING
        """, claim_id, source_id, evidence_type)

    async def persist_contradiction(
        self,
        claim_id_1: int,
        claim_id_2: int,
        contradiction_type: str,
        severity: str,
        explanation: str,
    ) -> None:
        """모순을 DB에 저장"""
        try:
            # claim_id_1 < claim_id_2 보장
            c1, c2 = sorted([claim_id_1, claim_id_2])
            pool = await db_manager.get_pool()
            async with pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO evidence_contradictions (
                        claim_id_1, claim_id_2, contradiction_type, severity, explanation
                    ) VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT (claim_id_1, claim_id_2) DO UPDATE SET
                        severity = EXCLUDED.severity,
                        explanation = EXCLUDED.explanation
                """, c1, c2, contradiction_type, severity, explanation)
        except Exception as e:
            logger.error(f"[EvidenceGraph] 모순 저장 실패: {e}")

    async def find_relevant_past_evidence(
        self,
        query: str,
        user_id: str,
        similarity_threshold: float = 0.80,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """사용자의 과거 연구에서 관련 증거 검색"""
        try:
            embedding = await embedding_manager.get_embedding(query)
            if not embedding:
                return []

            pool = await db_manager.get_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT
                        claim_id, claim_text, claim_type, confidence,
                        verification_status, session_id,
                        1 - (embedding <=> $1::vector) AS similarity
                    FROM evidence_claims
                    WHERE user_id = $2
                      AND 1 - (embedding <=> $1::vector) > $3
                    ORDER BY similarity DESC
                    LIMIT $4
                """, str(embedding), user_id, similarity_threshold, limit)

                results = []
                for row in rows:
                    # 해당 claim의 증거 체인도 조회
                    evidence = await self._get_claim_evidence(conn, row["claim_id"])
                    results.append({
                        "claim": {
                            "id": row["claim_id"],
                            "text": row["claim_text"],
                            "type": row["claim_type"],
                            "confidence": row["confidence"],
                            "status": row["verification_status"],
                            "similarity": float(row["similarity"]),
                        },
                        "evidence": evidence,
                    })
                return results

        except Exception as e:
            logger.error(f"[EvidenceGraph] 과거 증거 검색 실패: {e}")
            return []

    async def _get_claim_evidence(self, conn, claim_id: int) -> Dict[str, Any]:
        """특정 claim의 증거 체인 조회"""
        rows = await conn.fetch("""
            SELECT
                ec.evidence_type, ec.confidence,
                es.source_url, es.source_title, ec.evidence_snippet
            FROM evidence_chains ec
            JOIN evidence_sources es ON es.source_id = ec.source_id
            WHERE ec.claim_id = $1
        """, claim_id)

        supporting = []
        contradicting = []
        for row in rows:
            item = {
                "source_url": row["source_url"],
                "source_title": row["source_title"],
                "snippet": row["evidence_snippet"],
                "confidence": row["confidence"],
            }
            if row["evidence_type"] == "supporting":
                supporting.append(item)
            elif row["evidence_type"] == "contradicting":
                contradicting.append(item)

        return {"supporting": supporting, "contradicting": contradicting}


# 전역 인스턴스
evidence_graph_service = EvidenceGraphService()
