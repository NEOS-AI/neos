import redis.asyncio as redis
import json
import pickle
from typing import Any, Optional

from neos.config.settings import settings


class CacheManager:
    def __init__(self):
        self.redis_client: Optional[redis.Redis] = None
    
    async def initialize(self):
        """Redis 연결 초기화"""
        self.redis_client = redis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=False  # binary 데이터 지원
        )
        
    async def close(self):
        """Redis 연결 종료"""
        if self.redis_client:
            await self.redis_client.close()
    
    async def set(
        self, 
        key: str, 
        value: Any, 
        ttl: Optional[int] = None,
        serialize: str = "json"
    ) -> bool:
        """캐시 저장"""
        if not self.redis_client:
            await self.initialize()
            
        try:
            if serialize == "json":
                serialized_value = json.dumps(value, ensure_ascii=False)
            elif serialize == "pickle":
                serialized_value = pickle.dumps(value)
            else:
                serialized_value = str(value)
            
            ttl = ttl or settings.REDIS_TTL
            await self.redis_client.setex(key, ttl, serialized_value)
            return True
        except Exception as e:
            print(f"Cache set error: {e}")
            return False
    
    async def get(
        self, 
        key: str, 
        deserialize: str = "json"
    ) -> Optional[Any]:
        """캐시 조회"""
        if not self.redis_client:
            await self.initialize()
            
        try:
            value = await self.redis_client.get(key)
            if value is None:
                return None
                
            if deserialize == "json":
                return json.loads(value)
            elif deserialize == "pickle":
                return pickle.loads(value)
            else:
                return value.decode("utf-8") if isinstance(value, bytes) else value
        except Exception as e:
            print(f"Cache get error: {e}")
            return None
    
    async def delete(self, key: str) -> bool:
        """캐시 삭제"""
        if not self.redis_client:
            await self.initialize()
            
        try:
            await self.redis_client.delete(key)
            return True
        except Exception as e:
            print(f"Cache delete error: {e}")
            return False
    
    async def exists(self, key: str) -> bool:
        """캐시 존재 여부 확인"""
        if not self.redis_client:
            await self.initialize()
            
        try:
            return await self.redis_client.exists(key) > 0
        except Exception:
            return False
    
    async def health_check(self) -> bool:
        """Redis 연결 상태 확인"""
        try:
            if not self.redis_client:
                await self.initialize()
            await self.redis_client.ping()
            return True
        except Exception:
            return False
    
    def make_key(self, prefix: str, *args) -> str:
        """캐시 키 생성"""
        return f"{prefix}:" + ":".join(str(arg) for arg in args)


# 전역 캐시 매니저
cache_manager = CacheManager()
