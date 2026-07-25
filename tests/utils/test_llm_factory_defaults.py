"""LLMFactory 자동 기본 모델 해석 및 폴백 정책 테스트.

I3: model= 를 생략한 자동 호출은 provider × everyday 역할로 해석된다.
I4: 크로스 프로바이더 폴백은 명시적 선택이 없을 때만 동작한다.
"""

from types import SimpleNamespace

import pytest

from neos.config.schema import LLMConfig, ModelRoutingConfig
from neos.utils.llm_factory import LLMFactory, get_default_model


pytestmark = pytest.mark.no_db


class _RecordingProvider:
    """create_llm 인자를 기록하는 가짜 프로바이더."""

    name = "recording"
    calls: list[dict]

    def __init__(self) -> None:
        pass

    def get_provider_name(self) -> str:
        return self.name

    def create_llm(self, model, temperature, max_tokens, **kwargs):
        type(self).calls.append({"model": model, "temperature": temperature})
        return object()


def _make_provider(provider_name: str):
    """호출을 기록하는 프로바이더 클래스를 새로 만든다."""
    return type(
        f"Recording{provider_name.title()}Provider",
        (_RecordingProvider,),
        {"name": provider_name, "calls": []},
    )


class _FailingProvider:
    """생성 시점에 실패하는 프로바이더 (API 키 누락 등)."""

    def __init__(self) -> None:
        raise ValueError("ANTHROPIC_API_KEY is required for Anthropic provider")


def _settings(*, llm_model: str | None, openai_key: str = "test-openai-key"):
    return SimpleNamespace(
        LLM_PROVIDER="anthropic",
        LLM_TEMPERATURE=0.1,
        OPENAI_API_KEY=openai_key,
        config=SimpleNamespace(
            llm=LLMConfig(model=llm_model),
            model_routing=ModelRoutingConfig(),
        ),
    )


@pytest.fixture
def factory(monkeypatch):
    """레지스트리와 캐시를 격리한 LLMFactory를 돌려준다."""
    anthropic = _make_provider("anthropic")
    openai = _make_provider("openai")
    gemini = _make_provider("gemini")

    monkeypatch.setattr(
        LLMFactory,
        "_providers",
        {"anthropic": anthropic, "openai": openai, "gemini": gemini},
    )
    monkeypatch.setattr(LLMFactory, "_llm_cache", {})
    return SimpleNamespace(anthropic=anthropic, openai=openai, gemini=gemini)


# ---------------------------------------------------------------- I3


def test_automatic_call_resolves_anthropic_everyday_default(monkeypatch, factory):
    monkeypatch.setattr("neos.utils.llm_factory.settings", _settings(llm_model=None))

    LLMFactory.create_llm(use_cache=False)

    assert factory.anthropic.calls[0]["model"] == "claude-sonnet-5"


def test_openai_provider_resolves_openai_everyday_default(monkeypatch, factory):
    monkeypatch.setattr("neos.utils.llm_factory.settings", _settings(llm_model=None))

    LLMFactory.create_llm(provider="openai", use_cache=False)

    assert factory.openai.calls[0]["model"] == "gpt-5.6-terra"


def test_configured_llm_model_overrides_the_role_default(monkeypatch, factory):
    monkeypatch.setattr(
        "neos.utils.llm_factory.settings",
        _settings(llm_model="claude-opus-4-6"),
    )

    LLMFactory.create_llm(use_cache=False)

    assert factory.anthropic.calls[0]["model"] == "claude-opus-4-6"


def test_explicit_model_argument_wins_over_everything(monkeypatch, factory):
    monkeypatch.setattr(
        "neos.utils.llm_factory.settings",
        _settings(llm_model="claude-opus-4-6"),
    )

    LLMFactory.create_llm(model="claude-opus-5", use_cache=False)

    assert factory.anthropic.calls[0]["model"] == "claude-opus-5"


def test_get_default_model_reports_the_effective_automatic_model(monkeypatch, factory):
    """CLI 상태 표시는 None이 아니라 실제로 쓰일 모델을 보여줘야 한다."""
    monkeypatch.setattr("neos.utils.llm_factory.settings", _settings(llm_model=None))

    assert get_default_model() == "claude-sonnet-5"
    assert get_default_model("openai") == "gpt-5.6-terra"


def test_unrouted_provider_without_a_model_fails_clearly(monkeypatch, factory):
    monkeypatch.setattr("neos.utils.llm_factory.settings", _settings(llm_model=None))

    with pytest.raises(ValueError, match="gemini"):
        LLMFactory.create_llm(provider="gemini", use_cache=False)


# ---------------------------------------------------------------- I4


def test_automatic_call_falls_back_to_openai_everyday(monkeypatch, factory):
    monkeypatch.setattr("neos.utils.llm_factory.settings", _settings(llm_model=None))
    monkeypatch.setitem(LLMFactory._providers, "anthropic", _FailingProvider)

    LLMFactory.create_llm(use_cache=False)

    assert factory.openai.calls[0]["model"] == "gpt-5.6-terra"


def test_explicit_model_selection_is_never_replaced_by_fallback(monkeypatch, factory):
    monkeypatch.setattr("neos.utils.llm_factory.settings", _settings(llm_model=None))
    monkeypatch.setitem(LLMFactory._providers, "anthropic", _FailingProvider)

    with pytest.raises(ValueError):
        LLMFactory.create_llm(model="claude-opus-5", use_cache=False)

    assert factory.openai.calls == []


def test_explicit_provider_selection_is_never_replaced_by_fallback(monkeypatch, factory):
    monkeypatch.setattr("neos.utils.llm_factory.settings", _settings(llm_model=None))
    monkeypatch.setitem(LLMFactory._providers, "anthropic", _FailingProvider)

    with pytest.raises(ValueError):
        LLMFactory.create_llm(provider="anthropic", use_cache=False)

    assert factory.openai.calls == []
