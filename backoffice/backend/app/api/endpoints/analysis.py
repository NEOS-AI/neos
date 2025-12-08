"""Analysis run management endpoints."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.analysis_service import AnalysisService

router = APIRouter()


class AnalysisRunCreate(BaseModel):
    """Request model for creating an analysis run."""

    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    facet_types: Optional[List[str]] = None
    config: Optional[Dict[str, Any]] = None


class AnalysisRunResponse(BaseModel):
    """Response model for analysis run."""

    run_id: str
    name: str
    description: Optional[str]
    status: str
    total_conversations: int
    processed_conversations: int
    total_clusters: int
    progress_percentage: float
    current_stage: Optional[str]
    error_message: Optional[str]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


@router.post("", response_model=AnalysisRunResponse)
async def create_analysis_run(
    request: AnalysisRunCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Create a new analysis run.

    The analysis will be executed in the background.
    """
    service = AnalysisService(db)

    run = await service.create_analysis_run(
        name=request.name,
        description=request.description,
        start_date=request.start_date,
        end_date=request.end_date,
        facet_types=request.facet_types,
        config=request.config,
    )

    # Schedule background execution
    async def run_analysis_task():
        from app.core.database import get_db_context
        async with get_db_context() as session:
            analysis_service = AnalysisService(session)
            await analysis_service.run_analysis(run.run_id)

    background_tasks.add_task(run_analysis_task)

    return AnalysisRunResponse(
        run_id=run.run_id,
        name=run.name,
        description=run.description,
        status=run.status,
        total_conversations=run.total_conversations,
        processed_conversations=run.processed_conversations,
        total_clusters=run.total_clusters,
        progress_percentage=run.progress_percentage,
        current_stage=run.current_stage,
        error_message=run.error_message,
        started_at=run.started_at,
        completed_at=run.completed_at,
        created_at=run.created_at,
    )


@router.get("", response_model=List[AnalysisRunResponse])
async def list_analysis_runs(
    limit: int = Query(50, le=100),
    offset: int = Query(0, ge=0),
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """List all analysis runs."""
    service = AnalysisService(db)
    runs = await service.list_analysis_runs(
        limit=limit,
        offset=offset,
        status=status,
    )

    return [
        AnalysisRunResponse(
            run_id=run.run_id,
            name=run.name,
            description=run.description,
            status=run.status,
            total_conversations=run.total_conversations,
            processed_conversations=run.processed_conversations,
            total_clusters=run.total_clusters,
            progress_percentage=run.progress_percentage,
            current_stage=run.current_stage,
            error_message=run.error_message,
            started_at=run.started_at,
            completed_at=run.completed_at,
            created_at=run.created_at,
        )
        for run in runs
    ]


@router.get("/{run_id}", response_model=AnalysisRunResponse)
async def get_analysis_run(
    run_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get a specific analysis run."""
    service = AnalysisService(db)
    run = await service.get_analysis_run(run_id)

    if not run:
        raise HTTPException(status_code=404, detail="Analysis run not found")

    return AnalysisRunResponse(
        run_id=run.run_id,
        name=run.name,
        description=run.description,
        status=run.status,
        total_conversations=run.total_conversations,
        processed_conversations=run.processed_conversations,
        total_clusters=run.total_clusters,
        progress_percentage=run.progress_percentage,
        current_stage=run.current_stage,
        error_message=run.error_message,
        started_at=run.started_at,
        completed_at=run.completed_at,
        created_at=run.created_at,
    )


@router.get("/{run_id}/statistics")
async def get_analysis_statistics(
    run_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get detailed statistics for an analysis run."""
    service = AnalysisService(db)
    stats = await service.get_analysis_statistics(run_id)

    if not stats:
        raise HTTPException(status_code=404, detail="Analysis run not found")

    return stats


@router.delete("/{run_id}")
async def delete_analysis_run(
    run_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Delete an analysis run and all associated data."""
    service = AnalysisService(db)
    success = await service.delete_analysis_run(run_id)

    if not success:
        raise HTTPException(status_code=404, detail="Analysis run not found")

    return {"message": "Analysis run deleted successfully"}
