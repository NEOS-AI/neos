from __future__ import annotations

import json

from neos.database.connection import db_manager
from neos.workflow.harness.models import HarnessContract, HarnessRun


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
            json.dumps(run.metadata),
            run.started_at,
            run.completed_at,
        )
        for check in run.checks:
            await db_manager.execute(
                """
                INSERT INTO research_harness_check_results (
                    run_id, check_name, passed, score, severity, summary,
                    evidence, failed_items, repairable, metadata
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                """,
                run.run_id,
                check.name,
                check.passed,
                float(check.score),
                check.severity,
                check.summary,
                json.dumps(check.evidence),
                json.dumps(check.failed_items),
                check.repairable,
                json.dumps(check.metadata),
            )


harness_repository = HarnessRepository()
