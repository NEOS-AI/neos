"""Document API handlers - thin layer for FastAPI routes"""

from fastapi import (
    APIRouter,
    BackgroundTasks,
    HTTPException,
    UploadFile,
    File,
    Form
)
from typing import List, Optional
import json
import logging

from neos.api.models.document_models import (
    DocumentUploadResponse,
    DocumentInfo,
    DocumentListResponse,
    ChunkInfo,
    EntityInfo,
    DocumentSearchRequest,
    DocumentSearchResult,
    DocumentSearchResponse
)
from neos.api.services.document_service import DocumentService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])


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

        # 문서 처리
        document = await DocumentService.upload_and_process_document(
            file_content=file_content,
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
        result = await DocumentService.list_documents(user_id, status, skip, limit)

        # 응답 생성
        document_infos = []
        for doc in result["documents"]:
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

        return DocumentListResponse(total=result["total"], documents=document_infos)

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
        document = await DocumentService.get_document_by_id(document_id)

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
async def delete_document(document_id: int):
    """
    문서 삭제

    - **document_id**: 문서 ID
    """
    try:
        success = await DocumentService.delete_document(document_id)

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
        chunks = await DocumentService.get_document_chunks(document_id, skip, limit)

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
        entities = await DocumentService.get_document_knowledge_graph(document_id)

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
        results = await DocumentService.search_documents(
            query=request.query,
            top_k=request.top_k,
            user_id=request.user_id
        )

        search_results = [DocumentSearchResult(**result) for result in results]

        return DocumentSearchResponse(query=request.query, results=search_results)

    except Exception as e:
        logger.error(f"Document search failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Document search failed")
