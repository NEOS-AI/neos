from __future__ import annotations

import re
from typing import Any

from neos.config.settings import settings
from neos.workflow.harness.checkers.model_judge import (
    HarnessModelJudge,
    LangChainHarnessModelJudge,
    build_bias_perspective_prompt,
    build_factuality_prompt,
)
from neos.workflow.harness.models import HarnessCheckResult, HarnessContract
from neos.workflow.harness.models import HarnessMode


def _failed_severity(contract: HarnessContract, *, name: str) -> str:
    if contract.mode != HarnessMode.GATE:
        return "warning"
    required = set(contract.required_checks or [])
    optional = set(contract.optional_checks or [])
    if name in optional and name not in required:
        return "warning"
    return "critical"


class TopicCoverageChecker:
    name = "topic_coverage"

    def run(
        self,
        *,
        report: str,
        sources: list[dict],
        contract: HarnessContract,
        context: dict | None = None,
    ) -> HarnessCheckResult:
        topics = list(
            (contract.metadata or {}).get("coverage_requirements")
            or (context or {}).get("coverage_requirements")
            or []
        )
        if not topics:
            return HarnessCheckResult(
                name=self.name,
                passed=True,
                score=1.0,
                severity="info",
                summary="No topic coverage requirements configured.",
                metadata={"skipped": True},
            )

        lowered = report.lower()
        missing = [
            {"topic": topic}
            for topic in topics
            if str(topic).lower() not in lowered
        ]
        score = 1.0 - (len(missing) / max(1, len(topics)))
        return HarnessCheckResult(
            name=self.name,
            passed=not missing,
            score=max(score, 0.0),
            severity="warning",
            summary="Topic coverage requirements checked.",
            failed_items=missing,
            repairable=bool(missing),
            metadata={"required_topics": topics},
        )


class FactualityChecker:
    name = "factuality"

    def __init__(
        self,
        *,
        judge: HarnessModelJudge | None = None,
        model_checks_enabled: bool | None = None,
        timeout_seconds: float | None = None,
        max_claims: int | None = None,
    ) -> None:
        self.judge = judge or LangChainHarnessModelJudge()
        self.model_checks_enabled = model_checks_enabled
        self.timeout_seconds = timeout_seconds
        self.max_claims = max_claims

    def run(
        self,
        *,
        report: str,
        sources: list[dict],
        contract: HarnessContract,
        context: dict | None = None,
    ) -> HarnessCheckResult:
        required = self.name in set(contract.required_checks or [])
        if not self._is_selected(contract):
            return self._skipped("check_not_selected")
        return HarnessCheckResult(
            name=self.name,
            passed=not required,
            score=1.0 if not required else 0.0,
            severity=_failed_severity(contract, name=self.name) if required else "warning",
            summary="Model-based factuality check requires the async runner.",
            repairable=False,
            metadata={"skipped": True, "reason": "requires_async_runner"},
        )

    async def arun(
        self,
        *,
        report: str,
        sources: list[dict],
        contract: HarnessContract,
        context: dict | None = None,
    ) -> HarnessCheckResult:
        required = self.name in set(contract.required_checks or [])
        if not self._is_selected(contract):
            return self._skipped("check_not_selected")

        if not self._enabled():
            if required:
                return HarnessCheckResult(
                    name=self.name,
                    passed=False,
                    score=0.0,
                    severity=_failed_severity(contract, name=self.name),
                    summary="Required model-based factuality check is disabled.",
                    repairable=False,
                    metadata={"reason": "model_checks_disabled"},
                )
            return self._skipped("model_checks_disabled")

        claims = _sample_claims(report, max_claims=self._max_claims())
        if not claims:
            return self._skipped("no_sampled_claims")

        prompt = build_factuality_prompt(
            report=report,
            sources=sources,
            claims=claims,
        )
        payload = await self.judge.judge(
            prompt,
            timeout_seconds=self._timeout_seconds(),
        )
        failed_items = _as_list_of_dicts(payload.get("failed_items"))
        evidence = _as_list_of_dicts(payload.get("evidence"))
        passed = bool(payload.get("passed")) and not failed_items
        return HarnessCheckResult(
            name=self.name,
            passed=passed,
            score=float(payload.get("score") or 0.0),
            severity="info" if passed else _failed_severity(contract, name=self.name),
            summary=str(payload.get("summary") or "Factuality check completed."),
            evidence=evidence,
            failed_items=failed_items,
            repairable=not passed and bool(failed_items),
            metadata={
                "claim_count": len(claims),
                "model_check": True,
            },
        )

    def _is_selected(self, contract: HarnessContract) -> bool:
        selected = set(contract.required_checks or [])
        selected.update(contract.optional_checks or [])
        return self.name in selected

    def _enabled(self) -> bool:
        if self.model_checks_enabled is not None:
            return self.model_checks_enabled
        return bool(settings.RESEARCH_HARNESS_MODEL_CHECKS_ENABLED)

    def _timeout_seconds(self) -> float:
        if self.timeout_seconds is not None:
            return self.timeout_seconds
        return float(settings.RESEARCH_HARNESS_MODEL_CHECK_TIMEOUT_SECONDS)

    def _max_claims(self) -> int:
        if self.max_claims is not None:
            return self.max_claims
        return int(settings.RESEARCH_HARNESS_MODEL_CHECK_MAX_CLAIMS)

    def _skipped(self, reason: str) -> HarnessCheckResult:
        return HarnessCheckResult(
            name=self.name,
            passed=True,
            score=1.0,
            severity="info",
            summary=f"Factuality check skipped: {reason}.",
            metadata={"skipped": True, "reason": reason},
        )


class BiasPerspectiveChecker:
    name = "bias_perspective"

    def __init__(
        self,
        *,
        judge: HarnessModelJudge | None = None,
        model_checks_enabled: bool | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self.judge = judge or LangChainHarnessModelJudge()
        self.model_checks_enabled = model_checks_enabled
        self.timeout_seconds = timeout_seconds

    def run(
        self,
        *,
        report: str,
        sources: list[dict],
        contract: HarnessContract,
        context: dict | None = None,
    ) -> HarnessCheckResult:
        required = self.name in set(contract.required_checks or [])
        if not self._is_selected(contract):
            return self._skipped("check_not_selected")
        return HarnessCheckResult(
            name=self.name,
            passed=not required,
            score=1.0 if not required else 0.0,
            severity=_failed_severity(contract, name=self.name) if required else "warning",
            summary="Model-based bias/perspective check requires the async runner.",
            repairable=False,
            metadata={"skipped": True, "reason": "requires_async_runner"},
        )

    async def arun(
        self,
        *,
        report: str,
        sources: list[dict],
        contract: HarnessContract,
        context: dict | None = None,
    ) -> HarnessCheckResult:
        required = self.name in set(contract.required_checks or [])
        if not self._is_selected(contract):
            return self._skipped("check_not_selected")

        if not self._enabled():
            if required:
                return HarnessCheckResult(
                    name=self.name,
                    passed=False,
                    score=0.0,
                    severity=_failed_severity(contract, name=self.name),
                    summary="Required model-based bias/perspective check is disabled.",
                    repairable=False,
                    metadata={"reason": "model_checks_disabled"},
                )
            return self._skipped("model_checks_disabled")

        prompt = build_bias_perspective_prompt(
            report=report,
            sources=sources,
            high_risk_categories=contract.high_risk_categories,
        )
        payload = await self.judge.judge(
            prompt,
            timeout_seconds=self._timeout_seconds(),
        )
        failed_items = _as_list_of_dicts(payload.get("failed_items"))
        evidence = _as_list_of_dicts(payload.get("evidence"))
        passed = bool(payload.get("passed")) and not failed_items
        return HarnessCheckResult(
            name=self.name,
            passed=passed,
            score=float(payload.get("score") or 0.0),
            severity="info" if passed else _failed_severity(contract, name=self.name),
            summary=str(payload.get("summary") or "Bias/perspective check completed."),
            evidence=evidence,
            failed_items=failed_items,
            repairable=not passed and bool(failed_items),
            metadata={
                "high_risk_categories": contract.high_risk_categories,
                "model_check": True,
            },
        )

    def _is_selected(self, contract: HarnessContract) -> bool:
        selected = set(contract.required_checks or [])
        selected.update(contract.optional_checks or [])
        return self.name in selected

    def _enabled(self) -> bool:
        if self.model_checks_enabled is not None:
            return self.model_checks_enabled
        return bool(settings.RESEARCH_HARNESS_MODEL_CHECKS_ENABLED)

    def _timeout_seconds(self) -> float:
        if self.timeout_seconds is not None:
            return self.timeout_seconds
        return float(settings.RESEARCH_HARNESS_MODEL_CHECK_TIMEOUT_SECONDS)

    def _skipped(self, reason: str) -> HarnessCheckResult:
        return HarnessCheckResult(
            name=self.name,
            passed=True,
            score=1.0,
            severity="info",
            summary=f"Bias/perspective check skipped: {reason}.",
            metadata={"skipped": True, "reason": reason},
        )


def _sample_claims(report: str, *, max_claims: int) -> list[str]:
    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+", report.strip())
        if sentence.strip()
    ]
    factual = [
        sentence
        for sentence in sentences
        if re.search(r"\[[^\]]+\]|\d|%|\b(is|are|was|were|has|have|will)\b", sentence, re.IGNORECASE)
    ]
    return factual[: max(0, max_claims)]


def _as_list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]
