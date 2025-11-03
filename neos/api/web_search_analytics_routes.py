"""
Web Search Analytics API routes - delegates to handlers

This file serves as the entry point for analytics-related API endpoints.
The handlers are in the handlers/ directory, and the service layer
is in neos.database.web_search_analytics_service.
"""

from neos.api.handlers.analytics_handlers import router

__all__ = ["router"]
