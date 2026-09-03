"""`ChatRepository.get_conversation_messages`의 tail 의미론을 실제 DB로 검증한다.

같은 디렉터리의 `test_chat_repository_pagination.py`는 `FakeDB`로 생성된 SQL
문자열을 검사하는 방식을 쓰지만, 여기서 고치는 버그는 `ORDER BY
sequence_number ASC`가 **있어서** 생긴 버그다(커서 없이 호출하면 항상 앞쪽
N개를 반환해 최신 메시지가 잘려 나간다). 문자열 검사는 그 버그를 그대로
통과시키므로, 실제 DB에 메시지를 넣고 **무엇이 돌아오는지**로 검증한다.

테스트 사용자 이메일은 `...@example.com`으로 만든다 -- `tests/conftest.py`의
autouse 정리 픽스처가 이 패턴에 딸린 conversation/message/user를 지운다.
"""

import uuid

import pytest
from sqlalchemy import text

from neos.database.repositories.chat_repository import ChatRepository


async def _seed_conversation_with_messages(count: int) -> str:
    """실제 DB에 사용자·대화·메시지 `count`개를 만들고 conversation_id를 반환한다.

    메시지의 `sequence_number`는 지정하지 않는다 -- `messages` 테이블의
    트리거(`set_message_sequence_number`)가 대화별로 1부터 순서대로 채운다.
    """
    from neos.api.services.chat_service import ChatService
    from neos.database.connection import get_session_ctx
    from neos.database.models import User

    suffix = uuid.uuid4().hex[:8]
    user_id = f"fixture-mw-{suffix}"
    async with get_session_ctx() as session:
        session.add(
            User(
                user_id=user_id,
                email=f"fixture+{suffix}@example.com",
                username=user_id,
                password_hash="x",
            )
        )
        await session.commit()

    conversation = await ChatService.create_conversation(
        user_id=user_id,
        title="message window test",
    )
    conversation_id = conversation["conversation_id"]

    async with get_session_ctx() as session:
        for i in range(1, count + 1):
            await session.execute(
                text(
                    "INSERT INTO messages (message_id, conversation_id, role, content) "
                    "VALUES (:mid, :cid, 'user', :content)"
                ),
                {
                    "mid": f"{conversation_id}-msg-{i}",
                    "cid": conversation_id,
                    "content": f"message {i}",
                },
            )
        await session.commit()

    return conversation_id


def _sequence_numbers(messages):
    return [m.sequence_number for m in messages]


@pytest.mark.asyncio
async def test_no_cursor_returns_last_n_ascending():
    """25개 메시지 중 limit=20, 커서 없음 -> 6..25가 오름차순으로 온다.

    고치기 전에는 1..20 (오름차순으로 정렬된 "앞쪽" N개)이 와서 실패해야 한다.
    """
    conversation_id = await _seed_conversation_with_messages(25)

    messages = await ChatRepository.get_conversation_messages(
        conversation_id=conversation_id, limit=20
    )

    assert _sequence_numbers(messages) == list(range(6, 26))


@pytest.mark.asyncio
async def test_before_sequence_returns_last_n_below_cursor_ascending():
    """limit=20, before_sequence=10 -> 1..9 (9개, 오름차순)."""
    conversation_id = await _seed_conversation_with_messages(25)

    messages = await ChatRepository.get_conversation_messages(
        conversation_id=conversation_id, limit=20, before_sequence=10
    )

    assert _sequence_numbers(messages) == list(range(1, 10))


@pytest.mark.asyncio
async def test_before_sequence_small_window_ascending():
    """limit=5, before_sequence=20 -> 15..19 (오름차순)."""
    conversation_id = await _seed_conversation_with_messages(25)

    messages = await ChatRepository.get_conversation_messages(
        conversation_id=conversation_id, limit=5, before_sequence=20
    )

    assert _sequence_numbers(messages) == [15, 16, 17, 18, 19]


@pytest.mark.asyncio
async def test_after_sequence_unchanged_forward_catchup():
    """limit=5, after_sequence=10 -> 11..15 (오름차순, 기존 동작 불변)."""
    conversation_id = await _seed_conversation_with_messages(25)

    messages = await ChatRepository.get_conversation_messages(
        conversation_id=conversation_id, limit=5, after_sequence=10
    )

    assert _sequence_numbers(messages) == [11, 12, 13, 14, 15]


@pytest.mark.asyncio
async def test_limit_larger_than_total_returns_all_ascending():
    """limit이 전체 개수(25)보다 크면 전부가 오름차순으로 온다."""
    conversation_id = await _seed_conversation_with_messages(25)

    messages = await ChatRepository.get_conversation_messages(
        conversation_id=conversation_id, limit=100
    )

    assert _sequence_numbers(messages) == list(range(1, 26))
