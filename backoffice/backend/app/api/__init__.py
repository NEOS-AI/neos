"""API router configuration."""

from fastapi import APIRouter

from app.api.endpoints import analysis, clusters, health

api_router = APIRouter()

api_router.include_router(health.router, prefix="/health", tags=["health"])
api_router.include_router(analysis.router, prefix="/analysis", tags=["analysis"])
api_router.include_router(clusters.router, prefix="/clusters", tags=["clusters"])
