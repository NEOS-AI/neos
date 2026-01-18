"""Quality Metrics Collection System.

This module provides real-time tracking and reporting of refinement quality metrics,
LLM costs, and performance data for the iterative refinement system.

Features:
- Real-time metrics collection during refinement
- Cost tracking per LLM call
- Quality progression over iterations
- Performance benchmarking
- Console dashboard display
- JSON/CSV export

Design:
- Non-intrusive: Metrics collection doesn't affect refinement logic
- Async-safe: Thread-safe for parallel refinement
- Zero-overhead when disabled: Feature flag controlled
"""

import logging
import json
import csv
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path


logger = logging.getLogger(__name__)


# ============================================================================
# Data Structures
# ============================================================================

@dataclass
class IterationMetrics:
    """Metrics for a single iteration."""

    section_id: str
    iteration_number: int
    quality_score: float
    citation_coverage: float
    coherence: float
    completeness: float
    clarity: float
    duration_ms: int
    llm_calls: int
    improvements_made: List[str]
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class SectionMetrics:
    """Aggregated metrics for a section."""

    section_id: str
    section_title: str
    total_iterations: int
    initial_quality: float
    final_quality: float
    quality_improvement: float
    duration_seconds: float
    llm_calls: int
    estimated_cost_usd: float
    iterations_history: List[IterationMetrics] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        data = asdict(self)
        data["iterations_history"] = [it.to_dict() for it in self.iterations_history]
        return data


@dataclass
class ReportMetrics:
    """Overall report-level metrics."""

    report_id: str
    total_sections: int
    total_iterations: int
    avg_initial_quality: float
    avg_final_quality: float
    avg_quality_improvement: float
    total_duration_seconds: float
    total_llm_calls: int
    estimated_total_cost_usd: float
    sections: List[SectionMetrics] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        data = asdict(self)
        data["sections"] = [s.to_dict() for s in self.sections]
        return data


# ============================================================================
# Metrics Collector
# ============================================================================

class QualityMetricsCollector:
    """Collect and report quality metrics during refinement.

    Usage:
        collector = QualityMetricsCollector(report_id="report_123")

        # During refinement
        collector.record_iteration(
            section_id="intro",
            iteration=1,
            quality_score=0.75,
            ...
        )

        # At end
        report = collector.generate_report()
        collector.display_dashboard()
        collector.export_to_json("metrics.json")
    """

    def __init__(
        self,
        report_id: str,
        enabled: bool = True,
        llm_cost_per_1k_tokens: float = 0.015,  # Default: GPT-4 pricing
    ):
        """Initialize metrics collector.

        Args:
            report_id: Unique identifier for this report
            enabled: Whether to collect metrics (feature flag)
            llm_cost_per_1k_tokens: Cost per 1k tokens for estimation
        """
        self.report_id = report_id
        self.enabled = enabled
        self.llm_cost_per_1k_tokens = llm_cost_per_1k_tokens

        # Storage
        self.section_metrics: Dict[str, SectionMetrics] = {}
        self.current_section_iterations: Dict[str, List[IterationMetrics]] = {}

        # Timing
        self.start_time: Optional[datetime] = None
        self.end_time: Optional[datetime] = None

        logger.info(f"QualityMetricsCollector initialized (enabled={enabled})")

    def start_collection(self):
        """Start metrics collection (mark start time)."""
        if not self.enabled:
            return
        self.start_time = datetime.now()
        logger.debug("Metrics collection started")

    def record_iteration(
        self,
        section_id: str,
        section_title: str,
        iteration_number: int,
        quality_score: float,
        citation_coverage: float,
        coherence: float,
        completeness: float,
        clarity: float,
        duration_ms: int,
        llm_calls: int = 1,
        improvements_made: Optional[List[str]] = None,
    ):
        """Record metrics for a single iteration.

        Args:
            section_id: Unique section identifier
            section_title: Human-readable section title
            iteration_number: Iteration number (1-indexed)
            quality_score: Overall quality score (0-1)
            citation_coverage: Citation coverage (0-1)
            coherence: Coherence score (0-1)
            completeness: Completeness score (0-1)
            clarity: Clarity score (0-1)
            duration_ms: Duration in milliseconds
            llm_calls: Number of LLM calls made
            improvements_made: List of improvements applied
        """
        if not self.enabled:
            return

        iteration_metrics = IterationMetrics(
            section_id=section_id,
            iteration_number=iteration_number,
            quality_score=quality_score,
            citation_coverage=citation_coverage,
            coherence=coherence,
            completeness=completeness,
            clarity=clarity,
            duration_ms=duration_ms,
            llm_calls=llm_calls,
            improvements_made=improvements_made or [],
        )

        # Store iteration
        if section_id not in self.current_section_iterations:
            self.current_section_iterations[section_id] = []
            self.section_metrics[section_id] = SectionMetrics(
                section_id=section_id,
                section_title=section_title,
                total_iterations=0,
                initial_quality=quality_score,
                final_quality=quality_score,
                quality_improvement=0.0,
                duration_seconds=0.0,
                llm_calls=0,
                estimated_cost_usd=0.0,
            )

        self.current_section_iterations[section_id].append(iteration_metrics)

        # Update section metrics
        section = self.section_metrics[section_id]
        section.total_iterations = len(self.current_section_iterations[section_id])
        section.final_quality = quality_score
        section.quality_improvement = section.final_quality - section.initial_quality
        section.duration_seconds += duration_ms / 1000.0
        section.llm_calls += llm_calls
        section.estimated_cost_usd = self._estimate_cost(section.llm_calls)
        section.iterations_history = self.current_section_iterations[section_id]

        logger.debug(
            f"Recorded iteration {iteration_number} for {section_id}: "
            f"quality={quality_score:.2f}, duration={duration_ms}ms"
        )

    def finalize_collection(self):
        """Finalize metrics collection (mark end time)."""
        if not self.enabled:
            return
        self.end_time = datetime.now()
        logger.debug("Metrics collection finalized")

    def generate_report(self) -> ReportMetrics:
        """Generate aggregated report metrics.

        Returns:
            ReportMetrics object with all collected data
        """
        if not self.enabled:
            return ReportMetrics(
                report_id=self.report_id,
                total_sections=0,
                total_iterations=0,
                avg_initial_quality=0.0,
                avg_final_quality=0.0,
                avg_quality_improvement=0.0,
                total_duration_seconds=0.0,
                total_llm_calls=0,
                estimated_total_cost_usd=0.0,
            )

        sections = list(self.section_metrics.values())

        if not sections:
            logger.warning("No sections recorded")
            return ReportMetrics(
                report_id=self.report_id,
                total_sections=0,
                total_iterations=0,
                avg_initial_quality=0.0,
                avg_final_quality=0.0,
                avg_quality_improvement=0.0,
                total_duration_seconds=0.0,
                total_llm_calls=0,
                estimated_total_cost_usd=0.0,
            )

        # Aggregate
        total_iterations = sum(s.total_iterations for s in sections)
        avg_initial = sum(s.initial_quality for s in sections) / len(sections)
        avg_final = sum(s.final_quality for s in sections) / len(sections)
        avg_improvement = sum(s.quality_improvement for s in sections) / len(sections)
        total_duration = sum(s.duration_seconds for s in sections)
        total_llm_calls = sum(s.llm_calls for s in sections)
        total_cost = sum(s.estimated_cost_usd for s in sections)

        return ReportMetrics(
            report_id=self.report_id,
            total_sections=len(sections),
            total_iterations=total_iterations,
            avg_initial_quality=avg_initial,
            avg_final_quality=avg_final,
            avg_quality_improvement=avg_improvement,
            total_duration_seconds=total_duration,
            total_llm_calls=total_llm_calls,
            estimated_total_cost_usd=total_cost,
            sections=sections,
        )

    def display_dashboard(self):
        """Display metrics dashboard to console."""
        if not self.enabled:
            logger.info("Metrics collection disabled")
            return

        report = self.generate_report()

        # Build dashboard
        dashboard = self._build_dashboard_text(report)
        print("\n" + dashboard + "\n")

    def _build_dashboard_text(self, report: ReportMetrics) -> str:
        """Build console dashboard text.

        Args:
            report: ReportMetrics object

        Returns:
            Formatted dashboard string
        """
        lines = []
        lines.append("┌─────────────────────────────────────────────────┐")
        lines.append("│ Quality Metrics Dashboard                       │")
        lines.append("├─────────────────────────────────────────────────┤")
        lines.append(f"│ Report ID: {report.report_id:<36} │")
        lines.append(f"│ Sections: {report.total_sections:<38} │")
        lines.append(f"│ Total Iterations: {report.total_iterations:<30} │")
        lines.append("│                                                 │")
        lines.append("│ Quality Progression:                            │")
        lines.append(f"│   Initial:     {report.avg_initial_quality:>5.2f}                         │")
        lines.append(f"│   Final:       {report.avg_final_quality:>5.2f} ⭐                       │")
        lines.append(f"│   Improvement: +{report.avg_quality_improvement:>4.2f}                        │")
        lines.append("│                                                 │")
        lines.append("│ Performance:                                    │")
        lines.append(f"│   Duration:    {report.total_duration_seconds:>6.1f}s                       │")
        lines.append(f"│   LLM Calls:   {report.total_llm_calls:<33} │")
        lines.append(f"│   Est. Cost:   ${report.estimated_total_cost_usd:>5.2f}                     │")
        lines.append("│                                                 │")

        # Top 3 sections by improvement
        sorted_sections = sorted(
            report.sections,
            key=lambda s: s.quality_improvement,
            reverse=True
        )[:3]

        if sorted_sections:
            lines.append("│ Top Improvements:                               │")
            for i, section in enumerate(sorted_sections, 1):
                title = section.section_title[:20]
                lines.append(
                    f"│   {i}. {title:<20} (+{section.quality_improvement:.2f}){'│':>{26 - len(title)}} │"
                )

        lines.append("└─────────────────────────────────────────────────┘")

        return "\n".join(lines)

    def export_to_json(self, filepath: str):
        """Export metrics to JSON file.

        Args:
            filepath: Path to output JSON file
        """
        if not self.enabled:
            logger.info("Metrics collection disabled, skipping export")
            return

        report = self.generate_report()
        output_path = Path(filepath)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)

        logger.info(f"Metrics exported to {filepath}")

    def export_to_csv(self, filepath: str):
        """Export section metrics to CSV file.

        Args:
            filepath: Path to output CSV file
        """
        if not self.enabled:
            logger.info("Metrics collection disabled, skipping export")
            return

        report = self.generate_report()
        output_path = Path(filepath)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)

            # Header
            writer.writerow([
                "Section ID",
                "Section Title",
                "Iterations",
                "Initial Quality",
                "Final Quality",
                "Improvement",
                "Duration (s)",
                "LLM Calls",
                "Est. Cost ($)",
            ])

            # Data
            for section in report.sections:
                writer.writerow([
                    section.section_id,
                    section.section_title,
                    section.total_iterations,
                    f"{section.initial_quality:.3f}",
                    f"{section.final_quality:.3f}",
                    f"{section.quality_improvement:+.3f}",
                    f"{section.duration_seconds:.2f}",
                    section.llm_calls,
                    f"{section.estimated_cost_usd:.4f}",
                ])

        logger.info(f"Metrics exported to {filepath}")

    def _estimate_cost(self, llm_calls: int) -> float:
        """Estimate LLM cost based on call count.

        Args:
            llm_calls: Number of LLM calls

        Returns:
            Estimated cost in USD
        """
        # Rough estimate: ~1000 tokens per call (input + output)
        estimated_tokens = llm_calls * 1000
        cost = (estimated_tokens / 1000.0) * self.llm_cost_per_1k_tokens
        return cost


# ============================================================================
# Utility Functions
# ============================================================================

def create_metrics_collector(
    report_id: str,
    enabled: bool = True,
    **kwargs
) -> QualityMetricsCollector:
    """Factory function to create metrics collector.

    Args:
        report_id: Unique report identifier
        enabled: Whether to enable metrics collection
        **kwargs: Additional arguments for QualityMetricsCollector

    Returns:
        QualityMetricsCollector instance
    """
    return QualityMetricsCollector(report_id=report_id, enabled=enabled, **kwargs)
