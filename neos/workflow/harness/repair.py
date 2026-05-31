from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .models import (
    HarnessCheckResult,
    HarnessContract,
    HarnessRepairAction,
    HarnessRepairPlan,
)


class HarnessRepairPlanner:
    """Build targeted, bounded repair actions from failed harness checks."""

    def plan(
        self,
        *,
        contract: HarnessContract,
        failed_checks: list[HarnessCheckResult],
        attempt: int,
        context: dict[str, Any] | None = None,
    ) -> HarnessRepairPlan | None:
        context = context or {}
        repairable = [check for check in failed_checks if check.repairable]
        if not repairable:
            return None

        actions: list[HarnessRepairAction] = []
        seen: set[tuple[str, str]] = set()

        for check in repairable:
            for action in self._actions_for_check(check, contract, context):
                key = (action.action_type, action.target_check)
                if key in seen:
                    continue
                seen.add(key)
                actions.append(action)

        if not actions:
            return None

        return HarnessRepairPlan(
            attempt=attempt,
            actions=actions,
            max_attempts=contract.max_repair_attempts,
            budget_seconds=self._budget_seconds(contract),
            budget_tokens=context.get("repair_budget_tokens"),
        )

    def to_state(self, plan: HarnessRepairPlan | None) -> dict[str, Any] | None:
        if plan is None:
            return None
        return {
            "attempt": plan.attempt,
            "max_attempts": plan.max_attempts,
            "budget_seconds": plan.budget_seconds,
            "budget_tokens": plan.budget_tokens,
            "actions": [asdict(action) for action in plan.actions],
        }

    def _actions_for_check(
        self,
        check: HarnessCheckResult,
        contract: HarnessContract,
        context: dict[str, Any],
    ) -> list[HarnessRepairAction]:
        if check.name == "source_count":
            return [
                HarnessRepairAction(
                    action_type="request_more_sources",
                    target_check=check.name,
                    reason=check.summary,
                    params={
                        "query": context.get("original_query", ""),
                        "min_sources": contract.min_sources,
                        "required_sources": contract.required_sources,
                    },
                )
            ]
        if check.name == "source_diversity":
            return [
                HarnessRepairAction(
                    action_type="search_independent_domains",
                    target_check=check.name,
                    reason=check.summary,
                    params={
                        "query": context.get("original_query", ""),
                        "avoid_domains": context.get("dominant_domains", []),
                        "min_source_diversity": contract.min_source_diversity,
                    },
                )
            ]
        if check.name == "citation_validity":
            return [
                HarnessRepairAction(
                    action_type="rebuild_citation_map",
                    target_check=check.name,
                    reason=check.summary,
                    params={"failed_items": check.failed_items},
                )
            ]
        if check.name == "citation_coverage":
            return [
                HarnessRepairAction(
                    action_type="regenerate_cited_sections",
                    target_check=check.name,
                    reason=check.summary,
                    params={
                        "min_citation_coverage": contract.min_citation_coverage,
                        "failed_items": check.failed_items,
                    },
                )
            ]
        if check.name == "freshness":
            return [
                HarnessRepairAction(
                    action_type="date_constrained_freshness_search",
                    target_check=check.name,
                    reason=check.summary,
                    params={
                        "query": context.get("original_query", ""),
                        "freshness_window_days": contract.freshness_window_days,
                    },
                )
            ]
        return []

    def _budget_seconds(self, contract: HarnessContract) -> int:
        return 90 if contract.risk_level.value == "high" else 60
