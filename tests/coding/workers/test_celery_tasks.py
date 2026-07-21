import pytest

from neos.coding.workers import celery_tasks
from neos.coding.workers.execution import CodingTaskOutcome
from neos.workflow.celery_app import app, configure_coding_beat_schedule


class RecordingMetric:
    def __init__(self, records, name, labels=None) -> None:
        self.records = records
        self.name = name
        self.bound_labels = labels or {}

    def labels(self, **labels):
        return RecordingMetric(self.records, self.name, labels)

    def inc(self, amount=1) -> None:
        self.records.append((self.name, "inc", self.bound_labels, amount))

    def dec(self, amount=1) -> None:
        self.records.append((self.name, "dec", self.bound_labels, amount))


class RecordingMetrics:
    def __init__(self) -> None:
        self.records = []
        self.coding_worker_tasks_total = RecordingMetric(self.records, "worker_tasks")
        self.coding_worker_retry_total = RecordingMetric(self.records, "worker_retry")
        self.coding_worker_active_tasks = RecordingMetric(self.records, "worker_active")
        self.coding_reconciliation_tasks_total = RecordingMetric(
            self.records, "reconciliation"
        )


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

    result = celery_tasks.execute_coding_task.run("ct_1", None)

    assert result == {"task_id": "ct_1", "outcome": "completed"}


def test_nonterminal_delivery_enqueues_exactly_one_continuation(monkeypatch) -> None:
    calls = []

    async def run(**kwargs):
        return CodingTaskOutcome.CONTINUING

    async def current(**kwargs):
        return "cc_next"

    class RecordingDispatcher:
        def __init__(self, **kwargs):
            pass

        def enqueue(self, task_id, *, expected_checkpoint_id, source):
            calls.append((task_id, expected_checkpoint_id, source.value))
            return "next-delivery"

    monkeypatch.setattr(celery_tasks, "run_coding_delivery", run)
    monkeypatch.setattr(celery_tasks, "current_coding_checkpoint_id", current)
    monkeypatch.setattr(celery_tasks, "CeleryCodingTaskDispatcher", RecordingDispatcher)

    result = celery_tasks.execute_coding_task.run("ct_1", None)

    assert result == {"task_id": "ct_1", "outcome": "continuing"}
    assert calls == [("ct_1", "cc_next", "continuation")]


def test_stale_delivery_does_not_enqueue_successor(monkeypatch) -> None:
    calls = []

    async def run(**kwargs):
        return CodingTaskOutcome.LEASE_BUSY

    class RecordingDispatcher:
        def __init__(self, **kwargs):
            pass

        def enqueue(self, *args, **kwargs):
            calls.append((args, kwargs))

    monkeypatch.setattr(celery_tasks, "run_coding_delivery", run)
    monkeypatch.setattr(celery_tasks, "CeleryCodingTaskDispatcher", RecordingDispatcher)

    result = celery_tasks.execute_coding_task.run("ct_1", "cc_stale")

    assert result == {"task_id": "ct_1", "outcome": "lease_busy"}
    assert calls == []


def test_waiting_approval_does_not_enqueue_successor(monkeypatch) -> None:
    calls = []

    async def run(**kwargs):
        return CodingTaskOutcome.WAITING_APPROVAL

    class RecordingDispatcher:
        def __init__(self, **kwargs):
            pass

        def enqueue(self, *args, **kwargs):
            calls.append((args, kwargs))

    monkeypatch.setattr(celery_tasks, "run_coding_delivery", run)
    monkeypatch.setattr(celery_tasks, "CeleryCodingTaskDispatcher", RecordingDispatcher)

    result = celery_tasks.execute_coding_task.run("ct_1", "cc_approval")

    assert result == {"task_id": "ct_1", "outcome": "waiting_approval"}
    assert calls == []


def test_ambiguous_continuation_publish_does_not_retry_advancement(
    monkeypatch,
) -> None:
    run_calls = []

    async def run(**kwargs):
        run_calls.append(kwargs)
        return CodingTaskOutcome.CONTINUING

    async def current(**kwargs):
        return "cc_next"

    class AmbiguousDispatcher:
        def __init__(self, **kwargs):
            pass

        def enqueue(self, *args, **kwargs):
            raise ConnectionError("published then connection dropped")

    monkeypatch.setattr(celery_tasks, "run_coding_delivery", run)
    monkeypatch.setattr(celery_tasks, "current_coding_checkpoint_id", current)
    monkeypatch.setattr(celery_tasks, "CeleryCodingTaskDispatcher", AmbiguousDispatcher)

    result = celery_tasks.execute_coding_task.run("ct_1", None)

    assert result == {"task_id": "ct_1", "outcome": "continuing"}
    assert len(run_calls) == 1


def test_execute_task_records_active_and_bounded_outcome_metrics(
    monkeypatch,
) -> None:
    recording = RecordingMetrics()

    async def run(**kwargs):
        return CodingTaskOutcome.COMPLETED

    monkeypatch.setattr(celery_tasks, "run_coding_delivery", run)
    monkeypatch.setattr(celery_tasks, "metrics", recording)

    celery_tasks.execute_coding_task.run("ct_secret", None)

    assert recording.records == [
        ("worker_active", "inc", {}, 1),
        ("worker_tasks", "inc", {"outcome": "completed"}, 1),
        ("worker_active", "dec", {}, 1),
    ]
    assert all("ct_secret" not in str(record) for record in recording.records)


def test_execute_task_retries_infrastructure_failure_after_five_seconds(
    monkeypatch,
) -> None:
    class RetryRequested(Exception):
        pass

    recording = RecordingMetrics()

    async def fail(**kwargs):
        raise ConnectionError("database unavailable")

    def retry(*, exc, countdown):
        assert isinstance(exc, ConnectionError)
        assert countdown == 5
        raise RetryRequested

    monkeypatch.setattr(celery_tasks, "run_coding_delivery", fail)
    monkeypatch.setattr(celery_tasks.execute_coding_task, "retry", retry)
    monkeypatch.setattr(celery_tasks, "metrics", recording)

    with pytest.raises(RetryRequested):
        celery_tasks.execute_coding_task.run("ct_1", None)

    assert (
        "worker_retry",
        "inc",
        {"reason": "infrastructure"},
        1,
    ) in recording.records
    assert recording.records[-1] == ("worker_active", "dec", {}, 1)


def test_reconciliation_enqueues_each_discovered_task_and_counts_failures(
    monkeypatch,
) -> None:
    calls = []
    recording = RecordingMetrics()

    async def discover(**kwargs):
        return (("ct_1", None), ("ct_2", "cc_2"))

    class RecordingDispatcher:
        def __init__(self, **kwargs):
            pass

        def enqueue(self, task_id, *, expected_checkpoint_id, source):
            calls.append((task_id, expected_checkpoint_id, source.value))
            if task_id == "ct_2":
                raise ConnectionError("broker unavailable")
            return f"delivery-{task_id}"

    monkeypatch.setattr(celery_tasks, "discover_coding_tasks", discover)
    monkeypatch.setattr(celery_tasks, "CeleryCodingTaskDispatcher", RecordingDispatcher)
    monkeypatch.setattr(celery_tasks, "metrics", recording)

    result = celery_tasks.reconcile_coding_tasks.run()

    assert calls == [
        ("ct_1", None, "reconciliation"),
        ("ct_2", "cc_2", "reconciliation"),
    ]
    assert result == {"discovered": 2, "enqueued": 1, "failed": 1}
    assert recording.records == [
        ("reconciliation", "inc", {"outcome": "discovered"}, 2),
        ("reconciliation", "inc", {"outcome": "enqueued"}, 1),
        ("reconciliation", "inc", {"outcome": "failed"}, 1),
    ]


def test_coding_tasks_are_routed_to_dedicated_queue() -> None:
    route = app.conf.task_routes["neos.coding.workers.celery_tasks.execute_coding_task"]
    assert route == {"queue": "coding"}
    assert "coding" in {queue.name for queue in app.conf.task_queues}


def test_coding_reconciliation_schedule_follows_feature_flag() -> None:
    schedule = {}

    configure_coding_beat_schedule(schedule, enabled=True, interval=7.5)
    assert schedule["reconcile-coding-tasks"] == {
        "task": "neos.coding.workers.celery_tasks.reconcile_coding_tasks",
        "schedule": 7.5,
    }

    configure_coding_beat_schedule(schedule, enabled=False, interval=7.5)
    assert "reconcile-coding-tasks" not in schedule
    assert "expire-coding-approvals" not in schedule
