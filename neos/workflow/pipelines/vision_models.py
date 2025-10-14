"""
Vision 모델 통합

GPT-4o와 Claude Vision을 통합하여 이미지 분석을 제공합니다.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
from enum import Enum
import base64
from pathlib import Path

from neos.config.settings import settings


class VisionProvider(Enum):
    """Vision 모델 프로바이더"""
    GPT4O = "gpt4o"
    CLAUDE = "claude"
    AUTO = "auto"  # 자동 선택 (설정 기반)


class VisionModel(ABC):
    """
    Vision 모델 추상 베이스 클래스

    모든 Vision 모델이 구현해야 하는 공통 인터페이스입니다.
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key

    @abstractmethod
    async def analyze_image(
        self,
        image_data: str,  # base64 encoded image
        prompt: str,
        **kwargs
    ) -> Dict[str, Any]:
        """
        이미지 분석

        Args:
            image_data: Base64로 인코딩된 이미지
            prompt: 분석 요청 프롬프트
            **kwargs: 추가 파라미터

        Returns:
            분석 결과 딕셔너리
        """
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """
        모델 사용 가능 여부 확인

        Returns:
            사용 가능하면 True
        """
        pass

    def _create_result(
        self,
        description: str,
        objects: Optional[List[Dict[str, Any]]] = None,
        text: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        confidence: float = 0.0
    ) -> Dict[str, Any]:
        """
        표준화된 결과 생성

        Args:
            description: 이미지 설명
            objects: 감지된 객체 리스트
            text: OCR로 추출된 텍스트
            metadata: 추가 메타데이터
            confidence: 신뢰도 점수 (0.0-1.0)

        Returns:
            표준화된 결과 딕셔너리
        """
        return {
            "description": description,
            "objects": objects or [],
            "text": text or "",
            "metadata": metadata or {},
            "confidence": confidence,
        }


class GPT4oVision(VisionModel):
    """
    GPT-4o Vision 모델

    OpenAI의 GPT-4o를 사용한 이미지 분석
    """

    def __init__(self, api_key: Optional[str] = None):
        super().__init__(api_key or settings.OPENAI_API_KEY)
        self.model = "gpt-4o"  # GPT-4o 모델


    async def analyze_image(
        self,
        image_data: str,
        prompt: str,
        max_tokens: int = 1000,
        **kwargs
    ) -> Dict[str, Any]:
        """GPT-4o로 이미지 분석"""
        if not self.is_available():
            raise ValueError("OpenAI API key not configured")

        try:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=self.api_key)

            # GPT-4o Vision API 호출
            response = await client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{image_data}",
                                    "detail": kwargs.get("detail", "auto")  # auto, low, high
                                }
                            }
                        ]
                    }
                ],
                max_tokens=max_tokens,
                temperature=kwargs.get("temperature", 0.1)
            )

            # 응답 파싱
            content = response.choices[0].message.content

            # 추가 정보 추출 (간단한 파싱)
            result = self._parse_response(content)

            # 메타데이터 추가
            result["metadata"].update({
                "provider": "gpt4o",
                "model": self.model,
                "tokens_used": response.usage.total_tokens if response.usage else 0,
                "finish_reason": response.choices[0].finish_reason
            })

            return result

        except ImportError:
            raise ImportError("openai package not installed. Run: pip install openai")
        except Exception as e:
            return {
                "description": f"Error analyzing image with GPT-4o: {str(e)}",
                "objects": [],
                "text": "",
                "metadata": {"error": str(e), "provider": "gpt4o"},
                "confidence": 0.0
            }

    def is_available(self) -> bool:
        """OpenAI API 키 확인"""
        return bool(self.api_key and self.api_key.strip())

    def _parse_response(self, content: str) -> Dict[str, Any]:
        """
        GPT-4o 응답 파싱

        간단한 파싱으로 객체, 텍스트 등을 추출합니다.
        """
        # 기본 결과 (상세 파싱은 향후 개선 가능)
        return self._create_result(
            description=content,
            confidence=0.8  # GPT-4o는 일반적으로 높은 신뢰도
        )


class ClaudeVision(VisionModel):
    """
    Claude Vision 모델

    Anthropic의 Claude 3을 사용한 이미지 분석
    """

    def __init__(self, api_key: Optional[str] = None):
        super().__init__(api_key or settings.ANTHROPIC_API_KEY)
        self.model = "claude-3-5-sonnet-20241022"  # Claude 3.5 Sonnet

    async def analyze_image(
        self,
        image_data: str,
        prompt: str,
        max_tokens: int = 1000,
        **kwargs
    ) -> Dict[str, Any]:
        """Claude Vision으로 이미지 분석"""
        if not self.is_available():
            raise ValueError("Anthropic API key not configured")

        try:
            from anthropic import AsyncAnthropic

            client = AsyncAnthropic(api_key=self.api_key)

            # Claude Vision API 호출
            response = await client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/jpeg",  # 또는 image/png
                                    "data": image_data,
                                }
                            },
                            {
                                "type": "text",
                                "text": prompt
                            }
                        ]
                    }
                ],
                temperature=kwargs.get("temperature", 0.1)
            )

            # 응답 파싱
            content = response.content[0].text if response.content else ""

            result = self._parse_response(content)

            # 메타데이터 추가
            result["metadata"].update({
                "provider": "claude",
                "model": self.model,
                "tokens_used": response.usage.input_tokens + response.usage.output_tokens if response.usage else 0,
                "stop_reason": response.stop_reason
            })

            return result

        except ImportError:
            raise ImportError("anthropic package not installed. Run: pip install anthropic")
        except Exception as e:
            return {
                "description": f"Error analyzing image with Claude: {str(e)}",
                "objects": [],
                "text": "",
                "metadata": {"error": str(e), "provider": "claude"},
                "confidence": 0.0
            }

    def is_available(self) -> bool:
        """Anthropic API 키 확인"""
        return bool(self.api_key and self.api_key.strip())

    def _parse_response(self, content: str) -> Dict[str, Any]:
        """
        Claude 응답 파싱

        간단한 파싱으로 객체, 텍스트 등을 추출합니다.
        """
        return self._create_result(
            description=content,
            confidence=0.85  # Claude는 매우 높은 신뢰도
        )


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

        # 모델 생성
        if provider == VisionProvider.GPT4O:
            model = GPT4oVision()
        elif provider == VisionProvider.CLAUDE:
            model = ClaudeVision()
        else:
            raise ValueError(f"Unknown provider: {provider}")

        # 사용 가능 여부 확인
        if not model.is_available():
            raise ValueError(f"{provider.value} API key not configured")

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
        image_data: Base64 인코딩된 이미지
        prompt: 분석 요청 프롬프트
        provider: 사용할 프로바이더
        **kwargs: 추가 파라미터

    Returns:
        분석 결과
    """
    model = VisionModelFactory.create(provider)
    return await model.analyze_image(image_data, prompt, **kwargs)
