import json
from dataclasses import asdict

from prometheus_client import CollectorRegistry

from neos.coding.sandbox.observability import SandboxAuditEvent
from neos.observability.metrics import EnterpriseMetricsCollector


def test_sandbox_metrics_use_only_bounded_labels() -> None:
    collector = EnterpriseMetricsCollector(CollectorRegistry())

    assert collector.coding_sandbox_lifecycle_seconds._labelnames == (
        "provider",
        "operation",
        "outcome",
    )
    assert collector.coding_sandbox_stream_total._labelnames == (
        "stream",
        "outcome",
    )
    assert "sandbox_id" not in collector.coding_sandbox_active._labelnames


def test_audit_event_does_not_capture_contents_or_environment_values() -> None:
    event = SandboxAuditEvent.for_command(
        sandbox_id="sb_1",
        argv=("python", "secret.py", "--token=secret"),
        env={"TOKEN": "secret"},
        stdin_bytes=12,
        stdout_bytes=24,
        outcome="ok",
    )
    serialized = json.dumps(asdict(event))

    assert "secret" not in serialized
    assert event.executable_category == "python"
    assert event.environment_names == ("TOKEN",)
