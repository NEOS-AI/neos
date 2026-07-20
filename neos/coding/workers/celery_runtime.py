from datetime import UTC, datetime, timedelta

from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy.exc import SQLAlchemyError

from neos.coding.application.run_service import (
    CodingRunService,
    InProcessRunInterrupter,
)
from neos.coding.application.approval_service import CodingApprovalService
from neos.coding.workers.dispatcher import CodingDispatchSource
from neos.coding.loop.fake import FakeDurableCodingLoop
from neos.coding.persistence.postgres import PostgresCodingService
from neos.coding.repositories.run_repository import (
    PostgresCodingRunRepository,
)
from neos.coding.repositories.projection_repository import (
    PostgresCodingProjectionRepository,
)
from neos.coding.repositories.task_repository import CodingTaskRepository
from neos.coding.sandbox.observability import LoggingCodingAuditSink
from neos.coding.workers.execution import (
    CodingTaskOutcome,
    CodingTaskRunner,
)
from neos.database.connection import DatabaseManager
from neos.config.settings import settings
from neos.observability.metrics import metrics


def _build_run_repository(manager: DatabaseManager):
    return PostgresCodingRunRepository(manager.get_session)


def _build_runner(manager: DatabaseManager) -> CodingTaskRunner:
    repository = _build_run_repository(manager)
    runs = CodingRunService(
        tasks=CodingTaskRepository(manager),
        runs=repository,
        events=PostgresCodingService(manager.get_session),
        loop=FakeDurableCodingLoop(clock=lambda: datetime.now(UTC)),
        metrics=metrics,
        interrupter=InProcessRunInterrupter(),
        execution_lease=timedelta(seconds=settings.CODING_EXECUTION_LEASE_SECONDS),
    )
    return CodingTaskRunner(
        runs=runs,
        propagate_exceptions=(
            ConnectionError,
            OSError,
            SQLAlchemyError,
            SoftTimeLimitExceeded,
        ),
    )


def _build_approval_service(manager: DatabaseManager) -> CodingApprovalService:
    async def wake(task_id: str, checkpoint_id: str) -> None:
        from neos.coding.runtime import create_celery_dispatcher

        create_celery_dispatcher().enqueue(
            task_id,
            expected_checkpoint_id=checkpoint_id,
            source=CodingDispatchSource.APPROVAL,
        )

    return CodingApprovalService(
        _build_run_repository(manager),
        wake=wake,
        metrics=metrics,
        audit=LoggingCodingAuditSink(),
    )


async def expire_coding_approvals(
    *, limit: int, database_manager: DatabaseManager | None = None
) -> int:
    manager = database_manager or DatabaseManager()
    try:
        await manager.initialize()
        commits = await _build_approval_service(manager).expire_pending(limit=limit)
        return len(commits)
    finally:
        await manager.close()


def validate_coding_worker_settings(candidate) -> None:
    positive = {
        "CODING_CELERY_RECONCILIATION_SECONDS": (
            candidate.CODING_CELERY_RECONCILIATION_SECONDS
        ),
        "CODING_CELERY_DISCOVERY_BATCH_SIZE": (
            candidate.CODING_CELERY_DISCOVERY_BATCH_SIZE
        ),
        "CODING_CELERY_SOFT_TIME_LIMIT_SECONDS": (
            candidate.CODING_CELERY_SOFT_TIME_LIMIT_SECONDS
        ),
        "CODING_CELERY_HARD_TIME_LIMIT_SECONDS": (
            candidate.CODING_CELERY_HARD_TIME_LIMIT_SECONDS
        ),
        "CODING_EXECUTION_LEASE_SECONDS": (candidate.CODING_EXECUTION_LEASE_SECONDS),
    }
    for name, value in positive.items():
        if value <= 0:
            raise ValueError(f"{name} must be positive")
    if not candidate.CODING_CELERY_QUEUE.strip():
        raise ValueError("CODING_CELERY_QUEUE cannot be empty")
    if (
        candidate.CODING_CELERY_HARD_TIME_LIMIT_SECONDS
        <= candidate.CODING_CELERY_SOFT_TIME_LIMIT_SECONDS
    ):
        raise ValueError("CODING_CELERY_HARD_TIME_LIMIT_SECONDS must exceed soft limit")


async def run_coding_delivery(
    *,
    task_id: str,
    worker_id: str,
    expected_checkpoint_id: str | None,
    database_manager: DatabaseManager | None = None,
) -> CodingTaskOutcome:
    manager = database_manager or DatabaseManager()
    runtime = None
    try:
        await manager.initialize()
        if settings.config.coding_model.enabled:
            # The real loop's provider is owned by a CodingRuntime so there is
            # exactly one shutdown path for sandbox resources.
            from neos.coding.runtime import create_coding_runtime
            from neos.coding.sandbox.factory import create_sandbox_provider

            provider = create_sandbox_provider(settings.config.sandbox)
            try:
                repository = _build_run_repository(manager)
                runtime = create_coding_runtime(
                    events=PostgresCodingService(manager.get_session),
                    tasks=CodingTaskRepository(manager),
                    run_repository=repository,
                    projection_repository=PostgresCodingProjectionRepository(
                        manager.get_session
                    ),
                    loop=_create_worker_real_loop(manager, provider),
                    metrics_collector=metrics,
                    sandboxes=provider,
                )
            except BaseException:
                await provider.close()
                raise
            runner = CodingTaskRunner(
                runs=runtime.runs,
                propagate_exceptions=(
                    ConnectionError,
                    OSError,
                    SQLAlchemyError,
                    SoftTimeLimitExceeded,
                ),
            )
        else:
            runner = _build_runner(manager)
        return await runner.run(
            task_id=task_id,
            worker_id=worker_id,
            failure_error_code="worker_retry_exhausted",
            expected_checkpoint_id=expected_checkpoint_id,
        )
    finally:
        if runtime is not None:
            await runtime.close()
        await manager.close()


def _create_worker_real_loop(manager: DatabaseManager, provider):
    from neos.coding.runtime import _create_real_coding_loop

    return _create_real_coding_loop(
        config=settings.config,
        sandboxes=provider,
        session_factory=manager.get_session,
    )


async def discover_coding_tasks(
    *,
    limit: int,
    database_manager: DatabaseManager | None = None,
) -> tuple[tuple[str, str | None], ...]:
    manager = database_manager or DatabaseManager()
    try:
        await manager.initialize()
        repository = _build_run_repository(manager)
        return tuple(await repository.claimable_delivery_tokens(limit=limit))
    finally:
        await manager.close()


async def current_coding_checkpoint_id(
    *,
    task_id: str,
    database_manager: DatabaseManager | None = None,
) -> str | None:
    manager = database_manager or DatabaseManager()
    try:
        await manager.initialize()
        checkpoint = await _build_run_repository(manager).latest_checkpoint(task_id)
        return checkpoint.checkpoint_id if checkpoint is not None else None
    finally:
        await manager.close()
