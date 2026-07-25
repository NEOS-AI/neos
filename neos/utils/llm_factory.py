"""LLMFactory — 프로바이더 레지스트리 기반 LLM 팩토리

Phase 5 (OpenClaw ModelProvider 플러그인)

각 프로바이더 구현은 neos/providers/ 패키지로 분리되어 있다.
LLMFactory는 레지스트리 딕셔너리를 통해 프로바이더에 위임한다.

새 프로바이더 등록:
    from neos.providers.my_provider import MyProvider
    LLMFactory.register_provider("my_provider", MyProvider)
"""

import logging
from typing import Dict, List, Optional, Type

from langchain_core.language_models import BaseLanguageModel

from neos.config.settings import settings
from neos.providers.base import ModelProviderBase
from neos.providers.anthropic import AnthropicProvider
from neos.providers.openai import OpenAIProvider
from neos.providers.gemini import GeminiProvider
from neos.providers.ollama import OllamaProvider

logger = logging.getLogger(__name__)


# 하위 호환성을 위해 기존 코드가 llm_factory에서 직접 임포트하던 클래스 재노출
LLMProvider = ModelProviderBase


class LLMFactory:
    """프로바이더 레지스트리 기반 LLM 팩토리.

    프로바이더는 _providers 딕셔너리에 등록되며, create_llm() 호출 시
    해당 프로바이더의 create_llm()에 위임한다.
    """

    _providers: Dict[str, Type[ModelProviderBase]] = {
        "anthropic": AnthropicProvider,
        "openai": OpenAIProvider,
        "gemini": GeminiProvider,
        "ollama": OllamaProvider,
    }

    # LLM 인스턴스 캐시
    _llm_cache: Dict[str, BaseLanguageModel] = {}

    @classmethod
    def register_provider(cls, name: str, provider_class: Type[ModelProviderBase]) -> None:
        """런타임에 새 프로바이더를 등록한다.

        Args:
            name: 프로바이더 키 (예: "my_provider")
            provider_class: ModelProviderBase 구현 클래스
        """
        cls._providers[name] = provider_class
        logger.info("Registered LLM provider: %s", name)

    @classmethod
    def _get_cache_key(
        cls,
        provider: str,
        model: str,
        temperature: float,
        **kwargs,
    ) -> str:
        # 모든 kwargs를 키에 포함 — streaming 등 옵션이 다른 인스턴스를 구분
        extras = sorted((k, str(v)) for k, v in kwargs.items())
        return f"{provider}:{model}:{temperature}:{extras}"

    @classmethod
    def create_llm(
        cls,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        use_cache: bool = True,
        **kwargs,
    ) -> BaseLanguageModel:
        """설정된 프로바이더에 따라 LLM 인스턴스를 생성한다 (캐싱 지원).

        Args:
            provider: 프로바이더 키 ("anthropic", "openai", "gemini", "ollama")
            model: 모델 식별자 (None이면 settings.LLM_MODEL 사용)
            temperature: 온도 (None이면 settings.LLM_TEMPERATURE 사용)
            use_cache: 캐시 재사용 여부
            **kwargs: 프로바이더별 추가 파라미터

        Returns:
            BaseLanguageModel 인스턴스
        """
        provider_name = provider or settings.LLM_PROVIDER

        if provider_name not in cls._providers:
            raise ValueError(f"Unsupported LLM provider: {provider_name}")

        resolved_model = model or settings.LLM_MODEL
        resolved_temperature = temperature if temperature is not None else settings.LLM_TEMPERATURE
        resolved_max_tokens = kwargs.pop("max_tokens", 0)

        if use_cache:
            cache_key = cls._get_cache_key(
                provider_name,
                resolved_model,
                resolved_temperature,
                max_tokens=resolved_max_tokens,
                **kwargs,
            )
            if cache_key in cls._llm_cache:
                logger.debug("Using cached LLM: %s", cache_key)
                return cls._llm_cache[cache_key]

        try:
            provider_instance = cls._providers[provider_name]()
            llm = provider_instance.create_llm(
                model=resolved_model,
                temperature=resolved_temperature,
                max_tokens=resolved_max_tokens,
                **kwargs,
            )
            logger.info(
                "Created LLM: %s - %s",
                provider_instance.get_provider_name(),
                resolved_model,
            )

            if use_cache:
                cls._llm_cache[cache_key] = llm
                logger.debug("Cached LLM: %s", cache_key)

            return llm

        except Exception as exc:
            logger.error(
                "Failed to create LLM with provider %s: %s",
                provider_name,
                exc,
                exc_info=True,
            )

            # Ollama는 명시적 로컬 서비스 — 미설치/미실행 시 fallback 없이 즉시 실패
            if provider_name == "ollama":
                raise

            # 폴백: OpenAI가 사용 가능하면 전환
            if provider_name != "openai" and settings.OPENAI_API_KEY:
                logger.error(
                    "FALLING BACK to OpenAI from %s — check provider configuration",
                    provider_name,
                )
                fallback = OpenAIProvider()
                return fallback.create_llm(
                    model=settings.LLM_MODEL,
                    temperature=resolved_temperature,
                    max_tokens=resolved_max_tokens,
                    **kwargs,
                )
            raise

    @classmethod
    def clear_cache(cls) -> None:
        """LLM 인스턴스 캐시를 비운다."""
        cls._llm_cache.clear()
        logger.info("LLM cache cleared")

    @classmethod
    def get_available_providers(cls) -> List[str]:
        """현재 API 키 설정이 완료된 프로바이더 목록을 반환한다."""
        available = []
        for name, provider_class in cls._providers.items():
            try:
                instance = provider_class()
                if instance.validate_config():
                    available.append(name)
            except (ValueError, ImportError):
                pass
        return available

    @classmethod
    def validate_provider_config(cls, provider: str) -> bool:
        """특정 프로바이더 설정 유효성을 검사한다."""
        if provider not in cls._providers:
            return False
        try:
            instance = cls._providers[provider]()
            return instance.validate_config()
        except (ValueError, ImportError):
            return False

    @classmethod
    def list_provider_models(cls, provider: str) -> List[str]:
        """특정 프로바이더의 지원 모델 목록을 반환한다."""
        if provider not in cls._providers:
            return []
        try:
            return cls._providers[provider]().list_models()
        except (ValueError, ImportError):
            return []


# 전역 LLM Factory 인스턴스
llm_factory = LLMFactory()


# 편의 함수 (하위 호환성 유지)
def create_llm(**kwargs) -> BaseLanguageModel:
    return llm_factory.create_llm(**kwargs)


def create_openai_llm(**kwargs) -> BaseLanguageModel:
    return llm_factory.create_llm(provider="openai", **kwargs)


def create_anthropic_llm(**kwargs) -> BaseLanguageModel:
    return llm_factory.create_llm(provider="anthropic", **kwargs)


def create_gemini_llm(**kwargs) -> BaseLanguageModel:
    return llm_factory.create_llm(provider="gemini", **kwargs)


def create_ollama_llm(**kwargs) -> BaseLanguageModel:
    """Ollama 로컬 LLM 생성 (langchain-ollama 설치 필요)."""
    return llm_factory.create_llm(provider="ollama", **kwargs)


def get_recommended_models(provider: str) -> dict[str, str]:
    """Provider별 추천 모델 (fast / balanced / powerful)."""
    recommendations = {
        "openai": {
            "fast": "gpt-5-mini-2025-08-07",
            "balanced": "gpt-5.6-terra",
            "powerful": "gpt-5.6-sol",
        },
        "anthropic": {
            "fast": "claude-haiku-4-5-20251001",
            "balanced": "claude-sonnet-5",
            "powerful": "claude-opus-5",
        },
        "gemini": {
            "fast": "gemini-2.0-flash-exp",
            "balanced": "gemini-1.5-pro-latest",
            "powerful": "gemini-1.5-pro-latest",
        },
        "ollama": {
            "fast": "llama3.1:8b",
            "balanced": "llama3.1:8b",
            "powerful": "llama3.1:70b",
        },
    }
    return recommendations.get(provider, {})
