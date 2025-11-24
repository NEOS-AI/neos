"""Semantic Deduplication Utility

임베딩 기반 의미론적 중복 제거 유틸리티
"""

from typing import List, Dict, Any, Tuple, Optional
import logging
import numpy as np
from neos.config.settings import settings

logger = logging.getLogger(__name__)


class SemanticDeduplicator:
    """임베딩 기반 의미론적 중복 제거"""

    def __init__(self):
        self.embedding_service = None
        self.similarity_threshold = settings.SEMANTIC_SIMILARITY_THRESHOLD

    async def _get_embedding_service(self):
        """임베딩 서비스 획득 (lazy loading)"""
        if self.embedding_service is None:
            try:
                from neos.utils.embeddings import embedding_service
                self.embedding_service = embedding_service
            except Exception as e:
                logger.warning(f"Failed to load embedding service: {e}")
                self.embedding_service = None
        return self.embedding_service

    async def deduplicate_messages(
        self,
        messages: List[Dict[str, Any]],
        preserve_recent: int = 10
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """메시지 의미론적 중복 제거

        Args:
            messages: 메시지 리스트
            preserve_recent: 최근 N개 메시지는 무조건 보존

        Returns:
            (중복 제거된 메시지, 통계)
        """
        stats = {
            "removed_count": 0,
            "checked_count": 0,
            "method": "semantic" if settings.SEMANTIC_DEDUPLICATION else "text_hash"
        }

        if not messages or len(messages) <= preserve_recent:
            return messages, stats

        # 최근 메시지와 과거 메시지 분리
        recent_messages = messages[-preserve_recent:] if preserve_recent > 0 else []
        old_messages = messages[:-preserve_recent] if preserve_recent > 0 else messages

        # 시스템 메시지는 항상 보존
        system_messages = [msg for msg in old_messages if msg.get("role") == "system"]
        non_system_messages = [msg for msg in old_messages if msg.get("role") != "system"]

        # 중복 제거 수행
        if settings.SEMANTIC_DEDUPLICATION:
            try:
                unique_messages, dedup_stats = await self._semantic_deduplicate(non_system_messages)
                stats.update(dedup_stats)
            except Exception as e:
                logger.warning(f"Semantic deduplication failed: {e}, falling back to text hash")
                unique_messages, dedup_stats = self._text_hash_deduplicate(non_system_messages)
                stats.update(dedup_stats)
                stats["method"] = "text_hash_fallback"
        else:
            unique_messages, dedup_stats = self._text_hash_deduplicate(non_system_messages)
            stats.update(dedup_stats)

        # 재조합: 시스템 메시지 + 중복 제거된 메시지 + 최근 메시지
        result = system_messages + unique_messages + recent_messages

        logger.info(
            f"[SemanticDedup] Removed {stats['removed_count']} duplicate messages "
            f"using {stats['method']} method"
        )

        return result, stats

    async def _semantic_deduplicate(
        self,
        messages: List[Dict[str, Any]]
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """임베딩 기반 의미론적 중복 제거

        Args:
            messages: 메시지 리스트

        Returns:
            (중복 제거된 메시지, 통계)
        """
        stats = {"removed_count": 0, "checked_count": 0}

        if not messages:
            return messages, stats

        # 임베딩 서비스 확인
        embedding_service = await self._get_embedding_service()
        if not embedding_service:
            # Fallback to text hash
            return self._text_hash_deduplicate(messages)

        # 메시지 내용 추출
        contents = []
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str) and content.strip():
                contents.append(content)
            else:
                contents.append("")  # Empty content

        # 임베딩 생성
        try:
            embeddings = await self._get_embeddings_batch(contents, embedding_service)
        except Exception as e:
            logger.warning(f"Failed to generate embeddings: {e}")
            return self._text_hash_deduplicate(messages)

        if not embeddings or len(embeddings) != len(messages):
            logger.warning("Embedding count mismatch, using text hash fallback")
            return self._text_hash_deduplicate(messages)

        # 유사도 기반 중복 제거
        unique_messages = []
        unique_embeddings = []

        for i, (msg, emb) in enumerate(zip(messages, embeddings)):
            stats["checked_count"] += 1

            # 기존 메시지와 유사도 비교
            is_duplicate = False

            for unique_emb in unique_embeddings:
                similarity = self._cosine_similarity(emb, unique_emb)

                if similarity >= self.similarity_threshold:
                    is_duplicate = True
                    stats["removed_count"] += 1
                    logger.debug(
                        f"[SemanticDedup] Removed duplicate (similarity: {similarity:.3f})"
                    )
                    break

            if not is_duplicate:
                unique_messages.append(msg)
                unique_embeddings.append(emb)

        return unique_messages, stats

    def _text_hash_deduplicate(
        self,
        messages: List[Dict[str, Any]]
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """텍스트 해시 기반 중복 제거 (fallback)

        Args:
            messages: 메시지 리스트

        Returns:
            (중복 제거된 메시지, 통계)
        """
        stats = {"removed_count": 0, "checked_count": 0}

        seen_hashes = set()
        unique_messages = []

        for msg in messages:
            stats["checked_count"] += 1

            content = msg.get("content", "")
            if isinstance(content, str):
                # 처음 200자로 해시 생성
                content_hash = hash(content[:200].strip())

                if content_hash not in seen_hashes:
                    seen_hashes.add(content_hash)
                    unique_messages.append(msg)
                else:
                    stats["removed_count"] += 1
            else:
                # Non-string content는 항상 유지
                unique_messages.append(msg)

        return unique_messages, stats

    async def _get_embeddings_batch(
        self,
        texts: List[str],
        embedding_service: Any
    ) -> Optional[List[np.ndarray]]:
        """배치 임베딩 생성

        Args:
            texts: 텍스트 리스트
            embedding_service: 임베딩 서비스

        Returns:
            임베딩 리스트
        """
        try:
            # 빈 텍스트 제거
            valid_texts = [text if text.strip() else " " for text in texts]

            # 임베딩 서비스 호출
            if hasattr(embedding_service, 'get_embeddings_batch'):
                embeddings = await embedding_service.get_embeddings_batch(valid_texts)
            elif hasattr(embedding_service, 'get_embedding'):
                # Fallback: 하나씩 호출
                embeddings = []
                for text in valid_texts:
                    emb = await embedding_service.get_embedding(text)
                    embeddings.append(emb)
            else:
                logger.warning("Embedding service has no suitable method")
                return None

            # numpy array로 변환
            embeddings = [np.array(emb) for emb in embeddings]
            return embeddings

        except Exception as e:
            logger.error(f"Failed to get embeddings: {e}")
            return None

    def _cosine_similarity(self, vec1: np.ndarray, vec2: np.ndarray) -> float:
        """코사인 유사도 계산

        Args:
            vec1: 벡터 1
            vec2: 벡터 2

        Returns:
            유사도 (0~1)
        """
        try:
            dot_product = np.dot(vec1, vec2)
            norm1 = np.linalg.norm(vec1)
            norm2 = np.linalg.norm(vec2)

            if norm1 == 0 or norm2 == 0:
                return 0.0

            similarity = dot_product / (norm1 * norm2)

            # -1~1 범위를 0~1로 변환
            similarity = (similarity + 1) / 2

            return float(similarity)

        except Exception as e:
            logger.warning(f"Similarity calculation error: {e}")
            return 0.0

    async def find_similar_messages(
        self,
        query_message: Dict[str, Any],
        candidate_messages: List[Dict[str, Any]],
        top_k: int = 5
    ) -> List[Tuple[Dict[str, Any], float]]:
        """쿼리 메시지와 유사한 메시지 찾기

        Args:
            query_message: 쿼리 메시지
            candidate_messages: 후보 메시지 리스트
            top_k: 상위 K개 반환

        Returns:
            (메시지, 유사도) 튜플 리스트
        """
        embedding_service = await self._get_embedding_service()
        if not embedding_service:
            return []

        # 쿼리 임베딩
        query_content = query_message.get("content", "")
        if not query_content:
            return []

        try:
            query_embedding = await embedding_service.get_embedding(query_content)
            query_embedding = np.array(query_embedding)
        except Exception as e:
            logger.error(f"Failed to get query embedding: {e}")
            return []

        # 후보 임베딩
        candidate_contents = [msg.get("content", "") for msg in candidate_messages]
        candidate_embeddings = await self._get_embeddings_batch(
            candidate_contents,
            embedding_service
        )

        if not candidate_embeddings:
            return []

        # 유사도 계산
        similarities = []
        for msg, emb in zip(candidate_messages, candidate_embeddings):
            similarity = self._cosine_similarity(query_embedding, emb)
            similarities.append((msg, similarity))

        # 유사도 순 정렬
        similarities.sort(key=lambda x: x[1], reverse=True)

        return similarities[:top_k]


# 전역 인스턴스
semantic_deduplicator = SemanticDeduplicator()
