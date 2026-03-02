"""
Knowledge Graph Population Service (Phase 3.1)

검색 결과에서 엔티티/관계를 추출하여 KG를 자동 구축합니다.
비동기로 실행되어 검색 latency에 영향을 주지 않습니다.
"""

from typing import Dict, Any, List
import logging
import json

from neos.pipelines.document.knowledge_graph import KnowledgeGraphExtractor
from neos.database.connection import db_manager
from neos.utils.embeddings import embedding_manager
from neos.config.settings import settings

logger = logging.getLogger(__name__)


class KGPopulationService:
    """검색 결과에서 KG를 자동 구축하는 서비스"""

    def __init__(self):
        self.extractor = KnowledgeGraphExtractor()
        self.min_confidence = getattr(settings, "KG_MIN_CONFIDENCE", 0.7)

    async def populate_from_search_results(
        self,
        search_results: List[Dict[str, Any]],
        session_id: str,
    ) -> None:
        """검색 결과에서 엔티티/관계 추출 후 DB에 저장

        Args:
            search_results: 검색 결과 목록
            session_id: 세션 ID (source_document_id로 사용)
        """
        if not getattr(settings, "KG_POPULATION_ENABLED", True):
            return

        try:
            # 검색 결과에서 텍스트 추출 (최대 20개)
            kg_results = []
            for result in search_results[:20]:
                content = result.get("content") or result.get("query_text") or ""
                if not content or len(content) < 50:
                    continue

                try:
                    kg_result = await self.extractor.extract(
                        text=content[:3000],  # 텍스트 길이 제한
                        context={
                            "source_url": result.get("url"),
                            "source_title": result.get("title"),
                            "session_id": session_id,
                        },
                    )
                    kg_results.append(kg_result)
                except Exception as e:
                    logger.debug(f"KG extraction failed for result: {e}")
                    continue

            if not kg_results:
                return

            # 결과 병합
            merged = self.extractor.merge_results(kg_results)

            # DB에 저장
            await self._store_entities(merged.entities, session_id)
            await self._store_relations(merged.relations)

            logger.info(
                f"[KGPopulation] 저장 완료: "
                f"entities={len(merged.entities)}, "
                f"relations={len(merged.relations)}"
            )

        except Exception as e:
            logger.error(f"[KGPopulation] 실패: {e}", exc_info=True)

    async def _store_entities(self, entities, session_id: str) -> None:
        """엔티티를 DB에 저장"""
        pool = await db_manager.get_pool()
        async with pool.acquire() as conn:
            for entity in entities:
                if entity.confidence_score < self.min_confidence:
                    continue

                try:
                    # 엔티티 임베딩 생성
                    embed_text = f"{entity.entity_name} {entity.entity_description or ''}"
                    embedding = await embedding_manager.get_embedding(embed_text)

                    await conn.execute("""
                        INSERT INTO kg_entities (
                            entity_id, entity_type, entity_name, entity_description,
                            properties, confidence_score, embedding, source_document_id
                        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                        ON CONFLICT (entity_id) DO UPDATE SET
                            confidence_score = GREATEST(kg_entities.confidence_score, EXCLUDED.confidence_score),
                            updated_at = NOW()
                    """,
                        entity.entity_id,
                        entity.entity_type,
                        entity.entity_name,
                        entity.entity_description,
                        json.dumps(entity.properties or {}),
                        entity.confidence_score,
                        str(embedding) if embedding else None,
                        session_id,
                    )
                except Exception as e:
                    logger.debug(f"Entity insert failed: {e}")

    async def _store_relations(self, relations) -> None:
        """관계를 DB에 저장"""
        pool = await db_manager.get_pool()
        async with pool.acquire() as conn:
            for relation in relations:
                if relation.confidence_score < self.min_confidence:
                    continue

                try:
                    await conn.execute("""
                        INSERT INTO kg_relations (
                            source_entity_id, target_entity_id, relation_type,
                            confidence_score, properties
                        ) VALUES ($1, $2, $3, $4, $5)
                        ON CONFLICT (source_entity_id, target_entity_id, relation_type)
                        DO UPDATE SET
                            confidence_score = GREATEST(
                                kg_relations.confidence_score, EXCLUDED.confidence_score
                            )
                    """,
                        relation.source_entity_id,
                        relation.target_entity_id,
                        relation.relation_type,
                        relation.confidence_score,
                        json.dumps(relation.properties or {}),
                    )
                except Exception as e:
                    logger.debug(f"Relation insert failed: {e}")


# 전역 인스턴스
kg_population_service = KGPopulationService()
