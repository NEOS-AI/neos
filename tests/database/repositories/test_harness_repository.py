from datetime import datetime
import json

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


@pytest.mark.asyncio
async def test_harness_repository_summary_only_policy_stores_compact_details(monkeypatch):
    fake_db = FakeDB()
    monkeypatch.setattr("neos.database.repositories.harness_repository.db_manager", fake_db)
    monkeypatch.setattr(
        "neos.database.repositories.harness_repository.settings.RESEARCH_HARNESS_EVIDENCE_STORAGE_POLICY",
        "summary_only",
    )

    await HarnessRepository().save_run(
        run=_run_with_sensitive_check(),
        contract=_contract(),
    )

    check_values = fake_db.calls[1][1]
    assert json.loads(check_values[6]) == []
    assert json.loads(check_values[7]) == [{"count": 1}]
    run_metadata = json.loads(fake_db.calls[0][1][12])
    assert run_metadata["evidence_storage_policy"] == "summary_only"


@pytest.mark.asyncio
async def test_harness_repository_redacted_policy_hashes_sensitive_text(monkeypatch):
    fake_db = FakeDB()
    monkeypatch.setattr("neos.database.repositories.harness_repository.db_manager", fake_db)
    monkeypatch.setattr(
        "neos.database.repositories.harness_repository.settings.RESEARCH_HARNESS_EVIDENCE_STORAGE_POLICY",
        "redacted",
    )

    await HarnessRepository().save_run(
        run=_run_with_sensitive_check(),
        contract=_contract(),
    )

    failed_item = json.loads(fake_db.calls[1][1][7])[0]
    assert "claim" not in failed_item
    assert failed_item["claim_length"] == len("Sensitive unsupported claim")
    assert "claim_sha256" in failed_item
    assert failed_item["url_domain"] == "example.com"


@pytest.mark.asyncio
async def test_harness_repository_full_policy_preserves_raw_evidence(monkeypatch):
    fake_db = FakeDB()
    monkeypatch.setattr("neos.database.repositories.harness_repository.db_manager", fake_db)
    monkeypatch.setattr(
        "neos.database.repositories.harness_repository.settings.RESEARCH_HARNESS_EVIDENCE_STORAGE_POLICY",
        "full",
    )

    await HarnessRepository().save_run(
        run=_run_with_sensitive_check(),
        contract=_contract(),
    )

    failed_item = json.loads(fake_db.calls[1][1][7])[0]
    assert failed_item["claim"] == "Sensitive unsupported claim"
    assert failed_item["url"] == "https://example.com/private"


def _contract():
    return HarnessContract(
        mode=HarnessMode.GATE,
        risk_level=HarnessRiskLevel.MEDIUM,
        min_score=0.82,
    )


def _run_with_sensitive_check():
    now = datetime.now()
    return HarnessRun(
        run_id="harness-sensitive",
        mode=HarnessMode.GATE,
        verdict=HarnessVerdict.FAIL,
        score=0.2,
        checks=[
            HarnessCheckResult(
                name="factuality",
                passed=False,
                score=0.2,
                severity="critical",
                summary="unsupported",
                evidence=[{"text": "Sensitive source text", "score": 0.2}],
                failed_items=[
                    {
                        "claim": "Sensitive unsupported claim",
                        "url": "https://example.com/private",
                    }
                ],
                repairable=True,
            )
        ],
        failed_checks=["factuality"],
        repair_attempts=0,
        started_at=now,
        completed_at=now,
    )
