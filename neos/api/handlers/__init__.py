"""API handlers package - thin layer for FastAPI routes"""

from neos.api.handlers.query_handlers import router as query_router
from neos.api.handlers.document_handlers import router as document_router
from neos.api.handlers.multimodal_handlers import router as multimodal_router
from neos.api.handlers.analytics_handlers import router as analytics_router

__all__ = [
    "query_router",
    "document_router",
    "multimodal_router",
    "analytics_router",
]
