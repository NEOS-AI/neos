from __future__ import annotations

import pytest
from prometheus_client import CollectorRegistry

from neos.observability.metrics import EnterpriseMetricsCollector
from neos.subagent.metrics import MetricsEventSink, record_subagent_event


pytestmark = pytest.mark.no_db


class _Inner:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    async def emit(self, event_type: str, payload) -> None:
        self.events.append((event_type, dict(payload)))


def _collector() -> EnterpriseMetricsCollector:
    return EnterpriseMetricsCollector(registry=CollectorRegistry())


def test_record_advance_labels_are_low_cardinality() -> None:
    metrics = _collector()
    record_subagent_event(
        metrics,
        "subagent.step",
        {
            "spec": "explore",
            "parent_kind": "coding",
            "step_kind": "continuing",
            "run_id": "sa_should_not_be_a_label",
        },
    )
    record_subagent_event(
        metrics,
        "subagent.completed",
        {
            "spec": "explore",
            "parent_kind": "coding",
            "provider": "anthropic",
            "input_tokens": 10,
            "output_tokens": 4,
            "cost_micros": 7,
        },
    )
    assert (
        metrics.subagent_advance_total.labels(
            spec="explore", parent_kind="coding", outcome="continuing"
        )._value.get()
        == 1
    )
    assert (
        metrics.subagent_tokens_total.labels(
            spec="explore", parent_kind="coding", direction="input"
        )._value.get()
        == 10
    )
    assert (
        metrics.subagent_cost_micros_total.labels(
            spec="explore", parent_kind="coding", provider="anthropic"
        )._value.get()
        == 7
    )


def test_cas_mismatch_is_counted() -> None:
    metrics = _collector()
    record_subagent_event(
        metrics,
        "subagent.cas_mismatch",
        {"parent_kind": "deep_analysis"},
    )
    assert (
        metrics.subagent_cas_mismatch_total.labels(
            parent_kind="deep_analysis"
        )._value.get()
        == 1
    )


@pytest.mark.asyncio
async def test_metrics_sink_forwards_and_records() -> None:
    inner = _Inner()
    metrics = _collector()
    sink = MetricsEventSink(inner, metrics)
    await sink.emit(
        "subagent.step",
        {"spec": "explore", "parent_kind": "coding", "step_kind": "completed"},
    )
    assert inner.events[0][0] == "subagent.step"
    assert (
        metrics.subagent_advance_total.labels(
            spec="explore", parent_kind="coding", outcome="completed"
        )._value.get()
        == 1
    )
