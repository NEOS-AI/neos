from datetime import UTC, datetime

from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy.exc import SQLAlchemyError

from neos.coding.application.run_service import (
    CodingRunService,
    InProcessRunInterrupter,
)
from neos.coding.loop.fake import FakeDurableCodingLoop
from neos.coding.persistence.postgres import PostgresCodingService
from neos.coding.repositories.run_repository import (
    PostgresCodingRunRepository,
)
from neos.coding.repositories.task_repository import CodingTaskRepository
from neos.coding.workers.execution import (
    CodingTaskOutcome,
    CodingTaskRunner,
)
from neos.database.connection import DatabaseManager
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


async def run_coding_delivery(
    *,
    task_id: str,
    worker_id: str,
    database_manager: DatabaseManager | None = None,
) -> CodingTaskOutcome:
    manager = database_manager or DatabaseManager()
    try:
        await manager.initialize()
        return await _build_runner(manager).run(
            task_id=task_id,
            worker_id=worker_id,
            failure_error_code="worker_retry_exhausted",
        )
    finally:
        await manager.close()


async def discover_coding_tasks(
    *,
    limit: int,
    database_manager: DatabaseManager | None = None,
) -> tuple[str, ...]:
    manager = database_manager or DatabaseManager()
    try:
        await manager.initialize()
        repository = _build_run_repository(manager)
        return tuple(await repository.claimable_task_ids(limit=limit))
    finally:
        await manager.close()
