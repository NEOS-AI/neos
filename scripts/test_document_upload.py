#!/usr/bin/env python3
"""
문서 업로드 및 처리 통합 테스트 스크립트

이 스크립트는 다음을 테스트합니다:
1. 문서 업로드 (로컬/rustfs/S3)
2. 파일 저장 확인
3. 문서 처리 파이프라인
4. 청크 생성 및 임베딩
5. 지식 그래프 추출
6. 문서 검색

사용법:
    python scripts/test_document_upload.py --provider rustfs
    python scripts/test_document_upload.py --provider s3
    python scripts/test_document_upload.py --provider local
"""

import asyncio
import sys
import argparse
from pathlib import Path
from io import BytesIO
import logging

# 프로젝트 루트를 Python path에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from neos.storage.storage_service import StorageService
from neos.pipelines.document.document_processor import DocumentProcessor
from neos.api.services.document_service import DocumentService
from neos.config.settings import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# 테스트용 샘플 문서 생성
def create_sample_document(content: str, filename: str) -> BytesIO:
    """테스트용 샘플 텍스트 문서 생성"""
    file_obj = BytesIO(content.encode("utf-8"))
    file_obj.name = filename
    return file_obj


async def test_storage_provider(provider: str):
    """스토리지 프로바이더 기본 테스트"""
    logger.info(f"\n{'='*60}")
    logger.info(f"테스트 1: {provider.upper()} 스토리지 프로바이더 연결")
    logger.info(f"{'='*60}")

    try:
        # 스토리지 프로바이더 생성
        storage = StorageService.create_provider(provider)
        logger.info(f"✅ {provider} 스토리지 프로바이더 생성 성공")

        # 테스트 파일 생성
        test_content = b"Test content for storage provider"
        test_file = BytesIO(test_content)
        test_key = f"test/storage_test_{provider}.txt"

        # 업로드 테스트
        logger.info(f"📤 파일 업로드 테스트: {test_key}")
        storage_url = await storage.upload(
            file_obj=test_file,
            key=test_key,
            metadata={"test": "true"},
            content_type="text/plain"
        )
        logger.info(f"✅ 업로드 성공: {storage_url}")

        # 존재 확인
        exists = await storage.exists(test_key)
        logger.info(f"{'✅' if exists else '❌'} 파일 존재 확인: {exists}")

        # 다운로드 테스트
        logger.info(f"📥 파일 다운로드 테스트")
        downloaded = await storage.download(test_key)
        assert downloaded == test_content, "다운로드된 내용이 원본과 일치하지 않습니다"
        logger.info(f"✅ 다운로드 성공 (크기: {len(downloaded)} bytes)")

        # Presigned URL 테스트 (S3/rustfs만)
        if provider in ["s3", "rustfs"]:
            presigned_url = await storage.get_presigned_url(test_key)
            logger.info(f"✅ Presigned URL 생성: {presigned_url[:50]}...")

        # 삭제 테스트
        deleted = await storage.delete(test_key)
        logger.info(f"{'✅' if deleted else '❌'} 삭제 성공: {deleted}")

        return True

    except Exception as e:
        logger.error(f"❌ 스토리지 테스트 실패: {e}", exc_info=True)
        return False


async def test_document_processor(provider: str):
    """문서 프로세서 통합 테스트"""
    logger.info(f"\n{'='*60}")
    logger.info(f"테스트 2: 문서 처리 파이프라인 ({provider.upper()})")
    logger.info(f"{'='*60}")

    try:
        # 프로세서 초기화
        processor = DocumentProcessor(
            storage_provider=provider,
            enable_kg_extraction=True
        )
        logger.info(f"✅ DocumentProcessor 초기화 완료")

        # 샘플 문서 생성
        sample_content = """
# 인공지능과 머신러닝

## 개요
인공지능(AI)은 컴퓨터 시스템이 인간의 지능을 모방하는 기술입니다.
머신러닝은 AI의 하위 분야로, 데이터로부터 학습하는 알고리즘을 다룹니다.

## 주요 개념
- 지도 학습 (Supervised Learning)
- 비지도 학습 (Unsupervised Learning)
- 강화 학습 (Reinforcement Learning)

## 응용 분야
1. 자연어 처리 (NLP)
2. 컴퓨터 비전
3. 음성 인식
4. 추천 시스템

## 결론
AI와 머신러닝은 현대 기술의 핵심이며, 다양한 산업에 혁신을 가져오고 있습니다.
        """

        file_obj = create_sample_document(sample_content, "ai_ml_guide.txt")

        # 문서 처리
        logger.info(f"📄 문서 처리 시작...")
        document = await processor.process_document(
            file_obj=file_obj,
            filename="ai_ml_guide.txt",
            user_id="test_user",
            metadata={"category": "AI", "test": True},
            mime_type="text/plain"
        )

        logger.info(f"✅ 문서 처리 완료:")
        logger.info(f"   - Document ID: {document.id}")
        logger.info(f"   - Filename: {document.filename}")
        logger.info(f"   - Storage Provider: {document.storage_provider}")
        logger.info(f"   - Storage URL: {document.storage_url}")
        logger.info(f"   - Status: {document.processing_status}")
        logger.info(f"   - KG Extracted: {document.kg_extracted}")
        logger.info(f"   - Embedding Processed: {document.embedding_processed}")
        logger.info(f"   - FTS Indexed: {document.fts_indexed}")

        # 청크 확인
        from neos.api.services.document_service import DocumentService
        chunks = await DocumentService.get_document_chunks(document.id)
        logger.info(f"✅ 생성된 청크 수: {len(chunks)}")
        if chunks:
            logger.info(f"   - 첫 번째 청크: {chunks[0].chunk_text[:100]}...")

        # 지식 그래프 확인
        if document.kg_extracted:
            kg_entities = await DocumentService.get_document_knowledge_graph(document.id)
            logger.info(f"✅ 추출된 엔티티 수: {len(kg_entities)}")
            if kg_entities:
                for i, entity in enumerate(kg_entities[:3], 1):
                    logger.info(f"   {i}. {entity.entity_name} ({entity.entity_type}): {entity.entity_description}")

        return document

    except Exception as e:
        logger.error(f"❌ 문서 처리 테스트 실패: {e}", exc_info=True)
        return None


async def test_document_search(document_id: int):
    """문서 검색 테스트"""
    logger.info(f"\n{'='*60}")
    logger.info(f"테스트 3: 문서 검색 (시맨틱 검색)")
    logger.info(f"{'='*60}")

    try:
        queries = [
            "인공지능이란 무엇인가?",
            "머신러닝의 종류",
            "AI의 응용 분야"
        ]

        for query in queries:
            logger.info(f"\n🔍 검색 쿼리: '{query}'")

            results = await DocumentService.search_documents(
                query=query,
                top_k=3,
                user_id="test_user"
            )

            logger.info(f"✅ 검색 결과: {len(results)}개")
            for i, result in enumerate(results, 1):
                logger.info(f"   {i}. [{result['document_name']}] 유사도: {result['similarity_score']:.3f}")
                logger.info(f"      {result['chunk_text'][:100]}...")

        return True

    except Exception as e:
        logger.error(f"❌ 문서 검색 테스트 실패: {e}", exc_info=True)
        return False


async def test_document_deletion(document_id: int):
    """문서 삭제 테스트"""
    logger.info(f"\n{'='*60}")
    logger.info(f"테스트 4: 문서 삭제")
    logger.info(f"{'='*60}")

    try:
        success = await DocumentService.delete_document(document_id)

        if success:
            logger.info(f"✅ 문서 삭제 성공: ID={document_id}")

            # 삭제 확인
            document = await DocumentService.get_document_by_id(document_id)
            if document is None:
                logger.info(f"✅ 삭제 확인 완료")
            else:
                logger.warning(f"⚠️ 문서가 여전히 존재함")

        else:
            logger.error(f"❌ 문서 삭제 실패")

        return success

    except Exception as e:
        logger.error(f"❌ 문서 삭제 테스트 실패: {e}", exc_info=True)
        return False


async def run_all_tests(provider: str):
    """모든 테스트 실행"""
    logger.info(f"\n{'#'*60}")
    logger.info(f"문서 업로드 및 처리 통합 테스트")
    logger.info(f"스토리지 프로바이더: {provider.upper()}")
    logger.info(f"{'#'*60}")

    results = {}

    # 1. 스토리지 프로바이더 테스트
    results["storage"] = await test_storage_provider(provider)

    if not results["storage"]:
        logger.error("스토리지 테스트 실패로 인해 나머지 테스트를 건너뜁니다.")
        return results

    # 2. 문서 처리 파이프라인 테스트
    document = await test_document_processor(provider)
    results["processing"] = document is not None

    if not results["processing"]:
        logger.error("문서 처리 테스트 실패로 인해 나머지 테스트를 건너뜁니다.")
        return results

    # 3. 문서 검색 테스트
    results["search"] = await test_document_search(document.id)

    # 4. 문서 삭제 테스트
    results["deletion"] = await test_document_deletion(document.id)

    # 결과 요약
    logger.info(f"\n{'='*60}")
    logger.info(f"테스트 결과 요약")
    logger.info(f"{'='*60}")

    total = len(results)
    passed = sum(1 for v in results.values() if v)

    for test_name, success in results.items():
        status = "✅ PASS" if success else "❌ FAIL"
        logger.info(f"{status}: {test_name}")

    logger.info(f"\n총 {passed}/{total} 테스트 통과")

    return results


def main():
    """메인 함수"""
    parser = argparse.ArgumentParser(
        description="문서 업로드 및 처리 통합 테스트"
    )
    parser.add_argument(
        "--provider",
        type=str,
        default=settings.STORAGE_PROVIDER,
        choices=["local", "rustfs", "s3"],
        help="스토리지 프로바이더 (default: settings.STORAGE_PROVIDER)"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="상세 로그 출력"
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # 비동기 이벤트 루프 실행
    results = asyncio.run(run_all_tests(args.provider))

    # 모든 테스트가 통과했는지 확인
    all_passed = all(results.values())
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
