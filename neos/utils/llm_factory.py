from typing import Optional
from abc import ABC, abstractmethod
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain.schema.language_model import BaseLanguageModel
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
            "request_timeout": 60
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
            "timeout": 60
        }
        default_params.update(kwargs)
        
        return ChatAnthropic(**default_params)
    
    def get_provider_name(self) -> str:
        return "anthropic"

class LLMFactory:
    """LLM Factory 클래스 - Dependency Injection을 위한 팩토리"""
    
    _providers = {
        "openai": OpenAIProvider,
        "anthropic": AnthropicProvider
    }
    
    @classmethod
    def create_llm(
        self, 
        provider: Optional[str] = None, 
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        **kwargs
    ) -> BaseLanguageModel:
        """
        설정된 provider에 따라 LLM 인스턴스 생성
        
        Args:
            provider: LLM provider ("openai" or "anthropic")
            model: 모델 이름 (provider별 기본값 사용 시 None)
            temperature: 온도 설정 (기본값 사용 시 None)
            **kwargs: 추가 LLM 파라미터
        
        Returns:
            BaseLanguageModel: 생성된 LLM 인스턴스
        """
        provider_name = provider or settings.LLM_PROVIDER
        
        if provider_name not in self._providers:
            raise ValueError(f"Unsupported LLM provider: {provider_name}")
        
        try:
            provider_class = self._providers[provider_name]
            provider_instance = provider_class()
            
            # 파라미터 오버라이드
            llm_params = {}
            if model:
                llm_params["model"] = model
            if temperature is not None:
                llm_params["temperature"] = temperature
            
            llm_params.update(kwargs)
            
            llm = provider_instance.create_llm(**llm_params)
            
            logger.info(f"Created LLM: {provider_instance.get_provider_name()} - {llm_params.get('model', 'default')}")
            return llm
            
        except Exception as e:
            logger.error(f"Failed to create LLM with provider {provider_name}: {e}")
            
            # Fallback to OpenAI if available
            if provider_name != "openai" and settings.OPENAI_API_KEY:
                logger.warning("Falling back to OpenAI provider")
                fallback_provider = self._providers["openai"]()
                return fallback_provider.create_llm(**kwargs)
            
            raise e
    
    @classmethod
    def get_available_providers(cls) -> list[str]:
        """사용 가능한 provider 목록 반환"""
        available = []
        
        if settings.OPENAI_API_KEY:
            available.append("openai")
        
        if settings.ANTHROPIC_API_KEY:
            available.append("anthropic")
        
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

def get_recommended_models(provider: str) -> dict[str, str]:
    """Provider별 추천 모델"""
    recommendations = {
        "openai": {
            "fast": "gpt-3.5-turbo",
            "balanced": "gpt-4-turbo-preview", 
            "powerful": "gpt-4"
        },
        "anthropic": {
            "fast": "claude-3-haiku-20240307",
            "balanced": "claude-3-sonnet-20240229",
            "powerful": "claude-3-opus-20240229"
        }
    }
    
    return recommendations.get(provider, {})
