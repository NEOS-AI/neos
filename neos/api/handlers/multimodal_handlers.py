"""Multimodal API handlers - thin layer for FastAPI routes"""

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from typing import List, Optional
import uuid
import logging

from neos.api.models.multimodal_models import (
    MultimodalQueryResponse,
    ImageAnalysisResponse,
    SupportedTypesResponse
)
from neos.api.services.multimodal_service import MultimodalService
from neos.api.services.query_service import QueryService
from neos.api.dependencies.auth import get_current_active_user
from neos.database.models import User

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/query", response_model=MultimodalQueryResponse)
async def process_multimodal_query(
    background_tasks: BackgroundTasks,
    query: str = Form(..., description="사용자 쿼리"),
    files: List[UploadFile] = File(..., description="업로드할 파일들 (이미지, 문서, 오디오 등)"),
    user_id: Optional[str] = Form(
        None,
        description="Deprecated compatibility field; authenticated identity is used",
        deprecated=True,
    ),
    session_id: Optional[str] = Form(None, description="세션 ID"),
    language: Optional[str] = Form("ko", description="응답 언어 (ko/en)"),
    current_user: User = Depends(get_current_active_user),
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
        user_id = current_user.user_id

        # 사용자 생성/조회
        await QueryService.get_or_create_user(user_id)

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

        # UploadFile을 딕셔너리로 변환
        file_dicts = await MultimodalService.convert_upload_files_to_dict(files)

        # 멀티모달 쿼리 처리
        result = await MultimodalService.process_multimodal_query(
            query=query,
            file_dicts=file_dicts,
            user_id=user_id,
            session_id=session_id,
            language=language
        )

        return MultimodalQueryResponse(**result)

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
    user_id: Optional[str] = Form(
        None,
        description="Deprecated compatibility field; authenticated identity is used",
        deprecated=True,
    ),
    language: Optional[str] = Form("ko", description="응답 언어 (ko/en)"),
    current_user: User = Depends(get_current_active_user),
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
        user_id = current_user.user_id

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

        # 이미지 분석
        result = await MultimodalService.analyze_image(
            file_content=content,
            filename=image.filename,
            content_type=image.content_type,
            query=query,
            user_id=user_id,
            language=language
        )

        return ImageAnalysisResponse(**result)

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
        result = await MultimodalService.get_supported_types()
        return SupportedTypesResponse(**result)
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
        return await MultimodalService.check_health()
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "status": "unhealthy",
            "error": str(e)
        }
