from __future__ import annotations

import uuid
from typing import Any, Dict, List

from .models import ValidatorRun


class ContractCoverageValidator:
    validator_type = "contract_coverage"

    def validate(self, state: Dict[str, Any]) -> Dict[str, Any]:
        contract = state.get("validation_contract") or {}
        findings: List[str] = []
        score = 1.0

        required_sources = int(contract.get("required_sources") or 0)
        source_count = len(state.get("search_results") or [])
        if source_count < required_sources:
            findings.append(
                f"required_sources unmet: expected {required_sources}, found {source_count}"
            )
            score -= 0.35

        min_quality = float(contract.get("min_quality_score") or 0.0)
        quality_score = float(state.get("quality_score") or 0.0)
        if quality_score < min_quality:
            findings.append(
                f"min_quality_score unmet: expected {min_quality:.2f}, found {quality_score:.2f}"
            )
            score -= 0.25

        for criterion in contract.get("success_criteria") or []:
            findings.append(f"checked success_criteria: {criterion}")

        status = "passed" if not any("unmet" in item for item in findings) else "failed"
        return ValidatorRun(
            validator_run_id=f"validator-{uuid.uuid4()}",
            mission_id=state.get("mission_id", ""),
            validator_type=self.validator_type,
            status=status,
            score=max(score, 0.0),
            findings=findings,
            repair_suggestion=None
            if status == "passed"
            else "Repair mission output to satisfy the validation contract.",
        ).to_state()


class MissionValidator:
    def __init__(self, *, fact_check_processor: Any, quality_validator: Any) -> None:
        self.fact_check_processor = fact_check_processor
        self.quality_validator = quality_validator
        self.contract_validator = ContractCoverageValidator()

    async def validate(self, state: Dict[str, Any]) -> Dict[str, Any]:
        quality_updates = await self._ensure_quality_score(state)
        runs = list(state.get("validator_runs") or [])
        contract_run = self.contract_validator.validate(state)
        runs.append(contract_run)

        failed_checks = [
            finding
            for run in runs
            if run.get("status") != "passed"
            for finding in run.get("findings", [])
            if "unmet" in finding
        ]
        score = min((run.get("score", 0.0) for run in runs), default=0.0)
        summary = {
            "passed": not failed_checks,
            "score": score,
            "failed_checks": failed_checks,
            "validator_count": len(runs),
        }
        harness_summary = None
        if state.get("harness_verdict"):
            harness_summary = {
                "mode": state.get("harness_mode"),
                "verdict": state.get("harness_verdict"),
                "score": float(state.get("harness_score") or 0.0),
                "failed_checks": list(state.get("harness_failed_checks") or []),
            }
        if harness_summary:
            summary["harness"] = harness_summary
            if harness_summary["mode"] == "gate" and harness_summary["verdict"] in {
                "fail",
                "needs_repair",
            }:
                summary["passed"] = False
                summary["failed_checks"].extend(harness_summary["failed_checks"])
        result = {
            "validator_runs": runs,
            "validation_summary": summary,
            "mission_status": "completed" if summary["passed"] else "partial",
        }
        result.update(quality_updates)
        return result

    async def _ensure_quality_score(self, state: Dict[str, Any]) -> Dict[str, Any]:
        if state.get("quality_score") is not None:
            return {"quality_score": float(state.get("quality_score") or 0.0)}

        if self.quality_validator is None:
            state["quality_score"] = 0.0
            return {"quality_score": 0.0}

        quality_state = await self.quality_validator.validate_quality(state)
        if quality_state:
            state.update(quality_state)

        updates = {"quality_score": float(state.get("quality_score") or 0.0)}
        if state.get("quality_feedback") is not None:
            updates["quality_feedback"] = state.get("quality_feedback")
        if state.get("execution_steps") is not None:
            updates["execution_steps"] = state.get("execution_steps")
        return updates
