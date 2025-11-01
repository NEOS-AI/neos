"""API routes for document management"""

from fastapi import (
    APIRouter,
    BackgroundTasks,
    HTTPException,
    UploadFile,
    File,
    Form
)
from sqlalchemy import select, func
from typing import List, Optional
from pydantic import BaseModel
from io import BytesIO
import logging
import json

# from neos.config.settings import settings
from neos.database.connection import db_manager
from neos.database.models import Document, DocumentChunk, KnowledgeGraph
from neos.pipelines.document.document_processor import DocumentProcessor


# logger = get_logger(__name__)
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])


# ============================================================================
# Pydantic Models
# ============================================================================


class DocumentUploadResponse(BaseModel):
    """문서 업로드 응답"""

    document_id: int
    filename: str
    status: str
    message: str


class DocumentInfo(BaseModel):
    """문서 정보"""

    id: int
    filename: str
    original_filename: str
    file_size: Optional[int]
    mime_type: Optional[str]
    storage_provider: str
    storage_url: Optional[str]
    processing_status: str
    kg_extracted: bool
    embedding_processed: bool
    fts_indexed: bool
    created_at: str
    metadata: dict

    class Config:
        from_attributes = True


class DocumentListResponse(BaseModel):
    """문서 목록 응답"""

    total: int
    documents: List[DocumentInfo]


class ChunkInfo(BaseModel):
    """청크 정보"""

    id: int
    chunk_index: int
    chunk_text: str
    chunk_size: int
    page_number: Optional[int]
    chunk_type: Optional[str]

    class Config:
        from_attributes = True


class EntityInfo(BaseModel):
    """엔티티 정보"""

    id: int
    entity_id: str
    entity_type: str
    entity_name: str
    entity_description: Optional[str]
    confidence_score: float
    properties: dict
    relations: list

    class Config:
        from_attributes = True


class DocumentSearchRequest(BaseModel):
    """문서 검색 요청"""

    query: str
    top_k: int = 10
    user_id: Optional[str] = None


class DocumentSearchResult(BaseModel):
    """문서 검색 결과"""

    chunk_id: int
    document_id: int
    document_name: str
    chunk_text: str
    similarity_score: float
    page_number: Optional[int]


class DocumentSearchResponse(BaseModel):
    """문서 검색 응답"""

    query: str
    results: List[DocumentSearchResult]


# ============================================================================
# API Endpoints
# ============================================================================


@router.post("/upload", response_model=DocumentUploadResponse)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    user_id: str = Form(...),
    metadata: Optional[str] = Form(None),
):
    """
    문서 업로드 및 처리

    - **file**: 업로드할 파일
    - **user_id**: 사용자 ID
    - **metadata**: 추가 메타데이터 (JSON 문자열)
    """
    try:
        # 메타데이터 파싱
        metadata_dict = json.loads(metadata) if metadata else {}

        # 파일 읽기
        file_content = await file.read()
        file_obj = BytesIO(file_content)

        # DocumentProcessor 초기화
        processor = DocumentProcessor()

        # 문서 처리 (백그라운드에서 실행)
        document = await processor.process_document(
            file_obj=file_obj,
            filename=file.filename,
            user_id=user_id,
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


@router.get("/", response_model=DocumentListResponse)
async def list_documents(
    user_id: Optional[str] = None,
    status: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
):
    """
    문서 목록 조회

    - **user_id**: 사용자 ID (필터)
    - **status**: 처리 상태 (필터)
    - **skip**: 오프셋
    - **limit**: 최대 개수
    """
    try:
        # 쿼리 생성
        query = select(Document)

        if user_id:
            query = query.where(Document.user_id == user_id)

        if status:
            query = query.where(Document.processing_status == status)

        # open db session with async context manager
        async with db_manager.get_session() as session:
            # 총 개수 조회
            count_query = select(func.count()).select_from(query.subquery())
            total_result = await session.execute(count_query)
            total = total_result.scalar()

            # 문서 조회
            query = query.offset(skip).limit(limit).order_by(Document.created_at.desc())
            result = await session.execute(query)
            documents = result.scalars().all()

        # 응답 생성
        document_infos = []
        for doc in documents:
            document_infos.append(
                DocumentInfo(
                    id=doc.id,
                    filename=doc.filename,
                    original_filename=doc.original_filename,
                    file_size=doc.file_size,
                    mime_type=doc.mime_type,
                    storage_provider=doc.storage_provider,
                    storage_url=doc.storage_url,
                    processing_status=doc.processing_status,
                    kg_extracted=doc.kg_extracted,
                    embedding_processed=doc.embedding_processed,
                    fts_indexed=doc.fts_indexed,
                    created_at=doc.created_at.isoformat(),
                    metadata=doc.metadata or {},
                )
            )

        return DocumentListResponse(total=total, documents=document_infos)

    except Exception as e:
        logger.error(f"Failed to list documents: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to list documents")


@router.get("/{document_id}", response_model=DocumentInfo)
async def get_document(document_id: int):
    """
    문서 상세 정보 조회

    - **document_id**: 문서 ID
    """
    try:
        async with db_manager.get_session() as session:
            result = await session.execute(
                select(Document).where(Document.id == document_id)
            )
            document = result.scalar_one_or_none()

        if not document:
            raise HTTPException(status_code=404, detail="Document not found")

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
):
    """
    문서 삭제

    - **document_id**: 문서 ID
    """
    try:
        processor = DocumentProcessor()
        success = await processor.delete_document(document_id)

        if not success:
            raise HTTPException(status_code=404, detail="Document not found")

        return {"message": "Document deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete document: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to delete document")


@router.get("/{document_id}/chunks", response_model=List[ChunkInfo])
async def get_document_chunks(document_id: int, skip: int = 0, limit: int = 100):
    """
    문서의 청크 목록 조회

    - **document_id**: 문서 ID
    - **skip**: 오프셋
    - **limit**: 최대 개수
    """
    try:
        query = (
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
            .order_by(DocumentChunk.chunk_index)
            .offset(skip)
            .limit(limit)
        )

        # open db session with async context manager
        async with db_manager.get_session() as session:
            result = await session.execute(query)
            chunks = result.scalars().all()

        return [
            ChunkInfo(
                id=chunk.id,
                chunk_index=chunk.chunk_index,
                chunk_text=chunk.chunk_text,
                chunk_size=chunk.chunk_size,
                page_number=chunk.page_number,
                chunk_type=chunk.chunk_type,
            )
            for chunk in chunks
        ]

    except Exception as e:
        logger.error(f"Failed to get document chunks: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get document chunks")


@router.get("/{document_id}/knowledge-graph", response_model=List[EntityInfo])
async def get_document_knowledge_graph(document_id: int):
    """
    문서의 지식 그래프 조회

    - **document_id**: 문서 ID
    """
    try:
        query = select(KnowledgeGraph).where(
            KnowledgeGraph.document_id == document_id
        )

        async with db_manager.get_session() as session:
            result = await session.execute(query)
            entities = result.scalars().all()

        return [
            EntityInfo(
                id=entity.id,
                entity_id=entity.entity_id,
                entity_type=entity.entity_type,
                entity_name=entity.entity_name,
                entity_description=entity.entity_description,
                confidence_score=entity.confidence_score,
                properties=entity.properties or {},
                relations=entity.relations or [],
            )
            for entity in entities
        ]

    except Exception as e:
        logger.error(f"Failed to get knowledge graph: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get knowledge graph")


@router.post("/search", response_model=DocumentSearchResponse)
async def search_documents(request: DocumentSearchRequest):
    """
    문서 검색 (시맨틱 검색)

    - **query**: 검색 쿼리
    - **top_k**: 반환할 결과 개수
    - **user_id**: 사용자 ID (필터)
    """
    try:
        from neos.utils.embeddings import EmbeddingService

        # 쿼리 임베딩 생성
        embedding_service = EmbeddingService()
        query_embedding = await embedding_service.embed(request.query)

        # pgvector를 사용한 유사도 검색
        from sqlalchemy import text

        # 벡터 유사도 검색 쿼리
        similarity_query = text(
            """
            SELECT
                dc.id as chunk_id,
                dc.document_id,
                d.filename as document_name,
                dc.chunk_text,
                dc.page_number,
                1 - (dc.embedding <=> :query_embedding::vector) as similarity
            FROM document_chunks dc
            JOIN documents d ON dc.document_id = d.id
            WHERE d.embedding_processed = true
            """
        )

        # 사용자 필터 추가
        if request.user_id:
            similarity_query = text(
                str(similarity_query) + " AND d.user_id = :user_id"
            )

        similarity_query = text(
            str(similarity_query)
            + """
            ORDER BY dc.embedding <=> :query_embedding::vector
            LIMIT :top_k
        """
        )

        # 쿼리 실행
        params = {
            "query_embedding": str(query_embedding),
            "top_k": request.top_k,
        }
        if request.user_id:
            params["user_id"] = request.user_id

        # DB 세션 생성
        async with db_manager.get_session() as session:
            result = await session.execute(similarity_query, params)
            rows = result.fetchall()

        # 결과 변환
        search_results = []
        for row in rows:
            search_results.append(
                DocumentSearchResult(
                    chunk_id=row.chunk_id,
                    document_id=row.document_id,
                    document_name=row.document_name,
                    chunk_text=row.chunk_text,
                    similarity_score=float(row.similarity),
                    page_number=row.page_number,
                )
            )

        return DocumentSearchResponse(query=request.query, results=search_results)

    except Exception as e:
        logger.error(f"Document search failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Document search failed")
