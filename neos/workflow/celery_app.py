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

from neos.config.settings import get_settings


logger = logging.getLogger(__name__)
settings = get_settings()


def create_celery_app(candidate, *, name: str = "neos_workflow"):
    created = Celery(
        name,
        broker=candidate.CELERY_BROKER_URL,
        backend=candidate.CELERY_RESULT_BACKEND,
        include=[
            "neos.coding.workers.celery_tasks",
            "neos.tasks.gepa_opt_job_task",
        ],
    )
    created.conf.update(
        broker_url=candidate.CELERY_BROKER_URL,
        result_backend=candidate.CELERY_RESULT_BACKEND,
    )
    created.conf.broker_url = candidate.CELERY_BROKER_URL
    created.conf.result_backend = candidate.CELERY_RESULT_BACKEND
    return created


# Celery 앱 생성
app = create_celery_app(settings)

# Celery 설정
app.conf.update(
    broker_url=settings.CELERY_BROKER_URL,
    result_backend=settings.CELERY_RESULT_BACKEND,
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
        'neos.workflow.celery_tasks.execute_workflow_async': {'queue': 'search'},  # Phase 3.5
        'neos.coding.workers.celery_tasks.execute_coding_task': {
            'queue': settings.CODING_CELERY_QUEUE
        },
        # 관리형 샌드박스 컨트롤 플레인 — 처음에는 기존 coding 큐를 그대로
        # 쓴다(플랜 14 Task 6). 전용 큐는 실제 부하를 본 뒤에 가른다.
        'neos.coding.managed.allocate': {'queue': settings.CODING_CELERY_QUEUE},
        'neos.coding.managed.reconcile': {'queue': settings.CODING_CELERY_QUEUE},
        'neos.coding.managed.cleanup': {'queue': settings.CODING_CELERY_QUEUE},
        'neos.coding.managed.reconcile_quota': {
            'queue': settings.CODING_CELERY_QUEUE
        },
        'neos.coding.managed.probe_health': {
            'queue': settings.CODING_CELERY_QUEUE
        },
        'neos.tasks.run_gepa_opt_job': {'queue': 'gepa_opt'},
    },

    # 큐 정의 (우선순위 지원)
    task_queues=(
        Queue('default', Exchange('default'), routing_key='default', priority=5),
        Queue('search', Exchange('search'), routing_key='search', priority=8),
        Queue('analysis', Exchange('analysis'), routing_key='analysis', priority=7),
        Queue('generation', Exchange('generation'), routing_key='generation', priority=6),
        Queue(
            settings.CODING_CELERY_QUEUE,
            Exchange(settings.CODING_CELERY_QUEUE),
            routing_key=settings.CODING_CELERY_QUEUE,
        ),
        Queue('gepa_opt', Exchange('gepa_opt'), routing_key='gepa_opt'),
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
# Celery may reuse a named app during module reloads (worker boot tests and
# prefork initialization). Rebind transport settings from the current config.
app.conf.broker_url = settings.CELERY_BROKER_URL
app.conf.result_backend = settings.CELERY_RESULT_BACKEND


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

    # fork 후 부모 프로세스의 LLM 커넥션 풀을 상속하면 race condition 발생 가능
    # (httpx.AsyncClient 소켓 파일 디스크립터 공유 위험) — 캐시를 비워 새 커넥션 생성 강제
    from neos.utils.llm_factory import LLMFactory
    LLMFactory.clear_cache()
    logger.info("LLM cache cleared after fork")

    # import 시점 카탈로그 로드는 live overlay 를 동기화하지 않는다(순환 import).
    from neos.config.model_config import model_config
    from neos.config.model_discovery import sync_live_overlay

    sync_live_overlay(model_config.catalog)

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


def configure_coding_beat_schedule(
    schedule: dict, *, enabled: bool, interval: float
) -> None:
    if enabled:
        schedule["reconcile-coding-tasks"] = {
            "task": "neos.coding.workers.celery_tasks.reconcile_coding_tasks",
            "schedule": interval,
        }
        schedule["expire-coding-approvals"] = {
            "task": "neos.coding.workers.celery_tasks.expire_coding_approvals",
            "schedule": interval,
        }
    else:
        schedule.pop("reconcile-coding-tasks", None)
        schedule.pop("expire-coding-approvals", None)


_MANAGED_SANDBOX_BEAT_ENTRIES = (
    "reconcile-managed-sandboxes",
    "reconcile-managed-sandbox-quota",
    "probe-managed-sandbox-health",
)


def configure_managed_sandbox_beat_schedule(
    schedule: dict,
    *,
    enabled: bool,
    reconciliation_interval: float,
    health_interval: float,
) -> None:
    """관리형 컨트롤 플레인의 beat 항목.

    `sandbox.managed.enabled` **하나**에만 묶는다 -- `global_kill_switch`는
    신규 admission 만 막는 스위치라서 여기 들어오면 안 된다. 킬 스위치를 켠
    동안에도 이미 만들어진 리소스의 정리·조정은 계속 돌아야 한다
    (`neos.coding.managed.workers.managed_control_plane_enabled` 참조).
    """
    if enabled:
        schedule["reconcile-managed-sandboxes"] = {
            "task": "neos.coding.managed.reconcile",
            "schedule": reconciliation_interval,
        }
        schedule["reconcile-managed-sandbox-quota"] = {
            "task": "neos.coding.managed.reconcile_quota",
            "schedule": reconciliation_interval,
        }
        schedule["probe-managed-sandbox-health"] = {
            "task": "neos.coding.managed.probe_health",
            "schedule": health_interval,
        }
    else:
        for entry in _MANAGED_SANDBOX_BEAT_ENTRIES:
            schedule.pop(entry, None)


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
    # Phase 4: Cron 스케줄 폴러 — DB에서 만기 태스크를 매 1분마다 조회·실행
    'poll-scheduled-tasks': {
        'task': 'neos.tasks.poll_scheduled_tasks',
        'schedule': 60.0,  # 1분
    },
    # Phase 8 (A2UI): 만료된 UIFrameSession 레코드 정리 — 매시간 정각
    'cleanup-expired-ui-frames': {
        'task': 'neos.tasks.cleanup_expired_ui_frames',
        'schedule': 3600.0,  # 1시간
    },
    # Task 6 (Approval): 만료된 pending_approvals 자동 거부 — 5분마다
    'expire-pending-approvals': {
        'task': 'neos.tasks.expire_pending_approvals',
        'schedule': 300.0,  # 5분
    },
    # L5 개선 루프: deep_analysis 이벤트 로그 → 롤링 개선 신호 리포트 — 매일 1회
    'compute-deep-analysis-report': {
        'task': 'neos.tasks.compute_deep_analysis_report',
        'schedule': 86400.0,  # 24시간
    },
    # Phase 4 learn: prune/archive staged lessons — daily. No LLM consolidate.
    'curate-learned-skills': {
        'task': 'neos.tasks.curate_learned_skills',
        'schedule': 86400.0,  # 24시간
    },
}

configure_coding_beat_schedule(
    app.conf.beat_schedule,
    enabled=settings.CODING_CELERY_ENABLED,
    interval=settings.CODING_CELERY_RECONCILIATION_SECONDS,
)

_managed_sandbox_config = settings.config.sandbox.managed
configure_managed_sandbox_beat_schedule(
    app.conf.beat_schedule,
    enabled=_managed_sandbox_config.enabled,
    reconciliation_interval=(
        _managed_sandbox_config.reconciliation_interval_seconds
    ),
    health_interval=_managed_sandbox_config.health_probe_interval_seconds,
)


if __name__ == '__main__':
    # 개발 모드: 워커 직접 실행
    # python -m neos.workflow.celery_app worker --loglevel=info
    app.start()
