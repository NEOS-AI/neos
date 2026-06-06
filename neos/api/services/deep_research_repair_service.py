from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Callable

from neos.workflow.harness.models import (
    HarnessCheckResult,
    HarnessContract,
    HarnessRepairAction,
    HarnessRepairPlan,
)
from neos.workflow.harness.repair import HarnessRepairPlanner


ActionExecutor = Callable[..., Any]


@dataclass
class RepairActionResult:
    status: str
    reason: str | None = None
    added_sources: int = 0
    updated_sections: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class DeepResearchRepairService:
    def __init__(
        self,
        *,
        planner: HarnessRepairPlanner | None = None,
        action_executor: ActionExecutor | None = None,
    ) -> None:
        self.planner = planner or HarnessRepairPlanner()
        self.action_executor = action_executor

    async def repair(
        self,
        *,
        report_id: str,
        research_topic: str,
        contract: HarnessContract,
        failed_checks: list[HarnessCheckResult],
        attempt: int,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        if attempt > contract.max_repair_attempts:
            return {
                "attempt": attempt,
                "max_attempts": contract.max_repair_attempts,
                "budget_seconds": 0,
                "executed_actions": [],
                "skipped_actions": [
                    {
                        "reason": "attempts_exhausted",
                        "attempt": attempt,
                        "max_attempts": contract.max_repair_attempts,
                    }
                ],
            }

        repair_context = {
            **(context or {}),
            "research_topic": research_topic,
        }
        plan = self.planner.plan(
            contract=contract,
            failed_checks=failed_checks,
            attempt=attempt,
            context=repair_context,
        )
        if plan is None:
            return {
                "attempt": attempt,
                "max_attempts": contract.max_repair_attempts,
                "budget_seconds": 0,
                "executed_actions": [],
                "skipped_actions": [],
            }
        return await self._execute_plan(
            report_id=report_id,
            plan=plan,
            context=repair_context,
        )

    async def _execute_plan(
        self,
        *,
        report_id: str,
        plan: HarnessRepairPlan,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        executed_actions = []
        skipped_actions = []
        for action in plan.actions:
            if action.action_type not in SUPPORTED_ACTIONS:
                skipped_actions.append(
                    {
                        "action_type": action.action_type,
                        "reason": "unsupported_action",
                    }
                )
                continue
            result = await self._execute_action(
                report_id=report_id,
                action=action,
                context=context,
            )
            status = result.get("status", "executed")
            record = {
                "action_type": action.action_type,
                "target_check": action.target_check,
                "status": status,
            }
            record.update({key: value for key, value in result.items() if key != "status"})
            if status == "skipped":
                skipped_actions.append(record)
            else:
                executed_actions.append(record)

        return {
            "attempt": plan.attempt,
            "max_attempts": plan.max_attempts,
            "budget_seconds": plan.budget_seconds,
            "executed_actions": executed_actions,
            "skipped_actions": skipped_actions,
        }

    async def _execute_action(
        self,
        *,
        report_id: str,
        action: HarnessRepairAction,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        if self.action_executor is None:
            return {
                "status": "skipped",
                "reason": "no_direct_executor_configured",
            }
        result = self.action_executor(
            report_id=report_id,
            action=action,
            context=context,
        )
        if inspect.isawaitable(result):
            result = await result
        return self._normalize_action_result(result)

    @staticmethod
    def _normalize_action_result(result: Any) -> dict[str, Any]:
        if isinstance(result, RepairActionResult):
            return {
                "status": result.status,
                "reason": result.reason,
                "added_sources": result.added_sources,
                "updated_sections": result.updated_sections,
                **result.metadata,
            }
        if isinstance(result, dict):
            return result
        return {"status": "executed"}


SUPPORTED_ACTIONS = {
    "rebuild_citation_map",
    "regenerate_cited_sections",
    "request_more_sources",
    "search_independent_domains",
    "date_constrained_freshness_search",
    "regenerate_unsupported_claims",
    "add_perspective_balancing_sources",
}
