"""
Deep Research API routes - delegates to deep research handlers

This file serves as the entry point for deep research-related API endpoints.
All business logic is in the service layer, and request handling is in handlers.
"""

from neos.api.handlers.deep_research_handlers import router

__all__ = ["router"]
