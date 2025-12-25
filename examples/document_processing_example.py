"""
Document Processing Example

이 예제는 neos의 문서 처리 기능을 사용하는 방법을 보여줍니다.
"""

import asyncio
from pathlib import Path

from neos.pipelines.document.document_processor import DocumentProcessor
from neos.database.connection import get_session
from neos.database.models import Document, DocumentChunk, KnowledgeGraph
from sqlalchemy import select


async def example_upload_document():
    """문서 업로드 및 처리 예제"""
    print("=" * 80)
    print("문서 업로드 및 처리 예제")
    print("=" * 80)

    # DocumentProcessor 초기화
    processor = DocumentProcessor(
        storage_provider="local",  # 's3', 'rustfs', 'local' 중 선택
        enable_kg_extraction=True,  # 지식 그래프 추출 활성화
    )

    # 테스트 파일 경로
    test_file_path = Path("test_document.txt")

    # 테스트 파일이 없으면 생성
    if not test_file_path.exists():
        test_content = """
# 인공지능의 역사

## 초기 발전

인공지능(Artificial Intelligence, AI)의 역사는 1950년대로 거슬러 올라갑니다.
앨런 튜링(Alan Turing)은 1950년에 "Computing Machinery and Intelligence"라는
논문을 통해 기계가 사고할 수 있는지에 대한 질문을 제기했습니다.

## 다트머스 회의

1956년, 존 매카시(John McCarthy), 마빈 민스키(Marvin Minsky),
클로드 섀넌(Claude Shannon) 등이 다트머스 대학에서 회의를 열었습니다.
이 회의에서 "인공지능"이라는 용어가 처음 사용되었습니다.

## 현대 AI

2010년대 이후, 딥러닝의 발전으로 AI는 급격한 발전을 이루었습니다.
구글(Google), 오픈AI(OpenAI), 앤스로픽(Anthropic) 같은 기업들이
대규모 언어 모델을 개발하고 있습니다.
"""
        test_file_path.write_text(test_content)
        print(f"✅ 테스트 파일 생성: {test_file_path}")

    # 파일 업로드 및 처리
    with open(test_file_path, "rb") as f:
        document = await processor.process_document(
            file_obj=f,
            filename="test_document.txt",
            user_id="test_user",
            metadata={"category": "AI", "language": "ko"},
            mime_type="text/plain",
        )

    print(f"\n✅ 문서 처리 완료!")
    print(f"   - Document ID: {document.id}")
    print(f"   - Filename: {document.filename}")
    print(f"   - Status: {document.processing_status}")
    print(f"   - Storage: {document.storage_url}")
    print(f"   - KG Extracted: {document.kg_extracted}")
    print(f"   - Embedding Processed: {document.embedding_processed}")

    return document.id


async def example_query_document(document_id: int):
    """문서 조회 예제"""
    print("\n" + "=" * 80)
    print("문서 정보 조회")
    print("=" * 80)

    async for session in get_session():
        # 문서 조회
        result = await session.execute(
            select(Document).where(Document.id == document_id)
        )
        document = result.scalar_one()

        print("\n📄 문서 정보:")
        print(f"   - ID: {document.id}")
        print(f"   - 파일명: {document.filename}")
        print(f"   - 크기: {document.file_size} bytes" if document.file_size else "   - 크기: N/A")
        print(f"   - 해시: {document.file_hash}")
        print(f"   - 처리 상태: {document.processing_status}")

        # 청크 조회
        chunk_result = await session.execute(
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
            .limit(5)
        )
        chunks = chunk_result.scalars().all()

        print(f"\n📝 청크 정보 (총 {len(chunks)}개 중 5개):")
        for chunk in chunks[:5]:
            preview = chunk.chunk_text[:100] + "..." if len(chunk.chunk_text) > 100 else chunk.chunk_text
            print(f"   - Chunk #{chunk.chunk_index}: {preview}")

        # 지식 그래프 조회
        kg_result = await session.execute(
            select(KnowledgeGraph).where(KnowledgeGraph.document_id == document_id)
        )
        entities = kg_result.scalars().all()

        print(f"\n🔗 지식 그래프 (총 {len(entities)}개 엔티티):")
        for entity in entities:
            print(f"   - {entity.entity_name} ({entity.entity_type})")
            print(f"     설명: {entity.entity_description}")
            print(f"     신뢰도: {entity.confidence_score:.2f}")
            if entity.relations:
                print(f"     관계: {len(entity.relations)}개")

        break


async def example_semantic_search(query: str, user_id: str = "test_user"):
    """시맨틱 검색 예제"""
    print("\n" + "=" * 80)
    print(f"시맨틱 검색: '{query}'")
    print("=" * 80)

    from neos.utils.embeddings import EmbeddingService

    # 쿼리 임베딩 생성
    embedding_service = EmbeddingService()
    query_embedding = await embedding_service.embed(query)

    # 유사도 검색
    async for session in get_session():
        from sqlalchemy import text

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
            WHERE d.user_id = :user_id
                AND d.embedding_processed = true
            ORDER BY dc.embedding <=> :query_embedding::vector
            LIMIT 5
        """
        )

        result = await session.execute(
            similarity_query,
            {"query_embedding": str(query_embedding), "user_id": user_id},
        )
        rows = result.fetchall()

        print(f"\n🔍 검색 결과 (상위 {len(rows)}개):")
        for i, row in enumerate(rows, 1):
            print(f"\n{i}. 문서: {row.document_name}")
            print(f"   유사도: {row.similarity:.4f}")
            preview = row.chunk_text[:200] + "..." if len(row.chunk_text) > 200 else row.chunk_text
            print(f"   내용: {preview}")

        break


async def example_delete_document(document_id: int):
    """문서 삭제 예제"""
    print("\n" + "=" * 80)
    print(f"문서 삭제: ID={document_id}")
    print("=" * 80)

    processor = DocumentProcessor()
    success = await processor.delete_document(document_id)

    if success:
        print(f"✅ 문서 삭제 완료!")
    else:
        print(f"❌ 문서 삭제 실패!")


async def main():
    """메인 예제 실행"""
    print("\n🚀 NEOS 문서 처리 기능 예제\n")

    # 1. 문서 업로드
    document_id = await example_upload_document()

    # 2. 문서 조회
    await example_query_document(document_id)

    # 3. 시맨틱 검색
    await example_semantic_search("인공지능의 초기 발전", user_id="test_user")

    # 4. 문서 삭제 (주석 처리 - 필요시 해제)
    # await example_delete_document(document_id)

    print("\n" + "=" * 80)
    print("✅ 모든 예제 완료!")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
