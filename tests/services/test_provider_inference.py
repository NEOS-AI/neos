"""모델명 → provider 추론이 카탈로그를 먼저 본다.

예전에는 이름에 `gpt`/`claude`가 들어 있는지만 봤다. 그래서 `o3`처럼 둘 다
없는 OpenAI 모델이 기본 provider(anthropic)로 떨어졌다 — 카탈로그가
`openai`라고 말하고 OpenAI 피커에 노출되던 모델인데도.

`o3`는 이제 은퇴했지만 휴리스틱 자체는 그대로 틀렸다. 이름에 provider가
드러나지 않는 모델은 계속 나온다.
"""

import pytest

from neos.config.model_config import provider_for_model

pytestmark = pytest.mark.no_db


def test_catalog_decides_for_known_models() -> None:
    assert provider_for_model("claude-sonnet-5") == "anthropic"
    assert provider_for_model("claude-opus-5-5") == "anthropic"
    assert provider_for_model("gpt-6-sol") == "openai"
    assert provider_for_model("gpt-6-luna") == "openai"
    assert provider_for_model("gpt-6-astra") == "openai"
    assert provider_for_model("gpt-4o") == "openai"


def test_unknown_model_falls_back_to_the_given_default() -> None:
    assert provider_for_model("something-new", default="anthropic") == "anthropic"
    assert provider_for_model("something-new") is None


@pytest.fixture
def restore_model_config(monkeypatch):
    """스크래치 카탈로그를 쓴 뒤 실제 카탈로그를 되돌린다.

    `ModelConfig`는 클래스 수준 싱글톤이라 되돌리지 않으면 이후 모든
    테스트가 오염된다.
    """
    yield
    monkeypatch.delenv("NEOS_MODEL_CONFIG_PATH", raising=False)
    from neos.config.model_config import model_config

    model_config.reload()


def test_name_without_a_provider_hint_is_resolved_by_the_catalog(
    tmp_path, monkeypatch, restore_model_config
) -> None:
    """이름에 gpt/claude가 없어도 카탈로그가 알면 맞게 나온다.

    은퇴한 `o3`가 정확히 이 경우였다 — OpenAI 모델인데 이름만 보면 알 수 없어
    기본 provider(anthropic)로 잘못 갔다.
    """
    import yaml

    from neos.config.model_config import model_config

    scratch = tmp_path / "models.yaml"
    scratch.write_text(
        yaml.safe_dump(
            {"models": {"o4-preview": {"provider": "openai", "thinking": "none"}}},
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("NEOS_MODEL_CONFIG_PATH", str(scratch))
    model_config.reload()

    assert "gpt" not in "o4-preview" and "claude" not in "o4-preview"
    assert provider_for_model("o4-preview", default="anthropic") == "openai"


class TestChatServiceInference:
    def test_uses_the_catalog_before_the_name_heuristic(self) -> None:
        from neos.services.chat_llm_service import ChatLLMService

        service = ChatLLMService.__new__(ChatLLMService)
        service.default_provider = "anthropic"

        assert service._extract_provider_from_model("gpt-6-sol") == "openai"
        assert service._extract_provider_from_model("claude-sonnet-5") == "anthropic"

    def test_keeps_the_name_heuristic_for_uncatalogued_models(self) -> None:
        """카탈로그는 allowlist가 아니다 — 모르는 이름도 최선을 다한다."""
        from neos.services.chat_llm_service import ChatLLMService

        service = ChatLLMService.__new__(ChatLLMService)
        service.default_provider = "anthropic"

        assert service._extract_provider_from_model("gpt-9-unreleased") == "openai"
        assert service._extract_provider_from_model("claude-99") == "anthropic"
        assert service._extract_provider_from_model("mystery-model") == "anthropic"


class TestDeepAnalysisInference:
    def test_client_and_payload_shape_agree(self) -> None:
        """provider 선택과 요청 페이로드 형태가 같은 판단을 쓴다.

        `_default_client`와 `_call_provider`가 서로 다른 기준을 쓰면 Anthropic
        클라이언트에 OpenAI 페이로드를 보내는 조합이 생긴다.
        """
        from neos.workflow.deep_analysis import llm

        for model, expected in (
            ("claude-sonnet-5", True),
            ("claude-opus-5-5", True),
            ("gpt-6-sol", False),
            ("gpt-6-luna", False),
            ("gpt-6-astra", False),
            ("gpt-4o", False),
        ):
            assert llm._is_anthropic_model(model) is expected

    def test_uncatalogued_names_keep_the_prefix_heuristic(self) -> None:
        from neos.workflow.deep_analysis import llm

        assert llm._is_anthropic_model("claude-from-the-future") is True
        assert llm._is_anthropic_model("gpt-from-the-future") is False
