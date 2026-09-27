"""Document service layer - handles business logic"""

from typing import Optional, Dict, Any
from io import BytesIO
from sqlalchemy import select
import logging

from neos.database.connection import db_manager
from neos.database.models import Document
from neos.pipelines.document.document_processor import DocumentProcessor

logger = logging.getLogger(__name__)


class DocumentService:
    """Service layer for document processing"""

    @staticmethod
    async def upload_and_process_document(
        file_content: bytes,
        filename: str,
        user_id: str,
        metadata: Optional[Dict[str, Any]] = None,
        mime_type: Optional[str] = None
    ) -> Document:
        """
        문서 업로드 및 처리

        Args:
            file_content: 파일 내용 (바이트)
            filename: 파일명
            user_id: 사용자 ID
            metadata: 추가 메타데이터
            mime_type: MIME 타입

        Returns:
            생성된 Document 객체
        """
        file_obj = BytesIO(file_content)
        processor = DocumentProcessor()

        document = await processor.process_document(
            file_obj=file_obj,
            filename=filename,
            user_id=user_id,
            metadata=metadata or {},
            mime_type=mime_type,
        )

        return document

    @staticmethod
    async def get_document_by_id(document_id: int) -> Optional[Document]:
        """
        문서 상세 정보 조회

        Args:
            document_id: 문서 ID

        Returns:
            Document 객체 또는 None
        """
        async with db_manager.get_session() as session:
            result = await session.execute(
                select(Document).where(Document.id == document_id)
            )
            document = result.scalar_one_or_none()

        return document

    @staticmethod
    async def get_document_for_user(
        document_id: int,
        user_id: str,
    ) -> Optional[Document]:
        """Return a document only when it belongs to the authenticated user."""
        async with db_manager.get_session() as session:
            result = await session.execute(
                select(Document).where(
                    Document.id == document_id,
                    Document.user_id == user_id,
                )
            )
            return result.scalar_one_or_none()

    @staticmethod
    async def delete_document_for_user(document_id: int, user_id: str) -> bool:
        """Delete a document only after an owner-scoped lookup succeeds."""
        document = await DocumentService.get_document_for_user(document_id, user_id)
        if not document:
            return False
        processor = DocumentProcessor()
        return await processor.delete_document(document_id)

    @staticmethod
    async def delete_document(document_id: int) -> bool:
        """
        문서 삭제

        Args:
            document_id: 문서 ID

        Returns:
            성공 여부
        """
        processor = DocumentProcessor()
        success = await processor.delete_document(document_id)
        return success
