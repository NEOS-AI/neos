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
from typing import Any, List

from langchain_core.language_models import BaseLanguageModel


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
