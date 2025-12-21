"""Artifact/Document Service - 문서 및 제안 비즈니스 로직"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, delete
from typing import List, Optional
from datetime import datetime
from fastapi import HTTPException, status
import uuid as uuid_lib

from neos.database.models import ArtifactDocument, Suggestion
from neos.api.models.artifact_models import (
    DocumentResponse,
    SuggestionRequest,
    SuggestionResponse
)


class ArtifactService:
    """Artifact/문서 서비스"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_document(
        self,
        user_id: str,
        document_id: str,
        title: str,
        content: Optional[str],
        kind: str
    ) -> DocumentResponse:
        """
        문서 생성

        Args:
            user_id: 사용자 ID
            document_id: 문서 ID (UUID 문자열)
            title: 문서 제목
            content: 문서 내용
            kind: 문서 타입 (text, code, image, sheet)

        Returns:
            DocumentResponse: 생성된 문서
        """
        # UUID 변환
        try:
            doc_uuid = uuid_lib.UUID(document_id)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid document ID format: {document_id}"
            )

        # kind 값 검증
        valid_kinds = ['text', 'code', 'image', 'sheet']
        if kind not in valid_kinds:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid kind: {kind}. Must be one of {valid_kinds}"
            )

        # 문서 생성
        new_document = ArtifactDocument(
            id=doc_uuid,
            created_at=datetime.utcnow(),
            title=title,
            content=content,
            kind=kind,
            user_id=user_id
        )

        self.db.add(new_document)
        await self.db.commit()
        await self.db.refresh(new_document)

        return DocumentResponse(
            id=str(new_document.id),
            created_at=new_document.created_at,
            title=new_document.title,
            content=new_document.content,
            kind=new_document.kind,
            user_id=str(new_document.user_id)
        )


    async def get_document_versions(
        self,
        document_id: str,
        user_id: str
    ) -> List[DocumentResponse]:
        """
        문서의 모든 버전 조회

        Args:
            document_id: 문서 ID
            user_id: 사용자 ID

        Returns:
            List[DocumentResponse]: 문서 버전 목록 (created_at DESC 정렬)
        """
        try:
            doc_uuid = uuid_lib.UUID(document_id)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid document ID format: {document_id}"
            )

        query = select(ArtifactDocument).where(
            and_(
                ArtifactDocument.id == doc_uuid,
                ArtifactDocument.user_id == user_id
            )
        ).order_by(ArtifactDocument.created_at.desc())

        result = await self.db.execute(query)
        documents = result.scalars().all()

        if not documents:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found"
            )

        return [
            DocumentResponse(
                id=str(doc.id),
                created_at=doc.created_at,
                title=doc.title,
                content=doc.content,
                kind=doc.kind,
                user_id=str(doc.user_id)
            )
            for doc in documents
        ]

    async def get_latest_document(
        self,
        document_id: str,
        user_id: str
    ) -> DocumentResponse:
        """
        최신 문서 버전 조회

        Args:
            document_id: 문서 ID
            user_id: 사용자 ID

        Returns:
            DocumentResponse: 최신 문서
        """
        versions = await self.get_document_versions(document_id, user_id)
        if not versions:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found"
            )
        return versions[0]  # 이미 created_at DESC로 정렬됨

    async def delete_documents_after_timestamp(
        self,
        document_id: str,
        timestamp: Optional[datetime],
        user_id: str
    ) -> None:
        """
        특정 시간 이후의 문서 버전 삭제

        Args:
            document_id: 문서 ID
            timestamp: 삭제 기준 시간 (이 시간 이후의 버전을 삭제, None이면 모두 삭제)
            user_id: 사용자 ID
        """
        try:
            doc_uuid = uuid_lib.UUID(document_id)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid document ID format: {document_id}"
            )

        # 삭제할 문서 조회
        if timestamp:
            delete_query = delete(ArtifactDocument).where(
                and_(
                    ArtifactDocument.id == doc_uuid,
                    ArtifactDocument.user_id == user_id,
                    ArtifactDocument.created_at >= timestamp
                )
            )
        else:
            delete_query = delete(ArtifactDocument).where(
                and_(
                    ArtifactDocument.id == doc_uuid,
                    ArtifactDocument.user_id == user_id
                )
            )

        result = await self.db.execute(delete_query)
        await self.db.commit()

        if result.rowcount == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No documents found to delete"
            )

    async def create_suggestions(
        self,
        suggestions_data: List[SuggestionRequest],
        user_id: str
    ) -> List[SuggestionResponse]:
        """
        여러 제안 생성

        Args:
            suggestions_data: 제안 목록
            user_id: 사용자 ID

        Returns:
            List[SuggestionResponse]: 생성된 제안 목록
        """
        created_suggestions = []

        for suggestion_data in suggestions_data:
            # UUID 변환
            try:
                doc_uuid = uuid_lib.UUID(suggestion_data.document_id)
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid document ID format: {suggestion_data.document_id}"
                )

            # 문서 존재 확인
            doc_query = select(ArtifactDocument).where(
                and_(
                    ArtifactDocument.id == doc_uuid,
                    ArtifactDocument.created_at == suggestion_data.document_created_at,
                    ArtifactDocument.user_id == user_id
                )
            )
            doc_result = await self.db.execute(doc_query)
            document = doc_result.scalar_one_or_none()

            if not document:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Document not found: {suggestion_data.document_id}"
                )

            # 제안 생성
            new_suggestion = Suggestion(
                id=uuid_lib.uuid4(),
                document_id=doc_uuid,
                document_created_at=suggestion_data.document_created_at,
                original_text=suggestion_data.original_text,
                suggested_text=suggestion_data.suggested_text,
                description=suggestion_data.description,
                is_resolved=False,
                user_id=user_id,
                created_at=datetime.utcnow()
            )

            self.db.add(new_suggestion)
            created_suggestions.append(new_suggestion)

        await self.db.commit()

        # Refresh all suggestions
        for suggestion in created_suggestions:
            await self.db.refresh(suggestion)

        return [
            SuggestionResponse(
                id=str(suggestion.id),
                document_id=str(suggestion.document_id),
                document_created_at=suggestion.document_created_at,
                original_text=suggestion.original_text,
                suggested_text=suggestion.suggested_text,
                description=suggestion.description,
                is_resolved=suggestion.is_resolved,
                user_id=str(suggestion.user_id),
                created_at=suggestion.created_at
            )
            for suggestion in created_suggestions
        ]

    async def get_suggestions_by_document(
        self,
        document_id: str,
        user_id: str
    ) -> List[SuggestionResponse]:
        """
        문서의 제안 목록 조회

        Args:
            document_id: 문서 ID
            user_id: 사용자 ID

        Returns:
            List[SuggestionResponse]: 제안 목록
        """
        try:
            doc_uuid = uuid_lib.UUID(document_id)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid document ID format: {document_id}"
            )

        # 문서 소유권 확인
        doc_query = select(ArtifactDocument).where(
            and_(
                ArtifactDocument.id == doc_uuid,
                ArtifactDocument.user_id == user_id
            )
        ).limit(1)
        doc_result = await self.db.execute(doc_query)
        if not doc_result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found"
            )

        # 제안 조회
        query = select(Suggestion).where(
            Suggestion.document_id == doc_uuid
        ).order_by(Suggestion.created_at.desc())

        result = await self.db.execute(query)
        suggestions = result.scalars().all()

        return [
            SuggestionResponse(
                id=str(suggestion.id),
                document_id=str(suggestion.document_id),
                document_created_at=suggestion.document_created_at,
                original_text=suggestion.original_text,
                suggested_text=suggestion.suggested_text,
                description=suggestion.description,
                is_resolved=suggestion.is_resolved,
                user_id=str(suggestion.user_id),
                created_at=suggestion.created_at
            )
            for suggestion in suggestions
        ]

    async def resolve_suggestion(
        self,
        suggestion_id: str,
        is_resolved: bool,
        user_id: str
    ) -> SuggestionResponse:
        """
        제안 해결 상태 변경

        Args:
            suggestion_id: 제안 ID
            is_resolved: 해결 여부
            user_id: 사용자 ID

        Returns:
            SuggestionResponse: 업데이트된 제안
        """
        try:
            sugg_uuid = uuid_lib.UUID(suggestion_id)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid suggestion ID format: {suggestion_id}"
            )

        # 제안 조회
        query = select(Suggestion).where(
            and_(
                Suggestion.id == sugg_uuid,
                Suggestion.user_id == user_id
            )
        )
        result = await self.db.execute(query)
        suggestion = result.scalar_one_or_none()

        if not suggestion:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Suggestion not found"
            )

        # 상태 업데이트
        suggestion.is_resolved = is_resolved
        await self.db.commit()
        await self.db.refresh(suggestion)

        return SuggestionResponse(
            id=str(suggestion.id),
            document_id=str(suggestion.document_id),
            document_created_at=suggestion.document_created_at,
            original_text=suggestion.original_text,
            suggested_text=suggestion.suggested_text,
            description=suggestion.description,
            is_resolved=suggestion.is_resolved,
            user_id=str(suggestion.user_id),
            created_at=suggestion.created_at
        )
