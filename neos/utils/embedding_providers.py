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

    async def get_image_embedding(self, image_bytes: bytes, mime_type: str = "image/jpeg") -> Optional[List[float]]:
        """이미지 임베딩 생성 (멀티모달 지원 provider만 구현)"""
        raise NotImplementedError(f"{self.get_provider_name()} does not support image embedding")

    async def get_video_embedding(self, video_bytes: bytes, mime_type: str = "video/mp4") -> Optional[List[float]]:
        """영상 임베딩 생성 (멀티모달 지원 provider만 구현)"""
        raise NotImplementedError(f"{self.get_provider_name()} does not support video embedding")

    def supports_multimodal(self) -> bool:
        """멀티모달 임베딩 지원 여부"""
        return False


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """OpenAI 임베딩 Provider"""

    def __init__(self, model: str = "text-embedding-3-small"):
        if not settings.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY is required for OpenAI embeddings")

        import openai
        self.client = openai.AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        self.model = model

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
    """Google Gemini Embedding 2 Provider — google-genai SDK, native async"""

    SUPPORTED_MODELS = {
        "gemini-embedding-2-flash": {"max_dim": 3072, "multimodal": True,  "task_type": False},
        "gemini-embedding-2":       {"max_dim": 3072, "multimodal": True,  "task_type": False},
        "gemini-embedding-001":     {"max_dim": 3072, "multimodal": False, "task_type": True},
    }

    def __init__(self, model: str = "gemini-embedding-2-flash", dimension: int = 3072):
        if not settings.GOOGLE_API_KEY:
            raise ValueError("GOOGLE_API_KEY is required for Gemini embeddings")
        if not (1 <= dimension <= 3072):
            raise ValueError(f"Invalid embedding dimension: {dimension} (must be 1–3072)")

        from google import genai
        from google.genai import types as genai_types

        self._client = genai.Client(api_key=settings.GOOGLE_API_KEY)
        self._types = genai_types
        self.model = model
        self.dimension = dimension
        self._supports_task_type = self.SUPPORTED_MODELS.get(model, {}).get("task_type", False)

    def _make_config(self, task_type: str):
        """모델 버전에 따라 EmbedContentConfig 생성. Embedding 2 계열은 task_type 미지원."""
        kwargs = {"output_dimensionality": self.dimension}
        if self._supports_task_type:
            kwargs["task_type"] = task_type
        return self._types.EmbedContentConfig(**kwargs)

    async def get_embedding(self, text: str) -> Optional[List[float]]:
        try:
            response = await self._client.aio.models.embed_content(
                model=self.model,
                contents=text,
                config=self._make_config(settings.GEMINI_EMBEDDING_TASK_TYPE),
            )
            return response.embeddings[0].values
        except Exception as e:
            logger.error(f"Gemini embedding error: {e}")
            return None

    async def get_embeddings_batch(self, texts: List[str]) -> List[Optional[List[float]]]:
        try:
            response = await self._client.aio.models.embed_content(
                model=self.model,
                contents=texts,
                config=self._make_config(settings.GEMINI_EMBEDDING_TASK_TYPE),
            )
            return [e.values for e in response.embeddings]
        except Exception as e:
            logger.error(f"Gemini batch embedding error: {e}")
            logger.info("Falling back to individual embedding requests")
            results = []
            for text in texts:
                embedding = await self.get_embedding(text)
                results.append(embedding)
                if len(results) < len(texts):
                    await asyncio.sleep(0.05)
            return results

    async def get_image_embedding(self, image_bytes: bytes, mime_type: str = "image/jpeg") -> Optional[List[float]]:
        try:
            image_part = self._types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
            response = await self._client.aio.models.embed_content(
                model=self.model,
                contents=image_part,
                config=self._make_config(settings.GEMINI_EMBEDDING_IMAGE_TASK_TYPE),
            )
            return response.embeddings[0].values
        except Exception as e:
            logger.error(f"Gemini image embedding error: {e}")
            return None

    async def get_video_embedding(self, video_bytes: bytes, mime_type: str = "video/mp4") -> Optional[List[float]]:
        try:
            video_part = self._types.Part.from_bytes(data=video_bytes, mime_type=mime_type)
            response = await self._client.aio.models.embed_content(
                model=self.model,
                contents=video_part,
                config=self._make_config(settings.GEMINI_EMBEDDING_VIDEO_TASK_TYPE),
            )
            return response.embeddings[0].values
        except Exception as e:
            logger.error(f"Gemini video embedding error: {e}")
            return None

    def supports_multimodal(self) -> bool:
        return self.SUPPORTED_MODELS.get(self.model, {}).get("multimodal", False)

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
        embedding_dimension = dimension if dimension is not None else settings.EMBEDDING_DIMENSION

        if provider_name not in cls._providers:
            raise ValueError(f"Unsupported embedding provider: {provider_name}")

        provider_class = cls._providers[provider_name]

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
