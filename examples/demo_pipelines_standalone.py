"""
멀티모달 파이프라인 독립 실행 데모

이 스크립트는 다른 의존성 없이 파이프라인 시스템만 테스트합니다.
"""

import asyncio
import sys
import os

# neos.workflow 패키지 임포트 전에 __init__.py 임시 백업
from pathlib import Path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

print("="*60)
print("Multimodal Pipeline System - Standalone Demo")
print("="*60)
print()

# __init__.py 문제를 회피하기 위해 직접 파일 임포트
import importlib.util

def load_module_from_file(module_name, file_path):
    """파일에서 직접 모듈 로드"""
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module

# 필요한 모듈들을 직접 로드
pipelines_path = project_root / "neos" / "workflow" / "pipelines"

print("Loading pipeline modules...")
base = load_module_from_file("base", pipelines_path / "base.py")
text_pipeline = load_module_from_file("text_pipeline", pipelines_path / "text_pipeline.py")
router_module = load_module_from_file("router_module", pipelines_path / "router.py")

print("✓ Modules loaded successfully\n")

# 필요한 클래스들 가져오기
InputType = base.InputType
PipelineContext = base.PipelineContext
FileInput = base.FileInput
PipelineRegistry = base.PipelineRegistry
TextPipeline = text_pipeline.TextPipeline
InputRouter = router_module.InputRouter


async def demo_text_pipeline():
    """텍스트 파이프라인 데모"""
    print("="*60)
    print("Demo 1: Text Pipeline")
    print("="*60)

    pipeline = TextPipeline()

    queries = [
        "AI에 대해 설명해주세요",
        "Python과 Java를 비교 분석해주세요",
        "머신러닝과 딥러닝의 차이는 무엇인가요?",
    ]

    for i, query in enumerate(queries, 1):
        print(f"\n[Query {i}] {query}")
        print("-" * 60)

        context = PipelineContext(
            query=query,
            input_type=InputType.TEXT,
            user_id="demo_user",
            session_id="demo_session"
        )

        result = await pipeline.process(context)

        if result.success:
            print(f"✓ Status: SUCCESS")
            print(f"✓ Language: {result.metadata.get('language')}")
            print(f"✓ Word Count: {result.metadata.get('word_count')}")
            print(f"✓ Query Type: {result.analysis.get('query_type')}")
            print(f"✓ Processing Time: {result.processing_time_ms:.2f}ms")

            if result.insights:
                print(f"✓ Insights:")
                for insight in result.insights:
                    print(f"  - {insight}")
        else:
            print(f"✗ FAILED: {result.error}")

    return True


async def demo_input_router():
    """입력 라우터 데모"""
    print("\n" + "="*60)
    print("Demo 2: Input Router - Automatic Classification")
    print("="*60)

    router = InputRouter()

    test_cases = [
        ("텍스트 쿼리", None, InputType.TEXT),
        ("이미지 분석", [FileInput(filename="image.jpg", mime_type="image/jpeg")], InputType.IMAGE),
        ("문서 요약", [FileInput(filename="doc.pdf", mime_type="application/pdf")], InputType.DOCUMENT),
        ("오디오 전사", [FileInput(filename="audio.mp3", mime_type="audio/mpeg")], InputType.AUDIO),
        (
            "멀티모달",
            [
                FileInput(filename="img.jpg", mime_type="image/jpeg"),
                FileInput(filename="doc.pdf", mime_type="application/pdf"),
            ],
            InputType.MULTIMODAL
        ),
    ]

    for i, (query, files, expected_type) in enumerate(test_cases, 1):
        print(f"\n[Test Case {i}] {query}")
        print("-" * 60)

        classified_type = router.classify_input(query, files)

        status = "✓" if classified_type == expected_type else "✗"
        print(f"{status} Classified as: {classified_type.value}")
        print(f"  Expected: {expected_type.value}")

        if files:
            print(f"  Files: {len(files)}")
            for f in files:
                print(f"    - {f.filename} ({f.mime_type})")

    return True


async def demo_pipeline_registry():
    """파이프라인 레지스트리 데모"""
    print("\n" + "="*60)
    print("Demo 3: Pipeline Registry")
    print("="*60)

    registry = PipelineRegistry()

    # 파이프라인 등록
    text_pipe = TextPipeline()
    registry.register(InputType.TEXT, text_pipe)

    print(f"\n✓ Registered pipeline: {text_pipe.name}")

    # 조회
    retrieved = registry.get(InputType.TEXT)
    print(f"✓ Retrieved pipeline: {retrieved.name}")
    print(f"✓ Input type: {retrieved.input_type.value}")

    # 모든 파이프라인 조회
    all_pipelines = registry.get_all()
    print(f"\n✓ Total registered pipelines: {len(all_pipelines)}")

    for input_type, pipeline in all_pipelines.items():
        print(f"  - {input_type.value}: {pipeline.name}")

    return True


async def demo_korean_english_detection():
    """한글/영어 감지 데모"""
    print("\n" + "="*60)
    print("Demo 4: Language Detection")
    print("="*60)

    pipeline = TextPipeline()

    test_queries = [
        ("Hello, how are you?", "en"),
        ("안녕하세요, 잘 지내시나요?", "ko"),
        ("AI technology is amazing", "en"),
        ("인공지능 기술은 놀랍습니다", "ko"),
        ("Python programming", "en"),
        ("파이썬 프로그래밍", "ko"),
    ]

    for i, (query, expected_lang) in enumerate(test_queries, 1):
        print(f"\n[Query {i}] {query}")
        print("-" * 60)

        context = PipelineContext(
            query=query,
            input_type=InputType.TEXT
        )

        result = await pipeline.process(context)

        detected_lang = result.metadata.get("language")
        status = "✓" if detected_lang == expected_lang else "✗"

        print(f"{status} Detected: {detected_lang}, Expected: {expected_lang}")

    return True


async def run_all_demos():
    """모든 데모 실행"""
    print("\n" + "#"*60)
    print("# Starting Multimodal Pipeline Demos")
    print("#"*60)
    print()

    demos = [
        ("Text Pipeline", demo_text_pipeline),
        ("Input Router", demo_input_router),
        ("Pipeline Registry", demo_pipeline_registry),
        ("Language Detection", demo_korean_english_detection),
    ]

    results = []

    for name, demo_func in demos:
        try:
            success = await demo_func()
            results.append((name, True))
            print(f"\n✓ {name} demo completed successfully")
        except Exception as e:
            results.append((name, False))
            print(f"\n✗ {name} demo failed: {e}")
            import traceback
            traceback.print_exc()

    # 최종 요약
    print("\n" + "#"*60)
    print("# Demo Results Summary")
    print("#"*60)

    passed = sum(1 for _, success in results if success)
    total = len(results)

    for name, success in results:
        status = "✓ PASS" if success else "✗ FAIL"
        print(f"{status}: {name}")

    print(f"\nTotal: {passed}/{total} demos completed successfully")

    if passed == total:
        print("\n🎉 All demos passed!")
        return 0
    else:
        print(f"\n❌ {total - passed} demo(s) failed")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(run_all_demos())
    print("\n" + "="*60)
    print("Demo completed. Exit code:", exit_code)
    print("="*60)
    sys.exit(exit_code)
