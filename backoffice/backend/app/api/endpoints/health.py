"""Health check endpoints."""

from fastapi import APIRouter

from app.core.config import settings

router = APIRouter()


@router.get("")
async def health_check():
    """Basic health check endpoint."""
    return {
        "status": "healthy",
        "app_name": settings.APP_NAME,
        "version": settings.APP_VERSION,
    }


@router.get("/ready")
async def readiness_check():
    """Readiness check for Kubernetes probes."""
    return {"status": "ready"}
