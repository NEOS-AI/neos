from __future__ import annotations

import json

from neos.config.settings import settings
from neos.database.connection import db_manager
from neos.workflow.harness.models import HarnessContract, HarnessRun
from neos.workflow.harness.privacy import sanitize_check_result


class HarnessRepository:
    async def save_run(
        self,
        *,
        run: HarnessRun,
        contract: HarnessContract,
        session_id: str | None = None,
        report_id: str | None = None,
        user_id: str | None = None,
    ) -> None:
        evidence_policy = settings.RESEARCH_HARNESS_EVIDENCE_STORAGE_POLICY
        metadata = dict(run.metadata or {})
        metadata["evidence_storage_policy"] = evidence_policy
        metadata["retention_class"] = (
            "operational_summary"
            if evidence_policy == "summary_only"
            else "sensitive_eval"
        )
        metadata["access_policy"] = "internal_harness_review"
        await db_manager.execute(
            """
            INSERT INTO research_harness_runs (
                run_id, session_id, report_id, user_id, mode, verdict, score,
                risk_level, threshold, repair_attempts, failed_checks,
                contract, metadata, started_at, completed_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
            ON CONFLICT (run_id) DO NOTHING
            """,
            run.run_id,
            session_id,
            report_id,
            user_id,
            run.mode.value,
            run.verdict.value,
            float(run.score),
            contract.risk_level.value,
            float(contract.min_score),
            run.repair_attempts,
            json.dumps(run.failed_checks),
            json.dumps(contract.to_dict()),
            json.dumps(metadata),
            run.started_at,
            run.completed_at,
        )
        for check in run.checks:
            safe_check = sanitize_check_result(check, policy=evidence_policy)
            await db_manager.execute(
                """
                INSERT INTO research_harness_check_results (
                    run_id, check_name, passed, score, severity, summary,
                    evidence, failed_items, repairable, metadata
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                """,
                run.run_id,
                safe_check.name,
                safe_check.passed,
                float(safe_check.score),
                safe_check.severity,
                safe_check.summary,
                json.dumps(safe_check.evidence),
                json.dumps(safe_check.failed_items),
                safe_check.repairable,
                json.dumps(safe_check.metadata),
            )


harness_repository = HarnessRepository()
