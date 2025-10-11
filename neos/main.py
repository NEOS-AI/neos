import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
import time
import uuid

from neos.config.settings import settings
from neos.database.connection import db_manager
from neos.utils.cache import cache_manager
from neos.utils.embeddings import embedding_manager
from neos.api.routes import router
from neos.api.web_search_analytics_routes import router as web_search_analytics_router
from neos.workflow.graph import multi_agent_workflow


# 로깅 설정
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

TEST_EMBEDDING_ON_STARTUP = False  # 시작 시 임베딩 테스트 여부
IS_DEBUG = settings.DEBUG


@asynccontextmanager
async def lifespan(app: FastAPI):
    """애플리케이션 생명주기 관리"""
    # 시작 시 실행
    logger.info("🚀 Starting Multi-Agent AI System...")
    
    try:
        # 데이터베이스 연결 초기화
        logger.info("📊 Initializing database connection...")
        await db_manager.initialize()
        logger.info("✅ Database connection established")

        # Redis 캐시 연결 초기화
        logger.info("🔄 Initializing cache connection...")
        await cache_manager.initialize()
        logger.info("✅ Cache connection established")

        # 임베딩 매니저 테스트
        if TEST_EMBEDDING_ON_STARTUP:
            logger.info("🤖 Testing AI services...")
            test_embedding = await embedding_manager.get_embedding("test connection", use_cache=False)
            if test_embedding:
                logger.info("✅ OpenAI API connection verified")
            else:
                logger.warning("⚠️ OpenAI API connection issue")

        logger.info("🎉 Multi-Agent AI System startup completed successfully!")

    except Exception as e:
        logger.error(f"❌ Startup failed: {e}")
        raise e

    yield

    # 종료 시 실행
    logger.info("🔄 Shutting down Multi-Agent AI System...")

    try:
        # 데이터베이스 연결 종료
        await db_manager.close()
        logger.info("📊 Database connection closed")

        # Redis 캐시 연결 종료
        await cache_manager.close()
        logger.info("🔄 Cache connection closed")

        logger.info("✅ Shutdown completed successfully")

    except Exception as e:
        logger.error(f"❌ Shutdown error: {e}")


# FastAPI 애플리케이션 생성
app = FastAPI(
    title="Multi-Agent AI System",
    description="""**멀티 에이전트 AI 기반 지능형 검색 및 분석 시스템**""",
    version="0.4.3",
    lifespan=lifespan,
    docs_url="/docs" if IS_DEBUG else None,
    redoc_url="/redoc" if IS_DEBUG else None
)


# CORS 미들웨어 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if IS_DEBUG else ["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# GZip 압축 미들웨어
app.add_middleware(GZipMiddleware, minimum_size=1000)

# 요청 로깅 미들웨어
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """요청 로깅 및 성능 모니터링"""
    start_time = time.time()
    request_id = str(uuid.uuid4())[:8]
    
    # 요청 로깅
    logger.info(f"🔵 [{request_id}] {request.method} {request.url.path} - Start")
    
    try:
        response = await call_next(request)
        
        # 응답 시간 계산
        process_time = time.time() - start_time
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time"] = str(round(process_time * 1000, 2))
        
        # 성공 로깅
        logger.info(f"🟢 [{request_id}] {request.method} {request.url.path} - {response.status_code} - {process_time:.2f}s")
        
        return response
        
    except Exception as e:
        # 에러 로깅
        process_time = time.time() - start_time
        logger.error(f"🔴 [{request_id}] {request.method} {request.url.path} - Error: {str(e)} - {process_time:.2f}s")
        raise e

# 전역 예외 처리기
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """전역 예외 처리"""
    request_id = request.headers.get("X-Request-ID", "unknown")
    
    logger.error(f"🔴 Global exception [{request_id}]: {str(exc)}", exc_info=True)
    
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "request_id": request_id,
            "detail": str(exc) if IS_DEBUG else "An unexpected error occurred"
        }
    )

# HTTP 예외 처리기
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """HTTP 예외 처리"""
    request_id = request.headers.get("X-Request-ID", "unknown")
    
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.detail,
            "request_id": request_id,
            "status_code": exc.status_code
        }
    )

# API 라우터 등록
app.include_router(router, prefix=settings.API_V1_PREFIX, tags=["Multi-Agent AI"])
app.include_router(web_search_analytics_router, prefix=f"{settings.API_V1_PREFIX}/analytics", tags=["Web Search Analytics"])

# 루트 엔드포인트
@app.get("/")
async def root():
    """루트 엔드포인트 - 시스템 정보"""
    return {
        "name": "Multi-Agent AI System",
        "version": "1.0.0", 
        "description": "LangGraph, CrewAI, FastAPI 기반 멀티 에이전트 AI 시스템",
        "status": "running",
        "endpoints": {
            "docs": "/docs",
            "health": f"{settings.API_V1_PREFIX}/health",
            "query": f"{settings.API_V1_PREFIX}/query",
            "trending": f"{settings.API_V1_PREFIX}/trending",
            "websocket": f"{settings.API_V1_PREFIX}/ws/{{session_id}}"
        },
        "features": [
            "🔍 지능형 멀티모달 검색",
            "📊 고급 데이터 분석",
            "🎨 AI 콘텐츠 생성",
            "🚀 자동화된 워크플로우",
            "⚡ 실시간 처리",
            "📈 품질 모니터링"
        ]
    }


# 시스템 정보 엔드포인트
@app.get("/info")
async def system_info():
    """시스템 정보 및 설정"""
    return {
        "system": {
            "debug": IS_DEBUG,
            "log_level": settings.LOG_LEVEL,
            "api_prefix": settings.API_V1_PREFIX
        },
        "ai_services": {
            "embedding_model": settings.EMBEDDING_MODEL,
            "embedding_dimension": settings.EMBEDDING_DIMENSION,
            "max_iterations": settings.MAX_ITERATIONS,
            "agent_timeout": settings.AGENT_TIMEOUT
        },
        "database": {
            "pool_size": settings.DATABASE_POOL_SIZE,
            "max_overflow": settings.DATABASE_MAX_OVERFLOW
        },
        "cache": {
            "default_ttl": settings.REDIS_TTL
        },
        "agents": {
            "search_agents": multi_agent_workflow.config.SEARCH_AGENTS,
            "analysis_agents": multi_agent_workflow.config.ANALYSIS_AGENTS,
            "generation_agents": multi_agent_workflow.config.GENERATION_AGENTS
        }
    }

# 개발용 테스트 엔드포인트 (디버그 모드에서만)
if IS_DEBUG:
    @app.get("/debug/test-workflow")
    async def test_workflow():
        """워크플로우 테스트 (디버그 전용)"""
        test_input = {
            "user_id": "debug_user",
            "session_id": "debug_session", 
            "query": "안녕하세요, 테스트 쿼리입니다."
        }
        
        result = await multi_agent_workflow.execute_workflow(test_input)
        return result

    @app.get("/debug/cache-stats")
    async def cache_stats():
        """캐시 통계 (디버그 전용)"""
        try:
            # Redis 정보 조회
            info = await cache_manager.redis_client.info() if cache_manager.redis_client else {}
            return {
                "cache_available": cache_manager.redis_client is not None,
                "redis_info": {
                    "connected_clients": info.get("connected_clients", 0),
                    "used_memory_human": info.get("used_memory_human", "0B"),
                    "keyspace_hits": info.get("keyspace_hits", 0),
                    "keyspace_misses": info.get("keyspace_misses", 0)
                }
            }
        except Exception as e:
            return {"error": str(e), "cache_available": False}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8518,
        log_level=settings.LOG_LEVEL.lower(),
        access_log=True
    )
