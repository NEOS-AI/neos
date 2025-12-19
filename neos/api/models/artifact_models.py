"""Artifact/Document API Pydantic Models"""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
import uuid


class CreateDocumentRequest(BaseModel):
    """문서 생성 요청"""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Document ID (UUID)")
    title: str = Field(..., min_length=1, max_length=500, description="문서 제목")
    content: Optional[str] = Field(None, description="문서 내용")
    kind: str = Field("text", description="문서 타입 (text, code, image, sheet)")

    class Config:
        json_schema_extra = {
            "example": {
                "id": "550e8400-e29b-41d4-a716-446655440000",
                "title": "My First Document",
                "content": "This is the content of my document",
                "kind": "text"
            }
        }


class DocumentResponse(BaseModel):
    """문서 응답"""
    id: str
    created_at: datetime
    title: str
    content: Optional[str]
    kind: str
    user_id: str

    class Config:
        from_attributes = True
        json_schema_extra = {
            "example": {
                "id": "550e8400-e29b-41d4-a716-446655440000",
                "created_at": "2024-01-01T00:00:00",
                "title": "My First Document",
                "content": "This is the content",
                "kind": "text",
                "user_id": "user_abc123"
            }
        }


class SuggestionRequest(BaseModel):
    """제안 생성 요청"""
    document_id: str = Field(..., description="Document ID")
    document_created_at: datetime = Field(..., description="Document created timestamp")
    original_text: str = Field(..., min_length=1, description="원본 텍스트")
    suggested_text: str = Field(..., min_length=1, description="제안 텍스트")
    description: Optional[str] = Field(None, description="제안 설명")

    class Config:
        json_schema_extra = {
            "example": {
                "document_id": "550e8400-e29b-41d4-a716-446655440000",
                "document_created_at": "2024-01-01T00:00:00",
                "original_text": "This is wrong",
                "suggested_text": "This is correct",
                "description": "Fixed typo"
            }
        }


class SuggestionResponse(BaseModel):
    """제안 응답"""
    id: str
    document_id: str
    document_created_at: datetime
    original_text: str
    suggested_text: str
    description: Optional[str]
    is_resolved: bool
    user_id: str
    created_at: datetime

    class Config:
        from_attributes = True
        json_schema_extra = {
            "example": {
                "id": "660e8400-e29b-41d4-a716-446655440000",
                "document_id": "550e8400-e29b-41d4-a716-446655440000",
                "document_created_at": "2024-01-01T00:00:00",
                "original_text": "This is wrong",
                "suggested_text": "This is correct",
                "description": "Fixed typo",
                "is_resolved": False,
                "user_id": "user_abc123",
                "created_at": "2024-01-01T01:00:00"
            }
        }


class ResolveSuggestionRequest(BaseModel):
    """제안 해결 요청"""
    is_resolved: bool = Field(..., description="해결 여부")

    class Config:
        json_schema_extra = {
            "example": {
                "is_resolved": True
            }
        }
