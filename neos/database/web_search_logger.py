"""웹 검색 로그 저장 서비스

비동기 검색 로그 저장 및 메시지 큐 통합
"""

import hashlib
import uuid
from typing import Dict, Any, Optional
from datetime import datetime
from urllib.parse import urlparse
import logging

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from neos.database.connection import db_manager
from neos.database.web_search_models import (
    SearchEngine,
    WebSearchQuery,
    WebSearchResult,
    WebSearchMetric
)
from neos.database.web_search_types import (
    SearchLogRequest,
    SearchLogComplete,
    SearchQueryStatus
)
from neos.utils.message_queue import MessageQueueInterface, MessageQueueFactory
from neos.config.settings import settings

logger = logging.getLogger(__name__)


class WebSearchLogger:
    """웹 검색 로거

    검색 쿼리 및 결과를 비동기적으로 DB에 저장
    """

    def __init__(
        self,
        message_queue: Optional[MessageQueueInterface] = None,
        enable_async_logging: bool = True
    ):
        self.message_queue = message_queue
        self.enable_async_logging = enable_async_logging
        self.initialized = False

        # 검색 엔진 캐시 (engine_name -> engine_id)
        self.engine_cache: Dict[str, int] = {}

    async def initialize(self) -> None:
        """로거 초기화"""
        if self.initialized:
            return

        # 메시지 큐 초기화
        if self.enable_async_logging and self.message_queue:
            await self.message_queue.initialize()

            # 구독자 등록
            await self.message_queue.subscribe(
                "web_search_log",
                self._handle_search_log_message
            )
            logger.info("[WebSearchLogger] Message queue subscriber registered")

        # 검색 엔진 캐시 로드
        await self._load_engine_cache()

        self.initialized = True
        logger.info("[WebSearchLogger] Initialized")

    async def _load_engine_cache(self) -> None:
        """검색 엔진 캐시 로드"""
        try:
            async with await db_manager.get_session() as session:
                # get all active search engines
                result = await session.execute(
                    select(SearchEngine.id, SearchEngine.engine_name)
                    .where(SearchEngine.is_active)
                )
                engines = result.all()
                self.engine_cache = {name: id for id, name in engines}
                logger.info(f"[WebSearchLogger] Loaded {len(self.engine_cache)} engines to cache")
        except Exception as e:
            logger.error(f"[WebSearchLogger] Failed to load engine cache: {e}")

    async def _get_or_create_engine(
        self,
        engine_name: str,
        session: AsyncSession
    ) -> int:
        """검색 엔진 ID 조회 또는 생성"""
        # 캐시에서 조회
        if engine_name in self.engine_cache:
            return self.engine_cache[engine_name]

        # DB에서 조회
        result = await session.execute(
            select(SearchEngine.id)
            .where(SearchEngine.engine_name == engine_name)
        )
        engine = result.scalar_one_or_none()

        if engine:
            self.engine_cache[engine_name] = engine
            return engine

        # 새로운 엔진 등록
        new_engine = SearchEngine(
            engine_name=engine_name,
            engine_type="web",  # 기본값
            is_active=True
        )
        session.add(new_engine)
        await session.flush()

        self.engine_cache[engine_name] = new_engine.id
        logger.info(f"[WebSearchLogger] Created new engine: {engine_name} (id={new_engine.id})")

        return new_engine.id

    @staticmethod
    def generate_query_hash(query_text: str) -> str:
        """쿼리 해시 생성"""
        normalized = query_text.lower().strip()
        return hashlib.sha256(normalized.encode('utf-8')).hexdigest()

    @staticmethod
    def generate_url_hash(url: str) -> str:
        """URL 해시 생성"""
        return hashlib.sha256(url.encode('utf-8')).hexdigest()

    @staticmethod
    def generate_content_hash(content: str) -> str:
        """콘텐츠 해시 생성"""
        return hashlib.sha256(content.encode('utf-8')).hexdigest()

    @staticmethod
    def extract_domain(url: str) -> Optional[str]:
        """URL에서 도메인 추출"""
        try:
            parsed = urlparse(url)
            return parsed.netloc
        except Exception:
            return None


    async def log_search_start(
        self,
        request: SearchLogRequest
    ) -> str:
        """검색 시작 로그

        Args:
            request: 검색 로그 요청

        Returns:
            query_id: 생성된 쿼리 ID
        """
        query_id = str(uuid.uuid4())

        if self.enable_async_logging and self.message_queue:
            # 비동기 방식: 메시지 큐에 발행
            await self.message_queue.publish("web_search_log", {
                "type": "search_start",
                "query_id": query_id,
                "request": request.model_dump()
            })
            logger.debug(f"[WebSearchLogger] Published search_start for query_id={query_id}")
        else:
            # 동기 방식: 직접 DB에 저장
            await self._save_search_start(query_id, request)

        return query_id

    async def _save_search_start(
        self,
        query_id: str,
        request: SearchLogRequest
    ) -> None:
        """검색 시작 데이터 저장"""
        try:
            async with await db_manager.get_session() as session:
                engine_id = await self._get_or_create_engine(request.engine_name, session)

                query = WebSearchQuery(
                    query_id=query_id,
                    query_text=request.query_text,
                    query_hash=self.generate_query_hash(request.query_text),
                    query_language=request.query_language,
                    query_intent=request.query_intent,
                    engine_id=engine_id,
                    engine_name=request.engine_name,
                    user_id=request.user_id,
                    session_id=request.session_id,
                    search_params=request.search_params,
                    trace_id=request.trace_id,
                    parent_query_id=request.parent_query_id,
                    status=SearchQueryStatus.PENDING,
                    executed_at=datetime.utcnow()
                )

                session.add(query)
                await session.commit()
                logger.debug(f"[WebSearchLogger] Saved search_start for query_id={query_id}")

        except Exception as e:
            logger.error(f"[WebSearchLogger] Failed to save search_start: {e}")

    async def log_search_complete(
        self,
        complete: SearchLogComplete
    ) -> None:
        """검색 완료 로그

        Args:
            complete: 검색 완료 데이터
        """
        if self.enable_async_logging and self.message_queue:
            # 비동기 방식: 메시지 큐에 발행
            await self.message_queue.publish("web_search_log", {
                "type": "search_complete",
                "complete": complete.model_dump()
            })
            logger.debug(f"[WebSearchLogger] Published search_complete for query_id={complete.query_id}")
        else:
            # 동기 방식: 직접 DB에 저장
            await self._save_search_complete(complete)

    async def _save_search_complete(
        self,
        complete: SearchLogComplete
    ) -> None:
        """검색 완료 데이터 저장"""
        try:
            async with await db_manager.get_session() as session:
                # 쿼리 상태 업데이트
                stmt = (
                    update(WebSearchQuery)
                    .where(WebSearchQuery.query_id == complete.query_id)
                    .values(
                        status=complete.status,
                        execution_time_ms=complete.execution_time_ms,
                        total_results_count=len(complete.results),
                        results_returned_count=len(complete.results),
                        error_message=complete.error_message,
                        quality_score=complete.quality_score
                    )
                )
                await session.execute(stmt)

                # 검색 결과 저장
                for idx, result_item in enumerate(complete.results):
                    result = WebSearchResult(
                        result_id=str(uuid.uuid4()),
                        query_id=complete.query_id,
                        result_url=result_item.url,
                        url_hash=self.generate_url_hash(result_item.url),
                        result_position=result_item.position or idx + 1,
                        result_title=result_item.title,
                        result_content=result_item.content,
                        domain=self.extract_domain(result_item.url),
                        relevance_score=result_item.score,
                        content_hash=self.generate_content_hash(result_item.content or ""),
                        published_date=datetime.fromisoformat(result_item.published_date) if result_item.published_date else None,
                        metadata=result_item.metadata,
                        captured_at=datetime.utcnow(),
                        first_seen_at=datetime.utcnow()
                    )
                    session.add(result)

                # 메트릭 저장
                if complete.metrics:
                    metric = WebSearchMetric(
                        query_id=complete.query_id,
                        total_time_ms=complete.execution_time_ms,
                        **complete.metrics
                    )
                    session.add(metric)

                await session.commit()
                logger.debug(f"[WebSearchLogger] Saved search_complete for query_id={complete.query_id}")

        except Exception as e:
            logger.error(f"[WebSearchLogger] Failed to save search_complete: {e}")


    async def _handle_search_log_message(self, message: Dict[str, Any]) -> None:
        """메시지 큐 핸들러"""
        try:
            msg_type = message.get("type")

            if msg_type == "search_start":
                request = SearchLogRequest(**message["request"])
                await self._save_search_start(message["query_id"], request)

            elif msg_type == "search_complete":
                complete = SearchLogComplete(**message["complete"])
                await self._save_search_complete(complete)

            else:
                logger.warning(f"[WebSearchLogger] Unknown message type: {msg_type}")

        except Exception as e:
            logger.error(f"[WebSearchLogger] Error handling message: {e}")


    async def close(self) -> None:
        """로거 종료"""
        if self.message_queue:
            await self.message_queue.unsubscribe("web_search_log")
            await self.message_queue.close()

        logger.info("[WebSearchLogger] Closed")


# ============================================================================
# 글로벌 로거 인스턴스
# ============================================================================

_global_logger: Optional[WebSearchLogger] = None


async def get_search_logger() -> WebSearchLogger:
    """글로벌 검색 로거 인스턴스 반환"""
    global _global_logger

    if _global_logger is None:
        # 환경 설정에 따라 메시지 큐 생성
        enable_async = getattr(settings, "WEB_SEARCH_LOG_ASYNC", True)
        queue_type = getattr(settings, "WEB_SEARCH_LOG_QUEUE_TYPE", "memory")

        message_queue = None
        if enable_async:
            if queue_type == "redis":
                redis_url = getattr(settings, "REDIS_URL", None)
                if redis_url:
                    message_queue = MessageQueueFactory.create("redis", redis_url=redis_url)
                else:
                    logger.warning("[WebSearchLogger] REDIS_URL not set, falling back to memory queue")
                    message_queue = MessageQueueFactory.create("memory")
            else:
                message_queue = MessageQueueFactory.create("memory")

        _global_logger = WebSearchLogger(
            message_queue=message_queue,
            enable_async_logging=enable_async
        )
        await _global_logger.initialize()

    return _global_logger


async def cleanup_search_logger() -> None:
    """글로벌 로거 정리"""
    global _global_logger
    if _global_logger:
        await _global_logger.close()
        _global_logger = None
