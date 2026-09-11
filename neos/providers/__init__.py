"""NEOS Model Providers — 플러그인 방식 LLM 프로바이더 패키지

Phase 5 (OpenClaw ModelProvider 플러그인)

새 프로바이더 추가 방법:
1. ModelProviderBase를 상속한 클래스를 이 패키지에 추가
2. LLMFactory._providers 딕셔너리에 등록

    from neos.providers.my_provider import MyProvider
    LLMFactory.register_provider("my_provider", MyProvider)
"""

from .base import CodingCapabilities, ModelProviderBase
from .anthropic import AnthropicProvider
from .openai import OpenAIProvider
from .gemini import GeminiProvider
from .ollama import OllamaProvider

__all__ = [
    "CodingCapabilities",
    "ModelProviderBase",
    "AnthropicProvider",
    "OpenAIProvider",
    "GeminiProvider",
    "OllamaProvider",
]
