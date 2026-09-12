"""사용자가 통제하는 model_name이 세 문(턴 오버라이드/대화 생성/재생성)에서
같은 selectable 게이트를 통과해야 한다는 것을 고정한다.

- POST /conversations -> CreateConversationRequest.model_name
- POST /messages/{id}/regenerate -> RegenerateMessageRequest.model_name

둘 다 값이 명시적으로 주어졌을 때만 검증하고(생략 시 기존대로 서비스가
기본값을 정한다), 거부는 400 하나로 통일한다. "선택 불가 모델"과 "존재하지
않는 모델"은 정보 노출 방지를 위해 완전히 같은 메시지를 내야 한다.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from neos.api.handlers import chat_handlers
from neos.api.models.chat_models import CreateConversationRequest, RegenerateMessageRequest


def _conversation(model_name: str = "gpt-4o-mini") -> dict:
    return {
        "conversation_id": "c1",
        "user_id": "owner",
        "title": "New chat",
        "summary": None,
        "model_name": model_name,
        "model_version": None,
        "system_prompt": None,
        "temperature": 0.7,
        "max_tokens": None,
        "mode": "standard",
        "status": "active",
        "is_pinned": False,
        "is_shared": False,
        "share_token": None,
        "visibility": "private",
        "message_count": 0,
        "total_tokens_used": 0,
        "total_cost": 0.0,
        "last_message_at": None,
        "last_accessed_at": None,
        "created_at": "2026-07-01T00:00:00",
        "updated_at": "2026-07-01T00:00:00",
        "tags": [],
        "metadata": {},
    }


def _message() -> dict:
    return {
        "message_id": "m1",
        "conversation_id": "c1",
        "sequence_number": 2,
        "parent_message_id": None,
    }


CURRENT_USER = SimpleNamespace(user_id="owner", is_active=True)


# ---------------------------------------------------------------------------
# create_conversation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_conversation_rejects_non_selectable_catalog_model(monkeypatch):
    """claude-opus-4-8은 카탈로그 멤버지만 selectable: false -- 400이어야 한다."""
    create = AsyncMock(return_value=_conversation())
    monkeypatch.setattr(chat_handlers.ChatService, "create_conversation", create)
    request = CreateConversationRequest(conversation_id="c1", model_name="claude-opus-4-8")

    with pytest.raises(HTTPException) as exc_info:
        await chat_handlers.create_conversation(request, current_user=CURRENT_USER)

    assert exc_info.value.status_code == 400
    create.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_conversation_rejects_unknown_model_with_same_message(monkeypatch):
    """존재하지 않는 모델도 400 -- 그리고 non-selectable 케이스와 문구가 같아야 한다
    (어떤 모델이 존재하는지 흘리지 않기 위해)."""
    create = AsyncMock(return_value=_conversation())
    monkeypatch.setattr(chat_handlers.ChatService, "create_conversation", create)

    unknown_request = CreateConversationRequest(
        conversation_id="c1", model_name="totally-bogus-model"
    )
    non_selectable_request = CreateConversationRequest(
        conversation_id="c1", model_name="claude-opus-4-8"
    )

    with pytest.raises(HTTPException) as unknown_exc:
        await chat_handlers.create_conversation(unknown_request, current_user=CURRENT_USER)
    with pytest.raises(HTTPException) as non_selectable_exc:
        await chat_handlers.create_conversation(
            non_selectable_request, current_user=CURRENT_USER
        )

    assert unknown_exc.value.status_code == non_selectable_exc.value.status_code == 400
    assert unknown_exc.value.detail == non_selectable_exc.value.detail
    create.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_conversation_allows_omitted_model_name(monkeypatch):
    """model_name 생략 -- 기존대로 서비스 기본값에 맡기고 성공한다."""
    create = AsyncMock(return_value=_conversation())
    monkeypatch.setattr(chat_handlers.ChatService, "create_conversation", create)
    request = CreateConversationRequest(conversation_id="c1")

    result = await chat_handlers.create_conversation(request, current_user=CURRENT_USER)

    assert result is not None
    create.assert_awaited_once()
    assert create.await_args.kwargs["model_name"] is None


@pytest.mark.asyncio
async def test_create_conversation_allows_selectable_model(monkeypatch):
    """정상 선택 가능 모델(claude-sonnet-5)은 그대로 통과한다."""
    create = AsyncMock(return_value=_conversation(model_name="claude-sonnet-5"))
    monkeypatch.setattr(chat_handlers.ChatService, "create_conversation", create)
    request = CreateConversationRequest(conversation_id="c1", model_name="claude-sonnet-5")

    result = await chat_handlers.create_conversation(request, current_user=CURRENT_USER)

    assert result is not None
    create.assert_awaited_once()
    assert create.await_args.kwargs["model_name"] == "claude-sonnet-5"


@pytest.mark.asyncio
async def test_create_conversation_allows_selectable_gemini_model(monkeypatch):
    """gemini-1.5-pro-latest is selectable and not role-routed — the gate must not 400."""
    create = AsyncMock(return_value=_conversation(model_name="gemini-1.5-pro-latest"))
    monkeypatch.setattr(chat_handlers.ChatService, "create_conversation", create)
    request = CreateConversationRequest(
        conversation_id="c1", model_name="gemini-1.5-pro-latest"
    )

    result = await chat_handlers.create_conversation(request, current_user=CURRENT_USER)

    assert result is not None
    create.assert_awaited_once()
    assert create.await_args.kwargs["model_name"] == "gemini-1.5-pro-latest"


# ---------------------------------------------------------------------------
# regenerate_message
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_regenerate_message_rejects_non_selectable_catalog_model(monkeypatch):
    generate_response = AsyncMock()
    monkeypatch.setattr(chat_handlers.chat_llm_service, "generate_response", generate_response)
    monkeypatch.setattr(
        chat_handlers.ChatService, "get_conversation", AsyncMock(return_value=_conversation())
    )
    request = RegenerateMessageRequest(message_id="m1", model_name="claude-opus-4-8")

    with pytest.raises(HTTPException) as exc_info:
        await chat_handlers.regenerate_message(
            message_id="m1", request=request, original_message=_message()
        )

    assert exc_info.value.status_code == 400
    generate_response.assert_not_awaited()


@pytest.mark.asyncio
async def test_regenerate_message_rejects_unknown_model_with_same_message(monkeypatch):
    generate_response = AsyncMock()
    monkeypatch.setattr(chat_handlers.chat_llm_service, "generate_response", generate_response)
    monkeypatch.setattr(
        chat_handlers.ChatService, "get_conversation", AsyncMock(return_value=_conversation())
    )

    unknown_request = RegenerateMessageRequest(message_id="m1", model_name="totally-bogus-model")
    non_selectable_request = RegenerateMessageRequest(
        message_id="m1", model_name="claude-opus-4-8"
    )

    with pytest.raises(HTTPException) as unknown_exc:
        await chat_handlers.regenerate_message(
            message_id="m1", request=unknown_request, original_message=_message()
        )
    with pytest.raises(HTTPException) as non_selectable_exc:
        await chat_handlers.regenerate_message(
            message_id="m1", request=non_selectable_request, original_message=_message()
        )

    assert unknown_exc.value.status_code == non_selectable_exc.value.status_code == 400
    assert unknown_exc.value.detail == non_selectable_exc.value.detail
    generate_response.assert_not_awaited()


@pytest.mark.asyncio
async def test_regenerate_message_allows_omitted_model_name(monkeypatch):
    generate_response = AsyncMock(
        return_value={
            "content": "ok",
            "model_name": "gpt-4o-mini",
            "provider": "openai",
            "usage": {"total_tokens": 1, "prompt_tokens": 1, "completion_tokens": 0},
            "cost": {"total_cost": 0},
            "latency_ms": 1,
            "finish_reason": "stop",
        }
    )
    monkeypatch.setattr(chat_handlers.chat_llm_service, "generate_response", generate_response)
    monkeypatch.setattr(
        chat_handlers.ChatService, "get_conversation", AsyncMock(return_value=_conversation())
    )
    monkeypatch.setattr(
        chat_handlers.ChatService, "get_conversation_messages", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(
        chat_handlers.ChatService,
        "add_message",
        AsyncMock(
            return_value={
                "message_id": "m2",
                "conversation_id": "c1",
                "role": "assistant",
                "content": "ok",
                "sequence_number": 3,
                "parent_message_id": None,
                "status": "completed",
                "created_at": "2026-07-01T00:00:00",
                "updated_at": "2026-07-01T00:00:00",
            }
        ),
    )
    monkeypatch.setattr(
        chat_handlers.cost_calculator, "record_cost_for_existing_message", AsyncMock()
    )
    request = RegenerateMessageRequest(message_id="m1")

    result = await chat_handlers.regenerate_message(
        message_id="m1", request=request, original_message=_message()
    )

    assert result is not None
    generate_response.assert_awaited_once()
    assert generate_response.await_args.kwargs["model_name"] == "gpt-4o-mini"


@pytest.mark.asyncio
async def test_regenerate_message_allows_selectable_model(monkeypatch):
    generate_response = AsyncMock(
        return_value={
            "content": "ok",
            "model_name": "claude-sonnet-5",
            "provider": "anthropic",
            "usage": {"total_tokens": 1, "prompt_tokens": 1, "completion_tokens": 0},
            "cost": {"total_cost": 0},
            "latency_ms": 1,
            "finish_reason": "stop",
        }
    )
    monkeypatch.setattr(chat_handlers.chat_llm_service, "generate_response", generate_response)
    monkeypatch.setattr(
        chat_handlers.ChatService, "get_conversation", AsyncMock(return_value=_conversation())
    )
    monkeypatch.setattr(
        chat_handlers.ChatService, "get_conversation_messages", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(
        chat_handlers.ChatService,
        "add_message",
        AsyncMock(
            return_value={
                "message_id": "m2",
                "conversation_id": "c1",
                "role": "assistant",
                "content": "ok",
                "sequence_number": 3,
                "parent_message_id": None,
                "status": "completed",
                "created_at": "2026-07-01T00:00:00",
                "updated_at": "2026-07-01T00:00:00",
            }
        ),
    )
    monkeypatch.setattr(
        chat_handlers.cost_calculator, "record_cost_for_existing_message", AsyncMock()
    )
    request = RegenerateMessageRequest(message_id="m1", model_name="claude-sonnet-5")

    result = await chat_handlers.regenerate_message(
        message_id="m1", request=request, original_message=_message()
    )

    assert result is not None
    generate_response.assert_awaited_once()
    assert generate_response.await_args.kwargs["model_name"] == "claude-sonnet-5"


# ---------------------------------------------------------------------------
# shared gate location
# ---------------------------------------------------------------------------


def test_is_user_selectable_model_lives_in_model_config():
    """게이트는 카탈로그 사실을 판정하는 공개 함수로 model_config에 산다."""
    from neos.config.model_config import is_user_selectable_model

    assert is_user_selectable_model("claude-sonnet-5") is True
    assert is_user_selectable_model("claude-opus-4-8") is False
    assert is_user_selectable_model("totally-bogus-model") is False


def test_chat_stream_pipeline_imports_shared_gate():
    """chat_stream_pipeline은 두 번째 규칙을 만들지 않고 공유 게이트를 임포트해 쓴다."""
    from neos.api.services import chat_stream_pipeline
    from neos.config.model_config import is_user_selectable_model

    assert chat_stream_pipeline.is_user_selectable_model is is_user_selectable_model
