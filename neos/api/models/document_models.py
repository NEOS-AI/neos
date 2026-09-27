"""Document API Pydantic models"""

from pydantic import BaseModel
from typing import Optional


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
