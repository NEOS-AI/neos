"""OllamaProvider — Ollama 로컬 LLM 프로바이더 (신규)

Phase 5 (OpenClaw ModelProvider 플러그인)

Ollama는 로컬에서 오픈소스 LLM(Llama, Mistral, Gemma 등)을 실행한다.
langchain-ollama 패키지가 필요하다:
    uv add --optional ollama 'langchain-ollama>=0.2.0'

환경 변수:
    OLLAMA_BASE_URL       서버 주소 (기본: http://localhost:11434)
    OLLAMA_DEFAULT_MODEL  기본 모델 (기본: llama3.1:8b)
"""

import logging
from typing import Any, List

from langchain_core.language_models import BaseLanguageModel

from neos.config.settings import settings
from .base import ModelProviderBase

logger = logging.getLogger(__name__)


class OllamaProvider(ModelProviderBase):
    """Ollama 로컬 LLM 서버 프로바이더.

    langchain-ollama 패키지를 선택적으로 임포트하여 미설치 환경에서도
    다른 프로바이더 기능이 정상 동작하도록 설계되었다.
    """

    def __init__(self):
        # 임포트 가능 여부만 확인 (실제 연결은 create_llm 시점에 발생)
        try:
            import langchain_ollama  # noqa: F401
        except ImportError:
            raise ImportError(
                "langchain-ollama 패키지가 필요합니다. "
                "설치 명령: uv add --optional ollama 'langchain-ollama>=0.2.0'"
            )

    def get_provider_name(self) -> str:
        return "ollama"

    _DEFAULT_MODELS = [
        "llama3.1:8b",
        "llama3.1:70b",
        "mistral:7b",
        "gemma2:9b",
        "qwen2.5:7b",
        "deepseek-r1:8b",
    ]

    def list_models(self) -> List[str]:
        """실제 Ollama 서버에 설치된 모델 목록 조회.

        서버에 연결할 수 없거나 API 호출이 실패하면 기본 추천 목록을 반환한다.
        """
        try:
            import httpx

            resp = httpx.get(
                f"{settings.OLLAMA_BASE_URL}/api/tags",
                timeout=3.0,
            )
            resp.raise_for_status()
            models = [m["name"] for m in resp.json().get("models", [])]
            if models:
                return models
        except Exception:
            logger.debug("Ollama API unreachable, returning default model list")
        return self._DEFAULT_MODELS

    def validate_config(self) -> bool:
        return bool(settings.OLLAMA_BASE_URL)

    def create_llm(
        self,
        model: str,
        temperature: float,
        max_tokens: int,
        **kwargs: Any,
    ) -> BaseLanguageModel:
        """ChatOllama 인스턴스 생성.

        Ollama는 API 키가 없으므로 base_url만 설정한다.
        """
        from langchain_ollama import ChatOllama

        params: dict[str, Any] = {
            "model": model or settings.OLLAMA_DEFAULT_MODEL,
            "temperature": temperature,
            "base_url": settings.OLLAMA_BASE_URL,
        }
        if max_tokens:
            params["num_predict"] = max_tokens  # Ollama는 max_tokens 대신 num_predict 사용
        params.update(kwargs)

        logger.info(
            "Creating Ollama LLM: model=%s, base_url=%s",
            params["model"],
            params["base_url"],
        )
        return ChatOllama(**params)
