"""
Redis 기반 Rate Limiter
- Sliding Window 알고리즘 사용
- API 키별, IP별 요청 제한
- 초당/분당/시간당/일일 제한 지원
"""
import time
import logging
from typing import Optional, Tuple
from datetime import datetime, timedelta
import redis.asyncio as redis

from neos.config.settings import settings


logger = logging.getLogger(__name__)


class RedisRateLimiter:
    """
    Redis 기반 Rate Limiter (Sliding Window 알고리즘)

    특징:
    - 정확한 요청 수 계산 (Fixed Window보다 정확)
    - 메모리 효율적 (sorted set 사용)
    - 분산 환경 지원
    """

    def __init__(self):
        """Redis 연결 초기화"""
        self.redis_client: Optional[redis.Redis] = None
        self._initialized = False

    async def initialize(self):
        """Redis 연결 설정"""
        if self._initialized:
            return

        try:
            self.redis_client = redis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
                max_connections=settings.REDIS_POOL_SIZE
            )
            # 연결 테스트
            await self.redis_client.ping()
            self._initialized = True
            logger.info("Redis rate limiter initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Redis rate limiter: {e}")
            self.redis_client = None
            self._initialized = False

    async def close(self):
        """Redis 연결 종료"""
        if self.redis_client:
            await self.redis_client.close()
            self._initialized = False
            logger.info("Redis rate limiter connection closed")

    async def check_rate_limit(
        self,
        key: str,
        max_requests: int,
        window_seconds: int
    ) -> Tuple[bool, dict]:
        """
        Rate limit 확인 (Sliding Window 알고리즘)

        Args:
            key: Rate limit 키 (예: "api_key:abc123", "ip:192.168.1.1")
            max_requests: 최대 요청 수
            window_seconds: 시간 윈도우 (초 단위)

        Returns:
            (허용 여부, 메타데이터)
            메타데이터: {
                "allowed": bool,
                "current_requests": int,
                "limit": int,
                "remaining": int,
                "reset_at": int (UNIX timestamp),
                "retry_after": int (seconds)
            }

        Algorithm:
            1. 현재 시간 기준으로 window_seconds 이전 요청들을 카운트
            2. 오래된 요청들은 자동으로 제거 (메모리 절약)
            3. 요청 수가 max_requests 이하면 허용
        """
        if not self._initialized or not self.redis_client:
            # Redis 연결 실패 시 허용 (Fail-open)
            logger.warning("Redis not available, allowing request (fail-open)")
            return True, {
                "allowed": True,
                "current_requests": 0,
                "limit": max_requests,
                "remaining": max_requests,
                "reset_at": int(time.time()) + window_seconds,
                "retry_after": 0
            }

        try:
            current_time = time.time()
            window_start = current_time - window_seconds

            # Redis Sorted Set 키 (score = timestamp)
            redis_key = f"rate_limit:{key}"

            # 파이프라인 사용 (원자적 연산)
            pipe = self.redis_client.pipeline()

            # 1. 오래된 요청 제거 (window 밖의 요청)
            pipe.zremrangebyscore(redis_key, 0, window_start)

            # 2. 현재 window 내의 요청 수 카운트
            pipe.zcard(redis_key)

            # 3. 새 요청 추가
            pipe.zadd(redis_key, {str(current_time): current_time})

            # 4. 키 만료 시간 설정 (메모리 절약)
            pipe.expire(redis_key, window_seconds + 60)

            # 실행
            results = await pipe.execute()
            current_requests = results[1]  # zcard 결과

            # Rate limit 체크
            allowed = current_requests < max_requests
            remaining = max(0, max_requests - current_requests - 1)
            reset_at = int(current_time + window_seconds)

            # 제한 초과 시 retry_after 계산
            if not allowed:
                # 가장 오래된 요청의 시간 가져오기
                oldest = await self.redis_client.zrange(redis_key, 0, 0, withscores=True)
                if oldest:
                    oldest_timestamp = oldest[0][1]
                    retry_after = int(oldest_timestamp + window_seconds - current_time)
                else:
                    retry_after = window_seconds
            else:
                retry_after = 0

            metadata = {
                "allowed": allowed,
                "current_requests": current_requests + 1,  # 방금 추가한 요청 포함
                "limit": max_requests,
                "remaining": remaining,
                "reset_at": reset_at,
                "retry_after": max(0, retry_after)
            }

            # 제한 초과 로깅
            if not allowed:
                logger.warning(
                    f"Rate limit exceeded - "
                    f"key: {key}, "
                    f"requests: {current_requests + 1}/{max_requests}, "
                    f"window: {window_seconds}s, "
                    f"retry_after: {retry_after}s"
                )

            return allowed, metadata

        except Exception as e:
            # Redis 오류 시 허용 (Fail-open)
            logger.error(f"Redis error in rate limiter: {e}, allowing request")
            return True, {
                "allowed": True,
                "current_requests": 0,
                "limit": max_requests,
                "remaining": max_requests,
                "reset_at": int(time.time()) + window_seconds,
                "retry_after": 0
            }

    async def check_api_key_rate_limit(
        self,
        api_key_id: str,
        rate_limit_per_minute: int,
        max_requests_per_day: Optional[int] = None
    ) -> Tuple[bool, dict]:
        """
        API 키별 Rate Limit 확인 (분당 + 일일)

        Args:
            api_key_id: API 키 ID
            rate_limit_per_minute: 분당 요청 제한
            max_requests_per_day: 일일 최대 요청 수 (None = 무제한)

        Returns:
            (허용 여부, 메타데이터)
        """
        # 1. 분당 제한 체크
        minute_allowed, minute_metadata = await self.check_rate_limit(
            key=f"api_key:{api_key_id}:minute",
            max_requests=rate_limit_per_minute,
            window_seconds=60
        )

        if not minute_allowed:
            return False, minute_metadata

        # 2. 일일 제한 체크 (설정된 경우)
        if max_requests_per_day:
            day_allowed, day_metadata = await self.check_rate_limit(
                key=f"api_key:{api_key_id}:day",
                max_requests=max_requests_per_day,
                window_seconds=86400  # 24 hours
            )

            if not day_allowed:
                return False, day_metadata

        return True, minute_metadata

    async def check_ip_rate_limit(
        self,
        ip_address: str,
        max_requests_per_minute: int = 60
    ) -> Tuple[bool, dict]:
        """
        IP별 Rate Limit 확인

        Args:
            ip_address: 클라이언트 IP 주소
            max_requests_per_minute: 분당 최대 요청 수

        Returns:
            (허용 여부, 메타데이터)
        """
        return await self.check_rate_limit(
            key=f"ip:{ip_address}",
            max_requests=max_requests_per_minute,
            window_seconds=60
        )

    async def reset_rate_limit(self, key: str):
        """
        특정 키의 Rate Limit 리셋 (테스트/관리자 기능)

        Args:
            key: Rate limit 키
        """
        if self.redis_client:
            try:
                redis_key = f"rate_limit:{key}"
                await self.redis_client.delete(redis_key)
                logger.info(f"Rate limit reset for key: {key}")
            except Exception as e:
                logger.error(f"Failed to reset rate limit for {key}: {e}")


# 전역 Rate Limiter 인스턴스
rate_limiter = RedisRateLimiter()
