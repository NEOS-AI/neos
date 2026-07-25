import ast
from inspect import getsource
from textwrap import dedent

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


def test_managed_sandbox_metric_labels_are_fixed_cardinality() -> None:
    collector = EnterpriseMetricsCollector(CollectorRegistry())
    allowed = {
        "provider",
        "region",
        "operation",
        "outcome",
        "reason",
        "error_code",
        "decision",
        "state",
    }
    managed_metrics = (
        collector.coding_sandbox_admission_total,
        collector.coding_sandbox_allocation_total,
        collector.coding_sandbox_allocation_duration_seconds,
        collector.coding_sandbox_provider_circuit,
        collector.coding_sandbox_cleanup_age_seconds,
        collector.coding_sandbox_cleanup_total,
        collector.coding_sandbox_archive_total,
    )

    parsed = ast.parse(dedent(getsource(EnterpriseMetricsCollector)))
    managed_names = {metric._name for metric in managed_metrics}
    source_labels = {
        target.attr: {item.value for item in value.args[2].elts}
        for node in ast.walk(parsed)
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Attribute)
        and target.attr in managed_names
        if isinstance(value := node.value, ast.Call)
        and isinstance(value.args[2], ast.List)
        and all(isinstance(item, ast.Constant) for item in value.args[2].elts)
    }

    assert all(set(metric._labelnames).issubset(allowed) for metric in managed_metrics)
    assert source_labels and all(labels.issubset(allowed) for labels in source_labels.values())
    assert collector.coding_sandbox_admission_total._labelnames == (
        "decision",
        "reason",
    )
    assert collector.coding_sandbox_allocation_total._labelnames == (
        "provider",
        "region",
        "outcome",
        "error_code",
    )
    assert collector.coding_sandbox_allocation_duration_seconds._labelnames == (
        "provider",
        "region",
        "outcome",
    )
    assert collector.coding_sandbox_provider_circuit._labelnames == (
        "provider",
        "region",
        "state",
    )
    assert collector.coding_sandbox_cleanup_age_seconds._labelnames == (
        "provider",
        "region",
    )
    assert collector.coding_sandbox_cleanup_total._labelnames == (
        "provider",
        "region",
        "outcome",
        "error_code",
    )
    assert collector.coding_sandbox_archive_total._labelnames == (
        "provider",
        "operation",
        "outcome",
        "error_code",
    )


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
