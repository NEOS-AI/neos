"""
Celery 앱 설정 - 분산 에이전트 실행

Phase 3 Item 4: Celery 분산 실행
- 에이전트를 여러 워커에 분산하여 수평 확장
- 우선순위 큐 지원
- 장애 복구 (Late Ack)
"""

from celery import Celery
from celery.signals import worker_process_init, worker_process_shutdown
from kombu import Queue, Exchange
import logging

from neos.config.settings import settings


logger = logging.getLogger(__name__)

# Celery 앱 생성
app = Celery(
    'neos_workflow',
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND
)

# Celery 설정
app.conf.update(
    # 직렬화
    task_serializer=settings.CELERY_TASK_SERIALIZER,
    result_serializer=settings.CELERY_RESULT_SERIALIZER,
    accept_content=settings.CELERY_ACCEPT_CONTENT,

    # 타임존
    timezone=settings.CELERY_TIMEZONE,
    enable_utc=True,

    # 성능 최적화
    worker_prefetch_multiplier=settings.CELERY_WORKER_PREFETCH_MULTIPLIER,
    task_acks_late=settings.CELERY_TASK_ACKS_LATE,

    # 결과 저장
    result_expires=3600,  # 1시간 후 결과 삭제
    result_backend_transport_options={'master_name': 'mymaster'},

    # 라우팅 (우선순위 큐)
    task_routes={
        'neos.workflow.celery_tasks.execute_search_agent': {'queue': 'search'},
        'neos.workflow.celery_tasks.execute_analysis_agent': {'queue': 'analysis'},
        'neos.workflow.celery_tasks.execute_generation_agent': {'queue': 'generation'},
        'neos.workflow.celery_tasks.execute_agent_generic': {'queue': 'default'},
    },

    # 큐 정의 (우선순위 지원)
    task_queues=(
        Queue('default', Exchange('default'), routing_key='default', priority=5),
        Queue('search', Exchange('search'), routing_key='search', priority=8),
        Queue('analysis', Exchange('analysis'), routing_key='analysis', priority=7),
        Queue('generation', Exchange('generation'), routing_key='generation', priority=6),
    ),

    # 재시도 설정
    task_reject_on_worker_lost=True,
    task_default_retry_delay=30,  # 30초 후 재시도
    task_max_retries=3,

    # 타임아웃
    task_soft_time_limit=300,  # 5분 soft limit
    task_time_limit=360,  # 6분 hard limit

    # OpenTelemetry 통합 (Phase 3)
    task_send_sent_event=True,  # 태스크 전송 이벤트
)


@worker_process_init.connect
def init_worker(**kwargs):
    """
    워커 프로세스 초기화

    각 워커가 시작될 때 실행되어 필요한 리소스를 초기화합니다.
    """
    logger.info("Celery worker process initializing...")

    # OpenTelemetry 초기화
    if settings.OTEL_ENABLED:
        from neos.workflow.telemetry import setup_telemetry
        setup_telemetry(settings)
        logger.info("OpenTelemetry initialized in worker")

    # 데이터베이스 연결은 각 태스크에서 on-demand로 생성
    # (프로세스별 커넥션 풀 관리를 위해)

    logger.info("Celery worker ready")


@worker_process_shutdown.connect
def shutdown_worker(**kwargs):
    """
    워커 프로세스 종료

    워커 종료 시 리소스를 정리합니다.
    """
    logger.info("Celery worker shutting down...")

    # OpenTelemetry 정리
    if settings.OTEL_ENABLED:
        from neos.workflow.telemetry import shutdown_telemetry
        shutdown_telemetry()

    logger.info("Celery worker shutdown complete")


# Celery Beat 스케줄 (주기적 태스크)
app.conf.beat_schedule = {
    # 예: 매일 자정에 오래된 체크포인트 정리
    'cleanup-old-checkpoints': {
        'task': 'neos.workflow.celery_tasks.cleanup_old_checkpoints',
        'schedule': 86400.0,  # 24시간
    },
    # 예: 10분마다 캐시 통계 업데이트
    'update-cache-stats': {
        'task': 'neos.workflow.celery_tasks.update_cache_statistics',
        'schedule': 600.0,  # 10분
    },
}


if __name__ == '__main__':
    # 개발 모드: 워커 직접 실행
    # python -m neos.workflow.celery_app worker --loglevel=info
    app.start()
