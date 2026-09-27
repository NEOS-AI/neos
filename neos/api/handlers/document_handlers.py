"""Document API handlers - thin layer for FastAPI routes"""

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    UploadFile,
    File,
    Form,
)
from typing import Optional
import json
import logging

from neos.api.models.document_models import (
    DocumentUploadResponse,
    DocumentInfo
)
from neos.api.dependencies.auth import get_current_active_user
from neos.api.dependencies.resource_access import get_owned_document
from neos.api.services.document_service import DocumentService
from neos.database.models import Document, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/upload", response_model=DocumentUploadResponse)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    user_id: Optional[str] = Form(None, deprecated=True),
    metadata: Optional[str] = Form(None),
    current_user: User = Depends(get_current_active_user),
):
    """
    문서 업로드 및 처리

    - **file**: 업로드할 파일
    - **user_id**: 사용자 ID (deprecated, ignored)
    - **metadata**: 추가 메타데이터 (JSON 문자열)
    """
    try:
        # 메타데이터 파싱
        metadata_dict = json.loads(metadata) if metadata else {}

        # 파일 읽기
        file_content = await file.read()

        # 문서 처리
        document = await DocumentService.upload_and_process_document(
            file_content=file_content,
            filename=file.filename,
            user_id=current_user.user_id,
            metadata=metadata_dict,
            mime_type=file.content_type,
        )

        return DocumentUploadResponse(
            document_id=document.id,
            filename=document.filename,
            status=document.processing_status,
            message="Document uploaded and processing started",
        )

    except ValueError as e:
        logger.error(f"Validation error: {e}")
        raise HTTPException(status_code=400, detail=str(e))

    except Exception as e:
        logger.error(f"Document upload failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Document upload failed")


@router.get("/{document_id}", response_model=DocumentInfo)
async def get_document(
    document_id: int,
    owned_document: Document = Depends(get_owned_document),
):
    """
    문서 상세 정보 조회

    - **document_id**: 문서 ID
    """
    try:
        document = owned_document

        return DocumentInfo(
            id=document.id,
            filename=document.filename,
            original_filename=document.original_filename,
            file_size=document.file_size,
            mime_type=document.mime_type,
            storage_provider=document.storage_provider,
            storage_url=document.storage_url,
            processing_status=document.processing_status,
            kg_extracted=document.kg_extracted,
            embedding_processed=document.embedding_processed,
            fts_indexed=document.fts_indexed,
            created_at=document.created_at.isoformat(),
            metadata=document.metadata or {},
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get document: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get document")


@router.delete("/{document_id}")
async def delete_document(
    document_id: int,
    current_user: User = Depends(get_current_active_user),
    owned_document: Document = Depends(get_owned_document),
):
    """
    문서 삭제

    - **document_id**: 문서 ID
    """
    try:
        success = await DocumentService.delete_document_for_user(
            owned_document.id,
            current_user.user_id,
        )

        if not success:
            raise HTTPException(status_code=404, detail="Resource not found")

        return {"message": "Document deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete document: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to delete document")
