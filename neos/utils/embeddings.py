from typing import List, Optional
import openai
import numpy as np
import hashlib

from config.settings import settings

from .cache import cache_manager


class EmbeddingManager:
    def __init__(self):
        self.client = openai.AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        self.model = settings.EMBEDDING_MODEL
        self.dimension = settings.EMBEDDING_DIMENSION
    
    async def get_embedding(self, text: str, use_cache: bool = True) -> Optional[List[float]]:
        """텍스트 임베딩 생성"""
        if use_cache:
            # 캐시 키 생성
            cache_key = self._make_cache_key(text)
            cached_embedding = await cache_manager.get(cache_key, deserialize="pickle")
            if cached_embedding:
                return cached_embedding
        
        try:
            response = await self.client.embeddings.create(
                input=text,
                model=self.model
            )
            embedding = response.data[0].embedding
            
            if use_cache:
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
        """배치 임베딩 생성"""
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
                response = await self.client.embeddings.create(
                    input=uncached_texts,
                    model=self.model
                )
                
                for i, (idx, text) in enumerate(zip(uncached_indices, uncached_texts)):
                    embedding = response.data[i].embedding
                    results[idx] = embedding
                    
                    if use_cache:
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
        """캐시 키 생성"""
        text_hash = hashlib.md5(text.encode('utf-8')).hexdigest()
        return f"embedding:{self.model}:{text_hash}"


# 전역 임베딩 매니저
embedding_manager = EmbeddingManager()
