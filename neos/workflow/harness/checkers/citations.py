from __future__ import annotations

import re

from neos.workflow.harness.models import (
    HarnessCheckResult,
    HarnessContract,
    HarnessMode,
)

_CITATION_RE = re.compile(r"\[(\d+)\]")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


def _citation_markers(report: str) -> list[str]:
    return _CITATION_RE.findall(report or "")


def _source_ids(sources: list[dict]) -> set[str]:
    ids: set[str] = set()
    for index, source in enumerate(sources, start=1):
        for key in ("id", "source_id", "citation_id"):
            value = source.get(key)
            if value is not None:
                ids.add(str(value))
        ids.add(str(index))
    return ids


def _severity(contract: HarnessContract, passed: bool) -> str:
    if passed:
        return "info"
    return "critical" if contract.mode == HarnessMode.GATE else "warning"


class CitationValidityChecker:
    name = "citation_validity"

    def run(
        self,
        *,
        report: str,
        sources: list[dict],
        contract: HarnessContract,
        context: dict | None = None,
    ) -> HarnessCheckResult:
        markers = _citation_markers(report)
        if not markers:
            return HarnessCheckResult(
                name=self.name,
                passed=True,
                score=1.0,
                severity="info",
                summary="No citation markers found to validate.",
                metadata={"citation_count": 0},
            )

        valid_ids = _source_ids(sources)
        unknown = [{"marker": marker} for marker in markers if marker not in valid_ids]
        score = (len(markers) - len(unknown)) / len(markers)
        threshold = 0.95 if contract.mode == HarnessMode.GATE else 0.85
        passed = score >= threshold

        return HarnessCheckResult(
            name=self.name,
            passed=passed,
            score=float(score),
            severity=_severity(contract, passed),
            summary=(
                "All citation markers resolve to known sources."
                if passed
                else f"{len(unknown)} citation marker(s) do not resolve to known sources."
            ),
            failed_items=unknown,
            repairable=not passed,
            metadata={"citation_count": len(markers), "threshold": threshold},
        )


class CitationCoverageChecker:
    name = "citation_coverage"

    def run(
        self,
        *,
        report: str,
        sources: list[dict],
        contract: HarnessContract,
        context: dict | None = None,
    ) -> HarnessCheckResult:
        sentences = [
            sentence.strip()
            for sentence in _SENTENCE_RE.split(report or "")
            if sentence.strip()
        ]
        if not sentences:
            return HarnessCheckResult(
                name=self.name,
                passed=False,
                score=0.0,
                severity="critical" if contract.mode == HarnessMode.GATE else "warning",
                summary="No report text available for citation coverage.",
                repairable=False,
            )

        cited = [
            sentence
            for sentence in sentences
            if _CITATION_RE.search(sentence) or "(source:" in sentence.lower()
        ]
        score = len(cited) / len(sentences)
        passed = score >= contract.min_citation_coverage
        failed = [{"text": sentence} for sentence in sentences if sentence not in cited]

        return HarnessCheckResult(
            name=self.name,
            passed=passed,
            score=float(score),
            severity=_severity(contract, passed),
            summary=(
                "Citation coverage meets the contract."
                if passed
                else f"{len(failed)} sentence(s) lack citation coverage."
            ),
            failed_items=failed,
            repairable=not passed,
            metadata={
                "cited_sentences": len(cited),
                "total_sentences": len(sentences),
                "threshold": contract.min_citation_coverage,
            },
        )

