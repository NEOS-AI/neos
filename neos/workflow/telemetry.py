"""
OpenTelemetry 분산 추적 설정 모듈

이 모듈은 Neos Workflow System의 분산 추적을 위한 OpenTelemetry 설정을 제공합니다.
Jaeger를 백엔드로 사용하여 워크플로우 실행 추적, 성능 분석, 병목 지점 식별을 지원합니다.

주요 기능:
- OpenTelemetry 자동 계측 (FastAPI, SQLAlchemy, Redis, HTTP 클라이언트)
- Jaeger로 trace 데이터 전송
- 커스텀 span 생성 헬퍼 함수
- 워크플로우 노드 및 에이전트 실행 추적

사용법:
    # 애플리케이션 시작 시
    from neos.workflow.telemetry import setup_telemetry
    setup_telemetry()

    # 커스텀 span 생성
    from neos.workflow.telemetry import tracer
    with tracer.start_as_current_span("my_operation") as span:
        span.set_attribute("key", "value")
        # ... 작업 수행
"""

import logging
from typing import Optional
from contextlib import contextmanager

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.resources import Resource, SERVICE_NAME, SERVICE_VERSION, DEPLOYMENT_ENVIRONMENT
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.trace import Status, StatusCode, Span

from neos.config.settings import Settings

logger = logging.getLogger(__name__)

# 전역 tracer 인스턴스
tracer: Optional[trace.Tracer] = None
_telemetry_initialized = False


def setup_telemetry(settings: Optional[Settings] = None) -> Optional[trace.Tracer]:
    """
    OpenTelemetry 텔레메트리 설정 및 초기화

    Args:
        settings: Settings 인스턴스 (None이면 기본 설정 사용)

    Returns:
        trace.Tracer: 설정된 tracer 인스턴스 (비활성화 시 None)
    """
    global tracer, _telemetry_initialized

    if _telemetry_initialized:
        logger.warning("Telemetry already initialized, skipping...")
        return tracer

    if settings is None:
        settings = Settings()

    # OpenTelemetry 비활성화 시 early return
    if not settings.OTEL_ENABLED:
        logger.info("OpenTelemetry is disabled (OTEL_ENABLED=False)")
        _telemetry_initialized = True
        return None

    try:
        # Resource 정의 (서비스 메타데이터)
        resource = Resource.create({
            SERVICE_NAME: settings.OTEL_SERVICE_NAME,
            SERVICE_VERSION: settings.OTEL_SERVICE_VERSION,
            DEPLOYMENT_ENVIRONMENT: settings.OTEL_DEPLOYMENT_ENVIRONMENT,
        })

        # TracerProvider 생성
        tracer_provider = TracerProvider(resource=resource)

        # OTLP Exporter 설정 (Jaeger)
        otlp_exporter = OTLPSpanExporter(
            endpoint=settings.OTEL_EXPORTER_JAEGER_ENDPOINT,
            # timeout은 기본값(10초) 사용
        )

        # BatchSpanProcessor 설정 (성능 최적화)
        span_processor = BatchSpanProcessor(
            otlp_exporter,
            max_queue_size=settings.OTEL_BSP_MAX_QUEUE_SIZE,
            schedule_delay_millis=settings.OTEL_BSP_SCHEDULE_DELAY,
            max_export_batch_size=settings.OTEL_BSP_MAX_EXPORT_BATCH_SIZE,
        )

        tracer_provider.add_span_processor(span_processor)

        # Global TracerProvider 설정
        trace.set_tracer_provider(tracer_provider)

        # Tracer 인스턴스 생성
        tracer = trace.get_tracer(__name__)

        logger.info(
            f"OpenTelemetry initialized: service={settings.OTEL_SERVICE_NAME}, "
            f"environment={settings.OTEL_DEPLOYMENT_ENVIRONMENT}, "
            f"endpoint={settings.OTEL_EXPORTER_JAEGER_ENDPOINT}"
        )

        _telemetry_initialized = True
        return tracer

    except Exception as e:
        logger.error(f"Failed to initialize OpenTelemetry: {e}", exc_info=True)
        _telemetry_initialized = True
        return None


def instrument_app(app):
    """
    FastAPI 앱에 자동 계측 적용

    Args:
        app: FastAPI 애플리케이션 인스턴스
    """
    settings = Settings()

    if not settings.OTEL_ENABLED:
        return

    try:
        # FastAPI 자동 계측
        FastAPIInstrumentor.instrument_app(app)
        logger.info("FastAPI instrumentation enabled")

        # Redis 자동 계측 (연결 시점에 자동 적용)
        RedisInstrumentor().instrument()
        logger.info("Redis instrumentation enabled")

        # HTTPX (HTTP 클라이언트) 자동 계측
        HTTPXClientInstrumentor().instrument()
        logger.info("HTTPX instrumentation enabled")

    except Exception as e:
        logger.error(f"Failed to instrument app: {e}", exc_info=True)


def instrument_sqlalchemy_engine(engine):
    """
    SQLAlchemy 엔진에 자동 계측 적용

    Args:
        engine: SQLAlchemy 엔진 인스턴스
    """
    settings = Settings()

    if not settings.OTEL_ENABLED:
        return

    try:
        SQLAlchemyInstrumentor().instrument(
            engine=engine,
            enable_commenter=True,  # SQL 주석에 trace context 추가
        )
        logger.info("SQLAlchemy instrumentation enabled")

    except Exception as e:
        logger.error(f"Failed to instrument SQLAlchemy: {e}", exc_info=True)


@contextmanager
def trace_workflow_node(node_name: str, workflow_id: Optional[str] = None, **attributes):
    """
    워크플로우 노드 실행을 추적하는 컨텍스트 매니저

    Args:
        node_name: 노드 이름
        workflow_id: 워크플로우 ID (선택)
        **attributes: 추가 속성

    Example:
        with trace_workflow_node("query_classifier", workflow_id="abc123"):
            result = classify_query(query)
    """
    if tracer is None:
        yield None
        return

    with tracer.start_as_current_span(f"workflow.node.{node_name}") as span:
        span.set_attribute("workflow.node", node_name)
        if workflow_id:
            span.set_attribute("workflow.id", workflow_id)

        for key, value in attributes.items():
            span.set_attribute(key, value)

        try:
            yield span
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR))
            span.record_exception(e)
            raise


@contextmanager
def trace_agent_execution(
    agent_name: str,
    workflow_id: Optional[str] = None,
    **attributes
):
    """
    에이전트 실행을 추적하는 컨텍스트 매니저

    Args:
        agent_name: 에이전트 이름
        workflow_id: 워크플로우 ID (선택)
        **attributes: 추가 속성

    Example:
        with trace_agent_execution("search_agent", workflow_id="abc123"):
            result = await search_agent.execute(query)
    """
    if tracer is None:
        yield None
        return

    with tracer.start_as_current_span(f"agent.{agent_name}") as span:
        span.set_attribute("agent.name", agent_name)
        if workflow_id:
            span.set_attribute("workflow.id", workflow_id)

        for key, value in attributes.items():
            span.set_attribute(key, value)

        try:
            yield span
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR))
            span.record_exception(e)
            raise


@contextmanager
def trace_llm_call(
    model: str,
    provider: str,
    **attributes
):
    """
    LLM 호출을 추적하는 컨텍스트 매니저

    Args:
        model: 모델 이름 (예: gpt-4)
        provider: 제공자 이름 (예: openai)
        **attributes: 추가 속성 (prompt_tokens, completion_tokens 등)

    Example:
        with trace_llm_call("gpt-4", "openai", prompt_tokens=100):
            response = await llm.chat(messages)
    """
    if tracer is None:
        yield None
        return

    with tracer.start_as_current_span(f"llm.{provider}.{model}") as span:
        span.set_attribute("llm.model", model)
        span.set_attribute("llm.provider", provider)

        for key, value in attributes.items():
            span.set_attribute(f"llm.{key}", value)

        try:
            yield span
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR))
            span.record_exception(e)
            raise


@contextmanager
def trace_cache_access(
    operation: str,
    cache_type: str,
    **attributes
):
    """
    캐시 접근을 추적하는 컨텍스트 매니저

    Args:
        operation: 작업 타입 (get, set, delete 등)
        cache_type: 캐시 타입 (redis, smart_cache 등)
        **attributes: 추가 속성 (hit, miss, key 등)

    Example:
        with trace_cache_access("get", "smart_cache", key="query:abc"):
            cached_value = await cache.get(key)
    """
    if tracer is None:
        yield None
        return

    with tracer.start_as_current_span(f"cache.{operation}") as span:
        span.set_attribute("cache.operation", operation)
        span.set_attribute("cache.type", cache_type)

        for key, value in attributes.items():
            span.set_attribute(f"cache.{key}", value)

        try:
            yield span
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR))
            span.record_exception(e)
            raise


def add_span_event(span: Optional[Span], name: str, attributes: dict = None):
    """
    현재 span에 이벤트 추가

    Args:
        span: Span 인스턴스 (None이면 무시)
        name: 이벤트 이름
        attributes: 이벤트 속성
    """
    if span is None:
        return

    if attributes:
        span.add_event(name, attributes=attributes)
    else:
        span.add_event(name)


def set_span_attributes(span: Optional[Span], attributes: dict):
    """
    현재 span에 여러 속성 설정

    Args:
        span: Span 인스턴스 (None이면 무시)
        attributes: 속성 딕셔너리
    """
    if span is None:
        return

    for key, value in attributes.items():
        span.set_attribute(key, value)


def shutdown_telemetry():
    """
    텔레메트리 정리 및 종료

    애플리케이션 종료 시 호출하여 남은 trace 데이터를 전송합니다.
    """
    global _telemetry_initialized

    if not _telemetry_initialized:
        return

    try:
        tracer_provider = trace.get_tracer_provider()
        if hasattr(tracer_provider, 'shutdown'):
            tracer_provider.shutdown()
            logger.info("OpenTelemetry shutdown complete")
    except Exception as e:
        logger.error(f"Error during telemetry shutdown: {e}", exc_info=True)


# 애플리케이션 종료 시 자동 정리를 위한 atexit 등록
import atexit
atexit.register(shutdown_telemetry)
