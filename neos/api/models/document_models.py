"""Document API Pydantic models"""

from pydantic import BaseModel, Field
from typing import List, Optional


class DocumentUploadResponse(BaseModel):
    """문서 업로드 응답"""

    document_id: int
    filename: str
    status: str
    message: str


class DocumentInfo(BaseModel):
    """문서 정보"""

    id: int
    filename: str
    original_filename: str
    file_size: Optional[int]
    mime_type: Optional[str]
    storage_provider: str
    storage_url: Optional[str]
    processing_status: str
    kg_extracted: bool
    embedding_processed: bool
    fts_indexed: bool
    created_at: str
    metadata: dict

    class Config:
        from_attributes = True


class DocumentListResponse(BaseModel):
    """문서 목록 응답"""

    total: int
    documents: List[DocumentInfo]


class ChunkInfo(BaseModel):
    """청크 정보"""

    id: int
    chunk_index: int
    chunk_text: str
    chunk_size: int
    page_number: Optional[int]
    chunk_type: Optional[str]

    class Config:
        from_attributes = True


class EntityInfo(BaseModel):
    """엔티티 정보"""

    id: int
    entity_id: str
    entity_type: str
    entity_name: str
    entity_description: Optional[str]
    confidence_score: float
    properties: dict
    relations: list

    class Config:
        from_attributes = True


class DocumentSearchRequest(BaseModel):
    """문서 검색 요청"""

    query: str
    top_k: int = 10
    user_id: Optional[str] = Field(default=None, deprecated=True)


class DocumentSearchResult(BaseModel):
    """문서 검색 결과"""

    chunk_id: int
    document_id: int
    document_name: str
    chunk_text: str
    similarity_score: float
    page_number: Optional[int]


class DocumentSearchResponse(BaseModel):
    """문서 검색 응답"""

    query: str
    results: List[DocumentSearchResult]
