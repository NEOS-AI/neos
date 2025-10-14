"""
멀티모달 파이프라인 기본 테스트 스크립트

파이프라인 시스템의 핵심 기능을 검증합니다.
"""

import asyncio
import sys
from pathlib import Path

# 프로젝트 루트를 경로에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# 직접 모듈 임포트 (workflow/__init__.py의 의존성 회피)
from neos.workflow.pipelines.router import InputRouter
from neos.workflow.pipelines.text_pipeline import TextPipeline
from neos.workflow.pipelines.image_pipeline import ImagePipeline
from neos.workflow.pipelines.document_pipeline import DocumentPipeline
from neos.workflow.pipelines.audio_pipeline import AudioPipeline
from neos.workflow.pipelines.multimodal_pipeline import MultiModalPipeline
from neos.workflow.pipelines.unified_context import UnifiedContextLayer
from neos.workflow.pipelines.base import (
    PipelineContext,
    FileInput,
    InputType,
    PipelineRegistry,
)


async def test_text_pipeline():
    """텍스트 파이프라인 테스트"""
    print("\n" + "="*60)
    print("Test 1: TextPipeline")
    print("="*60)

    pipeline = TextPipeline()
    context = PipelineContext(
        query="AI의 발전 과정을 설명해주세요. 특히 딥러닝과 트랜스포머 모델에 대해 알고 싶습니다.",
        input_type=InputType.TEXT,
        user_id="test_user",
        session_id="test_session"
    )

    result = await pipeline.process(context)

    print(f"✓ Success: {result.success}")
    print(f"✓ Extracted Text: {result.extracted_text[:50]}...")
    print(f"✓ Language: {result.metadata.get('language')}")
    print(f"✓ Word Count: {result.metadata.get('word_count')}")
    print(f"✓ Query Type: {result.analysis.get('query_type')}")
    print(f"✓ Processing Time: {result.processing_time_ms:.2f}ms")

    if result.insights:
        print(f"✓ Insights: {result.insights}")

    return result.success


async def test_input_router():
    """입력 라우터 테스트"""
    print("\n" + "="*60)
    print("Test 2: InputRouter")
    print("="*60)

    router = InputRouter()

    # 텍스트 분류
    input_type = router.classify_input("안녕하세요", files=None)
    print(f"✓ Text classification: {input_type.value}")
    assert input_type == InputType.TEXT

    # 이미지 분류
    image_file = FileInput(
        filename="test.jpg",
        mime_type="image/jpeg",
        file_size=1024
    )
    input_type = router.classify_input("이미지 분석", files=[image_file])
    print(f"✓ Image classification: {input_type.value}")
    assert input_type == InputType.IMAGE

    # 문서 분류
    doc_file = FileInput(
        filename="document.pdf",
        mime_type="application/pdf",
        file_size=2048
    )
    input_type = router.classify_input("문서 요약", files=[doc_file])
    print(f"✓ Document classification: {input_type.value}")
    assert input_type == InputType.DOCUMENT

    # 멀티모달 분류
    multi_files = [image_file, doc_file]
    input_type = router.classify_input("종합 분석", files=multi_files)
    print(f"✓ Multimodal classification: {input_type.value}")
    assert input_type == InputType.MULTIMODAL

    return True


async def test_document_pipeline():
    """문서 파이프라인 테스트 (텍스트 파일)"""
    print("\n" + "="*60)
    print("Test 3: DocumentPipeline (Text File)")
    print("="*60)

    pipeline = DocumentPipeline()

    text_content = """
# AI 연구 보고서

## 서론
인공지능(AI)의 발전은 현대 사회를 크게 변화시키고 있습니다.

## 본론
1. 머신러닝의 발전
2. 딥러닝과 신경망
3. 트랜스포머 아키텍처

## 결론
AI 기술은 계속해서 진화할 것입니다.
"""

    file = FileInput(
        filename="report.txt",
        file_content=text_content.encode("utf-8"),
        mime_type="text/plain",
        file_size=len(text_content)
    )

    context = PipelineContext(
        query="이 보고서를 요약해주세요",
        input_type=InputType.DOCUMENT,
        files=[file],
        user_id="test_user"
    )

    result = await pipeline.process(context)

    print(f"✓ Success: {result.success}")
    print(f"✓ Document Type: {result.metadata.get('document_type')}")
    print(f"✓ Extracted Text Length: {len(result.extracted_text)} chars")
    print(f"✓ Line Count: {result.extracted_data.get('line_count')}")
    print(f"✓ Processing Time: {result.processing_time_ms:.2f}ms")

    if result.insights:
        print(f"✓ Insights: {result.insights}")

    return result.success


async def test_unified_context_layer():
    """통합 컨텍스트 레이어 테스트"""
    print("\n" + "="*60)
    print("Test 4: UnifiedContextLayer")
    print("="*60)

    layer = UnifiedContextLayer()

    # 텍스트 파이프라인 결과 생성
    pipeline = TextPipeline()
    context = PipelineContext(
        query="AI 기술 설명",
        input_type=InputType.TEXT,
        user_id="test_user",
        session_id="test_session",
        language="ko"
    )
    result = await pipeline.process(context)

    # 통합
    unified = layer.unify(result, context)

    print(f"✓ Original Query: {unified['original_query']}")
    print(f"✓ User ID: {unified['user_id']}")
    print(f"✓ Session ID: {unified['session_id']}")
    print(f"✓ Input Type: {unified['pipeline_metadata']['input_type']}")
    print(f"✓ Success: {unified['pipeline_metadata']['success']}")
    print(f"✓ Language: {unified['detected_language']}")

    # 워크플로우 상태 생성
    workflow_state = layer.create_workflow_state(unified)

    print(f"✓ Workflow State Created")
    print(f"  - User ID: {workflow_state['user_id']}")
    print(f"  - Session ID: {workflow_state['session_id']}")
    print(f"  - Query: {workflow_state['original_query']}")
    print(f"  - Has Pipeline Context: {'pipeline_context' in workflow_state}")

    return True


async def test_pipeline_registry():
    """파이프라인 레지스트리 테스트"""
    print("\n" + "="*60)
    print("Test 5: PipelineRegistry")
    print("="*60)

    registry = PipelineRegistry()

    # 파이프라인 등록
    text_pipeline = TextPipeline()
    image_pipeline = ImagePipeline()
    doc_pipeline = DocumentPipeline()

    registry.register(InputType.TEXT, text_pipeline)
    registry.register(InputType.IMAGE, image_pipeline)
    registry.register(InputType.DOCUMENT, doc_pipeline)

    # 조회
    retrieved_text = registry.get(InputType.TEXT)
    print(f"✓ Retrieved TEXT pipeline: {retrieved_text.name}")
    assert retrieved_text is text_pipeline

    retrieved_image = registry.get(InputType.IMAGE)
    print(f"✓ Retrieved IMAGE pipeline: {retrieved_image.name}")
    assert retrieved_image is image_pipeline

    # 모든 파이프라인 조회
    all_pipelines = registry.get_all()
    print(f"✓ Total pipelines registered: {len(all_pipelines)}")

    return True


async def run_all_tests():
    """모든 테스트 실행"""
    print("\n" + "#"*60)
    print("# Multimodal Pipeline System - Basic Tests")
    print("#"*60)

    results = []

    try:
        results.append(("InputRouter", await test_input_router()))
    except Exception as e:
        print(f"✗ InputRouter test failed: {e}")
        results.append(("InputRouter", False))

    try:
        results.append(("TextPipeline", await test_text_pipeline()))
    except Exception as e:
        print(f"✗ TextPipeline test failed: {e}")
        results.append(("TextPipeline", False))

    try:
        results.append(("DocumentPipeline", await test_document_pipeline()))
    except Exception as e:
        print(f"✗ DocumentPipeline test failed: {e}")
        results.append(("DocumentPipeline", False))

    try:
        results.append(("UnifiedContextLayer", await test_unified_context_layer()))
    except Exception as e:
        print(f"✗ UnifiedContextLayer test failed: {e}")
        results.append(("UnifiedContextLayer", False))

    try:
        results.append(("PipelineRegistry", await test_pipeline_registry()))
    except Exception as e:
        print(f"✗ PipelineRegistry test failed: {e}")
        results.append(("PipelineRegistry", False))

    # 결과 요약
    print("\n" + "#"*60)
    print("# Test Results Summary")
    print("#"*60)

    passed = sum(1 for _, success in results if success)
    total = len(results)

    for name, success in results:
        status = "✓ PASS" if success else "✗ FAIL"
        print(f"{status}: {name}")

    print(f"\nTotal: {passed}/{total} tests passed")

    if passed == total:
        print("\n🎉 All tests passed!")
        return 0
    else:
        print(f"\n❌ {total - passed} test(s) failed")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(run_all_tests())
    sys.exit(exit_code)
