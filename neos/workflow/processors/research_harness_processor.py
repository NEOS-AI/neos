"""LangGraph processor for the research validation harness."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from neos.workflow.harness.adapters.workflow_state import (
    extract_context,
    extract_report_text,
    extract_sources,
)
from neos.workflow.harness.contract_builder import build_harness_contract
from neos.workflow.harness.runner import HarnessRunner

from ..state import AgentState


class ResearchHarnessProcessor:
    def __init__(self, runner: HarnessRunner | None = None) -> None:
        self.runner = runner or HarnessRunner()

    async def process(self, state: AgentState) -> dict[str, Any]:
        contract = build_harness_contract(state)
        report = extract_report_text(state)
        sources = extract_sources(state)
        context = extract_context(state)
        repair_attempts = int(state.get("harness_repair_attempts") or 0)

        run = self.runner.run(
            report=report,
            sources=sources,
            contract=contract,
            context=context,
            repair_attempts=repair_attempts,
        )

        runs = list(state.get("harness_runs") or [])
        runs.append(run.to_dict())

        updates = {
            "harness_mode": run.mode.value,
            "harness_contract": contract.to_dict(),
            "harness_runs": runs,
            "harness_verdict": run.verdict.value,
            "harness_score": float(run.score),
            "harness_failed_checks": run.failed_checks,
            "harness_repair_plan": None,
            "harness_repair_attempts": repair_attempts,
            "harness_metadata": {
                "run_id": run.run_id,
                "check_count": len(run.checks),
                "threshold": contract.min_score,
                "risk_level": contract.risk_level.value,
            },
        }

        execution_steps = list(state.get("execution_steps") or [])
        execution_steps.append(
            {
                "step": "research_harness",
                "result": f"completed - verdict: {run.verdict.value}, score: {run.score:.2f}",
                "timestamp": datetime.now().isoformat(),
            }
        )
        updates["execution_steps"] = execution_steps
        return updates

