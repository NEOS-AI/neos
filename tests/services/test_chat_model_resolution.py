from neos.api.models.chat_models import CreateConversationRequest
from neos.api.services.chat_service import resolve_new_chat_model
from neos.services.chat_llm_service import resolve_conversation_chat_model


def test_new_chat_without_selection_uses_anthropic_everyday() -> None:
    request = CreateConversationRequest()

    assert request.model_name is None
    assert resolve_new_chat_model(request.model_name) == "claude-sonnet-5"


def test_explicit_chat_model_is_not_replaced() -> None:
    assert resolve_new_chat_model("openai/gpt-4.1") == "openai/gpt-4.1"


def test_stored_conversation_model_is_not_replaced() -> None:
    assert resolve_conversation_chat_model("openai/gpt-4.1") == "openai/gpt-4.1"
