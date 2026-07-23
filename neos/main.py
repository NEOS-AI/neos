import logging
from contextlib import asynccontextmanager
from fastapi import APIRouter, Depends, FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.routing import APIWebSocketRoute
import time
import uuid
import asyncio

from neos.config.settings import get_settings
from neos.database.connection import db_manager
from neos.utils.cache import cache_manager
from neos.utils.embeddings import embedding_manager
from neos.workflow.stream_manager import stream_manager
from neos.api.handlers.query_handlers import router
from neos.api.handlers.analytics_handlers import router as web_search_analytics_router
from neos.api.handlers.document_handlers import router as document_router
from neos.api.handlers.multimodal_handlers import router as multimodal_router
from neos.api.handlers.chat_handlers import router as chat_router
from neos.api.handlers.deep_research_handlers import router as deep_research_router
from neos.api.handlers.deep_analysis_analytics_handlers import (
    router as deep_analysis_analytics_router,
)
from neos.api.deep_analysis_routes import router as deep_analysis_router
from neos.api.handlers.auth import router as auth_router
from neos.api.handlers.skills_handlers import router as skills_router
from neos.api.handlers.workflow_stream_handlers import router as workflow_stream_router
from neos.api.handlers.unified_handlers import router as unified_router
from neos.api.handlers.vote_handlers import router as vote_router
from neos.api.handlers.artifact_handlers import router as artifact_router
from neos.api.handlers.research_session_handlers import router as research_session_router
from neos.api.handlers.async_research_handlers import router as async_research_router
from neos.api.handlers.export_handlers import router as export_router
from neos.api.handlers.refinement_handlers import router as refinement_router
from neos.api.handlers.template_handlers import router as template_router
from neos.api.handlers.approval_handlers import router as approval_router  # Phase 2: Execution Approval
from neos.api.handlers.autonomy_handlers import router as autonomy_router
from neos.api.handlers.scheduled_tasks_handlers import router as scheduled_tasks_router  # Phase 4: Cron 스케줄
from neos.api.handlers.ui_submit_handlers import router as ui_submit_router  # Phase 8: A2UI
from neos.api.handlers.coding_handlers import router as coding_router
from neos.api.handlers.coding_ws_handlers import router as coding_ws_router
from neos.api.handlers.coding_workspace_ws_handlers import (
    router as coding_workspace_ws_router,
)
from neos.coding.runtime import (
    close_coding_transport,
    coding_runtime,
    initialize_coding_transport,
    start_coding_outbox_dispatcher,
)
from neos.api.similarity_chat_routes import similarity_chat_router
from neos.api.dependencies.auth import get_current_admin_user
from neos.database.models import User
from neos.workflow.graph import multi_agent_workflow
from neos.utils.exceptions import NeosBaseException, get_exception_status_code, is_client_error
from neos.observability.metrics import get_metrics_collector
from neos.workflow.checkpointer import cleanup_checkpointer
from neos.workflow.telemetry import setup_telemetry, instrument_app, instrument_sqlalchemy_engine


__VERSION__ = "0.23.0"


settings = get_settings()


# 로깅 설정
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

TEST_EMBEDDING_ON_STARTUP = False  # 시작 시 임베딩 테스트 여부
IS_DEBUG = settings.DEBUG


def _router_with_routes(source_router: APIRouter, route_filter) -> APIRouter:
    """Return a router containing only routes that match route_filter."""
    filtered_router = APIRouter()
    filtered_router.routes = [route for route in source_router.routes if route_filter(route)]
    return filtered_router


def _router_without_websockets(source_router: APIRouter) -> APIRouter:
    """Return a router containing only HTTP routes from source_router."""
    return _router_with_routes(
        source_router,
        lambda route: not isinstance(route, APIWebSocketRoute),
    )


def _is_health_http_route(route) -> bool:
    """Health endpoints stay public under the HTTP authorization matrix."""
    return (
        not isinstance(route, APIWebSocketRoute)
        and getattr(route, "path", "").endswith("/health")
    )


def _include_router_for_runtime(api_router: APIRouter, **kwargs) -> None:
    """Include WebSockets only outside production until WebSocket auth is implemented."""
    if IS_DEBUG:
        app.include_router(api_router, **kwargs)
        return

    if any(isinstance(route, APIWebSocketRoute) for route in api_router.routes):
        app.include_router(_router_without_websockets(api_router), **kwargs)
        return

    app.include_router(api_router, **kwargs)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    애플리케이션 생명주기 관리 (Enterprise Edition)

    Startup:
    - Database connection
    - Redis cache
    - Metrics collector
    - Background tasks

    Shutdown:
    - Graceful connection cleanup
    - Metrics export
    - State persistence
    """
    # 시작 시 실행
    logger.info("🚀 Starting Multi-Agent AI System (Enterprise Edition)...")

    background_tasks = []
    _channel_adapters = []  # Phase 1: 채널 어댑터 인스턴스 (shutdown용)

    try:
        # OpenTelemetry 초기화 (Phase 3)
        logger.info("🔍 Initializing OpenTelemetry distributed tracing...")
        setup_telemetry(settings)
        if settings.OTEL_ENABLED:
            logger.info(f"✅ OpenTelemetry enabled: {settings.OTEL_SERVICE_NAME}")
        else:
            logger.info("ℹ️ OpenTelemetry disabled (set OTEL_ENABLED=true to enable)")

        # 데이터베이스 연결 초기화
        logger.info("📊 Initializing database connection...")
        await db_manager.initialize()
        logger.info("✅ Database connection established")

        # SQLAlchemy 엔진에 계측 적용
        if settings.OTEL_ENABLED and hasattr(db_manager, 'engine'):
            instrument_sqlalchemy_engine(db_manager.engine)
            logger.info("✅ SQLAlchemy instrumentation enabled")

        # Redis 캐시 연결 초기화
        logger.info("🔄 Initializing cache connection...")
        await cache_manager.initialize()
        logger.info("✅ Cache connection established")

        initialize_coding_transport(
            redis_client=cache_manager.redis_client,
            production=not IS_DEBUG,
        )
        logger.info("✅ Coding transport initialized")

        coding_outbox_task = start_coding_outbox_dispatcher()
        background_tasks.append(coding_outbox_task)
        logger.info("✅ Coding outbox dispatcher started")

        if coding_runtime.supervisor is not None:
            await coding_runtime.supervisor.start()
            logger.info("✅ Coding development supervisor started")

        # StreamManager 시작 (Phase 3 - SSE 재연결 지원)
        logger.info("📡 Starting SSE Stream Manager...")
        await stream_manager.start()
        logger.info("✅ Stream Manager started")

        # Metrics collector 초기화
        logger.info("📈 Initializing enterprise metrics collector...")
        metrics_collector = get_metrics_collector()

        # Start system metrics collection in background
        system_metrics_task = asyncio.create_task(
            metrics_collector.collect_system_metrics()
        )
        background_tasks.append(system_metrics_task)
        logger.info("✅ Metrics collector initialized")

        # 임베딩 매니저 테스트
        if TEST_EMBEDDING_ON_STARTUP:
            logger.info("🤖 Testing AI services...")
            test_embedding = await embedding_manager.get_embedding("test connection", use_cache=False)
            if test_embedding:
                logger.info("✅ OpenAI API connection verified")
            else:
                logger.warning("⚠️ OpenAI API connection issue")

        # Ray 분산 처리 초기화 (RAY_ENABLED=true 시에만)
        if getattr(settings, "RAY_ENABLED", False):
            logger.info("⚡ Initializing Ray distributed processing...")
            try:
                import ray
                if not ray.is_initialized():
                    ray.init(
                        address=getattr(settings, "RAY_ADDRESS", "auto"),
                        ignore_reinit_error=True,
                        object_store_memory=getattr(settings, "RAY_OBJECT_STORE_MEMORY", 2_000_000_000),
                    )
                logger.info(f"✅ Ray initialized: {ray.cluster_resources()}")

                # Phase 2: Stateless Named Actors 생성 (Atomizer, Planner, Aggregator, Verifier)
                from neos.workflow.ray_actors.stateless_actors import create_all_named_actors
                create_all_named_actors(
                    max_tasks_per_level=getattr(settings, "HYPER_DEEP_MAX_TASKS_PER_LEVEL", 3)
                )
                logger.info("✅ Ray Named Actors created (stateless actors)")

                # Phase 2: CostAccumulatorActor Named Actor 생성
                from neos.workflow.ray_actors.cost_accumulator import get_or_create_cost_accumulator
                get_or_create_cost_accumulator()
                logger.info("✅ CostAccumulatorActor ready")

            except Exception as e:
                logger.warning(f"⚠️ Ray initialization failed, falling back to sequential: {e}")

            # Worker Actor 준비 완료 대기 (콜드 스타트 타임아웃 방지)
            try:
                from neos.workflow.recursive.distributed_orchestrator import (
                    DistributedRecursiveOrchestrator,
                )
                orchestrator = getattr(multi_agent_workflow, "hyper_deep_orchestrator", None)
                if isinstance(orchestrator, DistributedRecursiveOrchestrator):
                    await orchestrator.warmup()
                    logger.info("✅ HyperDeep Worker Actors warmed up")
            except Exception as e:
                logger.warning(f"⚠️ Worker Actor warmup failed: {e}")

        # Skills 초기화
        logger.info("🎯 Initializing Skills system...")
        from neos.skills.manager import skill_manager

        # Register builtin skills with auto-discovery
        skill_manager.register_builtin_skills(use_auto_discovery=True)
        logger.info("✅ Builtin skills registered (auto-discovery)")

        # Initialize skills (optional - can be done on-demand)
        # await skill_manager.initialize_all()

        # ── Phase 1: 멀티채널 어댑터 초기화 (OpenClaw Channel Adapter Layer) ──
        _channel_adapters = []
        if any([
            settings.CHANNEL_TELEGRAM_ENABLED,
            settings.CHANNEL_DISCORD_ENABLED,
            settings.CHANNEL_SLACK_ENABLED,
        ]):
            logger.info("📲 Initializing Channel Adapters...")
            from neos.api.channels.gateway import ChannelGateway
            _channel_gateway = ChannelGateway(multi_agent_workflow)

            if settings.CHANNEL_TELEGRAM_ENABLED:
                try:
                    from neos.api.channels.adapters.telegram import TelegramAdapter
                    _telegram = TelegramAdapter(
                        token=settings.CHANNEL_TELEGRAM_BOT_TOKEN,
                        gateway=_channel_gateway,
                    )
                    asyncio.create_task(_telegram.start(), name="telegram_adapter")
                    _channel_adapters.append(_telegram)
                    logger.info("✅ Telegram adapter started")
                except Exception as e:
                    logger.warning(f"⚠️ Telegram adapter start failed: {e}")

            if settings.CHANNEL_DISCORD_ENABLED:
                try:
                    from neos.api.channels.adapters.discord import DiscordAdapter
                    _discord = DiscordAdapter(
                        token=settings.CHANNEL_DISCORD_BOT_TOKEN,
                        gateway=_channel_gateway,
                    )
                    asyncio.create_task(_discord.start(), name="discord_adapter")
                    _channel_adapters.append(_discord)
                    logger.info("✅ Discord adapter started")
                except Exception as e:
                    logger.warning(f"⚠️ Discord adapter start failed: {e}")

            if settings.CHANNEL_SLACK_ENABLED:
                try:
                    from neos.api.channels.adapters.slack import SlackAdapter
                    _slack = SlackAdapter(
                        token=settings.CHANNEL_SLACK_BOT_TOKEN,
                        gateway=_channel_gateway,
                    )
                    asyncio.create_task(_slack.start(), name="slack_adapter")
                    _channel_adapters.append(_slack)
                    logger.info("✅ Slack adapter started")
                except Exception as e:
                    logger.warning(f"⚠️ Slack adapter start failed: {e}")

        logger.info("🎉 Multi-Agent AI System (Enterprise Edition) startup completed successfully!")
        logger.info("📊 Metrics endpoint available at: /metrics")
        logger.info("🎯 Skills API available at: /api/v1/skills")

    except Exception as e:
        logger.error(f"❌ Startup failed: {e}")
        raise e

    yield

    # 종료 시 실행
    logger.info("🔄 Shutting down Multi-Agent AI System...")

    try:
        if coding_runtime.supervisor is not None:
            await coding_runtime.supervisor.stop()
            logger.info("✅ Coding development supervisor stopped")

        # Cancel background tasks
        for task in background_tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # StreamManager 정리
        logger.info("📡 Stopping SSE Stream Manager...")
        await stream_manager.stop()
        logger.info("✅ Stream Manager stopped")

        # PostgreSQL checkpointer cleanup
        logger.info("💾 Cleaning up workflow state manager...")
        await cleanup_checkpointer()
        logger.info("✅ Workflow state manager closed")

        await close_coding_transport()
        logger.info("✅ Coding transport closed")

        # 데이터베이스 연결 종료
        await db_manager.close()
        logger.info("📊 Database connection closed")

        # Redis 캐시 연결 종료
        await cache_manager.close()
        logger.info("🔄 Cache connection closed")

        # Phase 1: 채널 어댑터 종료
        if _channel_adapters:
            logger.info("📲 Stopping Channel Adapters...")
            for adapter in _channel_adapters:
                try:
                    await asyncio.wait_for(adapter.stop(), timeout=5.0)
                except (asyncio.TimeoutError, Exception) as e:
                    logger.warning(f"⚠️ Channel adapter stop error (non-critical): {e}")
            logger.info("✅ Channel Adapters stopped")

        # Ray 분산 처리 종료
        if getattr(settings, "RAY_ENABLED", False):
            try:
                import ray
                if ray.is_initialized():
                    ray.shutdown()
                    logger.info("⚡ Ray shutdown completed")
            except Exception as e:
                logger.warning(f"⚠️ Ray shutdown error: {e}")

        logger.info("✅ Shutdown completed successfully")

    except Exception as e:
        logger.error(f"❌ Shutdown error: {e}")


# FastAPI 애플리케이션 생성
app = FastAPI(
    title="Multi-Agent AI System",
    description="""**멀티 에이전트 AI 기반 지능형 검색 및 분석 시스템**""",
    version=__VERSION__,
    lifespan=lifespan,
    docs_url="/docs" if IS_DEBUG else None,
    redoc_url="/redoc" if IS_DEBUG else None
)

# OpenTelemetry FastAPI 자동 계측 적용 (Phase 3)
instrument_app(app)

# CORS 미들웨어 설정
# 보안 강화: DEBUG 모드에서도 특정 origin만 허용
allowed_origins = settings.CORS_ALLOWED_ORIGINS
if IS_DEBUG:
    # DEBUG 모드에서 추가 개발 origin 허용 (하지만 "*"는 사용하지 않음)
    dev_origins = ["http://localhost:3000", "http://localhost:5173", "http://127.0.0.1:3000"]
    allowed_origins = list(set(allowed_origins + dev_origins))
    logger.warning(f"🟡 DEBUG mode: CORS allowing origins: {allowed_origins}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID", "X-Process-Time"],
    max_age=600,  # CORS preflight 캐싱 (10분)
)

# GZip 압축 미들웨어
app.add_middleware(GZipMiddleware, minimum_size=1000)

# 요청 로깅 및 메트릭 수집 미들웨어 (Enterprise Edition)
@app.middleware("http")
async def log_and_track_requests(request: Request, call_next):
    """
    요청 로깅 및 Prometheus 메트릭 수집

    Tracks:
    - Request count by method/endpoint/status
    - Request duration
    - In-progress requests
    """
    start_time = time.time()
    request_id = str(uuid.uuid4())[:8]

    # Get metrics collector
    metrics_collector = get_metrics_collector()

    # Extract endpoint for metrics
    endpoint = request.url.path
    method = request.method

    # Track in-progress requests
    metrics_collector.http_requests_in_progress.labels(
        method=method,
        endpoint=endpoint
    ).inc()

    # 요청 로깅
    logger.info(f"🔵 [{request_id}] {method} {endpoint} - Start")

    try:
        response = await call_next(request)

        # 응답 시간 계산
        process_time = time.time() - start_time
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time"] = str(round(process_time * 1000, 2))

        # Track metrics
        status_code = str(response.status_code)

        metrics_collector.http_requests_total.labels(
            method=method,
            endpoint=endpoint,
            status=status_code
        ).inc()

        metrics_collector.http_request_duration_seconds.labels(
            method=method,
            endpoint=endpoint
        ).observe(process_time)

        # 성공 로깅
        logger.info(f"🟢 [{request_id}] {method} {endpoint} - {status_code} - {process_time:.2f}s")

        return response

    except Exception as e:
        # 에러 로깅 및 메트릭
        process_time = time.time() - start_time

        metrics_collector.http_requests_total.labels(
            method=method,
            endpoint=endpoint,
            status="500"
        ).inc()

        logger.error(f"🔴 [{request_id}] {method} {endpoint} - Error: {str(e)} - {process_time:.2f}s")
        raise e

    finally:
        # Decrement in-progress gauge
        metrics_collector.http_requests_in_progress.labels(
            method=method,
            endpoint=endpoint
        ).dec()


# 커스텀 예외 처리기
@app.exception_handler(NeosBaseException)
async def neos_exception_handler(request: Request, exc: NeosBaseException):
    """네오스 커스텀 예외 처리"""
    request_id = request.headers.get("X-Request-ID", "unknown")
    status_code = get_exception_status_code(exc)

    # 로그 레벨 결정 (클라이언트 오류는 warning, 서버 오류는 error)
    if is_client_error(exc):
        logger.warning(f"🟡 Client error [{request_id}]: {exc.message}", extra={"details": exc.details})
    else:
        logger.error(f"🔴 Server error [{request_id}]: {exc.message}", exc_info=True, extra={"details": exc.details})

    return JSONResponse(
        status_code=status_code,
        content={
            "error": exc.message,
            "request_id": request_id,
            "details": exc.details if IS_DEBUG else {},
            "type": exc.__class__.__name__
        }
    )

# HTTP 예외 처리기
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """HTTP 예외 처리"""
    request_id = request.headers.get("X-Request-ID", "unknown")

    logger.warning(f"🟡 HTTP exception [{request_id}]: {exc.detail}")

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.detail,
            "request_id": request_id,
            "status_code": exc.status_code
        }
    )

# 전역 예외 처리기 (fallback)
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """전역 예외 처리 (예상치 못한 예외용)"""
    request_id = request.headers.get("X-Request-ID", "unknown")

    logger.error(f"🔴 Unexpected exception [{request_id}]: {str(exc)}", exc_info=True)

    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "request_id": request_id,
            "detail": str(exc) if IS_DEBUG else "An unexpected error occurred",
            "type": "UnexpectedError"
        }
    )


# API 라우터 등록
_include_router_for_runtime(auth_router, prefix=settings.API_V1_PREFIX, tags=["Authentication"])  # 인증 라우터 추가
_include_router_for_runtime(router, prefix=settings.API_V1_PREFIX, tags=["Multi-Agent AI"])
_include_router_for_runtime(
    _router_with_routes(web_search_analytics_router, _is_health_http_route),
    prefix=f"{settings.API_V1_PREFIX}/analytics",
    tags=["Web Search Analytics"],
)
_include_router_for_runtime(
    _router_with_routes(
        web_search_analytics_router,
        lambda route: not _is_health_http_route(route),
    ),
    prefix=f"{settings.API_V1_PREFIX}/analytics",
    tags=["Web Search Analytics"],
    dependencies=[Depends(get_current_admin_user)],
)
_include_router_for_runtime(document_router, prefix=f"{settings.API_V1_PREFIX}/documents", tags=["Document Management"])
_include_router_for_runtime(multimodal_router, prefix=f"{settings.API_V1_PREFIX}/multimodal", tags=["Multimodal Processing"])
_include_router_for_runtime(chat_router, prefix=f"{settings.API_V1_PREFIX}/chat", tags=["Chat & Conversations"])
_include_router_for_runtime(deep_research_router, prefix=settings.API_V1_PREFIX, tags=["Deep Research"])
_include_router_for_runtime(deep_analysis_analytics_router, prefix=settings.API_V1_PREFIX, tags=["Deep Analysis Analytics"])
_include_router_for_runtime(deep_analysis_router, prefix=settings.API_V1_PREFIX, tags=["Deep Analysis Harness"])
_include_router_for_runtime(
    skills_router,
    prefix=f"{settings.API_V1_PREFIX}/skills",
    tags=["Skills Management"],
    dependencies=[Depends(get_current_admin_user)],
)
_include_router_for_runtime(workflow_stream_router, prefix=settings.API_V1_PREFIX, tags=["Workflow Streaming"])
_include_router_for_runtime(unified_router, tags=["Unified Processing"])  # 통합 API (문서 + 워크플로우)
_include_router_for_runtime(similarity_chat_router, prefix=f"{settings.API_V1_PREFIX}/chat", tags=["Similarity-based Chat"])
_include_router_for_runtime(vote_router, prefix=settings.API_V1_PREFIX, tags=["Votes & Feedback"])  # Vote API
_include_router_for_runtime(artifact_router, prefix=settings.API_V1_PREFIX, tags=["Artifacts & Documents"])  # Artifact API
_include_router_for_runtime(research_session_router, tags=["Research Sessions"])  # Research Session API (prefix already set in router)
_include_router_for_runtime(async_research_router, tags=["Async Research"])  # Phase 3.5: Celery-based async research
_include_router_for_runtime(export_router, tags=["Report Export"])  # Phase 3.4: Structured report export
_include_router_for_runtime(refinement_router, tags=["Research Refinement"])  # Phase 3.8: Interactive refinement
_include_router_for_runtime(template_router, tags=["Research Templates"])  # Phase 4.7: Research templates
_include_router_for_runtime(approval_router, prefix=settings.API_V1_PREFIX, tags=["Execution Approval"])  # Phase 2: OpenClaw Exec Approval
_include_router_for_runtime(autonomy_router, prefix=settings.API_V1_PREFIX, tags=["Agent Autonomy"])
_include_router_for_runtime(scheduled_tasks_router, prefix=settings.API_V1_PREFIX, tags=["Scheduled Tasks"])  # Phase 4: OpenClaw Cron
_include_router_for_runtime(ui_submit_router, prefix=settings.API_V1_PREFIX, tags=["A2UI"])  # Phase 8: OpenClaw A2UI
_include_router_for_runtime(coding_router, prefix=settings.API_V1_PREFIX, tags=["Coding Agent"])
app.include_router(
    coding_ws_router,
    prefix=settings.API_V1_PREFIX,
    tags=["Coding Agent WebSocket"],
)
app.include_router(
    coding_workspace_ws_router,
    prefix=settings.API_V1_PREFIX,
    tags=["Coding Workspace WebSocket"],
)


# === Enterprise Monitoring Endpoints ===

@app.get("/metrics")
async def metrics_endpoint(
    current_user: User = Depends(get_current_admin_user),
):
    """
    Prometheus metrics endpoint for enterprise monitoring.

    Exposes:
    - HTTP request metrics (rate, duration, errors)
    - Workflow execution metrics
    - Agent performance metrics
    - LLM API call metrics
    - Database and cache metrics
    - System resource metrics

    Configure Prometheus to scrape this endpoint:
    ```yaml
    scrape_configs:
      - job_name: 'neos'
        static_configs:
          - targets: ['localhost:8518']
    ```
    """
    metrics_collector = get_metrics_collector()
    metrics_data = metrics_collector.export_metrics()

    return Response(
        content=metrics_data,
        media_type=metrics_collector.get_content_type()
    )


@app.get(f"{settings.API_V1_PREFIX}/metrics/stats")
async def metrics_stats(
    current_user: User = Depends(get_current_admin_user),
):
    """
    Get human-readable metrics statistics.
    Useful for debugging and quick health checks.
    """
    return {
        "message": "Metrics available at /metrics endpoint",
        "prometheus_format": "Use /metrics for Prometheus scraping",
        "grafana_dashboards": "Import dashboards from /docs/grafana/",
        "alert_rules": "See /docs/prometheus/alerts.yml"
    }


# Root Endpoint
@app.get("/")
async def root():
    """Root Endpoint - System Information"""
    response = {
        "name": "Multi-Agent AI System",
        "version": __VERSION__,
        "status": "running",
        "health": f"{settings.API_V1_PREFIX}/health",
    }
    if IS_DEBUG:
        response["docs"] = "/docs"
    return response


# 시스템 정보 엔드포인트
@app.get("/info")
async def system_info(
    current_user: User = Depends(get_current_admin_user),
):
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
            "agent_timeout": settings.AGENT_TIMEOUT,
            "search_orchestration_timeout": settings.SEARCH_ORCHESTRATION_TIMEOUT,
            "agent_timeouts": settings.AGENT_TIMEOUTS
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

async def debug_test_workflow(
    current_user: User = Depends(get_current_admin_user),
):
    """워크플로우 테스트 (디버그 전용)."""
    test_input = {
        "user_id": current_user.user_id,
        "session_id": "debug_session",
        "query": "안녕하세요, 테스트 쿼리입니다.",
    }
    return await multi_agent_workflow.execute_workflow(test_input)


async def debug_cache_stats(
    _current_user: User = Depends(get_current_admin_user),
):
    """캐시 통계 (디버그 전용)."""
    try:
        info = (
            await cache_manager.redis_client.info()
            if cache_manager.redis_client
            else {}
        )
        return {
            "cache_available": cache_manager.redis_client is not None,
            "redis_info": {
                "connected_clients": info.get("connected_clients", 0),
                "used_memory_human": info.get("used_memory_human", "0B"),
                "keyspace_hits": info.get("keyspace_hits", 0),
                "keyspace_misses": info.get("keyspace_misses", 0),
            },
        }
    except Exception as e:
        return {"error": str(e), "cache_available": False}


# 개발용 테스트 엔드포인트 (디버그 모드에서만)
if IS_DEBUG:
    app.add_api_route(
        "/debug/test-workflow",
        debug_test_workflow,
        methods=["GET"],
    )
    app.add_api_route(
        "/debug/cache-stats",
        debug_cache_stats,
        methods=["GET"],
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8518,
        log_level=settings.LOG_LEVEL.lower(),
        access_log=True
    )
