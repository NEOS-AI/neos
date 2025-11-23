import re
import logging
from sqlalchemy import text, event
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import Pool

from neos.config.settings import settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


class DatabaseManager:
    def __init__(self):
        self.engine = None
        self.session_factory = None
        
    async def initialize(self):
        """데이터베이스 연결 초기화"""
        logger.info(
            f"데이터베이스 연결 풀 초기화: "
            f"pool_size={settings.DATABASE_POOL_SIZE}, "
            f"max_overflow={settings.DATABASE_MAX_OVERFLOW}, "
            f"pool_timeout={settings.DATABASE_POOL_TIMEOUT}s, "
            f"pool_recycle={settings.DATABASE_POOL_RECYCLE}s"
        )

        self.engine = create_async_engine(
            settings.DATABASE_URL,
            pool_size=settings.DATABASE_POOL_SIZE,
            max_overflow=settings.DATABASE_MAX_OVERFLOW,
            pool_timeout=settings.DATABASE_POOL_TIMEOUT,
            pool_recycle=settings.DATABASE_POOL_RECYCLE,
            echo=settings.DEBUG,
            pool_pre_ping=True,  # 연결 재사용 전 상태 확인
            # 준비된 구문 캐싱 활성화 (PostgreSQL)
            connect_args={
                "server_settings": {
                    "application_name": "neos_multi_agent",
                    "jit": "off"  # JIT 컴파일 비활성화로 짧은 쿼리 성능 향상
                }
            }
        )

        # 연결 풀 이벤트 리스너 추가
        self._setup_pool_listeners()

        self.session_factory = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False
        )

        # 테이블 생성
        try:
            async with self.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            logger.info("데이터베이스 테이블 초기화 완료")
        except Exception as e:
            logger.error(f"데이터베이스 초기화 실패: {e}")
            raise

    def _setup_pool_listeners(self):
        """연결 풀 이벤트 리스너 설정"""
        @event.listens_for(Pool, "connect")
        def receive_connect(dbapi_conn, connection_record):
            logger.debug("새 데이터베이스 연결 생성")

        @event.listens_for(Pool, "checkout")
        def receive_checkout(dbapi_conn, connection_record, connection_proxy):
            logger.debug("연결 풀에서 연결 체크아웃")

        @event.listens_for(Pool, "checkin")
        def receive_checkin(dbapi_conn, connection_record):
            logger.debug("연결 풀로 연결 반환")

    def get_pool_status(self) -> dict:
        """
        연결 풀 상태 조회

        Returns:
            dict: 풀 상태 정보
        """
        if not self.engine:
            return {"status": "not_initialized"}

        pool = self.engine.pool
        return {
            "size": pool.size(),
            "checked_in": pool.checkedin(),
            "checked_out": pool.checkedout(),
            "overflow": pool.overflow(),
            "max_overflow": settings.DATABASE_MAX_OVERFLOW,
            "pool_size": settings.DATABASE_POOL_SIZE,
            "total_connections": pool.size() + pool.overflow(),
            "available_connections": pool.checkedin(),
        }

    async def close(self):
        """데이터베이스 연결 종료"""
        if self.engine:
            logger.info("데이터베이스 연결 종료 중...")
            await self.engine.dispose()
            logger.info("데이터베이스 연결 종료 완료")

    async def get_session(self) -> AsyncSession:
        """세션 생성"""
        if not self.session_factory:
            await self.initialize()
        return self.session_factory()


    async def health_check(self) -> bool:
        """DB 연결 상태 확인"""
        try:
            async with await self.get_session() as session:
                await session.execute(text("SELECT 1"))
                logger.debug("데이터베이스 헬스 체크 성공")
                return True
        except Exception as e:
            logger.error(f"데이터베이스 헬스 체크 실패: {e}")
            return False

    async def execute_in_transaction(self, query: str, *params):
        """트랜잭션 내에서 쿼리 실행

        Args:
            query: SQL 쿼리 문자열 ($1, $2 형식의 플레이스홀더 사용)
            *params: 순서대로 바인딩될 파라미터들

        Returns:
            실행 결과
        """
        session = await self.get_session()
        try:
            # PostgreSQL의 $1, $2 형식을 :param1, :param2 형식으로 변환
            param_dict = {}
            converted_query = query
            for i, param in enumerate(params, 1):
                param_name = f"param{i}"
                converted_query = re.sub(rf'\${i}\b', f":{param_name}", converted_query)
                param_dict[param_name] = param

            result = await session.execute(text(converted_query), param_dict)
            # Note: commit은 호출자가 session.commit()으로 직접 관리
            return result
        except Exception:
            await session.rollback()
            raise
        finally:
            # 세션은 컨텍스트 매니저에서 관리되므로 여기서 닫지 않음
            pass

    async def execute(self, query: str, *params):
        """쿼리 실행 (INSERT, UPDATE, DELETE)

        Args:
            query: SQL 쿼리 문자열 ($1, $2 형식의 플레이스홀더 사용)
            *params: 순서대로 바인딩될 파라미터들
        """
        try:
            # PostgreSQL의 $1, $2 형식을 :param1, :param2 형식으로 변환
            # ::cast 구문을 보존하기 위해 regex 사용
            param_dict = {}
            converted_query = query
            for i, param in enumerate(params, 1):
                placeholder = f"${i}"
                param_name = f"param{i}"
                # $N을 :paramN으로 변경하되, $N:: 패턴은 :paramN::으로 변경
                converted_query = re.sub(rf'\${i}\b', f":{param_name}", converted_query)
                param_dict[param_name] = param

            async with await self.get_session() as session:
                result = await session.execute(text(converted_query), param_dict)
                await session.commit()
                return result
        except Exception as e:
            logger.error(f"데이터베이스 실행 에러: {e}")
            logger.error(f"쿼리: {query}")
            logger.error(f"파라미터: {params}")
            raise

    async def fetch_one(self, query: str, *params):
        """단일 row 조회"""
        try:
            # PostgreSQL의 $1, $2 형식을 :param1, :param2 형식으로 변환
            # ::cast 구문을 보존하기 위해 regex 사용
            param_dict = {}
            converted_query = query
            for i, param in enumerate(params, 1):
                placeholder = f"${i}"
                param_name = f"param{i}"
                # $N을 :paramN으로 변경하되, $N:: 패턴은 :paramN::으로 변경
                converted_query = re.sub(rf'\${i}\b', f":{param_name}", converted_query)
                param_dict[param_name] = param

            async with await self.get_session() as session:
                result = await session.execute(text(converted_query), param_dict)
                # Commit the transaction if the query modifies data (e.g., calling stored procedures)
                if query.strip().upper().startswith('SELECT') and 'create_' in query.lower():
                    await session.commit()
                row = result.fetchone()
                return row
        except Exception as e:
            logger.error(f"데이터베이스 fetch_one 에러: {e}")
            logger.error(f"쿼리: {query}")
            raise

    async def fetch_all(self, query: str, *params):
        """모든 row 조회"""
        try:
            # PostgreSQL의 $1, $2 형식을 :param1, :param2 형식으로 변환
            # ::cast 구문을 보존하기 위해 regex 사용
            param_dict = {}
            converted_query = query
            for i, param in enumerate(params, 1):
                placeholder = f"${i}"
                param_name = f"param{i}"
                # $N을 :paramN으로 변경하되, $N:: 패턴은 :paramN::으로 변경
                converted_query = re.sub(rf'\${i}\b', f":{param_name}", converted_query)
                param_dict[param_name] = param

            async with await self.get_session() as session:
                result = await session.execute(text(converted_query), param_dict)
                return result.fetchall()
        except Exception as e:
            logger.error(f"데이터베이스 fetch_all 에러: {e}")
            logger.error(f"쿼리: {query}")
            raise


# 전역 데이터베이스 매니저
db_manager = DatabaseManager()


async def get_session():
    """세션 생성 헬퍼 함수 (async generator)"""
    session = await db_manager.get_session()
    try:
        yield session
    finally:
        await session.close()


# Alias for compatibility with FastAPI dependency injection
get_db = get_session
