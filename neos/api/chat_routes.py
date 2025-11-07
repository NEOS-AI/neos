"""
Chat API routes - delegates to chat handlers

This file serves as the entry point for chat-related API endpoints.
All business logic is in the service layer, and request handling is in handlers.
"""

from neos.api.handlers.chat_handlers import router

__all__ = ["router"]
