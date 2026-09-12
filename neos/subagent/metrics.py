"""Low-cardinality subagent Prometheus recording. Decorator over EventSink."""

from __future__ import annotations

from typing import Any, Mapping

_PARENTS = frozenset({"coding", "deep_analysis"})
_SPECS = frozenset({"explore"})
_OUTCOMES = frozenset(
    {"continuing", "completed", "failed", "cancelled", "unknown_spec"}
)
_PROVIDERS = frozenset({"anthropic", "openai", "gemini", "ollama"})


def _parent(payload: Mapping[str, Any]) -> str:
    value = str(payload.get("parent_kind") or "")
    return value if value in _PARENTS else "coding"


def _spec(payload: Mapping[str, Any]) -> str:
    value = str(payload.get("spec") or "explore")
    return value if value in _SPECS else "explore"


def _outcome(payload: Mapping[str, Any], default: str) -> str:
    value = str(payload.get("step_kind") or payload.get("outcome") or default)
    return value if value in _OUTCOMES else default


def _provider(payload: Mapping[str, Any]) -> str:
    value = str(payload.get("provider") or "anthropic")
    return value if value in _PROVIDERS else "anthropic"


def record_subagent_event(metrics, event_type: str, payload: Mapping[str, Any]) -> None:
    if metrics is None:
        return
    parent = _parent(payload)
    spec = _spec(payload)
    if event_type == "subagent.cas_mismatch":
        metrics.subagent_cas_mismatch_total.labels(parent_kind=parent).inc()
        return
    if event_type == "subagent.step":
        outcome = _outcome(payload, "continuing")
        metrics.subagent_advance_total.labels(
            spec=spec, parent_kind=parent, outcome=outcome
        ).inc()
        histogram = getattr(metrics, "subagent_advance_seconds", None)
        if histogram is not None and payload.get("duration_sec") is not None:
            histogram.labels(spec=spec, parent_kind=parent).observe(
                float(payload["duration_sec"])
            )
        return
    if event_type == "subagent.completed":
        metrics.subagent_advance_total.labels(
            spec=spec, parent_kind=parent, outcome="completed"
        ).inc()
        metrics.subagent_tokens_total.labels(
            spec=spec, parent_kind=parent, direction="input"
        ).inc(int(payload.get("input_tokens") or 0))
        metrics.subagent_tokens_total.labels(
            spec=spec, parent_kind=parent, direction="output"
        ).inc(int(payload.get("output_tokens") or 0))
        metrics.subagent_cost_micros_total.labels(
            spec=spec, parent_kind=parent, provider=_provider(payload)
        ).inc(int(payload.get("cost_micros") or 0))
        return
    if event_type == "subagent.failed":
        metrics.subagent_advance_total.labels(
            spec=spec, parent_kind=parent, outcome="failed"
        ).inc()
        return
    if event_type == "subagent.cancelled":
        metrics.subagent_advance_total.labels(
            spec=spec, parent_kind=parent, outcome="cancelled"
        ).inc()
        return
    if event_type == "subagent.fold":
        fold = getattr(metrics, "subagent_fold_chars", None)
        if fold is not None:
            fold.labels(spec=spec).observe(int(payload.get("chars") or 0))


class MetricsEventSink:
    def __init__(self, inner, metrics) -> None:
        self._inner = inner
        self._metrics = metrics

    async def emit(self, event_type: str, payload: Mapping[str, Any]) -> None:
        if self._inner is not None:
            await self._inner.emit(event_type, payload)
        record_subagent_event(self._metrics, event_type, payload)
