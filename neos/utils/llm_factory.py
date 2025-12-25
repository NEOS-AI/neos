from typing import Optional, Dict
from abc import ABC, abstractmethod
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.language_models import BaseLanguageModel
import logging

from neos.config.settings import settings


logger = logging.getLogger(__name__)


class LLMProvider(ABC):
    """LLM Provider 추상 클래스"""
    
    @abstractmethod
    def create_llm(self, **kwargs) -> BaseLanguageModel:
        """LLM 인스턴스 생성"""
        pass
    
    @abstractmethod
    def get_provider_name(self) -> str:
        """Provider 이름 반환"""
        pass

class OpenAIProvider(LLMProvider):
    """OpenAI LLM Provider"""
    
    def __init__(self):
        if not settings.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY is required for OpenAI provider")
    
    def create_llm(self, **kwargs) -> ChatOpenAI:
        """OpenAI LLM 생성"""
        default_params = {
            "model": settings.LLM_MODEL,
            "temperature": settings.LLM_TEMPERATURE,
            "api_key": settings.OPENAI_API_KEY,
            "max_retries": 3,
            "request_timeout": settings.LLM_TIMEOUT
        }
        default_params.update(kwargs)

        return ChatOpenAI(**default_params)
    
    def get_provider_name(self) -> str:
        return "openai"

class AnthropicProvider(LLMProvider):
    """Anthropic LLM Provider"""

    def __init__(self):
        if not settings.ANTHROPIC_API_KEY:
            raise ValueError("ANTHROPIC_API_KEY is required for Anthropic provider")

    def create_llm(self, **kwargs) -> ChatAnthropic:
        """Anthropic LLM 생성"""
        default_params = {
            "model": settings.LLM_MODEL,
            "temperature": settings.LLM_TEMPERATURE,
            "api_key": settings.ANTHROPIC_API_KEY,
            "max_retries": 3,
            "timeout": settings.LLM_TIMEOUT
        }
        default_params.update(kwargs)

        # Thinking block 제어
        # 추가 최적화: disable_thinking 파라미터로 조건부 비활성화 지원
        disable_thinking = default_params.pop("disable_thinking", False)

        if (settings.THINKING_BLOCKS_ENABLED or settings.MAX_THINKING_LENGTH > 0) and not disable_thinking:
            if settings.MAX_THINKING_LENGTH < 1024:
                logger.warning("MAX_THINKING_LENGTH is set very low; increasing to 1024 tokens.")
                settings.MAX_THINKING_LENGTH = 1024
            # Check the actual temperature parameter being used, not the global settings
            if default_params.get("temperature", 1.0) != 1.0:
                logger.warning(f"Thinking blocks require temperature=1.0; overriding temperature={default_params.get('temperature')} → 1.0")
                default_params["temperature"] = 1.0
                settings.LLM_TEMPERATURE = 1.0

            thinking={
                "type": "enabled",
                "budget_tokens": settings.MAX_THINKING_LENGTH
            }
            default_params["thinking"] = thinking

            # max_tokens must be greater than thinking.budget_tokens
            # Set it to budget_tokens + sufficient output tokens (default: 4096)
            if "max_tokens" not in default_params:
                default_params["max_tokens"] = settings.MAX_THINKING_LENGTH + 4096
                logger.info(f"Set max_tokens={default_params['max_tokens']} (thinking.budget_tokens={settings.MAX_THINKING_LENGTH} + output=4096)")
            elif default_params["max_tokens"] <= settings.MAX_THINKING_LENGTH:
                logger.warning(f"max_tokens ({default_params['max_tokens']}) must be greater than thinking.budget_tokens ({settings.MAX_THINKING_LENGTH}); adjusting to {settings.MAX_THINKING_LENGTH + 4096}")
                default_params["max_tokens"] = settings.MAX_THINKING_LENGTH + 4096

        return ChatAnthropic(**default_params)

    def get_provider_name(self) -> str:
        return "anthropic"

class GeminiProvider(LLMProvider):
    """Google Gemini LLM Provider"""

    def __init__(self):
        if not settings.GOOGLE_API_KEY:
            raise ValueError("GOOGLE_API_KEY is required for Gemini provider")

    def create_llm(self, **kwargs) -> ChatGoogleGenerativeAI:
        """Gemini LLM 생성"""
        default_params = {
            "model": settings.LLM_MODEL,
            "temperature": settings.LLM_TEMPERATURE,
            "google_api_key": settings.GOOGLE_API_KEY,
            "max_retries": 3,
            "timeout": settings.LLM_TIMEOUT
        }
        default_params.update(kwargs)

        return ChatGoogleGenerativeAI(**default_params)

    def get_provider_name(self) -> str:
        return "gemini"

class LLMFactory:
    """LLM Factory 클래스 - Dependency Injection을 위한 팩토리"""

    _providers = {
        "openai": OpenAIProvider,
        "anthropic": AnthropicProvider,
        "gemini": GeminiProvider
    }

    # LLM 인스턴스 캐시 (이벤트 루프 충돌 방지)
    _llm_cache: Dict[str, BaseLanguageModel] = {}

    @classmethod
    def _get_cache_key(
        cls,
        provider: str,
        model: str,
        temperature: float,
        **kwargs
    ) -> str:
        """캐시 키 생성"""
        # disable_thinking 같은 파라미터는 캐시 키에 포함
        disable_thinking = kwargs.get("disable_thinking", False)
        max_tokens = kwargs.get("max_tokens", 0)
        return f"{provider}:{model}:{temperature}:{disable_thinking}:{max_tokens}"

    @classmethod
    def create_llm(
        cls,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        use_cache: bool = True,
        **kwargs
    ) -> BaseLanguageModel:
        """
        설정된 provider에 따라 LLM 인스턴스 생성 (캐싱 지원)

        Args:
            provider: LLM provider ("openai" or "anthropic")
            model: 모델 이름 (provider별 기본값 사용 시 None)
            temperature: 온도 설정 (기본값 사용 시 None)
            use_cache: 캐시된 인스턴스 재사용 여부 (기본값: True)
            **kwargs: 추가 LLM 파라미터

        Returns:
            BaseLanguageModel: 생성된 LLM 인스턴스
        """
        provider_name = provider or settings.LLM_PROVIDER

        if provider_name not in cls._providers:
            raise ValueError(f"Unsupported LLM provider: {provider_name}")

        try:
            provider_class = cls._providers[provider_name]
            provider_instance = provider_class()

            # 파라미터 오버라이드
            llm_params = {}
            if model:
                llm_params["model"] = model
            else:
                llm_params["model"] = settings.LLM_MODEL

            if temperature is not None:
                llm_params["temperature"] = temperature
            else:
                llm_params["temperature"] = settings.LLM_TEMPERATURE

            llm_params.update(kwargs)

            # 캐시 확인 (use_cache=True인 경우)
            if use_cache:
                cache_key = cls._get_cache_key(
                    provider_name,
                    llm_params["model"],
                    llm_params["temperature"],
                    **kwargs
                )

                if cache_key in cls._llm_cache:
                    logger.debug(f"Using cached LLM: {cache_key}")
                    return cls._llm_cache[cache_key]

            # 새 인스턴스 생성
            llm = provider_instance.create_llm(**llm_params)

            logger.info(f"Created LLM: {provider_instance.get_provider_name()} - {llm_params.get('model', 'default')}")

            # 캐시에 저장
            if use_cache:
                cls._llm_cache[cache_key] = llm
                logger.debug(f"Cached LLM: {cache_key}")

            return llm

        except Exception as e:
            logger.error(f"Failed to create LLM with provider {provider_name}: {e}")

            # Fallback to OpenAI if available
            if provider_name != "openai" and settings.OPENAI_API_KEY:
                logger.warning("Falling back to OpenAI provider")
                fallback_provider = cls._providers["openai"]()
                return fallback_provider.create_llm(**kwargs)

            raise e

    @classmethod
    def clear_cache(cls):
        """LLM 캐시 클리어"""
        cls._llm_cache.clear()
        logger.info("LLM cache cleared")


    @classmethod
    def get_available_providers(cls) -> list[str]:
        """사용 가능한 provider 목록 반환"""
        available = []

        if settings.OPENAI_API_KEY:
            available.append("openai")

        if settings.ANTHROPIC_API_KEY:
            available.append("anthropic")

        if settings.GOOGLE_API_KEY:
            available.append("gemini")

        return available
    
    @classmethod
    def validate_provider_config(cls, provider: str) -> bool:
        """Provider 설정 유효성 검사"""
        try:
            if provider not in cls._providers:
                return False
            
            provider_class = cls._providers[provider]
            provider_class()  # API 키 검증을 위한 인스턴스 생성 시도
            return True
            
        except ValueError:
            return False


# 전역 LLM Factory 인스턴스
llm_factory = LLMFactory()


# 편의 함수들
def create_llm(**kwargs) -> BaseLanguageModel:
    """기본 LLM 생성"""
    return llm_factory.create_llm(**kwargs)

def create_openai_llm(**kwargs) -> ChatOpenAI:
    """OpenAI LLM 강제 생성"""
    return llm_factory.create_llm(provider="openai", **kwargs)

def create_anthropic_llm(**kwargs) -> ChatAnthropic:
    """Anthropic LLM 강제 생성"""
    return llm_factory.create_llm(provider="anthropic", **kwargs)

def create_gemini_llm(**kwargs) -> ChatGoogleGenerativeAI:
    """Gemini LLM 강제 생성"""
    return llm_factory.create_llm(provider="gemini", **kwargs)

def get_recommended_models(provider: str) -> dict[str, str]:
    """Provider별 추천 모델"""
    recommendations = {
        "openai": {
            "fast": "gpt-5-mini-2025-08-07",
            "balanced": "gpt-5-2025-08-07",
            "powerful": "gpt-5-2025-08-07"
        },
        "anthropic": {
            "fast": "claude-haiku-4-5-20251001",
            "balanced": "claude-sonnet-4-5-20250929",
            "powerful": "claude-sonnet-4-5-20250929"
        },
        "gemini": {
            "fast": "gemini-2.0-flash-exp",
            "balanced": "gemini-1.5-pro-latest",
            "powerful": "gemini-1.5-pro-latest"
        }
    }

    return recommendations.get(provider, {})
