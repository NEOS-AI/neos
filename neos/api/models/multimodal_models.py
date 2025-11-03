"""Multimodal API Pydantic models"""

from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional


class MultimodalQueryResponse(BaseModel):
    """멀티모달 쿼리 응답"""

    success: bool
    response: str
    session_id: str
    input_type: str
    metadata: Dict[str, Any]
    processing_time_ms: float
    vision_analysis: Optional[Dict[str, Any]] = None
    extracted_text: Optional[str] = None
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class ImageAnalysisResponse(BaseModel):
    """이미지 분석 전용 응답"""

    success: bool
    filename: str
    description: Optional[str] = None
    objects: List[str] = Field(default_factory=list)
    ocr_text: Optional[str] = None
    image_metadata: Dict[str, Any]
    vision_provider: Optional[str] = None
    confidence: Optional[float] = None
    processing_time_ms: float


class SupportedTypesResponse(BaseModel):
    """지원하는 파일 타입 응답"""

    supported_types: Dict[str, List[str]]
    vision_enabled: bool
    vision_providers: List[str]
