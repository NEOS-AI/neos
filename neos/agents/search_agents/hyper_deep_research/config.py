"""Research Configuration Module.

This module contains configuration constants and settings for the
HyperDeepResearch agent.
"""

from dataclasses import dataclass, field
from typing import Dict, Any, Optional


@dataclass
class ResearchConfig:
    """Configuration for HyperDeepResearch agent.
    
    Contains all configurable parameters for research execution.
    """
    
    # Multi-query settings
    multi_query_expansion: int = 20  # Query variations per query
    parallel_search_batches: int = 5  # Number of parallel search batches

    # ★ NEW: Hybrid collection settings
    enable_hybrid_collection: bool = True  # Use intelligent strategy selection
    max_hybrid_queries: int = 10  # Max queries for hybrid collection (cost control)

    # Research intensity
    max_queries_per_phase: int = 30  # Maximum queries per phase
    results_per_query: int = 10  # Results per query
    min_total_sources: int = 100  # Minimum total sources
    target_total_sources: int = 200  # Target total sources
    
    # Analysis depth
    analysis_iterations: int = 3  # Number of analysis iterations
    cross_validation_rounds: int = 2  # Cross-validation rounds
    critical_thinking_passes: int = 2  # Critical thinking passes
    
    # Section and quality settings
    max_sections: int = 15  # Maximum report sections
    min_sources_per_section: int = 5  # Minimum sources per section
    timeout_per_phase: int = 900  # Phase timeout (15 minutes)
    quality_threshold: float = 0.9  # Quality threshold

    # ★ NEW: Iterative refinement settings (Ralph Loop-inspired)
    enable_iterative_refinement: bool = True  # Enable iterative report improvement
    max_iterations_per_section: int = 3  # Max refinement iterations per section
    section_quality_threshold: float = 0.8  # Quality threshold for section refinement
    enable_abstract_refinement: bool = True  # Refine abstract after section improvements
    enable_consistency_alignment: bool = True  # Align sections with abstract
    auto_citation_recommendation: bool = True  # Auto-recommend citations during refinement
    max_concurrent_refinements: int = 4  # Max concurrent section refinements (parallel processing)

    # ★ NEW: Quality metrics collection (A - Quality Metrics Dashboard)
    collect_metrics: bool = True  # Enable quality metrics collection and dashboard
    export_metrics_json: bool = False  # Export metrics to JSON file after refinement

    # ★ NEW: Adaptive thresholds (B - Adaptive Thresholds)
    adaptive_thresholds_enabled: bool = False  # Enable section-specific quality thresholds
    adaptive_threshold_config: Optional['AdaptiveThresholdConfig'] = None  # Adaptive threshold configuration

    # ★ NEW: Learning from Feedback (C - Learning System)
    enable_learning_feedback: bool = True  # Enable learning from improvement effectiveness
    learning_storage_path: Optional[str] = None  # Path to store learning data (default: .neos/learning_data/)
    min_samples_for_learning: int = 5  # Minimum samples before using learned priorities

    # ★ NEW: Smart Content Chunking (D - Content Chunking)
    enable_smart_chunking: bool = True  # Enable smart content chunking for long sections
    chunk_size: int = 4000  # Maximum characters per chunk
    chunk_overlap: int = 200  # Overlap between chunks for context continuity
    min_chunk_size: int = 500  # Minimum chunk size to avoid tiny fragments

    # ★ NEW: Conditional Refinement (E - Skip Good Sections)
    enable_conditional_refinement: bool = True  # Skip refinement for already-good sections
    skip_threshold_multiplier: float = 0.95  # Skip if quality >= threshold × multiplier (95%)

    # ★ NEW: Custom Quality Metric Weights (F - Custom Weights)
    quality_metric_weights: Optional[Dict[str, float]] = None  # Custom weights for quality metrics

    def __post_init__(self):
        """Initialize adaptive threshold config if enabled."""
        if self.adaptive_thresholds_enabled and self.adaptive_threshold_config is None:
            self.adaptive_threshold_config = AdaptiveThresholdConfig(enabled=True)

    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary."""
        return {
            "multi_query_expansion": self.multi_query_expansion,
            "parallel_search_batches": self.parallel_search_batches,
            "enable_hybrid_collection": self.enable_hybrid_collection,
            "max_hybrid_queries": self.max_hybrid_queries,
            "max_queries_per_phase": self.max_queries_per_phase,
            "results_per_query": self.results_per_query,
            "min_total_sources": self.min_total_sources,
            "target_total_sources": self.target_total_sources,
            "analysis_iterations": self.analysis_iterations,
            "cross_validation_rounds": self.cross_validation_rounds,
            "critical_thinking_passes": self.critical_thinking_passes,
            "max_sections": self.max_sections,
            "min_sources_per_section": self.min_sources_per_section,
            "timeout_per_phase": self.timeout_per_phase,
            "quality_threshold": self.quality_threshold,
            # Iterative refinement
            "enable_iterative_refinement": self.enable_iterative_refinement,
            "max_iterations_per_section": self.max_iterations_per_section,
            "section_quality_threshold": self.section_quality_threshold,
            "enable_abstract_refinement": self.enable_abstract_refinement,
            "enable_consistency_alignment": self.enable_consistency_alignment,
            "auto_citation_recommendation": self.auto_citation_recommendation,
            "max_concurrent_refinements": self.max_concurrent_refinements,
            # Quality metrics
            "collect_metrics": self.collect_metrics,
            "export_metrics_json": self.export_metrics_json,
            # Adaptive thresholds
            "adaptive_thresholds_enabled": self.adaptive_thresholds_enabled,
            # Learning from Feedback
            "enable_learning_feedback": self.enable_learning_feedback,
            "learning_storage_path": self.learning_storage_path,
            "min_samples_for_learning": self.min_samples_for_learning,
            # Smart Content Chunking
            "enable_smart_chunking": self.enable_smart_chunking,
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap,
            "min_chunk_size": self.min_chunk_size,
            # Conditional Refinement
            "enable_conditional_refinement": self.enable_conditional_refinement,
            "skip_threshold_multiplier": self.skip_threshold_multiplier,
            # Custom Quality Weights
            "quality_metric_weights": self.quality_metric_weights,
        }
    
    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> "ResearchConfig":
        """Create configuration from dictionary."""
        return cls(**{k: v for k, v in config_dict.items() if hasattr(cls, k)})

    def get_normalized_quality_weights(self) -> Dict[str, float]:
        """Get normalized quality metric weights.

        If custom weights are provided, validates and normalizes them to sum to 1.0.
        If not provided, returns default weights.

        Returns:
            Dictionary with normalized weights (sum = 1.0)

        Raises:
            ValueError: If weights are invalid (negative or zero sum)
        """
        import logging
        logger = logging.getLogger(__name__)

        if self.quality_metric_weights is None:
            # Default weights (from original implementation)
            return {
                "citation_coverage": 0.30,
                "citation_quality": 0.25,
                "coherence": 0.20,
                "completeness": 0.15,
                "clarity": 0.10,
            }

        # Validate all weights are non-negative
        for metric, weight in self.quality_metric_weights.items():
            if weight < 0:
                raise ValueError(
                    f"Quality metric weight for '{metric}' must be non-negative, got {weight}"
                )

        # Calculate sum for normalization
        total = sum(self.quality_metric_weights.values())
        if total == 0:
            raise ValueError("Sum of quality metric weights cannot be zero")

        # Normalize weights to sum to 1.0
        normalized = {k: v / total for k, v in self.quality_metric_weights.items()}

        # Log if normalization was needed (sum not already 1.0)
        if abs(total - 1.0) > 0.001:
            logger.info(
                f"Quality metric weights normalized from sum={total:.3f} to 1.0: {normalized}"
            )

        return normalized


@dataclass
class ResearchMetadata:
    """Metadata tracking for research process."""
    
    total_queries_executed: int = 0
    total_sources_collected: int = 0
    unique_domains: set = field(default_factory=set)
    analysis_iterations_completed: int = 0
    critical_reviews_completed: int = 0
    multi_query_searches: int = 0
    criticism_feedbacks_generated: int = 0
    additional_research_triggered: int = 0
    api_rate_limit_hits: int = 0
    
    # LLM cost tracking
    llm_calls: int = 0
    estimated_total_tokens: int = 0
    llm_calls_by_phase: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    
    # Skill/tool selection
    selected_skills: list = field(default_factory=list)
    selected_tools: list = field(default_factory=list)
    selection_reasoning: str = ""

    # ★ NEW: Iterative refinement tracking
    total_section_iterations: int = 0  # Total iterations across all sections
    sections_refined: int = 0  # Number of sections that underwent refinement
    abstract_refinement_performed: bool = False  # Was abstract refined?
    sections_realigned: int = 0  # Number of sections realigned with abstract
    average_section_quality: float = 0.0  # Average final quality score
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert metadata to dictionary."""
        return {
            "total_queries_executed": self.total_queries_executed,
            "total_sources_collected": self.total_sources_collected,
            "unique_domains": self.unique_domains,
            "analysis_iterations_completed": self.analysis_iterations_completed,
            "critical_reviews_completed": self.critical_reviews_completed,
            "multi_query_searches": self.multi_query_searches,
            "criticism_feedbacks_generated": self.criticism_feedbacks_generated,
            "additional_research_triggered": self.additional_research_triggered,
            "api_rate_limit_hits": self.api_rate_limit_hits,
            "llm_calls": self.llm_calls,
            "estimated_total_tokens": self.estimated_total_tokens,
            "llm_calls_by_phase": self.llm_calls_by_phase,
            "selected_skills": self.selected_skills,
            "selected_tools": self.selected_tools,
            "selection_reasoning": self.selection_reasoning,
            # Iterative refinement
            "total_section_iterations": self.total_section_iterations,
            "sections_refined": self.sections_refined,
            "abstract_refinement_performed": self.abstract_refinement_performed,
            "sections_realigned": self.sections_realigned,
            "average_section_quality": self.average_section_quality,
        }
    
    def reset(self) -> None:
        """Reset all metadata to initial values."""
        self.total_queries_executed = 0
        self.total_sources_collected = 0
        self.unique_domains = set()
        self.analysis_iterations_completed = 0
        self.critical_reviews_completed = 0
        self.multi_query_searches = 0
        self.criticism_feedbacks_generated = 0
        self.additional_research_triggered = 0
        self.api_rate_limit_hits = 0
        self.llm_calls = 0
        self.estimated_total_tokens = 0
        self.llm_calls_by_phase = {}
        self.selected_skills = []
        self.selected_tools = []
        self.selection_reasoning = ""
        # Iterative refinement
        self.total_section_iterations = 0
        self.sections_refined = 0
        self.abstract_refinement_performed = False
        self.sections_realigned = 0
        self.average_section_quality = 0.0


# ============================================================================
# Adaptive Threshold Configuration (B - Adaptive Thresholds)
# ============================================================================

@dataclass
class AdaptiveThresholdConfig:
    """Adaptive threshold configuration for section-specific quality standards.

    Different sections have different importance levels and should have
    different quality thresholds:
    - Abstract/Introduction/Conclusion: Higher (0.85-0.90) - Most critical
    - Results/Discussion: Medium (0.80) - Important but factual
    - Methodology/References: Lower (0.70-0.75) - Technical details

    This optimizes both quality and cost/performance.
    """

    enabled: bool = False  # Feature flag

    # Section type → threshold mapping
    thresholds: Dict[str, float] = field(default_factory=lambda: {
        "introduction": 0.85,      # Higher: Very important first impression
        "abstract": 0.90,          # Highest: Most critical summary
        "executive_summary": 0.90, # Highest: Executive-level overview
        "methodology": 0.75,       # Lower: Technical implementation details
        "results": 0.80,           # Medium: Important but largely factual
        "discussion": 0.80,        # Medium: Analysis and interpretation
        "conclusion": 0.85,        # Higher: Critical final summary
        "references": 0.70,        # Lower: Mostly formatting and completeness
        "appendix": 0.70,          # Lower: Supporting material
        "default": 0.75,           # Fallback for unclassified sections
    })

    def get_threshold(self, section_title: str) -> float:
        """Get quality threshold for a section based on its title.

        Args:
            section_title: Section title to classify

        Returns:
            Quality threshold (0.0-1.0)
        """
        section_type = self._classify_section(section_title)
        threshold = self.thresholds.get(section_type, 0.75)
        return threshold

    def _classify_section(self, title: str) -> str:
        """Classify section by analyzing title keywords.

        Supports both Korean and English keywords for international usage.

        Args:
            title: Section title

        Returns:
            Section type string (e.g., "introduction", "methodology")
        """
        title_lower = title.lower()

        # Keyword matching (Korean + English)
        if any(kw in title_lower for kw in ["introduction", "intro", "서론", "도입"]):
            return "introduction"
        elif any(kw in title_lower for kw in ["abstract", "요약", "개요", "초록"]):
            return "abstract"
        elif any(kw in title_lower for kw in ["executive", "경영진", "임원", "요약"]):
            return "executive_summary"
        elif any(kw in title_lower for kw in ["method", "methodology", "방법", "연구방법", "방법론"]):
            return "methodology"
        elif any(kw in title_lower for kw in ["result", "finding", "결과", "발견", "연구결과"]):
            return "results"
        elif any(kw in title_lower for kw in ["discussion", "analysis", "토론", "분석", "논의", "고찰"]):
            return "discussion"
        elif any(kw in title_lower for kw in ["conclusion", "결론", "맺음", "결어"]):
            return "conclusion"
        elif any(kw in title_lower for kw in ["reference", "참고", "출처", "참고문헌"]):
            return "references"
        elif any(kw in title_lower for kw in ["appendix", "부록", "첨부"]):
            return "appendix"
        else:
            return "default"


# Default configuration instance
DEFAULT_CONFIG = ResearchConfig()
