"""
Vision 모델 통합 데모

GPT-4o와 Claude Vision을 사용한 이미지 분석 데모입니다.
"""

import asyncio
import sys
from pathlib import Path
from PIL import Image
import io

# 프로젝트 루트 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# 직접 모듈 임포트 (workflow/__init__.py 의존성 회피)
import importlib.util

def load_module_from_file(module_name, file_path):
    """파일에서 직접 모듈 로드"""
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module

# 필요한 모듈들 로드
pipelines_path = project_root / "neos" / "workflow" / "pipelines"
base = load_module_from_file("pipelines_base", pipelines_path / "base.py")
vision_models = load_module_from_file("vision_models", pipelines_path / "vision_models.py")
image_pipeline = load_module_from_file("image_pipeline", pipelines_path / "image_pipeline.py")

# 필요한 클래스 가져오기
InputType = base.InputType
PipelineContext = base.PipelineContext
FileInput = base.FileInput
ImagePipeline = image_pipeline.ImagePipeline
VisionProvider = vision_models.VisionProvider
VisionModelFactory = vision_models.VisionModelFactory
GPT4oVision = vision_models.GPT4oVision
ClaudeVision = vision_models.ClaudeVision


async def demo_image_pipeline_with_vision():
    """Vision 통합된 ImagePipeline 데모"""
    print("="*60)
    print("Vision Model Integration Demo")
    print("="*60)
    print()

    # 1. Vision 비활성화 모드
    print("[Demo 1] ImagePipeline without Vision")
    print("-"*60)

    pipeline_no_vision = ImagePipeline(enable_vision=False)

    # 테스트 이미지 생성 (빨간색 사각형)
    img = Image.new("RGB", (200, 200), color="red")
    img_bytes = io.BytesIO()
    img.save(img_bytes, format="PNG")
    img_content = img_bytes.getvalue()

    file = FileInput(
        filename="red_square.png",
        file_content=img_content,
        mime_type="image/png",
        file_size=len(img_content)
    )

    context = PipelineContext(
        query="What color is this image?",
        input_type=InputType.IMAGE,
        files=[file],
        language="en"
    )

    result = await pipeline_no_vision.process(context)

    print(f"✓ Success: {result.success}")
    print(f"✓ Vision Enabled: {result.analysis['vision_enabled']}")
    print(f"✓ Insights: {result.insights}")
    print(f"✓ Processing Time: {result.processing_time_ms:.2f}ms")
    print()

    # 2. Vision 활성화 모드 (Mock 테스트)
    print("[Demo 2] ImagePipeline with Vision (Mock Test)")
    print("-"*60)

    pipeline_with_vision = ImagePipeline(
        vision_provider=VisionProvider.AUTO,
        enable_vision=True
    )

    # 파란색 이미지 생성
    img2 = Image.new("RGB", (300, 300), color="blue")
    img2_bytes = io.BytesIO()
    img2.save(img2_bytes, format="PNG")
    img2_content = img2_bytes.getvalue()

    file2 = FileInput(
        filename="blue_square.png",
        file_content=img2_content,
        mime_type="image/png",
        file_size=len(img2_content)
    )

    context2 = PipelineContext(
        query="이 이미지에서 무엇이 보이나요?",
        input_type=InputType.IMAGE,
        files=[file2],
        language="ko"
    )

    # Vision 모델이 없으면 에러가 날 것이므로 try-catch
    try:
        result2 = await pipeline_with_vision.process(context2)

        print(f"✓ Success: {result2.success}")
        print(f"✓ Vision Enabled: {result2.analysis['vision_enabled']}")

        if result2.extracted_text:
            print(f"✓ Vision Analysis: {result2.extracted_text[:100]}...")

        if "vision_provider" in result2.analysis:
            print(f"✓ Vision Provider: {result2.analysis['vision_provider']}")

        print(f"✓ Insights: {result2.insights}")
        print(f"✓ Processing Time: {result2.processing_time_ms:.2f}ms")

        if result2.warnings:
            print(f"⚠ Warnings: {result2.warnings}")

    except Exception as e:
        print(f"⚠ Vision API not configured or error occurred: {e}")
        print("  This is expected if you haven't set up OPENAI_API_KEY or ANTHROPIC_API_KEY")

    print()

    # 3. 통합 컨텍스트 확인
    print("[Demo 3] Unified Context")
    print("-"*60)
    print(result.unified_context[:500])
    print("...")
    print()

    return True


async def demo_vision_models():
    """Vision 모델 직접 사용 데모"""
    print("="*60)
    print("Direct Vision Model Usage Demo")
    print("="*60)
    print()

    # 1. Vision 모델 초기화 확인
    print("[Check 1] Vision Model Availability")
    print("-"*60)

    gpt4o = GPT4oVision()
    claude = ClaudeVision()

    print(f"✓ GPT-4o Available: {gpt4o.is_available()}")
    print(f"✓ Claude Available: {claude.is_available()}")
    print()

    # 2. Factory 패턴 테스트
    print("[Check 2] Vision Model Factory")
    print("-"*60)

    try:
        auto_model = VisionModelFactory.create(VisionProvider.AUTO)
        print(f"✓ Auto-selected model: {auto_model.__class__.__name__}")
    except ValueError as e:
        print(f"⚠ No Vision model available: {e}")
        print("  Please set OPENAI_API_KEY or ANTHROPIC_API_KEY in .env")

    print()


async def main():
    """메인 함수"""
    print("\n" + "#"*60)
    print("# Vision Integration Demos")
    print("#"*60)
    print()

    # Demo 1: Vision 모델 직접 사용
    await demo_vision_models()

    # Demo 2: ImagePipeline with Vision
    await demo_image_pipeline_with_vision()

    print("#"*60)
    print("# Demo Completed!")
    print("#"*60)
    print()

    print("Next Steps:")
    print("1. Set OPENAI_API_KEY or ANTHROPIC_API_KEY in .env")
    print("2. Set VISION_ENABLED=true in .env")
    print("3. Run with real image files to test Vision models")
    print()


if __name__ == "__main__":
    asyncio.run(main())
