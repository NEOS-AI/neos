"""
멀티모달 API 라우터

이미지, 문서, 오디오 등 다양한 파일과 텍스트를 함께 처리하는 API 엔드포인트
"""

from fastapi import APIRouter, HTTPException, BackgroundTasks, UploadFile, File, Form
from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional
import uuid
from datetime import datetime
import logging

from neos.workflow.multimodal_workflow import MultiModalWorkflow
from neos.workflow.pipelines import InputType
from neos.database.connection import db_manager
from neos.api.routes import get_or_create_user

logger = logging.getLogger(__name__)

# API 라우터 생성
router = APIRouter()


# ============================================================================
# Pydantic Models
# ============================================================================


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


# ============================================================================
# Helper Functions
# ============================================================================


async def convert_upload_files_to_dict(files: List[UploadFile]) -> List[Dict[str, Any]]:
    """
    UploadFile 객체들을 딕셔너리 형태로 변환

    Args:
        files: FastAPI UploadFile 객체 리스트

    Returns:
        변환된 파일 정보 딕셔너리 리스트
    """
    file_dicts = []

    for file in files:
        try:
            # 파일 내용 읽기
            content = await file.read()

            file_dict = {
                "filename": file.filename,
                "file_content": content,
                "mime_type": file.content_type,
                "file_size": len(content),
                "file_path": None,  # 업로드된 파일은 경로 없음
                "url": None
            }

            file_dicts.append(file_dict)

            # 파일 포인터 리셋 (혹시 모를 재사용을 위해)
            await file.seek(0)

        except Exception as e:
            logger.error(f"Failed to process file {file.filename}: {e}")
            raise HTTPException(
                status_code=400,
                detail=f"Failed to read file {file.filename}: {str(e)}"
            )

    return file_dicts


def extract_vision_analysis(result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    워크플로우 결과에서 Vision 분석 정보 추출

    Args:
        result: MultiModalWorkflow 실행 결과

    Returns:
        Vision 분석 정보 (있을 경우)
    """
    try:
        metadata = result.get("result", {}).get("metadata", {})

        # Vision 관련 정보 추출
        vision_info = {}

        if "vision_analysis" in metadata:
            vision_info["vision_analysis"] = metadata["vision_analysis"]

        if "image_description" in metadata:
            vision_info["description"] = metadata["image_description"]

        if "detected_objects" in metadata:
            vision_info["objects"] = metadata["detected_objects"]

        if "ocr_text" in metadata:
            vision_info["ocr_text"] = metadata["ocr_text"]

        if "vision_provider" in metadata:
            vision_info["provider"] = metadata["vision_provider"]

        if "confidence" in metadata:
            vision_info["confidence"] = metadata["confidence"]

        return vision_info if vision_info else None

    except Exception as e:
        logger.warning(f"Failed to extract vision analysis: {e}")
        return None


# ============================================================================
# API Endpoints
# ============================================================================


@router.post("/query", response_model=MultimodalQueryResponse)
async def process_multimodal_query(
    background_tasks: BackgroundTasks,
    query: str = Form(..., description="사용자 쿼리"),
    files: List[UploadFile] = File(..., description="업로드할 파일들 (이미지, 문서, 오디오 등)"),
    user_id: Optional[str] = Form(None, description="사용자 ID"),
    session_id: Optional[str] = Form(None, description="세션 ID"),
    language: Optional[str] = Form("ko", description="응답 언어 (ko/en)"),
):
    """
    멀티모달 쿼리 처리 (이미지 + 텍스트)

    이 엔드포인트는 텍스트 쿼리와 함께 여러 파일을 업로드하여 처리합니다.
    Vision 모델을 사용하여 이미지를 분석하고, 텍스트와 결합하여 응답을 생성합니다.

    **지원 파일 형식:**
    - 이미지: jpg, jpeg, png, gif, webp, bmp
    - 문서: pdf, docx, xlsx, pptx, txt, md, csv
    - 오디오: mp3, wav, ogg, flac, m4a, webm

    **사용 예시:**
    ```python
    import requests

    files = [("files", open("image.jpg", "rb"))]
    data = {
        "query": "이 이미지에 무엇이 보이나요?",
        "user_id": "user123",
        "language": "ko"
    }

    response = requests.post(
        "http://localhost:8518/api/v1/multimodal/query",
        files=files,
        data=data
    )
    print(response.json())
    ```
    """
    try:
        # 세션 ID 생성
        session_id = session_id or str(uuid.uuid4())
        user_id = user_id or f"anonymous_{uuid.uuid4().hex[:8]}"

        # 사용자 생성/조회
        await get_or_create_user(user_id)

        # 파일이 없으면 에러
        if not files or len(files) == 0:
            raise HTTPException(
                status_code=400,
                detail="At least one file is required for multimodal query"
            )

        # 파일 크기 제한 체크 (최대 50MB per file)
        MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
        for file in files:
            content = await file.read()
            await file.seek(0)  # 포인터 리셋

            if len(content) > MAX_FILE_SIZE:
                raise HTTPException(
                    status_code=400,
                    detail=f"File {file.filename} exceeds maximum size of 50MB"
                )

        logger.info(f"[Multimodal API] Processing query with {len(files)} file(s)")

        # UploadFile을 딕셔너리로 변환
        file_dicts = await convert_upload_files_to_dict(files)

        # MultiModalWorkflow 초기화 및 실행
        workflow = MultiModalWorkflow()

        start_time = datetime.utcnow()

        result = await workflow.process(
            query=query,
            files=file_dicts,
            user_id=user_id,
            session_id=session_id,
            language=language
        )

        end_time = datetime.utcnow()
        processing_time = (end_time - start_time).total_seconds() * 1000

        if not result.get("success", False):
            error_msg = result.get('error', 'Unknown error')
            logger.error(f"[Multimodal API] Workflow failed: {error_msg}")
            logger.error(f"[Multimodal API] Full result: {result}")
            raise HTTPException(
                status_code=500,
                detail=f"Workflow execution failed: {error_msg}"
            )

        # 응답 데이터 추출
        workflow_result = result.get("result", {})
        final_response = workflow_result.get("final_response", "")

        # 메타데이터가 없으면 빈 딕셔너리
        if not final_response and "response" in workflow_result:
            final_response = workflow_result["response"]

        metadata = workflow_result.get("response_metadata", {})
        if not metadata:
            metadata = workflow_result.get("metadata", {})

        # Vision 분석 정보 추출
        vision_analysis = extract_vision_analysis(result)

        # 추출된 텍스트 정보
        extracted_text = metadata.get("extracted_text")

        # 에러 및 경고 수집
        errors = workflow_result.get("errors", [])
        warnings = []

        # 입력 타입
        input_type = result.get("input_type", "unknown")

        # 응답 생성
        response = MultimodalQueryResponse(
            success=True,
            response=final_response,
            session_id=session_id,
            input_type=input_type,
            metadata=metadata,
            processing_time_ms=processing_time,
            vision_analysis=vision_analysis,
            extracted_text=extracted_text,
            errors=[str(e) for e in errors] if errors else [],
            warnings=warnings
        )

        logger.info(f"[Multimodal API] Successfully processed query in {processing_time:.0f}ms")

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Multimodal API] Error processing query: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to process multimodal query: {str(e)}"
        )


@router.post("/image/analyze", response_model=ImageAnalysisResponse)
async def analyze_image(
    image: UploadFile = File(..., description="분석할 이미지 파일"),
    query: Optional[str] = Form(None, description="이미지에 대한 질문 (선택)"),
    user_id: Optional[str] = Form(None, description="사용자 ID"),
    language: Optional[str] = Form("ko", description="응답 언어 (ko/en)"),
):
    """
    이미지 단독 분석 (Vision 모델 전용)

    이 엔드포인트는 이미지만 업로드하여 Vision 모델로 분석합니다.
    전체 워크플로우 없이 빠르게 이미지 내용을 파악할 수 있습니다.

    **사용 예시:**
    ```python
    import requests

    files = {"image": open("photo.jpg", "rb")}
    data = {"query": "이 사진에 무엇이 있나요?"}

    response = requests.post(
        "http://localhost:8518/api/v1/multimodal/image/analyze",
        files=files,
        data=data
    )
    print(response.json())
    ```
    """
    try:
        user_id = user_id or f"anonymous_{uuid.uuid4().hex[:8]}"

        # 파일 타입 체크
        if not image.content_type or not image.content_type.startswith("image/"):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid file type. Expected image, got {image.content_type}"
            )

        # 파일 크기 체크 (최대 20MB)
        content = await image.read()
        await image.seek(0)

        if len(content) > 20 * 1024 * 1024:  # 20MB
            raise HTTPException(
                status_code=400,
                detail="Image file exceeds maximum size of 20MB"
            )

        logger.info(f"[Image Analysis API] Analyzing image: {image.filename}")

        # 파일 딕셔너리 생성
        file_dict = {
            "filename": image.filename,
            "file_content": content,
            "mime_type": image.content_type,
            "file_size": len(content),
            "file_path": None,
            "url": None
        }

        # MultiModalWorkflow로 처리 (이미지만)
        workflow = MultiModalWorkflow()

        start_time = datetime.utcnow()

        # 쿼리가 없으면 기본 분석 요청
        analysis_query = query or "이 이미지를 자세히 분석해주세요."

        result = await workflow.process(
            query=analysis_query,
            files=[file_dict],
            user_id=user_id,
            session_id=str(uuid.uuid4()),
            language=language
        )

        end_time = datetime.utcnow()
        processing_time = (end_time - start_time).total_seconds() * 1000

        if not result.get("success", False):
            raise HTTPException(
                status_code=500,
                detail=f"Image analysis failed: {result.get('error', 'Unknown error')}"
            )

        # Vision 분석 정보 추출
        vision_info = extract_vision_analysis(result)

        metadata = result.get("result", {}).get("metadata", {})

        # 응답 생성
        response = ImageAnalysisResponse(
            success=True,
            filename=image.filename,
            description=vision_info.get("description") if vision_info else None,
            objects=vision_info.get("objects", []) if vision_info else [],
            ocr_text=vision_info.get("ocr_text") if vision_info else None,
            image_metadata={
                "width": metadata.get("width"),
                "height": metadata.get("height"),
                "format": metadata.get("format"),
                "mime_type": image.content_type,
                "file_size": len(content),
            },
            vision_provider=vision_info.get("provider") if vision_info else None,
            confidence=vision_info.get("confidence") if vision_info else None,
            processing_time_ms=processing_time
        )

        logger.info(f"[Image Analysis API] Successfully analyzed image in {processing_time:.0f}ms")

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Image Analysis API] Error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to analyze image: {str(e)}"
        )


@router.get("/supported-types", response_model=SupportedTypesResponse)
async def get_supported_types():
    """
    지원하는 파일 타입 목록 조회

    멀티모달 API가 지원하는 모든 파일 형식과 Vision 모델 정보를 반환합니다.
    """
    try:
        from neos.config.settings import settings

        # 지원하는 파일 타입들
        supported_types = {
            "image": [".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"],
            "document": [".pdf", ".docx", ".xlsx", ".pptx", ".txt", ".md", ".csv"],
            "audio": [".mp3", ".wav", ".ogg", ".flac", ".m4a", ".webm"],
        }

        # Vision 설정 정보
        vision_enabled = settings.VISION_ENABLED
        vision_providers = []

        if vision_enabled:
            if settings.OPENAI_API_KEY:
                vision_providers.append("gpt4o")
            if settings.ANTHROPIC_API_KEY:
                vision_providers.append("claude")

        return SupportedTypesResponse(
            supported_types=supported_types,
            vision_enabled=vision_enabled,
            vision_providers=vision_providers
        )

    except Exception as e:
        logger.error(f"Failed to get supported types: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve supported types: {str(e)}"
        )


@router.get("/health")
async def multimodal_health_check():
    """
    멀티모달 API 헬스 체크

    MultiModalWorkflow와 Vision 모델의 상태를 확인합니다.
    """
    try:
        from neos.config.settings import settings
        from neos.workflow.pipelines import VisionModelFactory

        health_info = {
            "status": "healthy",
            "multimodal_workflow": "available",
            "vision_enabled": settings.VISION_ENABLED,
            "vision_models": {}
        }

        # Vision 모델 가용성 체크
        if settings.VISION_ENABLED:
            try:
                # Factory를 통한 모델 생성 테스트
                vision_model = VisionModelFactory.create(provider="auto")
                if vision_model:
                    is_available = await vision_model.is_available()
                    health_info["vision_models"]["primary"] = {
                        "available": is_available,
                        "provider": type(vision_model).__name__
                    }
                else:
                    health_info["vision_models"]["primary"] = {
                        "available": False,
                        "error": "No vision model available"
                    }
            except Exception as e:
                health_info["vision_models"]["error"] = str(e)
                health_info["status"] = "degraded"

        return health_info

    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "status": "unhealthy",
            "error": str(e)
        }
