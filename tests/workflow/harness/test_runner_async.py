import pytest

from neos.workflow.harness.models import (
    HarnessCheckResult,
    HarnessContract,
    HarnessMode,
    HarnessRiskLevel,
)
from neos.workflow.harness.runner import HarnessRunner


class AsyncChecker:
    name = "async_check"

    async def arun(self, *, report, sources, contract, context=None):
        return HarnessCheckResult(
            name=self.name,
            passed=True,
            score=1.0,
            severity="info",
            summary="Async checker completed.",
        )


class SyncChecker:
    name = "sync_check"

    def run(self, *, report, sources, contract, context=None):
        return HarnessCheckResult(
            name=self.name,
            passed=True,
            score=0.9,
            severity="info",
            summary="Sync checker completed.",
        )


@pytest.mark.asyncio
async def test_runner_arun_executes_async_checkers():
    run = await HarnessRunner(checkers=[AsyncChecker()]).arun(
        report="Report",
        sources=[],
        contract=HarnessContract(
            mode=HarnessMode.ADVISORY,
            risk_level=HarnessRiskLevel.LOW,
            min_score=0.7,
            optional_checks=["async_check"],
        ),
        context={},
    )

    assert run.checks[0].name == "async_check"
    assert run.checks[0].passed is True


@pytest.mark.asyncio
async def test_runner_arun_executes_sync_checkers():
    run = await HarnessRunner(checkers=[SyncChecker()]).arun(
        report="Report",
        sources=[],
        contract=HarnessContract(
            mode=HarnessMode.ADVISORY,
            risk_level=HarnessRiskLevel.LOW,
            min_score=0.7,
            optional_checks=["sync_check"],
        ),
        context={},
    )

    assert run.checks[0].name == "sync_check"
    assert run.checks[0].passed is True
