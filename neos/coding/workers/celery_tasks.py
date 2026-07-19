import asyncio
import logging
from uuid import uuid4

from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy.exc import SQLAlchemyError

from neos.coding.workers.celery_runtime import (
    discover_coding_tasks,
    run_coding_delivery,
)
from neos.coding.workers.dispatcher import (
    CeleryCodingTaskDispatcher,
    CodingDispatchSource,
)
from neos.config.settings import settings
from neos.observability.metrics import metrics
from neos.workflow.celery_app import app


logger = logging.getLogger(__name__)
RETRY_DELAYS = (5, 15, 45)


@app.task(
    bind=True,
    name="neos.coding.workers.celery_tasks.execute_coding_task",
    acks_late=True,
    reject_on_worker_lost=True,
    max_retries=3,
    soft_time_limit=settings.CODING_CELERY_SOFT_TIME_LIMIT_SECONDS,
    time_limit=settings.CODING_CELERY_HARD_TIME_LIMIT_SECONDS,
    ignore_result=False,
)
def execute_coding_task(self, task_id: str) -> dict[str, str]:
    worker_id = f"celery-{self.request.id or uuid4().hex}"
    try:
        outcome = asyncio.run(
            run_coding_delivery(task_id=task_id, worker_id=worker_id)
        )
    except (
        ConnectionError,
        OSError,
        SQLAlchemyError,
        SoftTimeLimitExceeded,
    ) as exc:
        retry_index = min(self.request.retries, len(RETRY_DELAYS) - 1)
        raise self.retry(exc=exc, countdown=RETRY_DELAYS[retry_index])
    return {"task_id": task_id, "outcome": outcome.value}


@app.task(
    name="neos.coding.workers.celery_tasks.reconcile_coding_tasks",
    ignore_result=True,
)
def reconcile_coding_tasks() -> dict[str, int]:
    task_ids = asyncio.run(
        discover_coding_tasks(
            limit=settings.CODING_CELERY_DISCOVERY_BATCH_SIZE
        )
    )
    dispatcher = CeleryCodingTaskDispatcher(
        app=app,
        queue=settings.CODING_CELERY_QUEUE,
        metrics=metrics,
    )
    enqueued = 0
    failed = 0
    for task_id in task_ids:
        try:
            dispatcher.enqueue(
                task_id,
                source=CodingDispatchSource.RECONCILIATION,
            )
            enqueued += 1
        except Exception:
            failed += 1
            logger.exception(
                "Coding reconciliation dispatch failed",
                extra={"task_id": task_id},
            )
    return {
        "discovered": len(task_ids),
        "enqueued": enqueued,
        "failed": failed,
    }
