from types import SimpleNamespace

import pytest

from neos.coding.model.anthropic import AnthropicCodingModel
from neos.coding.model.gemini import GeminiCodingModel
from neos.coding.model.ollama import OllamaCodingModel
from neos.coding.model.openai import OpenAICodingModel
from neos.providers.anthropic import AnthropicProvider
from neos.providers.gemini import GeminiProvider
from neos.providers.ollama import OllamaProvider
from neos.providers.openai import OpenAIProvider
from neos.utils.llm_factory import LLMFactory

pytestmark = pytest.mark.no_db


def test_all_current_providers_advertise_coding_support() -> None:
    for provider in (AnthropicProvider, OpenAIProvider, GeminiProvider, OllamaProvider):
        instance = provider.__new__(provider)
        assert instance.coding_capabilities().supported is True
        assert instance.coding_capabilities().streaming_tools is True


def test_factory_builds_anthropic_coding_model(monkeypatch) -> None:
    monkeypatch.setattr(
        "neos.utils.anthropic_client.AsyncAnthropic",
        lambda **kwargs: SimpleNamespace(api_key=kwargs.get("api_key")),
    )

    model = LLMFactory.create_coding_model(provider="anthropic", api_key="sk-ant")

    assert isinstance(model, AnthropicCodingModel)


def test_factory_builds_openai_coding_model(monkeypatch) -> None:
    monkeypatch.setattr(
        "neos.utils.openai_client.AsyncOpenAI",
        lambda **kwargs: SimpleNamespace(api_key=kwargs.get("api_key")),
    )

    model = LLMFactory.create_coding_model(provider="openai", api_key="sk-openai")

    assert isinstance(model, OpenAICodingModel)


def test_factory_builds_gemini_coding_model(monkeypatch) -> None:
    import google.genai as genai

    monkeypatch.setattr(genai, "Client", lambda **kwargs: object())

    model = LLMFactory.create_coding_model(provider="gemini", api_key="gk")

    assert isinstance(model, GeminiCodingModel)


def test_factory_builds_ollama_coding_model(monkeypatch) -> None:
    monkeypatch.setattr(
        "httpx.AsyncClient",
        lambda **kwargs: object(),
    )

    model = LLMFactory.create_coding_model(
        provider="ollama", base_url="http://localhost:11434"
    )

    assert isinstance(model, OllamaCodingModel)
    assert model._base_url == "http://localhost:11434"


def test_gemini_list_models_comes_from_the_catalog() -> None:
    models = GeminiProvider.__new__(GeminiProvider).list_models()

    assert "gemini-2.0-flash-exp" in models
    assert "gemini-2.5-flash-lite" in models
    assert "gemini-1.5-pro-latest" in models
