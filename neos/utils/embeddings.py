from typing import List, Optional
import numpy as np
import hashlib

from neos.config.settings import settings

from .cache import cache_manager
from .embedding_providers import EmbeddingProviderFactory


class EmbeddingManager:
    """
    통합 임베딩 관리자

    여러 embedding provider를 지원하며 캐싱 기능을 제공합니다.
    """

    def __init__(self):
        # Provider factory를 통해 임베딩 provider 생성
        self.provider = EmbeddingProviderFactory.create()
        self.model = self.provider.get_model_name()
        self.dimension = self.provider.get_dimension()
        self.provider_name = self.provider.get_provider_name()

    async def get_embedding(self, text: str, use_cache: bool = True) -> Optional[List[float]]:
        """텍스트 임베딩 생성 (캐싱 지원)"""
        if use_cache:
            # 캐시 키 생성
            cache_key = self._make_cache_key(text)
            cached_embedding = await cache_manager.get(cache_key, deserialize="pickle")
            if cached_embedding:
                return cached_embedding

        try:
            # Provider를 통해 임베딩 생성
            embedding = await self.provider.get_embedding(text)

            if use_cache and embedding:
                # 캐시에 저장 (24시간)
                await cache_manager.set(cache_key, embedding, ttl=86400, serialize="pickle")

            return embedding
        except Exception as e:
            print(f"Embedding generation error: {e}")
            return None
    
    async def get_embeddings_batch(
        self,
        texts: List[str],
        use_cache: bool = True
    ) -> List[Optional[List[float]]]:
        """배치 임베딩 생성 (캐싱 지원)"""
        results = []
        uncached_texts = []
        uncached_indices = []

        if use_cache:
            # 캐시된 임베딩 확인
            for i, text in enumerate(texts):
                cache_key = self._make_cache_key(text)
                cached_embedding = await cache_manager.get(cache_key, deserialize="pickle")
                if cached_embedding:
                    results.append(cached_embedding)
                else:
                    results.append(None)
                    uncached_texts.append(text)
                    uncached_indices.append(i)
        else:
            uncached_texts = texts
            uncached_indices = list(range(len(texts)))
            results = [None] * len(texts)

        # 캐시되지 않은 텍스트들 처리
        if uncached_texts:
            try:
                # Provider를 통해 배치 임베딩 생성
                embeddings = await self.provider.get_embeddings_batch(uncached_texts)

                for i, (idx, text) in enumerate(zip(uncached_indices, uncached_texts)):
                    embedding = embeddings[i]
                    results[idx] = embedding

                    if use_cache and embedding:
                        cache_key = self._make_cache_key(text)
                        await cache_manager.set(cache_key, embedding, ttl=86400, serialize="pickle")

            except Exception as e:
                print(f"Batch embedding generation error: {e}")

        return results
    
    def cosine_similarity(self, a: List[float], b: List[float]) -> float:
        """코사인 유사도 계산"""
        a_np = np.array(a)
        b_np = np.array(b)
        return np.dot(a_np, b_np) / (np.linalg.norm(a_np) * np.linalg.norm(b_np))
    
    def _make_cache_key(self, text: str) -> str:
        """캐시 키 생성 (provider 및 model 포함)"""
        text_hash = hashlib.md5(text.encode('utf-8')).hexdigest()
        return f"embedding:{self.provider_name}:{self.model}:{text_hash}"

    # Alias for compatibility
    async def embed_batch(self, texts: List[str], use_cache: bool = True) -> List[Optional[List[float]]]:
        """Alias for get_embeddings_batch"""
        return await self.get_embeddings_batch(texts, use_cache)


# 전역 임베딩 매니저
embedding_manager = EmbeddingManager()
