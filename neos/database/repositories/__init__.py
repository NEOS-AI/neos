"""Database repositories for data access layer.

This package contains repository implementations following the Repository pattern
to decouple data access logic from business logic.
"""

from .analytics_repository import AnalyticsRepository

__all__ = ['AnalyticsRepository']
