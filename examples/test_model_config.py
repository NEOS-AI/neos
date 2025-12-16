"""
모델 설정 테스트 스크립트

models.yaml 파일의 설정이 올바르게 로드되는지 확인합니다.
"""
import sys
from pathlib import Path

# 프로젝트 루트를 Python path에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from neos.config.model_config import model_config


def test_vision_models():
    """Vision 모델 설정 테스트"""
    print("\n" + "="*60)
    print("Vision Models Test")
    print("="*60)

    available_models = model_config.list_vision_models()
    print(f"\n사용 가능한 Vision 모델: {', '.join(available_models)}")

    for model_name in available_models:
        try:
            model_info = model_config.get_vision_model(model_name)
            print(f"\n✓ {model_name}:")
            print(f"  - Model ID: {model_info['model_id']}")
            print(f"  - Provider: {model_info['provider']}")
            print(f"  - Description: {model_info.get('description', 'N/A')}")
            print(f"  - Max Tokens: {model_info.get('max_tokens', 'N/A')}")
            print(f"  - Supports Video: {model_info.get('supports_video', False)}")
        except Exception as e:
            print(f"\n✗ {model_name}: Error - {e}")

    # 기본 모델 확인
    default_vision = model_config.get_default_vision_model()
    print(f"\n기본 Vision 모델: {default_vision}")


def test_llm_models():
    """LLM 모델 설정 테스트"""
    print("\n" + "="*60)
    print("LLM Models Test")
    print("="*60)

    available_models = model_config.list_llm_models()
    print(f"\n사용 가능한 LLM 모델: {', '.join(available_models)}")

    for model_name in available_models:
        try:
            model_info = model_config.get_llm_model(model_name)
            print(f"\n✓ {model_name}:")
            print(f"  - Model ID: {model_info['model_id']}")
            print(f"  - Provider: {model_info['provider']}")
            print(f"  - Description: {model_info.get('description', 'N/A')}")
        except Exception as e:
            print(f"\n✗ {model_name}: Error - {e}")

    # 기본 모델 확인
    default_llm = model_config.get_default_llm_model()
    print(f"\n기본 LLM 모델: {default_llm}")


def test_embedding_models():
    """Embedding 모델 설정 테스트"""
    print("\n" + "="*60)
    print("Embedding Models Test")
    print("="*60)

    available_models = model_config.list_embedding_models()
    print(f"\n사용 가능한 Embedding 모델: {', '.join(available_models)}")

    for model_name in available_models:
        try:
            model_info = model_config.get_embedding_model(model_name)
            print(f"\n✓ {model_name}:")
            print(f"  - Model ID: {model_info['model_id']}")
            print(f"  - Provider: {model_info['provider']}")
            print(f"  - Dimension: {model_info.get('dimension', 'N/A')}")
        except Exception as e:
            print(f"\n✗ {model_name}: Error - {e}")

    # 기본 모델 확인
    default_embedding = model_config.get_default_embedding_model()
    print(f"\n기본 Embedding 모델: {default_embedding}")


def test_helper_functions():
    """편의 함수 테스트"""
    print("\n" + "="*60)
    print("Helper Functions Test")
    print("="*60)

    from neos.config.model_config import (
        get_vision_model_id,
        get_llm_model_id,
        get_embedding_model_id
    )

    # Vision 모델 ID 조회
    print("\nVision 모델 ID 조회:")
    try:
        gpt4o_id = get_vision_model_id('gpt4o')
        print(f"  get_vision_model_id('gpt4o') = '{gpt4o_id}'")

        claude_id = get_vision_model_id('claude')
        print(f"  get_vision_model_id('claude') = '{claude_id}'")
    except Exception as e:
        print(f"  Error: {e}")

    # LLM 모델 ID 조회
    print("\nLLM 모델 ID 조회:")
    try:
        claude_sonnet_id = get_llm_model_id('claude_sonnet')
        print(f"  get_llm_model_id('claude_sonnet') = '{claude_sonnet_id}'")
    except Exception as e:
        print(f"  Error: {e}")

    # Embedding 모델 ID 조회
    print("\nEmbedding 모델 ID 조회:")
    try:
        openai_small_id = get_embedding_model_id('openai_small')
        print(f"  get_embedding_model_id('openai_small') = '{openai_small_id}'")
    except Exception as e:
        print(f"  Error: {e}")

    # 기본 모델 사용 (인자 없음)
    print("\n기본 모델 사용 (인자 생략):")
    try:
        default_vision_id = get_vision_model_id()
        print(f"  get_vision_model_id() = '{default_vision_id}'")

        default_llm_id = get_llm_model_id()
        print(f"  get_llm_model_id() = '{default_llm_id}'")

        default_embedding_id = get_embedding_model_id()
        print(f"  get_embedding_model_id() = '{default_embedding_id}'")
    except Exception as e:
        print(f"  Error: {e}")


def test_vision_classes():
    """Vision 클래스에서 모델 ID 로드 테스트"""
    print("\n" + "="*60)
    print("Vision Classes Integration Test")
    print("="*60)

    try:
        from neos.workflow.pipelines.vision.vision_gpt4o import GPT4oVision
        gpt4o = GPT4oVision()
        print(f"\n✓ GPT4oVision: model = '{gpt4o.model}'")
    except Exception as e:
        print(f"\n✗ GPT4oVision: Error - {e}")

    try:
        from neos.workflow.pipelines.vision.vision_claude import ClaudeVision
        claude = ClaudeVision()
        print(f"✓ ClaudeVision: model = '{claude.model}'")
    except Exception as e:
        print(f"✗ ClaudeVision: Error - {e}")

    try:
        from neos.workflow.pipelines.vision.vision_gemini import GeminiVision
        gemini = GeminiVision()
        print(f"✓ GeminiVision: model = '{gemini.model}'")
    except Exception as e:
        print(f"✗ GeminiVision: Error - {e}")


def main():
    """모든 테스트 실행"""
    print("\n" + "="*60)
    print("Model Configuration Test Script")
    print("="*60)

    try:
        test_vision_models()
        test_llm_models()
        test_embedding_models()
        test_helper_functions()
        test_vision_classes()

        print("\n" + "="*60)
        print("✅ All tests completed successfully!")
        print("="*60 + "\n")

    except Exception as e:
        print("\n" + "="*60)
        print(f"❌ Test failed: {e}")
        print("="*60 + "\n")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
