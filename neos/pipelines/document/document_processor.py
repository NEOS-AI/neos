"""Main document processing pipeline"""

from datetime import datetime
from pathlib import Path
from typing import BinaryIO, Dict, List, Optional, Any
import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from neos.config.settings import settings
from neos.database.connection import get_session
from neos.database.models import Document, DocumentChunk, KnowledgeGraph
from neos.pipelines.document.chunker import DocumentChunker
from neos.pipelines.document.knowledge_graph import KnowledgeGraphExtractor
from neos.storage.storage_service import StorageService
from neos.utils.embeddings import EmbeddingService


logger = logging.getLogger(__name__)


class DocumentProcessor:
    """문서 처리 메인 파이프라인"""

    def __init__(
        self,
        storage_provider: Optional[str] = None,
        enable_kg_extraction: bool = None,
    ):
        """
        DocumentProcessor 초기화

        Args:
            storage_provider: 스토리지 프로바이더 ('s3', 'rustfs', 'local')
            enable_kg_extraction: 지식 그래프 추출 활성화 여부
        """
        self.storage_provider = storage_provider or settings.STORAGE_PROVIDER
        self.enable_kg_extraction = (
            enable_kg_extraction
            if enable_kg_extraction is not None
            else settings.KG_EXTRACTION_ENABLED
        )

        # 서비스 초기화
        self.storage = StorageService.create_provider(self.storage_provider)
        self.chunker = DocumentChunker()
        self.embedding_service = EmbeddingService()

        if self.enable_kg_extraction:
            self.kg_extractor = KnowledgeGraphExtractor()
        else:
            self.kg_extractor = None

        logger.info(
            f"DocumentProcessor initialized: storage={self.storage_provider}, "
            f"kg_extraction={self.enable_kg_extraction}"
        )

    async def process_document(
        self,
        file_obj: BinaryIO,
        filename: str,
        user_id: str,
        metadata: Optional[Dict[str, Any]] = None,
        mime_type: Optional[str] = None,
    ) -> Document:
        """
        문서 전체 처리 파이프라인

        Args:
            file_obj: 파일 객체
            filename: 파일명
            user_id: 사용자 ID
            metadata: 추가 메타데이터
            mime_type: MIME 타입

        Returns:
            Document 모델 인스턴스
        """
        logger.info(f"Starting document processing: {filename} for user {user_id}")

        try:
            # 1. 파일 검증
            self._validate_file(file_obj, filename)

            # 2. 파일 해시 계산
            file_hash = StorageService.compute_file_hash(file_obj)
            logger.debug(f"File hash: {file_hash}")

            # 3. 스토리지 키 생성
            storage_key = StorageService.generate_storage_key(
                user_id, filename, file_hash
            )

            # 4. 문서 레코드 생성
            async for session in get_session():
                document = await self._create_document_record(
                    session=session,
                    user_id=user_id,
                    filename=filename,
                    file_hash=file_hash,
                    storage_key=storage_key,
                    metadata=metadata,
                    mime_type=mime_type,
                )
                document_id = document.id
                break

            # 5. 스토리지에 업로드
            file_obj.seek(0)
            storage_url = await self.storage.upload(
                file_obj=file_obj,
                key=storage_key,
                metadata={"user_id": user_id, "filename": filename},
                content_type=mime_type,
            )

            # 6. 문서 업데이트 (storage_url)
            async for session in get_session():
                await self._update_document_storage_url(
                    session, document_id, storage_url
                )
                break

            # 7. 텍스트 추출
            file_obj.seek(0)
            text_content = await self._extract_text(file_obj, filename, mime_type)

            if not text_content:
                logger.warning(f"No text content extracted from {filename}")
                async for session in get_session():
                    await self._update_document_status(
                        session, document_id, "failed", "No text content extracted"
                    )
                    break
                return document

            # 8. 문서 청킹
            chunks = self.chunker.chunk_text(text_content, metadata=metadata)
            logger.info(f"Created {len(chunks)} chunks")

            # 9. 임베딩 생성 (병렬)
            chunk_texts = [chunk.chunk_text for chunk in chunks]
            embeddings = await self.embedding_service.embed_batch(chunk_texts)

            # 10. 청크 DB 저장
            async for session in get_session():
                await self._save_chunks(
                    session, document_id, chunks, embeddings
                )
                break

            # 11. 지식 그래프 추출 (옵션)
            if self.enable_kg_extraction and self.kg_extractor:
                logger.info("Starting knowledge graph extraction")
                kg_result = await self.kg_extractor.extract(
                    text_content,
                    context={"filename": filename, "metadata": metadata},
                )

                # 12. 지식 그래프 DB 저장
                async for session in get_session():
                    await self._save_knowledge_graph(
                        session, document_id, kg_result
                    )
                    break

            # 13. 문서 상태 업데이트
            async for session in get_session():
                await self._update_document_processing_status(
                    session,
                    document_id,
                    kg_extracted=self.enable_kg_extraction,
                    embedding_processed=True,
                    fts_indexed=True,
                )
                break

            logger.info(f"Document processing completed: {filename}")

            # 최종 문서 반환
            async for session in get_session():
                result = await session.execute(
                    select(Document).where(Document.id == document_id)
                )
                document = result.scalar_one()
                break

            return document

        except Exception as e:
            logger.error(f"Document processing failed: {e}", exc_info=True)

            # 에러 상태 업데이트
            if "document_id" in locals():
                async for session in get_session():
                    await self._update_document_status(
                        session, document_id, "failed", str(e)
                    )
                    break

            raise

    def _validate_file(self, file_obj: BinaryIO, filename: str):
        """파일 검증"""
        # 파일 크기 확인
        file_obj.seek(0, 2)  # 파일 끝으로 이동
        file_size = file_obj.tell()
        file_obj.seek(0)

        if file_size > settings.MAX_FILE_SIZE:
            raise ValueError(
                f"File size ({file_size} bytes) exceeds maximum ({settings.MAX_FILE_SIZE} bytes)"
            )

        # 파일 확장자 확인
        file_ext = Path(filename).suffix.lower()
        if file_ext not in settings.ALLOWED_FILE_EXTENSIONS:
            raise ValueError(
                f"File extension '{file_ext}' not allowed. Allowed: {settings.ALLOWED_FILE_EXTENSIONS}"
            )

        logger.debug(f"File validation passed: {filename} ({file_size} bytes)")

    async def _create_document_record(
        self,
        session: AsyncSession,
        user_id: str,
        filename: str,
        file_hash: str,
        storage_key: str,
        metadata: Optional[Dict[str, Any]],
        mime_type: Optional[str],
    ) -> Document:
        """문서 레코드 생성"""
        document = Document(
            user_id=user_id,
            filename=filename,
            original_filename=filename,
            file_hash=file_hash,
            storage_provider=self.storage_provider,
            storage_key=storage_key,
            mime_type=mime_type,
            metadata=metadata or {},
            processing_status="processing",
        )

        session.add(document)
        await session.commit()
        await session.refresh(document)

        logger.info(f"Document record created: ID={document.id}")
        return document

    async def _update_document_storage_url(
        self, session: AsyncSession, document_id: int, storage_url: str
    ):
        """문서 스토리지 URL 업데이트"""
        result = await session.execute(
            select(Document).where(Document.id == document_id)
        )
        document = result.scalar_one()
        document.storage_url = storage_url
        await session.commit()

    async def _update_document_status(
        self,
        session: AsyncSession,
        document_id: int,
        status: str,
        error: Optional[str] = None,
    ):
        """문서 처리 상태 업데이트"""
        result = await session.execute(
            select(Document).where(Document.id == document_id)
        )
        document = result.scalar_one()
        document.processing_status = status
        if error:
            document.processing_error = error
        await session.commit()

    async def _update_document_processing_status(
        self,
        session: AsyncSession,
        document_id: int,
        kg_extracted: bool = False,
        embedding_processed: bool = False,
        fts_indexed: bool = False,
    ):
        """문서 처리 완료 상태 업데이트"""
        result = await session.execute(
            select(Document).where(Document.id == document_id)
        )
        document = result.scalar_one()

        document.processing_status = "completed"
        document.kg_extracted = kg_extracted
        document.kg_extraction_date = datetime.utcnow() if kg_extracted else None
        document.embedding_processed = embedding_processed
        document.embedding_date = datetime.utcnow() if embedding_processed else None
        document.fts_indexed = fts_indexed
        document.fts_index_date = datetime.utcnow() if fts_indexed else None

        await session.commit()

    async def _extract_text(
        self, file_obj: BinaryIO, filename: str, mime_type: Optional[str]
    ) -> str:
        """파일에서 텍스트 추출"""
        # 기존 multimodal pipeline 활용
        from neos.pipelines.multimodal.base import create_pipeline

        file_obj.seek(0)
        file_bytes = file_obj.read()

        # 파이프라인 생성 및 실행
        pipeline = create_pipeline(
            filename=filename, file_bytes=file_bytes, mime_type=mime_type
        )

        result = await pipeline.process()

        # 텍스트 추출
        text_content = result.get("extracted_text", "")

        # 추가 분석 결과도 포함
        if result.get("analysis"):
            text_content += f"\n\n## Analysis\n{result['analysis']}"

        return text_content

    async def _save_chunks(
        self,
        session: AsyncSession,
        document_id: int,
        chunks: List,
        embeddings: List[List[float]],
    ):
        """청크를 DB에 저장"""
        for chunk, embedding in zip(chunks, embeddings):
            db_chunk = DocumentChunk(
                document_id=document_id,
                chunk_index=chunk.chunk_index,
                chunk_text=chunk.chunk_text,
                chunk_size=chunk.chunk_size,
                page_number=chunk.page_number,
                start_offset=chunk.start_offset,
                end_offset=chunk.end_offset,
                chunk_type=chunk.chunk_type,
                heading_hierarchy=chunk.heading_hierarchy,
                embedding=embedding,
                metadata=chunk.metadata or {},
            )
            session.add(db_chunk)

        await session.commit()
        logger.info(f"Saved {len(chunks)} chunks to database")

    async def _save_knowledge_graph(
        self, session: AsyncSession, document_id: int, kg_result
    ):
        """지식 그래프를 DB에 저장"""
        # 엔티티 임베딩 생성
        entity_texts = [
            f"{entity.entity_name}: {entity.entity_description or ''}"
            for entity in kg_result.entities
        ]

        if entity_texts:
            entity_embeddings = await self.embedding_service.embed_batch(entity_texts)
        else:
            entity_embeddings = []

        # 엔티티 저장
        for entity, embedding in zip(kg_result.entities, entity_embeddings):
            # 관계 정보를 JSON으로 변환
            relations_json = []
            for relation in kg_result.relations:
                if relation.source_entity_id == entity.entity_id:
                    relations_json.append(
                        {
                            "target_entity_id": relation.target_entity_id,
                            "relation_type": relation.relation_type,
                            "confidence": relation.confidence_score,
                            "properties": relation.properties or {},
                        }
                    )

            kg_entity = KnowledgeGraph(
                document_id=document_id,
                entity_id=entity.entity_id,
                entity_type=entity.entity_type,
                entity_name=entity.entity_name,
                entity_description=entity.entity_description,
                entity_embedding=embedding,
                relations=relations_json,
                properties=entity.properties or {},
                occurrences=entity.occurrences or [],
                confidence_score=entity.confidence_score,
            )
            session.add(kg_entity)

        await session.commit()
        logger.info(
            f"Saved {len(kg_result.entities)} entities to knowledge graph database"
        )

    async def delete_document(self, document_id: int) -> bool:
        """
        문서 삭제 (DB + 스토리지)

        Args:
            document_id: 문서 ID

        Returns:
            삭제 성공 여부
        """
        try:
            async for session in get_session():
                # 문서 조회
                result = await session.execute(
                    select(Document).where(Document.id == document_id)
                )
                document = result.scalar_one_or_none()

                if not document:
                    logger.warning(f"Document not found: ID={document_id}")
                    return False

                # 스토리지에서 삭제
                await self.storage.delete(document.storage_key)

                # DB에서 삭제 (cascade로 청크와 지식 그래프도 삭제)
                await session.delete(document)
                await session.commit()

                logger.info(f"Document deleted: ID={document_id}")
                return True

        except Exception as e:
            logger.error(f"Document deletion failed: {e}", exc_info=True)
            return False
