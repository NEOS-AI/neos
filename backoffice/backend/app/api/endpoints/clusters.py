"""Cluster management and query endpoints."""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.cluster_service import ClusterService

router = APIRouter()


class ClusterResponse(BaseModel):
    """Response model for a cluster."""

    id: str
    name: str
    description: Optional[str]
    level: int
    path: str
    conversation_count: int
    unique_user_count: int
    keywords: Optional[List[str]]
    top_facets: Optional[Dict[str, Any]]
    centroid: Optional[Dict[str, float]]
    children: List["ClusterResponse"] = []

    class Config:
        from_attributes = True


ClusterResponse.model_rebuild()


class UMAPPoint(BaseModel):
    """Response model for UMAP data point."""

    conversation_id: int
    x: float
    y: float
    cluster_id: Optional[int]
    task_type: Optional[str]
    language: Optional[str]


class TrendingTopic(BaseModel):
    """Response model for trending topic."""

    name: str
    count: int
    keywords: List[str]
    id: str


@router.get("/hierarchy/{analysis_run_id}")
async def get_cluster_hierarchy(
    analysis_run_id: int,
    max_depth: Optional[int] = Query(None, ge=1, le=10),
    db: AsyncSession = Depends(get_db),
):
    """Get the full cluster hierarchy for an analysis run."""
    service = ClusterService(db)
    hierarchy = await service.get_cluster_hierarchy(
        analysis_run_id=analysis_run_id,
        max_depth=max_depth,
    )
    return {"hierarchy": hierarchy}


@router.get("/{cluster_id}")
async def get_cluster(
    cluster_id: str,
    include_children: bool = False,
    db: AsyncSession = Depends(get_db),
):
    """Get a specific cluster by ID."""
    service = ClusterService(db)
    cluster = await service.get_cluster(
        cluster_id=cluster_id,
        include_children=include_children,
    )

    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")

    return {
        "id": cluster.cluster_id,
        "name": cluster.name,
        "description": cluster.description,
        "level": cluster.level,
        "path": cluster.path,
        "conversation_count": cluster.conversation_count,
        "unique_user_count": cluster.unique_user_count,
        "keywords": cluster.keywords,
        "top_facets": cluster.top_facets,
        "centroid": {
            "x": cluster.centroid_x,
            "y": cluster.centroid_y,
        } if cluster.centroid_x is not None else None,
    }


@router.get("/{cluster_id}/conversations")
async def get_cluster_conversations(
    cluster_id: str,
    limit: int = Query(50, le=100),
    offset: int = Query(0, ge=0),
    include_facets: bool = True,
    db: AsyncSession = Depends(get_db),
):
    """Get conversations belonging to a cluster."""
    service = ClusterService(db)
    conversations = await service.get_cluster_conversations(
        cluster_id=cluster_id,
        limit=limit,
        offset=offset,
        include_facets=include_facets,
    )
    return {"conversations": conversations, "count": len(conversations)}


@router.get("/umap/{analysis_run_id}")
async def get_umap_data(
    analysis_run_id: int,
    sample_size: int = Query(5000, le=10000),
    db: AsyncSession = Depends(get_db),
):
    """Get UMAP coordinates for visualization."""
    service = ClusterService(db)
    data = await service.get_umap_data(
        analysis_run_id=analysis_run_id,
        sample_size=sample_size,
    )
    return {"points": data, "count": len(data)}


@router.get("/facets/{analysis_run_id}/{facet_name}")
async def get_facet_distribution(
    analysis_run_id: int,
    facet_name: str,
    db: AsyncSession = Depends(get_db),
):
    """Get distribution of a specific facet."""
    service = ClusterService(db)
    distribution = await service.get_facet_distribution(
        analysis_run_id=analysis_run_id,
        facet_name=facet_name,
    )
    return {"facet": facet_name, "distribution": distribution}


@router.get("/search/{analysis_run_id}")
async def search_clusters(
    analysis_run_id: int,
    q: str = Query(..., min_length=1),
    limit: int = Query(20, le=50),
    db: AsyncSession = Depends(get_db),
):
    """Search clusters by name or keywords."""
    service = ClusterService(db)
    results = await service.search_clusters(
        analysis_run_id=analysis_run_id,
        query=q,
        limit=limit,
    )
    return {"results": results, "count": len(results)}


@router.get("/trending/{analysis_run_id}")
async def get_trending_topics(
    analysis_run_id: int,
    limit: int = Query(10, le=50),
    db: AsyncSession = Depends(get_db),
):
    """Get trending topics from cluster analysis."""
    service = ClusterService(db)
    topics = await service.get_trending_topics(
        analysis_run_id=analysis_run_id,
        limit=limit,
    )
    return {"topics": topics}


class CompareRequest(BaseModel):
    """Request model for cluster comparison."""

    cluster_ids: List[str]


@router.post("/compare")
async def compare_clusters(
    request: CompareRequest,
    db: AsyncSession = Depends(get_db),
):
    """Compare multiple clusters."""
    if len(request.cluster_ids) < 2:
        raise HTTPException(
            status_code=400,
            detail="At least 2 cluster IDs required for comparison",
        )

    if len(request.cluster_ids) > 5:
        raise HTTPException(
            status_code=400,
            detail="Maximum 5 clusters can be compared at once",
        )

    service = ClusterService(db)
    comparison = await service.compare_clusters(request.cluster_ids)
    return comparison
