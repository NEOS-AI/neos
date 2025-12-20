"""Artifact/Document API Handlers"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from datetime import datetime

from neos.database.connection import get_db
from neos.api.dependencies.auth import get_current_user
from neos.database.models import User
from neos.api.models.artifact_models import (
    CreateDocumentRequest,
    DocumentResponse,
    SuggestionRequest,
    SuggestionResponse,
    ResolveSuggestionRequest
)
from neos.api.services.artifact_service import ArtifactService


router = APIRouter(prefix="/documents", tags=["documents", "artifacts"])


@router.post("", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def create_document(
    doc_data: CreateDocumentRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    문서/아티팩트 생성

    - **id**: 문서 ID (UUID, 자동 생성 또는 지정)
    - **title**: 문서 제목
    - **content**: 문서 내용 (선택)
    - **kind**: 문서 타입 (text, code, image, sheet)

    같은 ID로 여러 버전을 생성할 수 있습니다 (created_at으로 구분).
    """
    service = ArtifactService(db)
    return await service.create_document(
        user_id=current_user.user_id,
        document_id=doc_data.id,
        title=doc_data.title,
        content=doc_data.content,
        kind=doc_data.kind
    )


@router.get("/{document_id}", response_model=List[DocumentResponse])
async def get_document_versions(
    document_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    문서의 모든 버전 조회

    - **document_id**: 문서 ID (UUID)

    Returns:
        문서의 모든 버전 목록 (최신 순)
    """
    service = ArtifactService(db)
    return await service.get_document_versions(document_id, current_user.user_id)


@router.get("/{document_id}/latest", response_model=DocumentResponse)
async def get_latest_document(
    document_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    최신 문서 버전 조회

    - **document_id**: 문서 ID (UUID)

    Returns:
        최신 버전의 문서
    """
    service = ArtifactService(db)
    return await service.get_latest_document(document_id, current_user.user_id)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document_versions(
    document_id: str,
    timestamp: Optional[datetime] = Query(None, description="이 시간 이후의 버전을 삭제 (없으면 모두 삭제)"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    특정 시간 이후의 문서 버전 삭제

    - **document_id**: 문서 ID (UUID)
    - **timestamp**: 삭제 기준 시간 (query parameter, 선택)

    timestamp가 없으면 해당 document_id의 모든 버전을 삭제합니다.
    """
    service = ArtifactService(db)
    await service.delete_documents_after_timestamp(
        document_id,
        timestamp,
        current_user.user_id
    )
    return None


@router.post("/suggestions", response_model=List[SuggestionResponse])
async def create_suggestions(
    suggestions_data: List[SuggestionRequest],
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    문서 제안 생성 (여러 개 동시 생성 가능)

    - **suggestions_data**: 제안 목록

    Returns:
        생성된 제안 목록
    """
    service = ArtifactService(db)
    return await service.create_suggestions(suggestions_data, current_user.user_id)


@router.get("/{document_id}/suggestions", response_model=List[SuggestionResponse])
async def get_suggestions(
    document_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    문서의 제안 목록 조회

    - **document_id**: 문서 ID (UUID)

    Returns:
        해당 문서의 모든 제안 목록
    """
    service = ArtifactService(db)
    return await service.get_suggestions_by_document(document_id, current_user.user_id)


@router.patch("/suggestions/{suggestion_id}/resolve", response_model=SuggestionResponse)
async def resolve_suggestion(
    suggestion_id: str,
    resolve_data: ResolveSuggestionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    제안 해결 상태 변경

    - **suggestion_id**: 제안 ID (UUID)
    - **is_resolved**: 해결 여부 (true/false)

    Returns:
        업데이트된 제안
    """
    service = ArtifactService(db)
    return await service.resolve_suggestion(
        suggestion_id,
        resolve_data.is_resolved,
        current_user.user_id
    )
