from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from neos.workflow.harness.events import HarnessEventType, build_harness_event
from neos.workflow.harness.models import (
    HarnessCheckResult,
    HarnessContract,
    HarnessMode,
    HarnessRiskLevel,
)
from neos.workflow.harness.repair import HarnessRepairPlanner


class ResearchHarnessRepairProcessor:
    def __init__(self, planner: HarnessRepairPlanner | None = None) -> None:
        self.planner = planner or HarnessRepairPlanner()

    async def process(self, state: dict[str, Any]) -> dict[str, Any]:
        attempts = int(state.get("harness_repair_attempts") or 0)
        contract = self._contract_from_state(state.get("harness_contract") or {})
        if attempts >= contract.max_repair_attempts:
            return {
                "harness_repair_plan": None,
                "harness_repair_attempts": attempts,
                "errors": list(state.get("errors") or [])
                + ["research_harness_repair_exhausted"],
            }

        failed_checks = self._failed_checks_from_state(state)
        plan = self.planner.plan(
            contract=contract,
            failed_checks=failed_checks,
            attempt=attempts + 1,
            context={
                "original_query": state.get("original_query", ""),
                **(state.get("harness_metadata") or {}),
            },
        )
        plan_state = self.planner.to_state(plan)
        required_agents = self._required_agents_for_plan(
            list(state.get("required_agents") or []),
            plan_state,
        )
        event_handler = state.get("_event_handler")

        if event_handler is not None and plan_state:
            await event_handler.on_node_progress(
                "research_harness_repair",
                json.dumps(
                    build_harness_event(
                        HarnessEventType.REPAIR_STARTED,
                        data={
                            "attempt": plan_state["attempt"],
                            "actions": plan_state.get("actions", []),
                        },
                    )
                ),
                0,
            )

        execution_steps = list(state.get("execution_steps") or [])
        execution_steps.append(
            {
                "step": "research_harness_repair",
                "result": "planned" if plan_state else "skipped",
                "timestamp": datetime.now().isoformat(),
            }
        )

        if event_handler is not None and plan_state:
            await event_handler.on_node_progress(
                "research_harness_repair",
                json.dumps(
                    build_harness_event(
                        HarnessEventType.REPAIR_COMPLETED,
                        data={
                            "attempt": plan_state["attempt"],
                            "action_count": len(plan_state.get("actions", [])),
                        },
                    )
                ),
                100,
            )

        return {
            "harness_repair_plan": plan_state,
            "harness_repair_attempts": attempts + 1 if plan_state else attempts,
            "required_agents": required_agents,
            "execution_steps": execution_steps,
        }

    def _contract_from_state(self, data: dict[str, Any]) -> HarnessContract:
        return HarnessContract(
            mode=HarnessMode(data.get("mode", "gate")),
            risk_level=HarnessRiskLevel(data.get("risk_level", "medium")),
            min_score=float(data.get("min_score", 0.82)),
            min_sources=int(data.get("min_sources", 3)),
            min_citation_coverage=float(data.get("min_citation_coverage", 0.75)),
            min_source_diversity=float(data.get("min_source_diversity", 0.60)),
            freshness_required=bool(data.get("freshness_required", False)),
            freshness_window_days=data.get("freshness_window_days"),
            required_sources=list(data.get("required_sources") or []),
            required_checks=list(data.get("required_checks") or []),
            optional_checks=list(data.get("optional_checks") or []),
            max_repair_attempts=int(data.get("max_repair_attempts", 1)),
            failure_policy=data.get("failure_policy", "block"),
            metadata=dict(data.get("metadata") or {}),
        )

    def _failed_checks_from_state(self, state: dict[str, Any]) -> list[HarnessCheckResult]:
        metadata = state.get("harness_metadata") or {}
        checks = metadata.get("check_results") or []
        return [
            HarnessCheckResult(
                name=item["name"],
                passed=bool(item.get("passed", False)),
                score=float(item.get("score", 0.0)),
                severity=item.get("severity", "warning"),
                summary=item.get("summary", ""),
                failed_items=list(item.get("failed_items") or []),
                repairable=bool(item.get("repairable", False)),
                metadata=dict(item.get("metadata") or {}),
            )
            for item in checks
            if not item.get("passed", False)
        ]

    def _required_agents_for_plan(
        self,
        current_agents: list[str],
        plan_state: dict[str, Any] | None,
    ) -> list[str]:
        agents = list(current_agents)
        if not plan_state:
            return agents
        action_types = {action["action_type"] for action in plan_state.get("actions", [])}
        if action_types & {
            "request_more_sources",
            "search_independent_domains",
            "date_constrained_freshness_search",
        }:
            if "realtime_info_search" not in agents:
                agents.append("realtime_info_search")
        return agents
