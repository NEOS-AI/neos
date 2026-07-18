from datetime import datetime

import pytest

from neos.api.services.pagination import (
    ConversationCursor,
    decode_conversation_cursor,
    encode_conversation_cursor,
)


def test_roundtrip_with_last_message_at():
    token = encode_conversation_cursor(
        is_pinned=True,
        last_message_at=datetime(2026, 7, 17, 12, 30, 45, 123456),
        created_at=datetime(2026, 7, 1, 9, 0, 0),
        conversation_id="conv_abc",
    )
    assert isinstance(token, str)
    decoded = decode_conversation_cursor(token)
    assert decoded == ConversationCursor(
        is_pinned=True,
        last_message_at=datetime(2026, 7, 17, 12, 30, 45, 123456),
        created_at=datetime(2026, 7, 1, 9, 0, 0),
        conversation_id="conv_abc",
    )


def test_roundtrip_with_null_last_message_at():
    token = encode_conversation_cursor(
        is_pinned=False,
        last_message_at=None,
        created_at=datetime(2026, 7, 1, 9, 0, 0),
        conversation_id="conv_xyz",
    )
    decoded = decode_conversation_cursor(token)
    assert decoded.last_message_at is None
    assert decoded.is_pinned is False
    assert decoded.conversation_id == "conv_xyz"


def test_decode_rejects_garbage():
    with pytest.raises(ValueError):
        decode_conversation_cursor("!!!not-base64!!!")


def test_decode_rejects_missing_fields():
    import base64
    import json

    bad = base64.urlsafe_b64encode(json.dumps({"p": True}).encode()).decode()
    with pytest.raises(ValueError):
        decode_conversation_cursor(bad)
