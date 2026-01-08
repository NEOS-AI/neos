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


# Default configuration instance
DEFAULT_CONFIG = ResearchConfig()
