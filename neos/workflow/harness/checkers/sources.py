from __future__ import annotations

from collections import Counter
from urllib.parse import urlparse

from neos.workflow.harness.models import (
    HarnessCheckResult,
    HarnessContract,
    HarnessMode,
)


def _domain(url: str | None) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    domain = parsed.netloc or parsed.path
    return domain.lower().removeprefix("www.")


def _source_key(source: dict, index: int) -> str:
    for key in ("url", "id", "title"):
        value = source.get(key)
        if value:
            return str(value)
    return str(index)


def _unique_sources(sources: list[dict]) -> list[dict]:
    seen: set[str] = set()
    unique: list[dict] = []
    for index, source in enumerate(sources):
        key = _source_key(source, index)
        if key not in seen:
            seen.add(key)
            unique.append(source)
    return unique


def _matches_required_source(source: dict, requirement: str) -> bool:
    needle = requirement.lower()
    values = [
        str(source.get("url") or "").lower(),
        str(source.get("title") or "").lower(),
        _domain(source.get("url")),
    ]
    return any(needle in value for value in values)


def _severity(contract: HarnessContract, passed: bool) -> str:
    if passed:
        return "info"
    return "critical" if contract.mode == HarnessMode.GATE else "warning"


class SourceCountChecker:
    name = "source_count"

    def run(
        self,
        *,
        report: str,
        sources: list[dict],
        contract: HarnessContract,
        context: dict | None = None,
    ) -> HarnessCheckResult:
        unique = _unique_sources(sources)
        missing_required = [
            requirement
            for requirement in contract.required_sources
            if not any(_matches_required_source(source, requirement) for source in unique)
        ]
        count_score = min(len(unique) / max(contract.min_sources, 1), 1.0)
        required_score = 1.0 if not missing_required else 0.0
        score = min(count_score, required_score)
        passed = len(unique) >= contract.min_sources and not missing_required

        return HarnessCheckResult(
            name=self.name,
            passed=passed,
            score=float(score),
            severity=_severity(contract, passed),
            summary=(
                "Source count meets the contract."
                if passed
                else f"{len(unique)} source(s) found; {contract.min_sources} required."
            ),
            failed_items=[{"required_source": item} for item in missing_required],
            repairable=not passed,
            metadata={
                "source_count": len(unique),
                "min_sources": contract.min_sources,
            },
        )


class SourceDiversityChecker:
    name = "source_diversity"

    def run(
        self,
        *,
        report: str,
        sources: list[dict],
        contract: HarnessContract,
        context: dict | None = None,
    ) -> HarnessCheckResult:
        unique = _unique_sources(sources)
        domains = [_domain(source.get("url")) for source in unique if _domain(source.get("url"))]
        if not domains:
            passed = not contract.required_sources and contract.mode != HarnessMode.GATE
            return HarnessCheckResult(
                name=self.name,
                passed=passed,
                score=0.0 if not passed else 1.0,
                severity=_severity(contract, passed),
                summary="No source domains available for diversity analysis.",
                repairable=not passed,
            )

        counts = Counter(domains)
        diversity = len(counts) / len(domains)
        dominance = max(counts.values()) / len(domains)
        passed = (
            diversity >= contract.min_source_diversity
            and (contract.mode != HarnessMode.GATE or dominance <= 0.60)
        )

        return HarnessCheckResult(
            name=self.name,
            passed=passed,
            score=float(diversity),
            severity=_severity(contract, passed),
            summary=(
                "Source diversity meets the contract."
                if passed
                else "Source set is dominated by too few domains."
            ),
            failed_items=[] if passed else [{"dominant_share": dominance}],
            repairable=not passed,
            metadata={
                "domain_count": len(counts),
                "source_count": len(domains),
                "dominant_share": dominance,
                "threshold": contract.min_source_diversity,
            },
        )

