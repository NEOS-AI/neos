import redis.asyncio as redis
import json
import pickle
import logging
from typing import Any, Optional, List

from neos.config.settings import settings

logger = logging.getLogger(__name__)


class CacheManager:
    def __init__(self):
        self.redis_client: Optional[redis.Redis] = None
        self.connection_pool: Optional[redis.ConnectionPool] = None

    async def initialize(self):
        """Redis 연결 풀 초기화"""
        logger.info(
            f"Redis 연결 풀 초기화: "
            f"pool_size={settings.REDIS_POOL_SIZE}, "
            f"min_idle={settings.REDIS_MIN_IDLE_CONNECTIONS}"
        )

        # 연결 풀 생성
        self.connection_pool = redis.ConnectionPool.from_url(
            settings.REDIS_URL,
            max_connections=settings.REDIS_POOL_SIZE,
            decode_responses=False,  # binary 데이터 지원
            encoding="utf-8",
            socket_keepalive=True,
            socket_connect_timeout=5,
            retry_on_timeout=True,
            health_check_interval=30  # 30초마다 연결 상태 확인
        )

        # Redis 클라이언트 생성
        self.redis_client = redis.Redis(
            connection_pool=self.connection_pool,
            decode_responses=False
        )

        # 연결 테스트
        try:
            await self.redis_client.ping()
            logger.info("Redis 연결 성공")
        except Exception as e:
            logger.error(f"Redis 연결 실패: {e}")
            raise

    async def close(self):
        """Redis 연결 풀 종료"""
        if self.redis_client:
            logger.info("Redis 연결 종료 중...")
            await self.redis_client.close()

        if self.connection_pool:
            await self.connection_pool.disconnect()
            logger.info("Redis 연결 풀 종료 완료")


    async def get_pool_status(self) -> dict:
        """
        Redis 연결 풀 상태 조회

        Returns:
            dict: 풀 상태 정보
        """
        if not self.connection_pool:
            return {"status": "not_initialized"}

        try:
            pool = self.connection_pool
            # simple ping with connection pool
            await pool.get_connection("PING")

            # Redis 연결 풀은 직접적인 상태 조회 메소드가 제한적
            return {
                "max_connections": settings.REDIS_POOL_SIZE,
                "min_idle_connections": settings.REDIS_MIN_IDLE_CONNECTIONS,
                "pool_initialized": self.connection_pool is not None,
                "client_initialized": self.redis_client is not None,
            }
        except Exception as e:
            logger.error(f"Redis 풀 상태 조회 실패: {e}")
            return {"status": "error", "error": str(e)}
    
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
            logger.debug(f"캐시 저장 성공: {key} (TTL={ttl}s)")
            return True
        except Exception as e:
            logger.error(f"캐시 저장 에러: {key} - {e}")
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
            logger.error(f"캐시 조회 에러: {key} - {e}")
            return None
    
    async def delete(self, key: str) -> bool:
        """캐시 삭제"""
        if not self.redis_client:
            await self.initialize()
            
        try:
            await self.redis_client.delete(key)
            logger.debug(f"캐시 삭제 성공: {key}")
            return True
        except Exception as e:
            logger.error(f"캐시 삭제 에러: {key} - {e}")
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

    async def mget(self, keys: List[str], deserialize: str = "json") -> List[Optional[Any]]:
        """
        여러 캐시를 한 번에 조회 (파이프라이닝)

        Args:
            keys: 조회할 키 리스트
            deserialize: 역직렬화 방식

        Returns:
            List[Optional[Any]]: 조회 결과 리스트
        """
        if not self.redis_client:
            await self.initialize()

        try:
            values = await self.redis_client.mget(keys)
            results = []
            for value in values:
                if value is None:
                    results.append(None)
                elif deserialize == "json":
                    try:
                        results.append(json.loads(value))
                    except Exception:
                        results.append(None)
                elif deserialize == "pickle":
                    try:
                        results.append(pickle.loads(value))
                    except Exception:
                        results.append(None)
                else:
                    results.append(value.decode("utf-8") if isinstance(value, bytes) else value)
            return results
        except Exception as e:
            logger.error(f"캐시 다중 조회 에러: {e}")
            return [None] * len(keys)

    async def mset(
        self,
        key_value_pairs: dict,
        ttl: Optional[int] = None,
        serialize: str = "json"
    ) -> bool:
        """
        여러 캐시를 한 번에 저장 (파이프라이닝)

        Args:
            key_value_pairs: {key: value} 형태의 딕셔너리
            ttl: TTL (초)
            serialize: 직렬화 방식

        Returns:
            bool: 성공 여부
        """
        if not self.redis_client:
            await self.initialize()

        try:
            pipeline = self.redis_client.pipeline()
            ttl = ttl or settings.REDIS_TTL

            for key, value in key_value_pairs.items():
                if serialize == "json":
                    serialized_value = json.dumps(value, ensure_ascii=False)
                elif serialize == "pickle":
                    serialized_value = pickle.dumps(value)
                else:
                    serialized_value = str(value)

                pipeline.setex(key, ttl, serialized_value)

            await pipeline.execute()
            logger.debug(f"캐시 다중 저장 성공: {len(key_value_pairs)}개")
            return True
        except Exception as e:
            logger.error(f"캐시 다중 저장 에러: {e}")
            return False

    async def delete_pattern(self, pattern: str) -> int:
        """
        패턴과 일치하는 모든 키 삭제

        Args:
            pattern: Redis 패턴 (예: "user:*", "session:123:*")

        Returns:
            int: 삭제된 키 개수
        """
        if not self.redis_client:
            await self.initialize()

        try:
            keys = []
            async for key in self.redis_client.scan_iter(match=pattern):
                keys.append(key)

            if keys:
                deleted = await self.redis_client.delete(*keys)
                logger.info(f"패턴 매칭 캐시 삭제: {pattern} - {deleted}개")
                return deleted
            return 0
        except Exception as e:
            logger.error(f"패턴 매칭 캐시 삭제 에러: {pattern} - {e}")
            return 0


# 전역 캐시 매니저
cache_manager = CacheManager()
