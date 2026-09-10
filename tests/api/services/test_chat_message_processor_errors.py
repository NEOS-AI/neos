"""N8 리뷰 Finding 3 — LLM 스트림의 error 청크가 content 로 둔갑하면 안 된다.

`process_message_stream` 이 `generate_llm_response_stream` 이 낸 모든 청크를
무조건 `{"type": "content", ...}` 로 다시 포장하던 시절엔, 첨부 거부
(`AttachmentNotSupportedError`) 로 인한 `{"type": "error", ...}` 청크가 빈
content 청크로 바뀌어 거부 메시지가 사라졌다. 이 테스트는 error 청크가
error 로 그대로 나가고, 루프가 거기서 멈춰 어시스턴트 메시지를 저장하지
않음을 확인한다.
"""

import os
from unittest.mock import AsyncMock

import pytest

os.environ.setdefault("GOOGLE_API_KEY", "test-key")

from neos.api.services import chat_message_processor
from neos.api.services.standard_chat_processor import StandardChatProcessor


def _conversation():
    return {
        "conversation_id": "c1",
        "model_name": "gpt-4o-mini",
        "system_prompt": "",
        "temperature": 0.7,
        "max_tokens": None,
    }


@pytest.mark.asyncio
async def test_error_chunk_is_forwarded_as_error_not_content(monkeypatch):
    add_message = AsyncMock(
        return_value={
            "message_id": "u1",
            "conversation_id": "c1",
            "role": "user",
            "content": "봐줘",
            "sequence_number": 1,
        }
    )
    monkeypatch.setattr(chat_message_processor.ChatService, "add_message", add_message)
    monkeypatch.setattr(
        chat_message_processor.ChatService,
        "get_conversation",
        AsyncMock(return_value=_conversation()),
    )
    monkeypatch.setattr(
        chat_message_processor.ChatService,
        "get_conversation_messages",
        AsyncMock(return_value=[]),
    )

    async def fake_stream(**kwargs):
        yield {
            "type": "error",
            "error": "gpt-4o-mini는 첨부 1개(scan.png)를 받지 않습니다.",
            "code": "attachment_unsupported",
        }

    monkeypatch.setattr(
        chat_message_processor.chat_llm_service,
        "generate_response_stream",
        fake_stream,
    )

    processor = StandardChatProcessor()
    events = [
        event
        async for event in processor.process_message_stream(
            conversation_id="c1",
            user_content="봐줘",
            user_id="u1",
        )
    ]

    error_events = [e for e in events if e.get("type") == "error"]
    content_events = [e for e in events if e.get("type") == "content"]

    assert error_events, f"error 이벤트가 없다: {events}"
    assert error_events[0]["code"] == "attachment_unsupported"
    assert "scan.png" in error_events[0]["error"]
    assert not content_events, f"error 가 content 로 둔갑했다: {content_events}"

    # 어시스턴트 메시지는 저장되지 않는다 — add_message 는 유저 턴 1번만 불렸다.
    assert add_message.await_count == 1
