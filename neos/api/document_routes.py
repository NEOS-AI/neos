"""
Document API routes - delegates to handlers

This file serves as the entry point for document-related API endpoints.
All business logic has been moved to the service layer,
and request handling has been moved to handlers.
"""

from neos.api.handlers.document_handlers import router

__all__ = ["router"]
