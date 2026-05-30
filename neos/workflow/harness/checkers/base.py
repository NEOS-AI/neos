from __future__ import annotations

from typing import Protocol

from neos.workflow.harness.models import HarnessCheckResult, HarnessContract


class BaseHarnessChecker(Protocol):
    name: str

    def run(
        self,
        *,
        report: str,
        sources: list[dict],
        contract: HarnessContract,
        context: dict | None = None,
    ) -> HarnessCheckResult:
        ...

