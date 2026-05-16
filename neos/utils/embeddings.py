import logging
from typing import List, Optional
import numpy as np
import hashlib
import random

logger = logging.getLogger(__name__)

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

            if settings.EMBEDDING_DATASET_ENABLED and embedding:
                if random.random() < settings.EMBEDDING_DATASET_SAMPLE_RATE:
                    try:
                        from neos.dataset.embedding_collector import embedding_collector
                        await embedding_collector.record(
                            input_text=text,
                            embedding=embedding,
                            provider=self.provider_name,
                            model=self.model,
                            dimension=self.dimension,
                            modality="text",
                        )
                    except Exception:
                        pass

            return embedding
        except Exception as e:
            logger.error("Embedding generation error: %s", e)
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
                logger.error("Batch embedding generation error: %s", e)

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

    async def get_image_embedding(self, image_bytes: bytes, mime_type: str = "image/jpeg") -> Optional[List[float]]:
        """이미지 임베딩 생성 (멀티모달 지원 provider 전용)"""
        if not self.provider.supports_multimodal():
            logger.warning("Provider %s does not support image embedding", self.provider_name)
            return None
        embedding = await self.provider.get_image_embedding(image_bytes, mime_type)

        if settings.EMBEDDING_DATASET_ENABLED and embedding:
            if random.random() < settings.EMBEDDING_DATASET_SAMPLE_RATE:
                try:
                    from neos.dataset.embedding_collector import embedding_collector
                    await embedding_collector.record(
                        input_text=None,
                        embedding=embedding,
                        provider=self.provider_name,
                        model=self.model,
                        dimension=self.dimension,
                        modality="image",
                        mime_type=mime_type,
                        input_size_bytes=len(image_bytes),
                    )
                except Exception:
                    pass

        return embedding

    async def get_video_embedding(self, video_bytes: bytes, mime_type: str = "video/mp4") -> Optional[List[float]]:
        """영상 임베딩 생성 (멀티모달 지원 provider 전용)"""
        if not self.provider.supports_multimodal():
            logger.warning("Provider %s does not support video embedding", self.provider_name)
            return None
        embedding = await self.provider.get_video_embedding(video_bytes, mime_type)

        if settings.EMBEDDING_DATASET_ENABLED and embedding:
            if random.random() < settings.EMBEDDING_DATASET_SAMPLE_RATE:
                try:
                    from neos.dataset.embedding_collector import embedding_collector
                    await embedding_collector.record(
                        input_text=None,
                        embedding=embedding,
                        provider=self.provider_name,
                        model=self.model,
                        dimension=self.dimension,
                        modality="video",
                        mime_type=mime_type,
                        input_size_bytes=len(video_bytes),
                    )
                except Exception:
                    pass

        return embedding

    def supports_multimodal(self) -> bool:
        """멀티모달 임베딩 지원 여부"""
        return self.provider.supports_multimodal()

    # Alias for compatibility
    async def embed_batch(self, texts: List[str], use_cache: bool = True) -> List[Optional[List[float]]]:
        """Alias for get_embeddings_batch"""
        return await self.get_embeddings_batch(texts, use_cache)


# 전역 임베딩 매니저
embedding_manager = EmbeddingManager()
