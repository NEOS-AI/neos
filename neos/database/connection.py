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
            async with self.get_session() as session:
                await session.execute("SELECT 1")
                return True
        except Exception:
            return False


# 전역 데이터베이스 매니저
db_manager = DatabaseManager()
