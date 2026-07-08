"""Document service layer - handles business logic"""

from typing import List, Optional, Dict, Any
from io import BytesIO
from sqlalchemy import select, func, text
import logging

from neos.database.connection import db_manager
from neos.database.models import Document, DocumentChunk, KnowledgeGraph
from neos.pipelines.document.document_processor import DocumentProcessor
from neos.utils.embeddings import embedding_manager

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
    async def list_documents(
        user_id: Optional[str] = None,
        status: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> Dict[str, Any]:
        """
        문서 목록 조회

        Args:
            user_id: 사용자 ID (필터)
            status: 처리 상태 (필터)
            skip: 오프셋
            limit: 최대 개수

        Returns:
            {"total": int, "documents": List[Document]}
        """
        # 쿼리 생성
        query = select(Document)

        if user_id:
            query = query.where(Document.user_id == user_id)

        if status:
            query = query.where(Document.processing_status == status)

        async with db_manager.get_session() as session:
            # 총 개수 조회
            count_query = select(func.count()).select_from(query.subquery())
            total_result = await session.execute(count_query)
            total = total_result.scalar()

            # 문서 조회
            query = query.offset(skip).limit(limit).order_by(Document.created_at.desc())
            result = await session.execute(query)
            documents = result.scalars().all()

        return {
            "total": total,
            "documents": documents
        }

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

    @staticmethod
    async def get_document_chunks(
        document_id: int,
        skip: int = 0,
        limit: int = 100
    ) -> List[DocumentChunk]:
        """
        문서의 청크 목록 조회

        Args:
            document_id: 문서 ID
            skip: 오프셋
            limit: 최대 개수

        Returns:
            DocumentChunk 리스트
        """
        query = (
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
            .order_by(DocumentChunk.chunk_index)
            .offset(skip)
            .limit(limit)
        )

        async with db_manager.get_session() as session:
            result = await session.execute(query)
            chunks = result.scalars().all()

        return chunks

    @staticmethod
    async def get_document_knowledge_graph(document_id: int) -> List[KnowledgeGraph]:
        """
        문서의 지식 그래프 조회

        Args:
            document_id: 문서 ID

        Returns:
            KnowledgeGraph 엔티티 리스트
        """
        query = select(KnowledgeGraph).where(
            KnowledgeGraph.document_id == document_id
        )

        async with db_manager.get_session() as session:
            result = await session.execute(query)
            entities = result.scalars().all()

        return entities

    @staticmethod
    async def search_documents(
        query: str,
        top_k: int = 10,
        user_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        문서 검색 (시맨틱 검색)

        Args:
            query: 검색 쿼리
            top_k: 반환할 결과 개수
            user_id: 사용자 ID (필터)

        Returns:
            검색 결과 리스트
        """
        # 쿼리 임베딩 생성
        query_embedding = await embedding_manager.get_embedding(query)

        # 벡터 유사도 검색 쿼리
        similarity_query = text(
            """
            SELECT
                dc.id as chunk_id,
                dc.document_id,
                d.filename as document_name,
                dc.chunk_text,
                dc.page_number,
                1 - (dc.embedding::halfvec(3072) <=> :query_embedding::halfvec(3072)) as similarity
            FROM document_chunks dc
            JOIN documents d ON dc.document_id = d.id
            WHERE d.embedding_processed = true
            """
        )

        # 사용자 필터 추가
        if user_id:
            similarity_query = text(
                str(similarity_query) + " AND d.user_id = :user_id"
            )

        similarity_query = text(
            str(similarity_query)
            + """
            ORDER BY dc.embedding::halfvec(3072) <=> :query_embedding::halfvec(3072)
            LIMIT :top_k
        """
        )

        # 쿼리 실행
        params = {
            "query_embedding": str(query_embedding),
            "top_k": top_k,
        }
        if user_id:
            params["user_id"] = user_id

        async with db_manager.get_session() as session:
            result = await session.execute(similarity_query, params)
            rows = result.fetchall()

        # 결과 변환
        search_results = []
        for row in rows:
            search_results.append({
                "chunk_id": row.chunk_id,
                "document_id": row.document_id,
                "document_name": row.document_name,
                "chunk_text": row.chunk_text,
                "similarity_score": float(row.similarity),
                "page_number": row.page_number,
            })

        return search_results
