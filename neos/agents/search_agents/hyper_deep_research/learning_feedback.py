"""Learning from Feedback Module.

This module implements a feedback learning system that tracks the effectiveness
of improvement suggestions and prioritizes high-impact improvements in future iterations.

Design Philosophy:
- Track which improvements lead to quality increases
- Build a historical effectiveness model
- Prioritize high-impact improvements automatically
- Continuous learning from refinement data

★ Learning Point ─────────────────
This is a self-improving system: the more reports are refined,
the better it becomes at identifying effective improvements.
─────────────────────────────────
"""

import json
import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field, asdict
from pathlib import Path
from datetime import datetime
from collections import defaultdict


logger = logging.getLogger(__name__)


# ============================================================================
# Data Structures
# ============================================================================

@dataclass
class ImprovementRecord:
    """Record of a single improvement application.

    Tracks what improvement was applied and its effect on quality.
    """

    improvement_type: str  # e.g., "Add more citations", "Improve coherence"
    section_id: str
    iteration_number: int
    quality_before: float
    quality_after: float
    quality_delta: float
    success: bool  # True if quality improved
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class ImprovementStats:
    """Aggregated statistics for an improvement type.

    Tracks historical effectiveness of a specific improvement type.
    """

    improvement_type: str
    times_applied: int = 0
    times_successful: int = 0
    total_quality_delta: float = 0.0
    avg_quality_delta: float = 0.0
    success_rate: float = 0.0
    last_updated: str = field(default_factory=lambda: datetime.now().isoformat())

    def update(self, record: ImprovementRecord):
        """Update statistics with a new record.

        Args:
            record: New improvement record to incorporate
        """
        self.times_applied += 1
        if record.success:
            self.times_successful += 1
        self.total_quality_delta += record.quality_delta

        # Recalculate aggregates
        self.avg_quality_delta = self.total_quality_delta / self.times_applied
        self.success_rate = self.times_successful / self.times_applied
        self.last_updated = datetime.now().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


# ============================================================================
# Improvement Tracker
# ============================================================================

class ImprovementTracker:
    """Track effectiveness of improvement suggestions over time.

    This class maintains a learning database of which improvements work best,
    allowing the system to prioritize effective improvements in future iterations.

    Usage:
        tracker = ImprovementTracker()

        # Record improvement application
        tracker.record_improvement(
            improvement_type="Add more citations",
            section_id="intro",
            iteration=1,
            quality_before=0.65,
            quality_after=0.82
        )

        # Get prioritized improvements
        prioritized = tracker.prioritize_improvements([
            "Add more citations",
            "Improve coherence",
            "Simplify language"
        ])
    """

    def __init__(
        self,
        storage_path: Optional[str] = None,
        min_samples_for_learning: int = 5,
    ):
        """Initialize improvement tracker.

        Args:
            storage_path: Path to store learning data (JSON file)
            min_samples_for_learning: Minimum records before using learned priorities
        """
        self.storage_path = storage_path
        self.min_samples = min_samples_for_learning

        # In-memory storage
        self.records: List[ImprovementRecord] = []
        self.stats: Dict[str, ImprovementStats] = {}

        # Load existing data if available
        if storage_path:
            self._load_from_disk()

        logger.info(
            f"ImprovementTracker initialized: "
            f"storage={storage_path}, min_samples={min_samples_for_learning}"
        )

    def record_improvement(
        self,
        improvement_type: str,
        section_id: str,
        iteration_number: int,
        quality_before: float,
        quality_after: float,
    ):
        """Record an improvement application and its effect.

        Args:
            improvement_type: Type of improvement (e.g., "Add more citations")
            section_id: Section identifier
            iteration_number: Iteration number
            quality_before: Quality score before improvement
            quality_after: Quality score after improvement
        """
        # Calculate effect
        quality_delta = quality_after - quality_before
        success = quality_delta > 0.01  # Improved by at least 0.01

        # Create record
        record = ImprovementRecord(
            improvement_type=improvement_type,
            section_id=section_id,
            iteration_number=iteration_number,
            quality_before=quality_before,
            quality_after=quality_after,
            quality_delta=quality_delta,
            success=success,
        )

        # Store record
        self.records.append(record)

        # Update statistics
        if improvement_type not in self.stats:
            self.stats[improvement_type] = ImprovementStats(
                improvement_type=improvement_type
            )
        self.stats[improvement_type].update(record)

        logger.debug(
            f"Recorded improvement: {improvement_type} -> delta={quality_delta:+.3f}"
        )

        # Auto-save if storage configured
        if self.storage_path:
            self._save_to_disk()

    def prioritize_improvements(
        self,
        improvements: List[str],
        fallback_order: Optional[List[str]] = None,
    ) -> List[str]:
        """Prioritize improvements based on historical effectiveness.

        Args:
            improvements: List of improvement types to prioritize
            fallback_order: Order to use if not enough learning data

        Returns:
            Prioritized list of improvements (most effective first)
        """
        # Check if we have enough learning data
        if len(self.records) < self.min_samples:
            logger.info(
                f"Not enough learning data ({len(self.records)}/{self.min_samples}), "
                f"using fallback order"
            )
            return fallback_order or improvements

        # Calculate priority scores using Balanced strategy
        # Priority = avg_quality_delta × success_rate × confidence
        scored_improvements = []

        for improvement in improvements:
            stats = self.stats.get(improvement)

            if stats is None or stats.times_applied == 0:
                # No data for this improvement, assign neutral score
                score = 0.0
                confidence = 0.0
            else:
                # Confidence increases with more samples (max at 10 samples)
                confidence = min(1.0, stats.times_applied / 10.0)

                # Balanced score: effectiveness × reliability × confidence
                score = (
                    stats.avg_quality_delta *  # How much improvement?
                    stats.success_rate *        # How reliable?
                    confidence                  # How confident are we?
                )

            scored_improvements.append((improvement, score, confidence))

        # Sort by score (descending)
        scored_improvements.sort(key=lambda x: x[1], reverse=True)

        # Extract sorted improvement names
        prioritized = [imp for imp, score, conf in scored_improvements]

        # Log prioritization for transparency
        logger.info("Improvement prioritization (Balanced strategy):")
        for imp, score, conf in scored_improvements[:3]:
            stats = self.stats.get(imp)
            if stats:
                logger.info(
                    f"  • {imp}: score={score:.4f} "
                    f"(delta={stats.avg_quality_delta:+.3f}, "
                    f"success={stats.success_rate:.2f}, "
                    f"confidence={conf:.2f})"
                )

        return prioritized

    def get_stats(self, improvement_type: str) -> Optional[ImprovementStats]:
        """Get statistics for a specific improvement type.

        Args:
            improvement_type: Type of improvement

        Returns:
            ImprovementStats if available, None otherwise
        """
        return self.stats.get(improvement_type)

    def get_all_stats(self) -> Dict[str, ImprovementStats]:
        """Get all improvement statistics.

        Returns:
            Dictionary mapping improvement type to stats
        """
        return self.stats.copy()

    def generate_report(self) -> Dict[str, Any]:
        """Generate a learning report showing effectiveness of improvements.

        Returns:
            Dictionary with learning insights
        """
        if not self.stats:
            return {
                "total_records": 0,
                "message": "No learning data available yet"
            }

        # Sort by effectiveness
        sorted_stats = sorted(
            self.stats.values(),
            key=lambda s: s.avg_quality_delta,
            reverse=True
        )

        return {
            "total_records": len(self.records),
            "total_improvement_types": len(self.stats),
            "most_effective": [
                {
                    "type": stat.improvement_type,
                    "avg_delta": stat.avg_quality_delta,
                    "success_rate": stat.success_rate,
                    "times_applied": stat.times_applied,
                }
                for stat in sorted_stats[:5]
            ],
            "least_effective": [
                {
                    "type": stat.improvement_type,
                    "avg_delta": stat.avg_quality_delta,
                    "success_rate": stat.success_rate,
                    "times_applied": stat.times_applied,
                }
                for stat in sorted_stats[-3:]
            ] if len(sorted_stats) > 3 else [],
        }

    def _save_to_disk(self):
        """Save learning data to disk."""
        if not self.storage_path:
            return

        try:
            storage_file = Path(self.storage_path)
            storage_file.parent.mkdir(parents=True, exist_ok=True)

            data = {
                "records": [r.to_dict() for r in self.records],
                "stats": {k: v.to_dict() for k, v in self.stats.items()},
                "last_updated": datetime.now().isoformat(),
            }

            with open(storage_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            logger.debug(f"Learning data saved to {self.storage_path}")
        except Exception as e:
            logger.error(f"Failed to save learning data: {e}")

    def _load_from_disk(self):
        """Load learning data from disk."""
        if not self.storage_path:
            return

        try:
            storage_file = Path(self.storage_path)
            if not storage_file.exists():
                logger.info("No existing learning data found")
                return

            with open(storage_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Restore records
            self.records = [
                ImprovementRecord(**r) for r in data.get("records", [])
            ]

            # Restore stats
            self.stats = {
                k: ImprovementStats(**v)
                for k, v in data.get("stats", {}).items()
            }

            logger.info(
                f"Loaded learning data: {len(self.records)} records, "
                f"{len(self.stats)} improvement types"
            )
        except Exception as e:
            logger.error(f"Failed to load learning data: {e}")


# ============================================================================
# Integration Helper
# ============================================================================

def create_improvement_tracker(
    enable_learning: bool = True,
    storage_path: Optional[str] = None,
    **kwargs
) -> Optional[ImprovementTracker]:
    """Factory function to create improvement tracker.

    Args:
        enable_learning: Whether to enable learning
        storage_path: Path to store learning data
        **kwargs: Additional arguments for ImprovementTracker

    Returns:
        ImprovementTracker instance or None if disabled
    """
    if not enable_learning:
        return None

    # Default storage path if not provided
    if storage_path is None:
        storage_path = ".neos/learning_data/improvement_feedback.json"

    return ImprovementTracker(storage_path=storage_path, **kwargs)
