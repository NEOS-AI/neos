"""메시지 큐 인터페이스 및 구현체"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Callable, Awaitable
import asyncio
import json
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class MessageQueueInterface(ABC):
    """메시지 큐 추상 인터페이스

    추후 Redis Pub/Sub, Kafka 등으로 마이그레이션 가능하도록 설계
    """

    @abstractmethod
    async def initialize(self) -> None:
        """큐 초기화"""
        pass

    @abstractmethod
    async def publish(self, channel: str, message: Dict[str, Any]) -> bool:
        """메시지 발행"""
        pass

    @abstractmethod
    async def subscribe(
        self,
        channel: str,
        handler: Callable[[Dict[str, Any]], Awaitable[None]]
    ) -> None:
        """채널 구독"""
        pass

    @abstractmethod
    async def unsubscribe(self, channel: str) -> None:
        """채널 구독 해제"""
        pass

    @abstractmethod
    async def close(self) -> None:
        """큐 연결 종료"""
        pass


class InMemoryMessageQueue(MessageQueueInterface):
    """인메모리 메시지 큐 구현체 (기본 구현)

    개발 및 테스트용. 프로덕션에서는 Redis나 Kafka 사용 권장.
    """

    def __init__(self, max_queue_size: int = 10000):
        self.max_queue_size = max_queue_size
        self.queues: Dict[str, asyncio.Queue] = {}
        self.subscribers: Dict[str, asyncio.Task] = {}
        self.running = False

    async def initialize(self) -> None:
        """큐 초기화"""
        self.running = True
        logger.info("[InMemoryMessageQueue] Initialized")

    async def publish(self, channel: str, message: Dict[str, Any]) -> bool:
        """메시지 발행"""
        try:
            if not self.running:
                logger.warning(f"[InMemoryMessageQueue] Cannot publish to {channel}: queue not running")
                return False

            # 채널 큐가 없으면 생성
            if channel not in self.queues:
                self.queues[channel] = asyncio.Queue(maxsize=self.max_queue_size)

            # 메시지에 타임스탬프 추가
            message_with_meta = {
                "data": message,
                "timestamp": datetime.utcnow().isoformat(),
                "channel": channel
            }

            # 큐가 가득 찼을 경우 가장 오래된 메시지 제거
            if self.queues[channel].full():
                try:
                    self.queues[channel].get_nowait()
                    logger.warning(f"[InMemoryMessageQueue] Queue {channel} full, dropped oldest message")
                except asyncio.QueueEmpty:
                    pass

            await self.queues[channel].put(message_with_meta)
            logger.debug(f"[InMemoryMessageQueue] Published message to {channel}")
            return True

        except Exception as e:
            logger.error(f"[InMemoryMessageQueue] Error publishing to {channel}: {e}")
            return False

    async def subscribe(
        self,
        channel: str,
        handler: Callable[[Dict[str, Any]], Awaitable[None]]
    ) -> None:
        """채널 구독"""
        if channel in self.subscribers:
            logger.warning(f"[InMemoryMessageQueue] Already subscribed to {channel}")
            return

        # 채널 큐가 없으면 생성
        if channel not in self.queues:
            self.queues[channel] = asyncio.Queue(maxsize=self.max_queue_size)

        # create asyncio task for subscriber loop
        task = asyncio.create_task(self._subscriber_loop(channel, handler))
        self.subscribers[channel] = task
        logger.info(f"[InMemoryMessageQueue] Subscribed to {channel}")


    async def _subscriber_loop(
        self,
        channel: str,
        handler: Callable[[Dict[str, Any]], Awaitable[None]]
    ) -> None:
        """구독자 루프"""
        logger.info(f"[InMemoryMessageQueue] Subscriber loop started for {channel}")

        while self.running:
            try:
                # 메시지 대기 (타임아웃 포함)
                message = await asyncio.wait_for(
                    self.queues[channel].get(),
                    timeout=1.0
                )

                # 핸들러 실행
                try:
                    await handler(message["data"])
                except Exception as e:
                    logger.error(f"[InMemoryMessageQueue] Handler error for {channel}: {e}")

            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                logger.info(f"[InMemoryMessageQueue] Subscriber loop cancelled for {channel}")
                break
            except Exception as e:
                logger.error(f"[InMemoryMessageQueue] Subscriber loop error for {channel}: {e}")
                await asyncio.sleep(1)

        logger.info(f"[InMemoryMessageQueue] Subscriber loop ended for {channel}")

    async def unsubscribe(self, channel: str) -> None:
        """채널 구독 해제"""
        if channel in self.subscribers:
            self.subscribers[channel].cancel()
            try:
                await self.subscribers[channel]
            except asyncio.CancelledError:
                pass
            del self.subscribers[channel]
            logger.info(f"[InMemoryMessageQueue] Unsubscribed from {channel}")

    async def close(self) -> None:
        """큐 연결 종료"""
        logger.info("[InMemoryMessageQueue] Closing...")
        self.running = False

        # 모든 구독자 취소
        for channel in list(self.subscribers.keys()):
            await self.unsubscribe(channel)

        # 큐 비우기
        for queue in self.queues.values():
            while not queue.empty():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    break

        logger.info("[InMemoryMessageQueue] Closed")


class RedisPubSubMessageQueue(MessageQueueInterface):
    """Redis Pub/Sub 기반 메시지 큐 (추후 구현)

    Redis를 사용한 메시지 큐 구현체.
    redis.asyncio 라이브러리 필요.
    """

    def __init__(self, redis_url: str):
        self.redis_url = redis_url
        self.redis_client = None
        self.pubsub = None
        self.subscribers: Dict[str, asyncio.Task] = {}
        logger.info(f"[RedisPubSubMessageQueue] Initialized with URL: {redis_url}")

    async def initialize(self) -> None:
        """Redis 연결 초기화"""
        try:
            import redis.asyncio as redis
            self.redis_client = redis.from_url(self.redis_url, decode_responses=True)
            await self.redis_client.ping()
            logger.info("[RedisPubSubMessageQueue] Connected to Redis")
        except ImportError:
            raise ImportError("redis package is required for RedisPubSubMessageQueue. Install with: pip install redis")
        except Exception as e:
            logger.error(f"[RedisPubSubMessageQueue] Failed to connect to Redis: {e}")
            raise

    async def publish(self, channel: str, message: Dict[str, Any]) -> bool:
        """메시지 발행"""
        try:
            if not self.redis_client:
                logger.error("[RedisPubSubMessageQueue] Redis client not initialized")
                return False

            message_json = json.dumps({
                "data": message,
                "timestamp": datetime.utcnow().isoformat()
            })

            await self.redis_client.publish(channel, message_json)
            logger.debug(f"[RedisPubSubMessageQueue] Published message to {channel}")
            return True

        except Exception as e:
            logger.error(f"[RedisPubSubMessageQueue] Error publishing to {channel}: {e}")
            return False

    async def subscribe(
        self,
        channel: str,
        handler: Callable[[Dict[str, Any]], Awaitable[None]]
    ) -> None:
        """채널 구독"""
        if channel in self.subscribers:
            logger.warning(f"[RedisPubSubMessageQueue] Already subscribed to {channel}")
            return

        task = asyncio.create_task(self._subscriber_loop(channel, handler))
        self.subscribers[channel] = task
        logger.info(f"[RedisPubSubMessageQueue] Subscribed to {channel}")

    async def _subscriber_loop(
        self,
        channel: str,
        handler: Callable[[Dict[str, Any]], Awaitable[None]]
    ) -> None:
        """구독자 루프"""
        pubsub = self.redis_client.pubsub()
        await pubsub.subscribe(channel)
        logger.info(f"[RedisPubSubMessageQueue] Subscriber loop started for {channel}")

        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    try:
                        data = json.loads(message["data"])
                        await handler(data["data"])
                    except Exception as e:
                        logger.error(f"[RedisPubSubMessageQueue] Handler error for {channel}: {e}")
        except asyncio.CancelledError:
            logger.info(f"[RedisPubSubMessageQueue] Subscriber loop cancelled for {channel}")
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.close()
            logger.info(f"[RedisPubSubMessageQueue] Subscriber loop ended for {channel}")

    async def unsubscribe(self, channel: str) -> None:
        """채널 구독 해제"""
        if channel in self.subscribers:
            self.subscribers[channel].cancel()
            try:
                await self.subscribers[channel]
            except asyncio.CancelledError:
                pass
            del self.subscribers[channel]
            logger.info(f"[RedisPubSubMessageQueue] Unsubscribed from {channel}")

    async def close(self) -> None:
        """Redis 연결 종료"""
        logger.info("[RedisPubSubMessageQueue] Closing...")

        for channel in list(self.subscribers.keys()):
            await self.unsubscribe(channel)

        if self.redis_client:
            await self.redis_client.close()

        logger.info("[RedisPubSubMessageQueue] Closed")


# ============================================================================
# 메시지 큐 팩토리
# ============================================================================

class MessageQueueFactory:
    """메시지 큐 팩토리

    환경 설정에 따라 적절한 메시지 큐 구현체를 생성
    """

    @staticmethod
    def create(queue_type: str = "memory", **kwargs) -> MessageQueueInterface:
        """메시지 큐 생성

        Args:
            queue_type: 큐 타입 ('memory', 'redis', 'kafka')
            **kwargs: 큐별 설정 파라미터

        Returns:
            MessageQueueInterface 구현체
        """
        if queue_type == "memory":
            max_size = kwargs.get("max_queue_size", 10000)
            return InMemoryMessageQueue(max_queue_size=max_size)

        elif queue_type == "redis":
            redis_url = kwargs.get("redis_url")
            if not redis_url:
                raise ValueError("redis_url is required for redis queue type")
            return RedisPubSubMessageQueue(redis_url=redis_url)

        elif queue_type == "kafka":
            # TODO: Kafka 구현 추가
            raise NotImplementedError("Kafka message queue not yet implemented")

        else:
            raise ValueError(f"Unknown queue type: {queue_type}")
