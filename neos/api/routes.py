"""
Main API routes - delegates to handlers

This file serves as the main entry point for the API.
All business logic has been moved to the service layer,
and request handling has been moved to handlers.
"""

from neos.api.handlers.query_handlers import router

__all__ = ["router"]
