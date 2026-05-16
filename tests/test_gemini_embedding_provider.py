"""GeminiEmbeddingProvider 단위 테스트 — google-genai SDK mock 사용"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _make_embedding_response(n: int = 1, dim: int = 3072):
    """mock embed_content 응답 생성"""
    embeddings = []
    for i in range(n):
        e = MagicMock()
        e.values = [float(i) / dim] * dim
        embeddings.append(e)
    resp = MagicMock()
    resp.embeddings = embeddings
    return resp


@pytest.fixture
def provider():
    with patch("neos.utils.embedding_providers.settings") as mock_settings:
        mock_settings.GOOGLE_API_KEY = "test-key"
        mock_settings.GEMINI_EMBEDDING_TASK_TYPE = "retrieval_document"
        mock_settings.GEMINI_EMBEDDING_IMAGE_TASK_TYPE = "retrieval_document"
        mock_settings.GEMINI_EMBEDDING_VIDEO_TASK_TYPE = "retrieval_document"

        with patch("google.genai.Client") as mock_client_cls:
            from neos.utils.embedding_providers import GeminiEmbeddingProvider

            instance = MagicMock()
            instance.aio = MagicMock()
            instance.aio.models = MagicMock()
            mock_client_cls.return_value = instance

            p = GeminiEmbeddingProvider(model="gemini-embedding-2-flash", dimension=3072)
            p._client = instance
            yield p


@pytest.mark.asyncio
async def test_get_embedding_returns_list(provider):
    provider._client.aio.models.embed_content = AsyncMock(
        return_value=_make_embedding_response(n=1, dim=3072)
    )
    result = await provider.get_embedding("hello world")
    assert result is not None
    assert len(result) == 3072
    assert isinstance(result[0], float)


@pytest.mark.asyncio
async def test_get_embeddings_batch_returns_multiple(provider):
    provider._client.aio.models.embed_content = AsyncMock(
        return_value=_make_embedding_response(n=3, dim=3072)
    )
    texts = ["foo", "bar", "baz"]
    result = await provider.get_embeddings_batch(texts)
    assert len(result) == 3
    assert all(len(e) == 3072 for e in result)


@pytest.mark.asyncio
async def test_get_image_embedding_not_none(provider):
    provider._client.aio.models.embed_content = AsyncMock(
        return_value=_make_embedding_response(n=1, dim=3072)
    )
    fake_image = b"\xff\xd8\xff" + b"\x00" * 100
    result = await provider.get_image_embedding(fake_image, mime_type="image/jpeg")
    assert result is not None
    assert len(result) == 3072


def test_supports_multimodal_true_for_v2(provider):
    assert provider.supports_multimodal() is True


def test_dimension_is_3072_by_default():
    with patch("neos.utils.embedding_providers.settings") as mock_settings:
        mock_settings.GOOGLE_API_KEY = "test-key"
        mock_settings.GEMINI_EMBEDDING_TASK_TYPE = "retrieval_document"
        mock_settings.GEMINI_EMBEDDING_IMAGE_TASK_TYPE = "retrieval_document"
        mock_settings.GEMINI_EMBEDDING_VIDEO_TASK_TYPE = "retrieval_document"

        with patch("google.genai.Client"):
            from neos.utils.embedding_providers import GeminiEmbeddingProvider
            p = GeminiEmbeddingProvider()
            assert p.get_dimension() == 3072
            assert p.get_model_name() == "gemini-embedding-2-flash"


# ── 오류 경로 테스트 ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_embedding_returns_none_on_api_error(provider):
    """API 예외 발생 시 None 반환 확인"""
    provider._client.aio.models.embed_content = AsyncMock(
        side_effect=Exception("API quota exceeded")
    )
    result = await provider.get_embedding("hello world")
    assert result is None


@pytest.mark.asyncio
async def test_get_embedding_returns_none_on_empty_response(provider):
    """response.embeddings가 빈 리스트면 IndexError → None 반환 확인"""
    empty_resp = MagicMock()
    empty_resp.embeddings = []
    provider._client.aio.models.embed_content = AsyncMock(return_value=empty_resp)
    result = await provider.get_embedding("hello world")
    assert result is None


@pytest.mark.asyncio
async def test_get_embeddings_batch_fallback_on_error(provider):
    """배치 요청 실패 시 개별 fallback으로 결과 반환 확인"""
    call_count = 0

    async def side_effect(model, contents, config):
        nonlocal call_count
        call_count += 1
        if isinstance(contents, list):
            raise Exception("batch failed")
        resp = MagicMock()
        resp.embeddings = [MagicMock(values=[0.1] * 3072)]
        return resp

    provider._client.aio.models.embed_content = side_effect
    result = await provider.get_embeddings_batch(["a", "b"])
    assert len(result) == 2
    assert all(r is not None for r in result)
    assert call_count == 3  # 배치 1회 실패 + 개별 2회


@pytest.mark.asyncio
async def test_get_image_embedding_returns_none_on_error(provider):
    """이미지 임베딩 API 오류 시 None 반환 확인"""
    provider._client.aio.models.embed_content = AsyncMock(
        side_effect=Exception("unsupported mime type")
    )
    result = await provider.get_image_embedding(b"\xff\xd8\xff", mime_type="image/jpeg")
    assert result is None


def test_invalid_dimension_raises_value_error():
    """유효하지 않은 dimension 값은 ValueError 발생 확인"""
    with patch("neos.utils.embedding_providers.settings") as mock_settings:
        mock_settings.GOOGLE_API_KEY = "test-key"
        with patch("google.genai.Client"):
            from neos.utils.embedding_providers import GeminiEmbeddingProvider
            with pytest.raises(ValueError, match="Invalid embedding dimension"):
                GeminiEmbeddingProvider(dimension=0)


def test_embedding_2_does_not_use_task_type(provider):
    """Embedding 2 계열 모델은 _supports_task_type=False 확인"""
    assert provider._supports_task_type is False
