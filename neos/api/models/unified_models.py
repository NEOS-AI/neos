"""
통합 API 요청/응답 모델

문서 처리와 워크플로우를 통합하는 API 모델
"""

from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from enum import Enum
from datetime import datetime


class ProcessingMode(str, Enum):
    """처리 모드"""
    AUTO = "auto"  # 자동 감지 (문서 유무에 따라)
    TEXT_ONLY = "text_only"  # 텍스트 쿼리만
    DOCUMENT_ONLY = "document_only"  # 문서만
    DOCUMENT_WITH_QUERY = "document_with_query"  # 문서 + 쿼리


class DocumentInfo(BaseModel):
    """문서 정보"""
    filename: str
    mime_type: Optional[str] = None
    file_size: Optional[int] = None
    file_content: Optional[bytes] = None  # Base64로 인코딩된 문서
    file_path: Optional[str] = None  # 또는 파일 경로


class UnifiedProcessingRequest(BaseModel):
    """통합 처리 요청"""
    query: str = Field(..., description="사용자 질문")
    session_id: Optional[str] = Field(None, description="세션 ID")
    user_id: Optional[str] = Field(
        None,
        description="Deprecated compatibility field; authenticated identity is used",
        deprecated=True,
    )

    # 문서 정보 (선택)
    documents: Optional[List[DocumentInfo]] = Field(None, description="처리할 문서 목록")

    # 처리 옵션
    mode: ProcessingMode = Field(ProcessingMode.AUTO, description="처리 모드")
    bypass_cache: bool = Field(False, description="캐시 우회 여부")
    enable_vision: bool = Field(True, description="Vision 분석 활성화")
    max_images_to_analyze: int = Field(10, description="최대 분석 이미지 수")

    # 스트리밍 옵션
    stream_options: Optional[Dict[str, Any]] = Field(None, description="스트리밍 옵션")

    class Config:
        json_schema_extra = {
            "example": {
                "query": "이 문서의 주요 내용을 요약해주세요",
                "documents": [
                    {
                        "filename": "report.pdf",
                        "mime_type": "application/pdf"
                    }
                ],
                "mode": "document_with_query",
                "enable_vision": True
            }
        }


class DocumentProcessingResult(BaseModel):
    """문서 처리 결과"""
    document_type: str
    page_count: Optional[int] = None
    slide_count: Optional[int] = None
    paragraph_count: Optional[int] = None

    # 추출된 정보
    text: str
    char_count: int
    word_count: int

    # 구조화된 데이터
    has_images: bool = False
    has_tables: bool = False
    image_count: int = 0
    table_count: int = 0

    # Vision 분석 결과
    vision_analysis: Optional[List[Dict[str, Any]]] = None

    # 메타데이터
    metadata: Dict[str, Any] = {}
    extraction_method: str


class UnifiedStreamEvent(BaseModel):
    """통합 스트리밍 이벤트"""
    event: str  # started, document_processing, node_started, completed 등
    session_id: str
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())

    # 진행 상황
    phase: Optional[str] = None  # "document_extraction", "workflow_execution"
    progress_percent: int = 0

    # 이벤트 데이터
    content: Optional[str] = None
    data: Dict[str, Any] = {}
    error: Optional[str] = None

    # 문서 처리 정보
    document_processing: Optional[DocumentProcessingResult] = None

    # 워크플로우 정보
    node_name: Optional[str] = None
    agent_name: Optional[str] = None
    execution_time_ms: Optional[int] = None


class UnifiedProcessingResponse(BaseModel):
    """통합 처리 응답"""
    success: bool
    session_id: str

    # 문서 처리 결과
    documents_processed: Optional[List[DocumentProcessingResult]] = None

    # 워크플로우 결과
    response: str
    quality_score: float

    # 실행 정보
    execution_time_ms: int
    cache_hit: bool = False

    # 메타데이터
    metadata: Dict[str, Any] = {}
    errors: List[str] = []
