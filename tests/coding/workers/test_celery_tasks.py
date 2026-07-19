import pytest

from neos.coding.workers import celery_tasks
from neos.coding.workers.execution import CodingTaskOutcome
from neos.workflow.celery_app import app, configure_coding_beat_schedule


def test_execute_task_is_registered_with_coding_limits() -> None:
    assert celery_tasks.execute_coding_task.name == (
        "neos.coding.workers.celery_tasks.execute_coding_task"
    )
    assert celery_tasks.execute_coding_task.acks_late is True
    assert celery_tasks.execute_coding_task.reject_on_worker_lost is True


def test_execute_task_returns_only_bounded_identity_and_outcome(
    monkeypatch,
) -> None:
    async def run(**kwargs):
        return CodingTaskOutcome.COMPLETED

    monkeypatch.setattr(celery_tasks, "run_coding_delivery", run)

    result = celery_tasks.execute_coding_task.run("ct_1")

    assert result == {"task_id": "ct_1", "outcome": "completed"}


def test_execute_task_retries_infrastructure_failure_after_five_seconds(
    monkeypatch,
) -> None:
    class RetryRequested(Exception):
        pass

    async def fail(**kwargs):
        raise ConnectionError("database unavailable")

    def retry(*, exc, countdown):
        assert isinstance(exc, ConnectionError)
        assert countdown == 5
        raise RetryRequested

    monkeypatch.setattr(celery_tasks, "run_coding_delivery", fail)
    monkeypatch.setattr(celery_tasks.execute_coding_task, "retry", retry)

    with pytest.raises(RetryRequested):
        celery_tasks.execute_coding_task.run("ct_1")


def test_reconciliation_enqueues_each_discovered_task_and_counts_failures(
    monkeypatch,
) -> None:
    calls = []

    async def discover(**kwargs):
        return ("ct_1", "ct_2")

    class RecordingDispatcher:
        def __init__(self, **kwargs):
            pass

        def enqueue(self, task_id, *, source):
            calls.append((task_id, source.value))
            if task_id == "ct_2":
                raise ConnectionError("broker unavailable")
            return f"delivery-{task_id}"

    monkeypatch.setattr(celery_tasks, "discover_coding_tasks", discover)
    monkeypatch.setattr(
        celery_tasks, "CeleryCodingTaskDispatcher", RecordingDispatcher
    )

    result = celery_tasks.reconcile_coding_tasks.run()

    assert calls == [
        ("ct_1", "reconciliation"),
        ("ct_2", "reconciliation"),
    ]
    assert result == {"discovered": 2, "enqueued": 1, "failed": 1}


def test_coding_tasks_are_routed_to_dedicated_queue() -> None:
    route = app.conf.task_routes[
        "neos.coding.workers.celery_tasks.execute_coding_task"
    ]
    assert route == {"queue": "coding"}
    assert "coding" in {queue.name for queue in app.conf.task_queues}


def test_coding_reconciliation_schedule_follows_feature_flag() -> None:
    schedule = {}

    configure_coding_beat_schedule(
        schedule, enabled=True, interval=7.5
    )
    assert schedule["reconcile-coding-tasks"] == {
        "task": "neos.coding.workers.celery_tasks.reconcile_coding_tasks",
        "schedule": 7.5,
    }

    configure_coding_beat_schedule(
        schedule, enabled=False, interval=7.5
    )
    assert "reconcile-coding-tasks" not in schedule
