from __future__ import annotations

from typing import Any

from neos.workflow.harness.models import HarnessCheckResult, HarnessContract, HarnessMode


class PerformanceBudgetChecker:
    name = "performance_budget"

    def run(
        self,
        *,
        report: str,
        sources: list[dict],
        contract: HarnessContract,
        context: dict | None = None,
    ) -> HarnessCheckResult:
        context = context or {}
        budgets = _configured_budgets(contract.metadata or {})
        if not budgets:
            return HarnessCheckResult(
                name=self.name,
                passed=True,
                score=1.0,
                severity="info",
                summary="No performance budgets configured.",
                metadata={"skipped": True},
            )

        failed_items = []
        evidence = []
        for budget_key, metric_key in BUDGET_METRICS.items():
            if budget_key not in budgets:
                continue
            observed = _observed_metric(context, metric_key)
            if observed is None:
                continue
            threshold = budgets[budget_key]
            item = {
                "metric": metric_key,
                "observed": observed,
                "threshold": threshold,
            }
            evidence.append(item)
            if float(observed) > float(threshold):
                failed_items.append(item)

        checked_count = max(1, len(evidence))
        score = 1.0 - (len(failed_items) / checked_count)
        return HarnessCheckResult(
            name=self.name,
            passed=not failed_items,
            score=max(0.0, score),
            severity="critical" if failed_items and contract.mode == HarnessMode.GATE else "warning",
            summary="Performance budgets checked.",
            evidence=evidence,
            failed_items=failed_items,
            repairable=False,
            metadata={"configured_budgets": sorted(budgets)},
        )


BUDGET_METRICS = {
    "max_processing_time_ms": "processing_time_ms",
    "max_validation_latency_ms": "validation_latency_ms",
    "max_total_llm_calls": "llm_call_count",
    "max_total_tokens": "total_tokens",
    "max_repair_attempts_observed": "repair_attempts",
}


def _configured_budgets(metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        key: metadata[key]
        for key in BUDGET_METRICS
        if metadata.get(key) is not None
    }


def _observed_metric(context: dict[str, Any], metric_key: str) -> Any:
    if metric_key == "total_tokens":
        token_usage = context.get("token_usage") or {}
        if isinstance(token_usage, dict):
            return token_usage.get("total_tokens")
        return None
    if metric_key == "repair_attempts":
        return context.get("repair_attempts", context.get("harness_repair_attempts"))
    return context.get(metric_key)
