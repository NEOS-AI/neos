"""LLMFactory — 프로바이더 레지스트리 기반 LLM 팩토리

Phase 5 (OpenClaw ModelProvider 플러그인)

각 프로바이더 구현은 neos/providers/ 패키지로 분리되어 있다.
LLMFactory는 레지스트리 딕셔너리를 통해 프로바이더에 위임한다.

새 프로바이더 등록:
    from neos.providers.my_provider import MyProvider
    LLMFactory.register_provider("my_provider", MyProvider)
"""

import logging
from typing import Dict, List, Optional, Type, cast

from langchain_core.language_models import BaseLanguageModel

from neos.config.model_config import get_model_spec, tiers_for_provider
from neos.config.model_routing import ModelProvider, resolve_model
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

    # 카탈로그에 없는 모델을 이미 경고한 이름들 — 로그 폭주를 막는다
    _warned_unknown_models: set[str] = set()

    # request.model_name은 사용자 입력이다 — 캡이 없으면 이 집합이 무한정
    # 자란다. 캡에 도달하면 dedup 기록은 멈추지만 경고 자체는 계속 낸다
    # (운영자에게 신호를 계속 주는 쪽을 택함; 대신 그 이름은 매 호출마다
    # 다시 경고될 수 있다).
    _MAX_WARNED_UNKNOWN_MODELS = 1000

    @classmethod
    def register_provider(cls, name: str, provider_class: Type[ModelProviderBase]) -> None:
        """런타임에 새 프로바이더를 등록한다.

        Args:
            name: 프로바이더 키 (예: "my_provider")
            provider_class: ModelProviderBase 구현 클래스
        """
        cls._providers[name] = provider_class
        logger.info("Registered LLM provider: %s", name)

    # 역할 라우팅 정책이 적용되는 프로바이더. 나머지는 명시적 모델을 요구한다.
    _ROLE_ROUTED_PROVIDERS = frozenset({"anthropic", "openai"})

    @classmethod
    def _resolve_default_model(cls, provider_name: str) -> str:
        """model= 을 생략한 자동 호출의 기본 모델을 해석한다.

        `llm.model`이 설정돼 있으면 배포 오버라이드로 취급하고, 없으면
        provider × everyday 역할 기본값을 쓴다.
        """
        configured = settings.config.llm.model

        if provider_name in cls._ROLE_ROUTED_PROVIDERS:
            return resolve_model(
                config=settings.config.model_routing,
                provider=cast(ModelProvider, provider_name),
                role="everyday",
                feature_override=configured,
            ).model

        if configured:
            return configured

        raise ValueError(
            f"No default model for provider {provider_name!r}: "
            "pass model= explicitly or set llm.model in configuration"
        )

    @classmethod
    def _warn_if_unknown_model(cls, model: str) -> None:
        """카탈로그에 없는 모델을 이름별 1회 경고한다.

        카탈로그는 allowlist가 아니다 — 카탈로그 갱신 전에도 신종 모델을
        지정할 수 있어야 하므로 통과시킨다. 다만 그 모델의 가격과 thinking
        계약은 기본값으로 떨어진다.
        """
        if model in cls._warned_unknown_models:
            return
        if get_model_spec(model) is not None:
            return
        if len(cls._warned_unknown_models) < cls._MAX_WARNED_UNKNOWN_MODELS:
            cls._warned_unknown_models.add(model)
        logger.warning(
            "Model %r is not declared in the model catalog "
            "(neos/config/models.yaml); pricing and thinking contract fall back "
            "to defaults",
            model,
        )

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
            model: 모델 식별자 (None이면 provider × everyday 역할 기본값으로 해석)
            temperature: 온도 (None이면 settings.LLM_TEMPERATURE 사용)
            use_cache: 캐시 재사용 여부
            **kwargs: 프로바이더별 추가 파라미터

        Returns:
            BaseLanguageModel 인스턴스
        """
        # 호출자가 provider나 model을 직접 지정했는지 — 폴백 허용 여부를 가른다
        explicit_selection = provider is not None or model is not None
        provider_name = provider or settings.LLM_PROVIDER

        if provider_name not in cls._providers:
            raise ValueError(f"Unsupported LLM provider: {provider_name}")

        resolved_model = model or cls._resolve_default_model(provider_name)
        cls._warn_if_unknown_model(resolved_model)
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

            # 호출자가 provider나 model을 명시했으면 그 선택을 절대 덮어쓰지 않는다.
            # 크로스 프로바이더 폴백은 아무것도 지정하지 않은 자동 워크로드 전용이다.
            if explicit_selection:
                logger.error(
                    "NOT falling back from %s/%s — caller explicitly selected %s",
                    provider_name,
                    resolved_model,
                    "model" if model is not None else "provider",
                )
                raise

            fallback_class = cls._providers.get("openai")
            if provider_name != "openai" and fallback_class and settings.OPENAI_API_KEY:
                fallback_model = resolve_model(
                    config=settings.config.model_routing,
                    provider="openai",
                    role="everyday",
                ).model
                logger.error(
                    "FALLING BACK to OpenAI %s from %s — check provider configuration",
                    fallback_model,
                    provider_name,
                )
                return fallback_class().create_llm(
                    model=fallback_model,
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

    @classmethod
    def create_coding_model(
        cls,
        *,
        provider: str,
        api_key: str | None = None,
        base_url: str | None = None,
        **kwargs,
    ):
        """코딩 루프용 네이티브 `CodingModel` 을 프로바이더에 위임해 만든다.

        LangChain `create_llm()` 과 섞지 않는다. 프로바이더 생성자의
        환경변수 검사는 건너뛴다 — 런타임이 `config.secrets` 에서 키를
        넘긴다.
        """
        if provider not in cls._providers:
            raise ValueError(f"Unsupported LLM provider: {provider}")
        provider_class = cls._providers[provider]
        instance = provider_class.__new__(provider_class)
        capabilities = instance.coding_capabilities()
        if not capabilities.supported:
            raise ValueError(f"{provider} does not support the coding loop")
        return instance.create_coding_model(
            api_key=api_key, base_url=base_url, **kwargs
        )


# 전역 LLM Factory 인스턴스
llm_factory = LLMFactory()


# 편의 함수 (하위 호환성 유지)
def create_llm(**kwargs) -> BaseLanguageModel:
    return llm_factory.create_llm(**kwargs)


def get_default_model(provider: Optional[str] = None) -> str:
    """model= 없이 호출했을 때 실제로 쓰일 모델을 돌려준다 (상태 표시용)."""
    return LLMFactory._resolve_default_model(provider or settings.LLM_PROVIDER)


def create_openai_llm(**kwargs) -> BaseLanguageModel:
    return llm_factory.create_llm(provider="openai", **kwargs)


def create_anthropic_llm(**kwargs) -> BaseLanguageModel:
    return llm_factory.create_llm(provider="anthropic", **kwargs)


def create_gemini_llm(**kwargs) -> BaseLanguageModel:
    return llm_factory.create_llm(provider="gemini", **kwargs)


def create_ollama_llm(**kwargs) -> BaseLanguageModel:
    """Ollama 로컬 LLM 생성 (langchain-ollama 설치 필요)."""
    return llm_factory.create_llm(provider="ollama", **kwargs)


def create_coding_model(*, provider: str, **kwargs):
    return llm_factory.create_coding_model(provider=provider, **kwargs)


def get_recommended_models(provider: str) -> dict[str, str]:
    """Provider별 추천 모델 (fast / balanced / powerful).

    모델 카탈로그(`neos/config/models.yaml`)의 `tiers`에서 파생된다.
    라우팅 역할이 아니라 운영자용 수동 참고값이다
    (`docs/CONFIGURATION.md` — Model Routing 참조).
    """
    return tiers_for_provider(provider)
