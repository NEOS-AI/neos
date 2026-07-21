from prometheus_client import CollectorRegistry

from neos.observability.metrics import EnterpriseMetricsCollector
from tests.coding.test_durable_phase_vertical_slice import DurableCodingHarness


class RecordingMetric:
    def __init__(self, sink, name) -> None:
        self._sink = sink
        self._name = name
        self._labels = {}

    def labels(self, **labels):
        bound = RecordingMetric(self._sink, self._name)
        bound._labels = labels
        return bound

    def inc(self) -> None:
        self._sink.append((self._name, self._labels, "inc"))

    def observe(self, value) -> None:
        self._sink.append((self._name, self._labels, value))


class RecordingCodingMetrics:
    def __init__(self) -> None:
        self.records = []
        self.coding_phase_duration_seconds = RecordingMetric(
            self.records, "phase_duration"
        )
        self.coding_checkpoint_total = RecordingMetric(
            self.records, "checkpoint"
        )
        self.coding_steering_latency_seconds = RecordingMetric(
            self.records, "steering"
        )
        self.coding_resume_total = RecordingMetric(self.records, "resume")
        self.coding_lease_contention_total = RecordingMetric(
            self.records, "lease"
        )

    @property
    def resume_outcomes(self):
        return [
            labels["outcome"]
            for name, labels, _ in self.records
            if name == "resume"
        ]


def test_coding_metrics_expose_only_bounded_labels() -> None:
    collector = EnterpriseMetricsCollector(CollectorRegistry())

    assert collector.coding_phase_duration_seconds._labelnames == ("phase",)
    assert collector.coding_resume_total._labelnames == ("outcome",)
    assert collector.coding_lease_contention_total._labelnames == ("outcome",)
    assert collector.coding_approval_total._labelnames == ("risk", "outcome")
    assert collector.coding_approval_latency_seconds._labelnames == ("outcome",)


def test_supervisor_metrics_use_only_bounded_labels() -> None:
    collector = EnterpriseMetricsCollector(CollectorRegistry())

    assert collector.coding_supervisor_tasks_total._labelnames == ("outcome",)
    assert collector.coding_supervisor_retry_total._labelnames == ("reason",)
    assert collector.coding_supervisor_active_tasks._labelnames == ()


def test_celery_worker_metrics_use_only_bounded_labels() -> None:
    collector = EnterpriseMetricsCollector(CollectorRegistry())

    assert collector.coding_worker_tasks_total._labelnames == ("outcome",)
    assert collector.coding_worker_retry_total._labelnames == ("reason",)
    assert collector.coding_worker_active_tasks._labelnames == ()
    assert collector.coding_dispatch_total._labelnames == (
        "source",
        "outcome",
    )
    assert collector.coding_reconciliation_tasks_total._labelnames == (
        "outcome",
    )


async def test_normal_safe_point_continuation_is_not_counted_as_resume() -> None:
    metrics = RecordingCodingMetrics()
    harness = DurableCodingHarness(metrics=metrics)
    task = await harness.create_task(owner_id="u1", prompt="Fix it")

    await harness.advance_one_safe_point(task.task_id, worker_id="worker-a")
    await harness.advance_one_safe_point(task.task_id, worker_id="worker-a")

    assert metrics.resume_outcomes == []
