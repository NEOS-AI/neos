from datetime import datetime

import pytest

from neos.database.repositories.harness_repository import HarnessRepository
from neos.workflow.harness.models import (
    HarnessCheckResult,
    HarnessContract,
    HarnessMode,
    HarnessRiskLevel,
    HarnessRun,
    HarnessVerdict,
)


class FakeDB:
    def __init__(self):
        self.calls = []

    async def execute(self, query, *values):
        self.calls.append((query, values))


@pytest.mark.asyncio
async def test_harness_repository_saves_run_and_checks(monkeypatch):
    fake_db = FakeDB()
    monkeypatch.setattr(
        "neos.database.repositories.harness_repository.db_manager",
        fake_db,
    )
    repository = HarnessRepository()
    contract = HarnessContract(
        mode=HarnessMode.GATE,
        risk_level=HarnessRiskLevel.MEDIUM,
        min_score=0.82,
    )
    now = datetime.now()
    run = HarnessRun(
        run_id="harness-1",
        mode=HarnessMode.GATE,
        verdict=HarnessVerdict.PASS,
        score=0.91,
        checks=[
            HarnessCheckResult(
                name="source_count",
                passed=True,
                score=1.0,
                severity="info",
                summary="ok",
            )
        ],
        failed_checks=[],
        repair_attempts=0,
        started_at=now,
        completed_at=now,
    )

    await repository.save_run(
        run=run,
        contract=contract,
        session_id="session-1",
        user_id="user-1",
    )

    assert len(fake_db.calls) == 2
    assert "INSERT INTO research_harness_runs" in fake_db.calls[0][0]
    assert "INSERT INTO research_harness_check_results" in fake_db.calls[1][0]
