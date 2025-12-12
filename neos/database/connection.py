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

        ⚠️  보안 경고: 가능하면 이 메서드 대신 SQLAlchemy ORM을 사용하세요!

        Args:
            query: SQL 쿼리 문자열
            *params: 순서대로 바인딩될 파라미터들

        Returns:
            실행 결과

        Note:
            이 메서드는 자동으로 commit을 수행합니다.
            세션은 자동으로 닫히므로 호출자는 세션을 관리하지 않아도 됩니다.
        """
        async with await self.get_session() as session:
            try:
                # 파라미터 변환
                param_dict = {}
                converted_query = query

                if '$' in query and params:
                    for i, param in enumerate(params, 1):
                        param_name = f"param{i}"
                        converted_query = re.sub(rf'\${i}\b', f":{param_name}", converted_query)
                        param_dict[param_name] = param
                else:
                    for i, param in enumerate(params, 1):
                        param_dict[f"param{i}"] = param

                result = await session.execute(text(converted_query), param_dict)
                await session.commit()
                return result
            except Exception as e:
                await session.rollback()
                logger.error(f"트랜잭션 실행 에러: {e}")
                logger.error(f"쿼리: {query[:200]}...")
                raise
            # 컨텍스트 매니저가 자동으로 세션을 닫음

    async def execute(self, query: str, *params):
        """쿼리 실행 (INSERT, UPDATE, DELETE)

        ⚠️  보안 경고: 가능하면 이 메서드 대신 SQLAlchemy ORM을 사용하세요!
        이 메서드는 레거시 코드 호환성을 위해 유지됩니다.

        Args:
            query: SQL 쿼리 문자열 (:param1, :param2 형식 권장)
            *params: 순서대로 바인딩될 파라미터들

        Security:
            - 절대 사용자 입력을 query 문자열에 직접 포함하지 마세요
            - 모든 동적 값은 params로 전달하세요
        """
        try:
            # 파라미터 딕셔너리 생성
            param_dict = {}
            converted_query = query

            # $1, $2 형식 감지 및 변환 (레거시 지원)
            if '$' in query and params:
                for i, param in enumerate(params, 1):
                    param_name = f"param{i}"
                    # $N을 :paramN으로 안전하게 변경 (word boundary 사용)
                    converted_query = re.sub(rf'\${i}\b', f":{param_name}", converted_query)
                    param_dict[param_name] = param
            else:
                # :param1, :param2 형식인 경우
                for i, param in enumerate(params, 1):
                    param_dict[f"param{i}"] = param

            async with await self.get_session() as session:
                # text()는 SQL injection을 방지하는 prepared statement 사용
                result = await session.execute(text(converted_query), param_dict)
                await session.commit()
                return result
        except Exception as e:
            logger.error(f"데이터베이스 실행 에러: {e}")
            logger.error(f"쿼리: {query[:200]}...")  # 쿼리 일부만 로깅 (보안)
            logger.error(f"파라미터 개수: {len(params)}")
            raise

    async def fetch_one(self, query: str, *params):
        """단일 row 조회

        ⚠️  보안 경고: 가능하면 이 메서드 대신 SQLAlchemy ORM을 사용하세요!

        Args:
            query: SQL 쿼리 문자열
            *params: 파라미터들

        Security:
            - 사용자 입력을 query 문자열에 직접 포함하지 마세요
            - 모든 동적 값은 params로 전달하세요
        """
        try:
            param_dict = {}
            converted_query = query

            # $1, $2 형식 감지 및 변환 (레거시 지원)
            if '$' in query and params:
                for i, param in enumerate(params, 1):
                    param_name = f"param{i}"
                    converted_query = re.sub(rf'\${i}\b', f":{param_name}", converted_query)
                    param_dict[param_name] = param
            else:
                for i, param in enumerate(params, 1):
                    param_dict[f"param{i}"] = param

            async with await self.get_session() as session:
                result = await session.execute(text(converted_query), param_dict)
                # Commit the transaction if the query modifies data (e.g., calling stored procedures)
                if query.strip().upper().startswith('SELECT') and 'create_' in query.lower():
                    await session.commit()
                row = result.fetchone()
                return row
        except Exception as e:
            logger.error(f"데이터베이스 fetch_one 에러: {e}")
            logger.error(f"쿼리: {query[:200]}...")  # 쿼리 일부만 로깅
            raise

    async def fetch_all(self, query: str, *params):
        """모든 row 조회

        ⚠️  보안 경고: 가능하면 이 메서드 대신 SQLAlchemy ORM을 사용하세요!

        Args:
            query: SQL 쿼리 문자열
            *params: 파라미터들

        Security:
            - 사용자 입력을 query 문자열에 직접 포함하지 마세요
            - 모든 동적 값은 params로 전달하세요
        """
        try:
            param_dict = {}
            converted_query = query

            # $1, $2 형식 감지 및 변환 (레거시 지원)
            if '$' in query and params:
                for i, param in enumerate(params, 1):
                    param_name = f"param{i}"
                    converted_query = re.sub(rf'\${i}\b', f":{param_name}", converted_query)
                    param_dict[param_name] = param
            else:
                for i, param in enumerate(params, 1):
                    param_dict[f"param{i}"] = param

            async with await self.get_session() as session:
                result = await session.execute(text(converted_query), param_dict)
                return result.fetchall()
        except Exception as e:
            logger.error(f"데이터베이스 fetch_all 에러: {e}")
            logger.error(f"쿼리: {query[:200]}...")  # 쿼리 일부만 로깅
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
get_db_session = get_session
