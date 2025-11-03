"""
Vision 모델 팩토리 및 헬퍼 함수
"""

from typing import Dict, Any

from neos.config.settings import settings

from .vision_base import VisionModel, VisionProvider
from .vision_gpt4o import GPT4oVision
from .vision_claude import ClaudeVision


class VisionModelFactory:
    """
    Vision 모델 팩토리

    설정에 따라 적절한 Vision 모델을 생성합니다.
    """

    @staticmethod
    def create(provider: VisionProvider = VisionProvider.AUTO) -> VisionModel:
        """
        Vision 모델 생성

        Args:
            provider: 사용할 프로바이더 (AUTO면 설정에서 선택)

        Returns:
            VisionModel 인스턴스

        Raises:
            ValueError: 사용 가능한 모델이 없을 때

        Examples:
            >>> model = VisionModelFactory.create()  # AUTO 선택
            >>> model = VisionModelFactory.create(VisionProvider.GPT4O)
        """
        if provider == VisionProvider.AUTO:
            # 설정에서 자동 선택
            llm_provider = settings.LLM_PROVIDER.lower()
            if llm_provider == "openai":
                provider = VisionProvider.GPT4O
            elif llm_provider == "anthropic":
                provider = VisionProvider.CLAUDE
            else:
                # 기본값: 사용 가능한 첫 번째 모델
                if settings.OPENAI_API_KEY:
                    provider = VisionProvider.GPT4O
                elif settings.ANTHROPIC_API_KEY:
                    provider = VisionProvider.CLAUDE
                else:
                    raise ValueError("No Vision model API key configured")

        # 모델 생성 (fallback 포함)
        if provider == VisionProvider.GPT4O:
            model = GPT4oVision()
            if not model.is_available():
                # OpenAI 실패 시 Claude로 fallback
                print("[VisionModelFactory] GPT4o not available, trying Claude...")
                model = ClaudeVision()
        elif provider == VisionProvider.CLAUDE:
            model = ClaudeVision()
            if not model.is_available():
                # Claude 실패 시 GPT4o로 fallback
                print("[VisionModelFactory] Claude not available, trying GPT4o...")
                model = GPT4oVision()
        else:
            raise ValueError(f"Unknown provider: {provider}")

        # 최종 사용 가능 여부 확인
        if not model.is_available():
            raise ValueError(f"No Vision model API key configured (tried {provider.value})")

        return model


# 편의 함수
async def analyze_image_with_vision(
    image_data: str,
    prompt: str,
    provider: VisionProvider = VisionProvider.AUTO,
    **kwargs
) -> Dict[str, Any]:
    """
    이미지 분석 편의 함수

    Args:
        image_data: Base64 인코딩된 이미지 데이터
        prompt: 분석 요청 프롬프트
        provider: Vision 모델 프로바이더
        **kwargs: 추가 파라미터

    Returns:
        분석 결과

    Examples:
        >>> result = await analyze_image_with_vision(
        ...     image_data="base64_string",
        ...     prompt="이 이미지를 설명해주세요",
        ...     filename="photo.png"
        ... )
    """
    model = VisionModelFactory.create(provider)
    return await model.analyze_image(image_data, prompt, **kwargs)
