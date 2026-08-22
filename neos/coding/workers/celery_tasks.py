import asyncio
import logging
from uuid import uuid4

from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy.exc import SQLAlchemyError

from neos.coding.managed.workers import (
    ALLOCATE_TASK,
    CLEANUP_TASK,
    PROBE_HEALTH_TASK,
    RECONCILE_QUOTA_TASK,
    RECONCILE_TASK,
    advance_managed_allocation,
    clean_managed_allocation,
    probe_managed_sandbox_health,
    reconcile_managed_sandboxes,
    release_managed_sandbox_quota,
)
from neos.coding.workers.celery_runtime import (
    current_coding_checkpoint_id,
    discover_coding_tasks,
    expire_coding_approvals,
    run_coding_delivery,
)
from neos.coding.workers.execution import CodingTaskOutcome
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
def execute_coding_task(
    self, task_id: str, expected_checkpoint_id: str | None
) -> dict[str, str]:
    worker_id = f"celery-{self.request.id or uuid4().hex}"
    metrics.coding_worker_active_tasks.inc()
    try:
        outcome = asyncio.run(
            run_coding_delivery(
                task_id=task_id,
                worker_id=worker_id,
                expected_checkpoint_id=expected_checkpoint_id,
            )
        )
        metrics.coding_worker_tasks_total.labels(outcome=outcome.value).inc()
    except (
        ConnectionError,
        OSError,
        SQLAlchemyError,
        SoftTimeLimitExceeded,
    ) as exc:
        metrics.coding_worker_retry_total.labels(reason="infrastructure").inc()
        retry_index = min(self.request.retries, len(RETRY_DELAYS) - 1)
        raise self.retry(exc=exc, countdown=RETRY_DELAYS[retry_index])
    finally:
        metrics.coding_worker_active_tasks.dec()
    if outcome is CodingTaskOutcome.CONTINUING:
        next_checkpoint_id = asyncio.run(current_coding_checkpoint_id(task_id=task_id))
        try:
            CeleryCodingTaskDispatcher(
                app=app,
                queue=settings.CODING_CELERY_QUEUE,
                metrics=metrics,
            ).enqueue(
                task_id,
                expected_checkpoint_id=next_checkpoint_id,
                source=CodingDispatchSource.CONTINUATION,
            )
        except Exception:
            # send_task may publish and then raise. Retrying this delivery
            # would re-run advancement; reconciliation safely republishes the
            # current durable generation if no message reached the broker.
            logger.exception(
                "Coding continuation dispatch uncertain",
                extra={"task_id": task_id},
            )
    return {"task_id": task_id, "outcome": outcome.value}


@app.task(
    name="neos.coding.workers.celery_tasks.reconcile_coding_tasks",
    ignore_result=True,
)
def reconcile_coding_tasks() -> dict[str, int]:
    task_ids = asyncio.run(
        discover_coding_tasks(limit=settings.CODING_CELERY_DISCOVERY_BATCH_SIZE)
    )
    dispatcher = CeleryCodingTaskDispatcher(
        app=app,
        queue=settings.CODING_CELERY_QUEUE,
        metrics=metrics,
    )
    enqueued = 0
    failed = 0
    for task_id, expected_checkpoint_id in task_ids:
        try:
            dispatcher.enqueue(
                task_id,
                expected_checkpoint_id=expected_checkpoint_id,
                source=CodingDispatchSource.RECONCILIATION,
            )
            enqueued += 1
        except Exception:
            failed += 1
            logger.exception(
                "Coding reconciliation dispatch failed",
                extra={"task_id": task_id},
            )
    metrics.coding_reconciliation_tasks_total.labels(outcome="discovered").inc(
        len(task_ids)
    )
    metrics.coding_reconciliation_tasks_total.labels(outcome="enqueued").inc(enqueued)
    metrics.coding_reconciliation_tasks_total.labels(outcome="failed").inc(failed)
    return {
        "discovered": len(task_ids),
        "enqueued": enqueued,
        "failed": failed,
    }


@app.task(
    name="neos.coding.workers.celery_tasks.expire_coding_approvals",
    ignore_result=True,
)
def expire_coding_approval_requests() -> dict[str, int]:
    count = asyncio.run(
        expire_coding_approvals(
            limit=settings.config.coding_model.approval_reconciliation_batch_size
        )
    )
    return {"expired": count}


# --- 관리형 샌드박스 컨트롤 플레인 (플랜 14 Task 6) -----------------------
#
# 리턴값은 결과 백엔드에 저장된다 -- 그래서 **식별자와 상태 이름 말고는 아무것도
# 싣지 않는다.** provider 참조·raw 에러·저장소 URL 이 여기 실리면 브로커가
# 그것을 영구 보존한다 (플랜 Global Constraints).
#
# 재시도를 Celery 에 맡기지 않는다(`max_retries` 없음): 정리 재시도는
# `cleanup_retry_backoff_seconds` 수열과 `coding_sandbox_cleanup_attempts`
# 원장이 소유하고, 조정 주기가 밀린 후보를 다시 발행한다. Celery 재시도를
# 겹치면 같은 할당에 대해 두 개의 백오프가 동시에 돈다.


@app.task(
    bind=True,
    name=ALLOCATE_TASK,
    acks_late=True,
    reject_on_worker_lost=True,
    ignore_result=False,
)
def advance_managed_sandbox(
    self, allocation_id: str, expected_generation: int | None = None
) -> dict[str, str]:
    allocation = asyncio.run(
        advance_managed_allocation(
            allocation_id=allocation_id,
            worker_id=f"celery-{self.request.id or uuid4().hex}",
            expected_generation=expected_generation,
        )
    )
    return {
        "allocation_id": allocation.allocation_id,
        "state": allocation.state.value,
    }


@app.task(
    bind=True,
    name=CLEANUP_TASK,
    acks_late=True,
    reject_on_worker_lost=True,
    ignore_result=False,
)
def clean_managed_sandbox(
    self, allocation_id: str, expected_generation: int | None = None
) -> dict[str, str | None]:
    outcome = asyncio.run(
        clean_managed_allocation(
            allocation_id=allocation_id,
            worker_id=f"celery-{self.request.id or uuid4().hex}",
            expected_generation=expected_generation,
        )
    )
    return {
        "allocation_id": outcome.allocation_id,
        "state": outcome.state.value,
        "error_code": (
            outcome.error_code.value if outcome.error_code is not None else None
        ),
    }


@app.task(name=RECONCILE_TASK, ignore_result=True)
def reconcile_managed_sandbox_lifecycle() -> dict[str, int]:
    return asyncio.run(reconcile_managed_sandboxes())


@app.task(name=RECONCILE_QUOTA_TASK, ignore_result=True)
def reconcile_managed_sandbox_quota() -> dict[str, int]:
    released = asyncio.run(release_managed_sandbox_quota())
    return {"released": len(released)}


@app.task(name=PROBE_HEALTH_TASK, ignore_result=True)
def probe_managed_sandbox_providers() -> dict[str, int]:
    return {"probed": len(asyncio.run(probe_managed_sandbox_health()))}
