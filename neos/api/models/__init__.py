"""API Pydantic models package"""

from neos.api.models.query_models import (
    QueryRequest,
    QueryResponse,
    HealthCheckResponse,
    TrendingQuery,
    RelatedQuery,
    HyperResearchReportResponse,
    HyperResearchReportSummary,
    HyperResearchReportsListResponse
)

from neos.api.models.document_models import (
    DocumentUploadResponse,
    DocumentInfo,
    DocumentListResponse,
    ChunkInfo,
    EntityInfo,
    DocumentSearchRequest,
    DocumentSearchResult,
    DocumentSearchResponse
)

from neos.api.models.multimodal_models import (
    MultimodalQueryResponse,
    ImageAnalysisResponse,
    SupportedTypesResponse
)

__all__ = [
    # Query models
    "QueryRequest",
    "QueryResponse",
    "HealthCheckResponse",
    "TrendingQuery",
    "RelatedQuery",
    "HyperResearchReportResponse",
    "HyperResearchReportSummary",
    "HyperResearchReportsListResponse",
    # Document models
    "DocumentUploadResponse",
    "DocumentInfo",
    "DocumentListResponse",
    "ChunkInfo",
    "EntityInfo",
    "DocumentSearchRequest",
    "DocumentSearchResult",
    "DocumentSearchResponse",
    # Multimodal models
    "MultimodalQueryResponse",
    "ImageAnalysisResponse",
    "SupportedTypesResponse",
]
