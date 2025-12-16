"""
임베딩 Provider 추상화 레이어

여러 임베딩 provider를 지원하기 위한 통합 인터페이스를 제공합니다.
"""

from abc import ABC, abstractmethod
from typing import List, Optional
import logging
import asyncio

from neos.config.settings import settings

logger = logging.getLogger(__name__)


class EmbeddingProvider(ABC):
    """임베딩 Provider 추상 클래스"""

    @abstractmethod
    async def get_embedding(self, text: str) -> Optional[List[float]]:
        """단일 텍스트 임베딩 생성"""
        pass

    @abstractmethod
    async def get_embeddings_batch(self, texts: List[str]) -> List[Optional[List[float]]]:
        """배치 임베딩 생성"""
        pass

    @abstractmethod
    def get_dimension(self) -> int:
        """임베딩 차원 반환"""
        pass

    @abstractmethod
    def get_model_name(self) -> str:
        """모델 이름 반환"""
        pass

    @abstractmethod
    def get_provider_name(self) -> str:
        """Provider 이름 반환"""
        pass


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """OpenAI 임베딩 Provider"""

    def __init__(self, model: str = "text-embedding-3-small"):
        if not settings.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY is required for OpenAI embeddings")

        import openai
        self.client = openai.AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        self.model = model

        # 모델별 차원 매핑
        self.dimension_map = {
            "text-embedding-3-small": 1536,
            "text-embedding-3-large": 3072,
            "text-embedding-ada-002": 1536
        }
        self.dimension = self.dimension_map.get(model, 1536)

    async def get_embedding(self, text: str) -> Optional[List[float]]:
        try:
            response = await self.client.embeddings.create(
                input=text,
                model=self.model
            )
            return response.data[0].embedding
        except Exception as e:
            logger.error(f"OpenAI embedding error: {e}")
            return None

    async def get_embeddings_batch(self, texts: List[str]) -> List[Optional[List[float]]]:
        try:
            response = await self.client.embeddings.create(
                input=texts,
                model=self.model
            )
            return [data.embedding for data in response.data]
        except Exception as e:
            logger.error(f"OpenAI batch embedding error: {e}")
            return [None] * len(texts)

    def get_dimension(self) -> int:
        return self.dimension

    def get_model_name(self) -> str:
        return self.model

    def get_provider_name(self) -> str:
        return "openai"


class GeminiEmbeddingProvider(EmbeddingProvider):
    """Google Gemini 임베딩 Provider"""

    def __init__(self, model: str = "gemini-embedding-001", dimension: int = 1536):
        if not settings.GOOGLE_API_KEY:
            raise ValueError("GOOGLE_API_KEY is required for Gemini embeddings")

        import google.generativeai as genai
        genai.configure(api_key=settings.GOOGLE_API_KEY)

        self.model = model
        self.dimension = dimension  # Gemini는 유연한 차원 지원 (128-3072)
        self.genai = genai

    async def get_embedding(self, text: str) -> Optional[List[float]]:
        try:
            # Gemini SDK는 동기식이므로 executor로 래핑
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: self.genai.embed_content(
                    model=self.model,
                    content=text,
                    task_type="retrieval_document",
                    output_dimensionality=self.dimension
                )
            )
            return result['embedding']
        except Exception as e:
            logger.error(f"Gemini embedding error: {e}")
            return None

    async def get_embeddings_batch(self, texts: List[str]) -> List[Optional[List[float]]]:
        """
        Gemini batch embedding

        Note: Gemini API는 batch 호출을 지원합니다.
        """
        try:
            # Batch API 호출
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: self.genai.embed_content(
                    model=self.model,
                    content=texts,
                    task_type="retrieval_document",
                    output_dimensionality=self.dimension
                )
            )

            # 결과가 단일 임베딩인 경우와 리스트인 경우 처리
            if isinstance(result.get('embedding'), list) and len(result['embedding']) > 0:
                # 첫 번째 요소가 숫자인지 확인 (단일 임베딩)
                if isinstance(result['embedding'][0], (int, float)):
                    # 단일 텍스트에 대한 임베딩
                    return [result['embedding']]
                else:
                    # 여러 텍스트에 대한 임베딩
                    return result['embedding']

            return [None] * len(texts)

        except Exception as e:
            logger.error(f"Gemini batch embedding error: {e}")
            # 오류 시 개별 처리로 폴백
            logger.info("Falling back to individual embedding requests")
            results = []
            for text in texts:
                embedding = await self.get_embedding(text)
                results.append(embedding)
                # Rate limiting을 위한 작은 지연
                if len(results) < len(texts):
                    await asyncio.sleep(0.05)  # 50ms
            return results

    def get_dimension(self) -> int:
        return self.dimension

    def get_model_name(self) -> str:
        return self.model

    def get_provider_name(self) -> str:
        return "gemini"


class EmbeddingProviderFactory:
    """임베딩 Provider 팩토리"""

    _providers = {
        "openai": OpenAIEmbeddingProvider,
        "gemini": GeminiEmbeddingProvider
    }

    @classmethod
    def create(
        cls,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        dimension: Optional[int] = None
    ) -> EmbeddingProvider:
        """
        임베딩 provider 생성

        Args:
            provider: "openai" or "gemini" (기본값: settings.EMBEDDING_PROVIDER)
            model: 모델 이름 (기본값: settings.EMBEDDING_MODEL)
            dimension: 임베딩 차원 (기본값: settings.EMBEDDING_DIMENSION, Gemini 전용)

        Returns:
            EmbeddingProvider 인스턴스
        """
        provider_name = provider or settings.EMBEDDING_PROVIDER
        model_name = model or settings.EMBEDDING_MODEL
        embedding_dimension = dimension or settings.EMBEDDING_DIMENSION

        if provider_name not in cls._providers:
            raise ValueError(f"Unsupported embedding provider: {provider_name}")

        provider_class = cls._providers[provider_name]

        # Provider별로 다른 파라미터 전달
        if provider_name == "gemini":
            return provider_class(model=model_name, dimension=embedding_dimension)
        else:
            return provider_class(model=model_name)

    @classmethod
    def get_available_providers(cls) -> List[str]:
        """사용 가능한 provider 목록 반환"""
        available = []
        if settings.OPENAI_API_KEY:
            available.append("openai")
        if settings.GOOGLE_API_KEY:
            available.append("gemini")
        return available
