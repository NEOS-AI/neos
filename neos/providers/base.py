"""ModelProviderBase — 모델 프로바이더 플러그인 인터페이스

Phase 5 (OpenClaw ModelProvider 플러그인)

새 프로바이더를 추가하려면:
1. ModelProviderBase를 상속한 클래스 구현
2. neos/providers/ 에 파일 추가
3. LLMFactory._providers 딕셔너리에 등록

설계 원칙:
- create_llm()은 LangChain BaseLanguageModel을 반환하여 기존 코드와 호환
- list_models()는 프로바이더가 지원하는 모델 식별자 목록 반환
- validate_config()는 API 키 등 필수 설정 유효성 검사
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, List, Protocol

from langchain_core.language_models import BaseLanguageModel


@dataclass(frozen=True, slots=True)
class CodingCapabilities:
    """What the coding harness can ask this vendor to do.

    `create_llm()` stays LangChain-shaped for chat/HDR. The coding loop
    never sees that type — it talks to a `CodingModel` from
    `create_coding_model()`.
    """

    supported: bool = False
    streaming_tools: bool = False
    prompt_cache: bool = False


class CodingModelPort(Protocol):
    def stream(self, request: Any) -> Any: ...


class ModelProviderBase(ABC):
    """모델 프로바이더 플러그인 추상 기본 클래스.

    모든 프로바이더는 이 인터페이스를 구현해야 한다.
    """

    @abstractmethod
    def create_llm(
        self,
        model: str,
        temperature: float,
        max_tokens: int,
        **kwargs: Any,
    ) -> BaseLanguageModel:
        """LLM 인스턴스 생성.

        Args:
            model: 모델 식별자 (예: "claude-opus-4-6", "gpt-4o")
            temperature: 샘플링 온도 (0.0~1.0)
            max_tokens: 최대 출력 토큰 수
            **kwargs: 프로바이더별 추가 파라미터

        Returns:
            LangChain BaseLanguageModel 호환 인스턴스
        """
        ...

    @abstractmethod
    def list_models(self) -> List[str]:
        """이 프로바이더가 지원하는 추천 모델 식별자 목록 반환."""
        ...

    @abstractmethod
    def get_provider_name(self) -> str:
        """프로바이더 고유 이름 반환 (레지스트리 키로 사용)."""
        ...

    def validate_config(self) -> bool:
        """설정 유효성 검사. 기본 구현은 True 반환.

        필수 API 키 검증 등 프로바이더별 설정 검사가 필요하면 오버라이드한다.
        """
        return True

    def coding_capabilities(self) -> CodingCapabilities:
        """코딩 루프가 이 벤더를 쓸 수 있는지. 기본은 불가."""
        return CodingCapabilities()

    def create_coding_model(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        max_tool_input_bytes: int = 65_536,
        max_tool_input_depth: int = 16,
        **kwargs: Any,
    ) -> CodingModelPort:
        """네이티브 코딩 스트림 어댑터를 만든다.

        LangChain `create_llm()` 과 분리한다. 코딩 루프는 tool JSON
        조각·413·stop reason 을 벤더 어휘 없이 받아야 한다.
        """
        raise NotImplementedError(
            f"{self.get_provider_name()} does not support the coding loop"
        )
