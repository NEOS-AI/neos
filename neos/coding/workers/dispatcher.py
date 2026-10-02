from enum import StrEnum
from typing import Any, Protocol


EXECUTE_CODING_TASK = "neos.coding.workers.celery_tasks.execute_coding_task"


class CodingDispatchSource(StrEnum):
    API = "api"
    RECONCILIATION = "reconciliation"
    CONTINUATION = "continuation"
    APPROVAL = "approval"
    #: Q10b -- a person resumed a paused task.
    RESUME = "resume"


class CodingTaskDispatcher(Protocol):
    def enqueue(
        self,
        task_id: str,
        *,
        expected_checkpoint_id: str | None,
        source: CodingDispatchSource,
    ) -> str: ...


class CeleryCodingTaskDispatcher:
    def __init__(self, *, app: Any, queue: str, metrics: Any | None = None) -> None:
        if not queue.strip():
            raise ValueError("coding Celery queue cannot be empty")
        self._app = app
        self._queue = queue
        self._metrics = metrics

    def enqueue(
        self,
        task_id: str,
        *,
        expected_checkpoint_id: str | None,
        source: CodingDispatchSource,
    ) -> str:
        try:
            result = self._app.send_task(
                EXECUTE_CODING_TASK,
                args=[task_id, expected_checkpoint_id],
                queue=self._queue,
            )
        except Exception:
            self._record(source, "failed")
            raise
        self._record(source, "enqueued")
        return str(result.id)

    def _record(self, source: CodingDispatchSource, outcome: str) -> None:
        metric = getattr(self._metrics, "coding_dispatch_total", None)
        if metric is not None:
            metric.labels(source=source.value, outcome=outcome).inc()
