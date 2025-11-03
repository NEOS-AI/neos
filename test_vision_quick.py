"""
Vision 모델 빠른 테스트
"""

import asyncio
import base64
from pathlib import Path

from neos.workflow.pipelines.vision_models import VisionModelFactory, VisionProvider


async def test_vision():
    """Vision 모델 테스트"""

    # 테스트 이미지 로드
    image_path = "test_image.jpg"

    if not Path(image_path).exists():
        print(f"❌ Test image not found: {image_path}")
        return

    with open(image_path, "rb") as f:
        image_bytes = f.read()
        image_base64 = base64.b64encode(image_bytes).decode('utf-8')

    print(f"✅ Loaded image: {len(image_base64)} chars")

    # 1. GPT-4o 테스트
    print("\n" + "="*80)
    print("Testing GPT-4o Vision")
    print("="*80)

    try:
        from neos.workflow.pipelines.vision_models import GPT4oVision

        gpt4o = GPT4oVision()

        if gpt4o.is_available():
            print("✅ GPT-4o API key configured")

            result = await gpt4o.analyze_image(
                image_data=image_base64,
                prompt="이 이미지를 간단히 설명해주세요."
            )

            print(f"✅ GPT-4o Response:")
            print(f"   Description: {result['description'][:100]}...")
            print(f"   Provider: {result['metadata'].get('provider')}")
            print(f"   Model: {result['metadata'].get('model')}")
        else:
            print("⚠️  GPT-4o API key not configured")

    except Exception as e:
        print(f"❌ GPT-4o Error: {e}")
        import traceback
        traceback.print_exc()

    # 2. Claude 테스트
    print("\n" + "="*80)
    print("Testing Claude Vision")
    print("="*80)

    try:
        from neos.workflow.pipelines.vision_models import ClaudeVision

        claude = ClaudeVision()

        if claude.is_available():
            print(f"✅ Claude API key configured")
            print(f"   Model: {claude.model}")

            result = await claude.analyze_image(
                image_data=image_base64,
                prompt="이 이미지를 간단히 설명해주세요."
            )

            if "error" in result["metadata"]:
                print(f"❌ Claude Error: {result['metadata']['error']}")
                print(f"   Error Type: {result['metadata'].get('error_type')}")
                if "traceback" in result["metadata"]:
                    print(f"   Traceback:\n{result['metadata']['traceback']}")
            else:
                print(f"✅ Claude Response:")
                print(f"   Description: {result['description'][:100]}...")
                print(f"   Provider: {result['metadata'].get('provider')}")
                print(f"   Model: {result['metadata'].get('model')}")
        else:
            print("⚠️  Claude API key not configured")

    except Exception as e:
        print(f"❌ Claude Error: {e}")
        import traceback
        traceback.print_exc()

    # 3. Factory 테스트 (AUTO)
    print("\n" + "="*80)
    print("Testing VisionModelFactory (AUTO)")
    print("="*80)

    try:
        model = VisionModelFactory.create(provider=VisionProvider.AUTO)
        print(f"✅ Factory selected: {type(model).__name__}")

        result = await model.analyze_image(
            image_data=image_base64,
            prompt="이 이미지를 간단히 설명해주세요."
        )

        if "error" in result["metadata"]:
            print(f"❌ Error: {result['metadata']['error']}")
        else:
            print(f"✅ Response:")
            print(f"   Description: {result['description'][:100]}...")
            print(f"   Provider: {result['metadata'].get('provider')}")

    except Exception as e:
        print(f"❌ Factory Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_vision())
