"""
시맨틱 캐싱 시스템

임베딩 기반 유사도 검색을 통해 유사한 쿼리의 캐시를 찾습니다.
"""
import logging
import numpy as np
from typing import Optional, Dict, Any, List, Tuple
import hashlib
import json

from .cache import cache_manager
from .embeddings import get_embeddings
from ..config.settings import settings

logger = logging.getLogger(__name__)


class SemanticCache:
    """
    시맨틱 캐싱 시스템

    임베딩 벡터 간의 코사인 유사도를 사용하여 유사한 쿼리를 찾고
    캐시된 결과를 반환합니다.
    """

    def __init__(
        self,
        similarity_threshold: float = None,
        cache_prefix: str = "semantic_cache"
    ):
        """
        Args:
            similarity_threshold: 유사도 임계값 (기본값: settings.SEMANTIC_CACHE_THRESHOLD)
            cache_prefix: 캐시 키 프리픽스
        """
        self.similarity_threshold = similarity_threshold or settings.SEMANTIC_CACHE_THRESHOLD
        self.cache_prefix = cache_prefix
        self.embeddings_cache_key = f"{cache_prefix}:embeddings"
        self.metadata_cache_key = f"{cache_prefix}:metadata"

    async def get(self, query: str, context: Dict[str, Any] = None) -> Optional[Any]:
        """
        시맨틱 캐시에서 유사한 쿼리의 결과를 가져옵니다.

        Args:
            query: 검색할 쿼리
            context: 추가 컨텍스트 정보

        Returns:
            Optional[Any]: 캐시된 결과 (없으면 None)
        """
        if not settings.SEMANTIC_CACHE_ENABLED:
            return None

        try:
            # 쿼리 임베딩 생성
            query_embedding = await get_embeddings([query])
            if not query_embedding or len(query_embedding) == 0:
                logger.warning("쿼리 임베딩 생성 실패")
                return None

            query_vector = np.array(query_embedding[0])

            # 저장된 임베딩 가져오기
            cached_embeddings = await cache_manager.get(
                self.embeddings_cache_key,
                deserialize="pickle"
            )

            if not cached_embeddings:
                logger.debug("저장된 임베딩 없음")
                return None

            # 가장 유사한 쿼리 찾기
            most_similar = self._find_most_similar(
                query_vector,
                cached_embeddings,
                context
            )

            if not most_similar:
                logger.debug("유사한 캐시 항목 없음")
                return None

            cache_key, similarity = most_similar
            logger.info(
                f"시맨틱 캐시 히트: 유사도={similarity:.3f}, "
                f"임계값={self.similarity_threshold}"
            )

            # 캐시된 결과 가져오기
            cached_result = await cache_manager.get(
                cache_key,
                deserialize="pickle"
            )

            if cached_result:
                # 메타데이터에 유사도 정보 추가
                if isinstance(cached_result, dict):
                    cached_result["_semantic_cache_hit"] = True
                    cached_result["_similarity_score"] = float(similarity)

            return cached_result

        except Exception as e:
            logger.error(f"시맨틱 캐시 조회 에러: {e}")
            return None

    async def set(
        self,
        query: str,
        result: Any,
        context: Dict[str, Any] = None,
        ttl: Optional[int] = None
    ) -> bool:
        """
        시맨틱 캐시에 쿼리와 결과를 저장합니다.

        Args:
            query: 저장할 쿼리
            result: 저장할 결과
            context: 추가 컨텍스트 정보
            ttl: TTL (초)

        Returns:
            bool: 성공 여부
        """
        if not settings.SEMANTIC_CACHE_ENABLED:
            return False

        try:
            # 쿼리 임베딩 생성
            query_embedding = await get_embeddings([query])
            if not query_embedding or len(query_embedding) == 0:
                logger.warning("쿼리 임베딩 생성 실패")
                return False

            # 캐시 키 생성
            cache_key = self._generate_cache_key(query, context)

            # 결과 저장
            ttl = ttl or settings.WORKFLOW_RESPONSE_CACHE_TTL
            success = await cache_manager.set(
                cache_key,
                result,
                ttl=ttl,
                serialize="pickle"
            )

            if not success:
                logger.error("캐시 저장 실패")
                return False

            # 임베딩 메타데이터 저장
            await self._store_embedding_metadata(
                cache_key,
                query,
                query_embedding[0],
                context,
                ttl
            )

            logger.debug(f"시맨틱 캐시 저장 성공: {cache_key}")
            return True

        except Exception as e:
            logger.error(f"시맨틱 캐시 저장 에러: {e}")
            return False

    def _generate_cache_key(self, query: str, context: Dict[str, Any] = None) -> str:
        """
        캐시 키 생성

        Args:
            query: 쿼리
            context: 컨텍스트

        Returns:
            str: 캐시 키
        """
        # 쿼리 + 컨텍스트의 해시값 사용
        content = query
        if context:
            # 중요한 컨텍스트만 포함 (user_id는 제외하여 사용자 간 캐시 공유)
            context_keys = ["intent", "quality_requirement", "language"]
            context_str = json.dumps(
                {k: context.get(k) for k in context_keys if k in context},
                sort_keys=True
            )
            content += context_str

        hash_value = hashlib.sha256(content.encode()).hexdigest()
        return f"{self.cache_prefix}:result:{hash_value}"

    async def _store_embedding_metadata(
        self,
        cache_key: str,
        query: str,
        embedding: List[float],
        context: Dict[str, Any],
        ttl: int
    ):
        """
        임베딩 메타데이터 저장

        Args:
            cache_key: 캐시 키
            query: 쿼리
            embedding: 임베딩 벡터
            context: 컨텍스트
            ttl: TTL
        """
        # 저장된 임베딩 가져오기
        cached_embeddings = await cache_manager.get(
            self.embeddings_cache_key,
            deserialize="pickle"
        ) or {}

        # 새 임베딩 추가
        cached_embeddings[cache_key] = {
            "query": query,
            "embedding": embedding,
            "context": context or {}
        }

        # 임베딩 저장 (오래된 항목 제한)
        max_cached_queries = 1000  # 최대 1000개의 쿼리만 저장
        if len(cached_embeddings) > max_cached_queries:
            # 가장 오래된 항목 제거 (간단한 구현: 첫 번째 항목들 제거)
            keys_to_remove = list(cached_embeddings.keys())[:len(cached_embeddings) - max_cached_queries]
            for key in keys_to_remove:
                del cached_embeddings[key]

        # 저장
        await cache_manager.set(
            self.embeddings_cache_key,
            cached_embeddings,
            ttl=ttl,
            serialize="pickle"
        )

    def _find_most_similar(
        self,
        query_vector: np.ndarray,
        cached_embeddings: Dict[str, Dict],
        context: Dict[str, Any] = None
    ) -> Optional[Tuple[str, float]]:
        """
        가장 유사한 임베딩 찾기

        Args:
            query_vector: 쿼리 벡터
            cached_embeddings: 캐시된 임베딩들
            context: 컨텍스트

        Returns:
            Optional[Tuple[str, float]]: (cache_key, similarity) 또는 None
        """
        max_similarity = -1.0
        best_cache_key = None

        for cache_key, metadata in cached_embeddings.items():
            cached_vector = np.array(metadata["embedding"])

            # 코사인 유사도 계산
            similarity = self._cosine_similarity(query_vector, cached_vector)

            # 컨텍스트 일치 여부 확인 (선택적)
            if context and not self._context_matches(context, metadata.get("context", {})):
                continue

            if similarity > max_similarity and similarity >= self.similarity_threshold:
                max_similarity = similarity
                best_cache_key = cache_key

        if best_cache_key:
            return (best_cache_key, max_similarity)

        return None

    @staticmethod
    def _cosine_similarity(vec1: np.ndarray, vec2: np.ndarray) -> float:
        """
        코사인 유사도 계산

        Args:
            vec1: 벡터 1
            vec2: 벡터 2

        Returns:
            float: 코사인 유사도 (0~1)
        """
        dot_product = np.dot(vec1, vec2)
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return dot_product / (norm1 * norm2)

    @staticmethod
    def _context_matches(context1: Dict[str, Any], context2: Dict[str, Any]) -> bool:
        """
        컨텍스트 일치 여부 확인

        Args:
            context1: 컨텍스트 1
            context2: 컨텍스트 2

        Returns:
            bool: 일치 여부
        """
        # 중요한 컨텍스트 필드만 비교
        important_fields = ["intent", "language"]

        for field in important_fields:
            if context1.get(field) != context2.get(field):
                return False

        return True

    async def clear(self):
        """시맨틱 캐시 모두 삭제"""
        try:
            # 임베딩 메타데이터 삭제
            await cache_manager.delete(self.embeddings_cache_key)

            # 결과 캐시 삭제
            deleted_count = await cache_manager.delete_pattern(f"{self.cache_prefix}:result:*")
            logger.info(f"시맨틱 캐시 삭제: {deleted_count}개")

            return True
        except Exception as e:
            logger.error(f"시맨틱 캐시 삭제 에러: {e}")
            return False


# 전역 시맨틱 캐시 인스턴스
semantic_cache = SemanticCache()
