from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from neos.config.settings import settings


class Base(DeclarativeBase):
    pass


class DatabaseManager:
    def __init__(self):
        self.engine = None
        self.session_factory = None
        
    async def initialize(self):
        """데이터베이스 연결 초기화"""
        self.engine = create_async_engine(
            settings.DATABASE_URL,
            pool_size=settings.DATABASE_POOL_SIZE,
            max_overflow=settings.DATABASE_MAX_OVERFLOW,
            echo=settings.DEBUG,
            pool_pre_ping=True,
        )
        
        self.session_factory = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False
        )
        
        # 테이블 생성
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def close(self):
        """데이터베이스 연결 종료"""
        if self.engine:
            await self.engine.dispose()

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
                return True
        except Exception as e:
            print(f"Database health check error: {e}")
            return False

    async def execute(self, query: str, *params):
        """쿼리 실행 (INSERT, UPDATE, DELETE)

        Args:
            query: SQL 쿼리 문자열 ($1, $2 형식의 플레이스홀더 사용)
            *params: 순서대로 바인딩될 파라미터들
        """
        try:
            # PostgreSQL의 $1, $2 형식을 :param1, :param2 형식으로 변환
            param_dict = {}
            converted_query = query
            for i, param in enumerate(params, 1):
                placeholder = f"${i}"
                param_name = f"param{i}"
                converted_query = converted_query.replace(placeholder, f":{param_name}")
                param_dict[param_name] = param

            async with await self.get_session() as session:
                result = await session.execute(text(converted_query), param_dict)
                await session.commit()
                return result
        except Exception as e:
            print(f"[ERROR] Database execute error: {e}")
            print(f"[ERROR] Query: {query}")
            print(f"[ERROR] Params: {params}")
            raise

    async def fetch_one(self, query: str, *params):
        """단일 row 조회"""
        try:
            # PostgreSQL의 $1, $2 형식을 :param1, :param2 형식으로 변환
            param_dict = {}
            converted_query = query
            for i, param in enumerate(params, 1):
                placeholder = f"${i}"
                param_name = f"param{i}"
                converted_query = converted_query.replace(placeholder, f":{param_name}")
                param_dict[param_name] = param

            async with await self.get_session() as session:
                result = await session.execute(text(converted_query), param_dict)
                # Commit the transaction if the query modifies data (e.g., calling stored procedures)
                if query.strip().upper().startswith('SELECT') and 'create_' in query.lower():
                    await session.commit()
                row = result.fetchone()
                return row
        except Exception as e:
            print(f"[ERROR] Database fetch_one error: {e}")
            raise

    async def fetch_all(self, query: str, *params):
        """모든 row 조회"""
        try:
            # PostgreSQL의 $1, $2 형식을 :param1, :param2 형식으로 변환
            param_dict = {}
            converted_query = query
            for i, param in enumerate(params, 1):
                placeholder = f"${i}"
                param_name = f"param{i}"
                converted_query = converted_query.replace(placeholder, f":{param_name}")
                param_dict[param_name] = param

            async with await self.get_session() as session:
                result = await session.execute(text(converted_query), param_dict)
                return result.fetchall()
        except Exception as e:
            print(f"[ERROR] Database fetch_all error: {e}")
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
