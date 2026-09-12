from __future__ import annotations

import pytest
from prometheus_client import CollectorRegistry

from neos.observability.metrics import EnterpriseMetricsCollector
from neos.subagent.metrics import (
    MetricsEventSink,
    record_fold_rollup,
    record_live_children,
    record_policy_capped,
    record_subagent_event,
)


pytestmark = pytest.mark.no_db


class _Inner:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    async def emit(self, event_type: str, payload) -> None:
        self.events.append((event_type, dict(payload)))


def _collector() -> EnterpriseMetricsCollector:
    return EnterpriseMetricsCollector(registry=CollectorRegistry())


def _histogram_samples(histogram, suffix: str, **labels) -> float:
    for metric in histogram.collect():
        for sample in metric.samples:
            if not sample.name.endswith(suffix):
                continue
            if all(sample.labels.get(key) == value for key, value in labels.items()):
                return sample.value
    return 0.0


def _histogram_count(histogram, **labels) -> float:
    return _histogram_samples(histogram, "_count", **labels)


def _histogram_sum(histogram, **labels) -> float:
    return _histogram_samples(histogram, "_sum", **labels)


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


def test_approach_m_metrics_use_only_bounded_labels() -> None:
    metrics = _collector()
    assert metrics.subagent_live_children._labelnames == ("parent_kind", "spec")
    assert metrics.subagent_policy_capped_total._labelnames == ("parent_kind",)
    assert metrics.subagent_fold_rollup_tokens_total._labelnames == (
        "parent_kind",
        "direction",
    )
    assert metrics.subagent_fold_rollup_cost_micros_total._labelnames == (
        "parent_kind",
        "provider",
    )
    assert "run_id" not in metrics.subagent_live_children._labelnames
    assert "task_id" not in metrics.subagent_fold_rollup_cost_micros_total._labelnames
    assert "model" not in metrics.subagent_fold_rollup_cost_micros_total._labelnames


def test_live_children_histogram_is_low_cardinality() -> None:
    metrics = _collector()
    record_live_children(
        metrics,
        parent_kind="coding",
        spec="explore",
        count=2,
    )
    record_live_children(
        metrics,
        parent_kind="not-a-parent",
        spec="invented-spec",
        count=1,
    )
    observed = metrics.subagent_live_children
    labels = {"parent_kind": "coding", "spec": "explore"}
    assert _histogram_count(observed, **labels) == 2
    assert _histogram_sum(observed, **labels) == 3.0


def test_policy_capped_is_counted() -> None:
    metrics = _collector()
    record_policy_capped(metrics, parent_kind="coding")
    record_policy_capped(metrics, parent_kind="deep_analysis")
    assert (
        metrics.subagent_policy_capped_total.labels(parent_kind="coding")._value.get()
        == 1
    )
    assert (
        metrics.subagent_policy_capped_total.labels(
            parent_kind="deep_analysis"
        )._value.get()
        == 1
    )


def test_fold_rollup_records_parent_priced_spend_not_child_cost_micros() -> None:
    metrics = _collector()
    record_fold_rollup(
        metrics,
        parent_kind="coding",
        provider="anthropic",
        input_tokens=2,
        output_tokens=3,
        cost_micros=5,
    )
    assert (
        metrics.subagent_fold_rollup_tokens_total.labels(
            parent_kind="coding", direction="input"
        )._value.get()
        == 2
    )
    assert (
        metrics.subagent_fold_rollup_tokens_total.labels(
            parent_kind="coding", direction="output"
        )._value.get()
        == 3
    )
    assert (
        metrics.subagent_fold_rollup_cost_micros_total.labels(
            parent_kind="coding", provider="anthropic"
        )._value.get()
        == 5
    )
    assert (
        metrics.subagent_cost_micros_total.labels(
            spec="explore", parent_kind="coding", provider="anthropic"
        )._value.get()
        == 0
    )


def test_step_payload_extras_do_not_observe_live_children_or_raise() -> None:
    metrics = _collector()
    record_subagent_event(
        metrics,
        "subagent.step",
        {
            "spec": "explore",
            "parent_kind": "coding",
            "step_kind": "continuing",
            "live_count": "not-a-number",
            "run_id": "sa_should_not_be_a_label",
            "transcript": "forbidden",
            "brief": "forbidden",
        },
    )
    labels = {"parent_kind": "coding", "spec": "explore"}
    assert _histogram_count(metrics.subagent_live_children, **labels) == 0
    assert _histogram_sum(metrics.subagent_live_children, **labels) == 0.0
    assert (
        metrics.subagent_advance_total.labels(
            spec="explore", parent_kind="coding", outcome="continuing"
        )._value.get()
        == 1
    )


def test_completed_remaps_invented_labels_and_ignores_extras() -> None:
    metrics = _collector()
    record_subagent_event(
        metrics,
        "subagent.completed",
        {
            "spec": "invented-spec",
            "parent_kind": "not-a-parent",
            "provider": "not-a-provider",
            "input_tokens": 2,
            "output_tokens": 3,
            "cost_micros": 4,
            "run_id": "sa_should_not_be_a_label",
            "transcript": "forbidden",
        },
    )
    assert (
        metrics.subagent_advance_total.labels(
            spec="explore", parent_kind="coding", outcome="completed"
        )._value.get()
        == 1
    )
    assert (
        metrics.subagent_tokens_total.labels(
            spec="explore", parent_kind="coding", direction="input"
        )._value.get()
        == 2
    )
    assert (
        metrics.subagent_cost_micros_total.labels(
            spec="explore", parent_kind="coding", provider="anthropic"
        )._value.get()
        == 4
    )


def test_duration_failed_cancelled_fold_and_policy_none() -> None:
    metrics = _collector()
    labels = {"spec": "explore", "parent_kind": "coding"}
    record_subagent_event(
        metrics,
        "subagent.step",
        {
            "spec": "explore",
            "parent_kind": "coding",
            "step_kind": "continuing",
            "duration_sec": 1.5,
        },
    )
    assert _histogram_count(metrics.subagent_advance_seconds, **labels) == 1
    assert _histogram_sum(metrics.subagent_advance_seconds, **labels) == 1.5
    record_subagent_event(
        metrics,
        "subagent.step",
        {
            "spec": "explore",
            "parent_kind": "coding",
            "step_kind": "continuing",
        },
    )
    assert _histogram_count(metrics.subagent_advance_seconds, **labels) == 1
    record_subagent_event(
        metrics,
        "subagent.failed",
        {"spec": "explore", "parent_kind": "coding"},
    )
    record_subagent_event(
        metrics,
        "subagent.cancelled",
        {"spec": "explore", "parent_kind": "coding"},
    )
    record_subagent_event(
        metrics,
        "subagent.fold",
        {"spec": "explore", "chars": 12},
    )
    assert (
        metrics.subagent_advance_total.labels(
            spec="explore", parent_kind="coding", outcome="failed"
        )._value.get()
        == 1
    )
    assert (
        metrics.subagent_advance_total.labels(
            spec="explore", parent_kind="coding", outcome="cancelled"
        )._value.get()
        == 1
    )
    assert _histogram_count(metrics.subagent_fold_chars, spec="explore") == 1
    assert _histogram_sum(metrics.subagent_fold_chars, spec="explore") == 12.0
    record_policy_capped(None, parent_kind="coding")


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
