"""HyperDeepResearch Agent Package.

This package contains a refactored implementation of the HyperDeepResearch agent
following clean architecture principles and design patterns.

Structure:
- prompts/: Multilingual prompt templates
- repository/: Database access layer (Repository pattern)
- utils/: Utility functions and helpers
- config.py: Research configuration and metadata classes
- data_collection.py: Data collection and search operations
- analysis.py: Topic, deep, gap, and validation analysis
- skills_integration.py: External skills integration (ArXiv, PubMed, Wikipedia)
- report_generator.py: Report generation and assembly
- agent.py: Main agent implementation
"""

# Import from refactored module (use agent_refactored for modular version)
from .agent import HyperDeepResearchAgent

# Import modular components for direct access
from .config import ResearchConfig, ResearchMetadata
from .data_collection import DataCollector, ComplexSearchExecutor
from .analysis import (
    TopicAnalyzer,
    ResearchPlanner,
    DeepAnalyzer,
    GapAnalyzer,
    ValidationAnalyzer,
    DataSummarizer,
)
from .skills_integration import SkillsIntegrator
from .report_generator import ReportGenerator, CriticismProcessor, QueryGenerator


__all__ = [
    # Main agent
    "HyperDeepResearchAgent",
    # Configuration
    "ResearchConfig",
    "ResearchMetadata",
    # Data collection
    "DataCollector",
    "ComplexSearchExecutor",
    # Analysis
    "TopicAnalyzer",
    "ResearchPlanner",
    "DeepAnalyzer",
    "GapAnalyzer",
    "ValidationAnalyzer",
    "DataSummarizer",
    # Skills
    "SkillsIntegrator",
    # Report generation
    "ReportGenerator",
    "CriticismProcessor",
    "QueryGenerator",
]
