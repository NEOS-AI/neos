"""LangGraph processor for the research validation harness."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from neos.config.settings import settings
from neos.workflow.harness.adapters.workflow_state import (
    extract_context,
    extract_report_text,
    extract_sources,
)
from neos.workflow.harness.contract_builder import build_harness_contract
from neos.workflow.harness.events import HarnessEventType, build_harness_event
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
        event_handler = state.get("_event_handler")

        if event_handler is not None:
            await event_handler.on_node_progress(
                "research_harness",
                json.dumps(
                    build_harness_event(
                        HarnessEventType.STARTED,
                        data={"mode": contract.mode.value},
                    )
                ),
                0,
            )

        async def emit_check_event(event_type: HarnessEventType, payload: dict) -> None:
            if event_handler is None:
                return
            await event_handler.on_node_progress(
                "research_harness",
                json.dumps(build_harness_event(event_type, data=payload)),
                50,
            )

        run = await self.runner.arun(
            report=report,
            sources=sources,
            contract=contract,
            context=context,
            repair_attempts=repair_attempts,
            event_callback=emit_check_event if event_handler is not None else None,
        )

        if settings.RESEARCH_HARNESS_PERSIST_RUNS:
            from neos.database.repositories.harness_repository import harness_repository

            await harness_repository.save_run(
                run=run,
                contract=contract,
                session_id=state.get("session_id"),
                user_id=state.get("user_id"),
            )

        if event_handler is not None:
            await event_handler.on_node_progress(
                "research_harness",
                json.dumps(
                    build_harness_event(
                        HarnessEventType.COMPLETED,
                        run_id=run.run_id,
                        data={
                            "verdict": run.verdict.value,
                            "score": float(run.score),
                            "failed_checks": run.failed_checks,
                        },
                    )
                ),
                100,
            )

        runs = list(state.get("harness_runs") or [])
        runs.append(run.to_dict())
        thinking_trace = list(state.get("thinking_trace") or [])
        for event in (run.metadata or {}).get("trace_events", []):
            thinking_trace.append(
                {
                    "node_id": "research_harness",
                    "run_id": run.run_id,
                    **event,
                }
            )
        harness_summary = {
            "enabled": run.mode.value != "off",
            "mode": run.mode.value,
            "verdict": run.verdict.value,
            "score": float(run.score),
            "failed_checks": run.failed_checks,
            "repair_attempts": repair_attempts,
            "threshold": contract.min_score,
            "risk_level": contract.risk_level.value,
        }
        compact_checks = [
            {
                "name": check.name,
                "passed": check.passed,
                "score": float(check.score),
                "severity": check.severity,
                "summary": check.summary,
                "repairable": check.repairable,
                "failed_items": check.failed_items,
                "metadata": check.metadata,
            }
            for check in run.checks
        ]

        updates = {
            "harness_mode": run.mode.value,
            "harness_contract": contract.to_dict(),
            "harness_runs": runs,
            "harness_verdict": run.verdict.value,
            "harness_score": float(run.score),
            "harness_failed_checks": run.failed_checks,
            "harness_repair_plan": None,
            "harness_repair_attempts": repair_attempts,
            "thinking_trace": thinking_trace,
            "harness_metadata": {
                "run_id": run.run_id,
                "check_count": len(run.checks),
                "threshold": contract.min_score,
                "risk_level": contract.risk_level.value,
                "check_results": compact_checks,
            },
        }
        if state.get("response_metadata") is not None:
            response_metadata = dict(state.get("response_metadata") or {})
            response_metadata["harness"] = harness_summary
            updates["response_metadata"] = response_metadata

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
