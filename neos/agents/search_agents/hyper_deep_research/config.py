"""Research Configuration Module.

This module contains configuration constants and settings for the
HyperDeepResearch agent.
"""

from dataclasses import dataclass, field
from typing import Dict, Any


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
        }
    
    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> "ResearchConfig":
        """Create configuration from dictionary."""
        return cls(**{k: v for k, v in config_dict.items() if hasattr(cls, k)})


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


# Default configuration instance
DEFAULT_CONFIG = ResearchConfig()
