"""HyperDeepResearch Agent Package.

This package contains a refactored implementation of the HyperDeepResearch agent
following clean architecture principles and design patterns.

Structure:
- prompts/: Multilingual prompt templates
- repository/: Database access layer (Repository pattern)
- utils/: Utility functions and helpers
- agent.py: Main agent implementation
"""

from .agent import HyperDeepResearchAgent


__all__ = ["HyperDeepResearchAgent"]
