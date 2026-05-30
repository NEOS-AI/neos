from neos.workflow.harness.checkers.citations import (
    CitationCoverageChecker,
    CitationValidityChecker,
)
from neos.workflow.harness.checkers.freshness import FreshnessChecker
from neos.workflow.harness.checkers.metadata import MetadataIntegrityChecker
from neos.workflow.harness.checkers.sources import (
    SourceCountChecker,
    SourceDiversityChecker,
)
from neos.workflow.harness.models import (
    HarnessContract,
    HarnessMode,
    HarnessRiskLevel,
)


def gate_contract(**overrides):
    values = {
        "mode": HarnessMode.GATE,
        "risk_level": HarnessRiskLevel.MEDIUM,
        "min_score": 0.82,
    }
    values.update(overrides)
    return HarnessContract(**values)


def test_citation_validity_fails_unknown_marker():
    result = CitationValidityChecker().run(
        report="Known claim [9].",
        sources=[{"id": "1", "url": "https://example.com/report"}],
        contract=gate_contract(),
    )

    assert result.name == "citation_validity"
    assert result.passed is False
    assert result.repairable is True
    assert result.failed_items[0]["marker"] == "9"


def test_citation_coverage_fails_uncited_claims():
    result = CitationCoverageChecker().run(
        report="Revenue increased by 12% in 2025 [1]. Customer churn decreased.",
        sources=[{"id": "1", "url": "https://example.com/report"}],
        contract=gate_contract(min_citation_coverage=0.75),
    )

    assert result.name == "citation_coverage"
    assert result.passed is False
    assert result.score < 0.75
    assert result.repairable is True


def test_source_count_fails_below_minimum():
    result = SourceCountChecker().run(
        report="answer [1]",
        sources=[{"id": "1", "url": "https://example.com/report"}],
        contract=gate_contract(min_sources=3),
    )

    assert result.name == "source_count"
    assert result.passed is False
    assert result.score < 1.0


def test_source_diversity_fails_single_domain_dominance():
    result = SourceDiversityChecker().run(
        report="answer [1] [2] [3]",
        sources=[
            {"id": "1", "url": "https://example.com/a"},
            {"id": "2", "url": "https://example.com/b"},
            {"id": "3", "url": "https://example.com/c"},
        ],
        contract=gate_contract(min_source_diversity=0.60),
    )

    assert result.name == "source_diversity"
    assert result.passed is False
    assert result.severity == "critical"


def test_freshness_fails_old_known_source_date():
    result = FreshnessChecker().run(
        report="latest result [1]",
        sources=[{"id": "1", "url": "https://example.com", "published_at": "2024-01-01"}],
        contract=gate_contract(freshness_required=True, freshness_window_days=30),
        context={"now": "2026-05-30T00:00:00"},
    )

    assert result.name == "freshness"
    assert result.passed is False
    assert result.severity == "critical"


def test_metadata_integrity_fails_empty_report():
    result = MetadataIntegrityChecker().run(
        report="",
        sources=[],
        contract=gate_contract(),
        context={},
    )

    assert result.name == "metadata_integrity"
    assert result.passed is False
    assert result.repairable is False

