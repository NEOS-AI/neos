"""대화 목록 keyset 페이지네이션 커서 코덱.

커서는 정렬 튜플 (is_pinned, last_message_at, created_at, conversation_id)을
base64url(JSON)로 인코딩한 불투명 토큰이다. 프론트엔드는 내용을 해석하지 않고
그대로 되돌려 보낸다. 상세: docs/superpowers/specs/2026-07-17-sidebar-pagination-design.md
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ConversationCursor:
    is_pinned: bool
    last_message_at: datetime | None
    created_at: datetime
    conversation_id: str


def encode_conversation_cursor(
    is_pinned: bool,
    last_message_at: datetime | None,
    created_at: datetime,
    conversation_id: str,
) -> str:
    payload = {
        "p": bool(is_pinned),
        "m": last_message_at.isoformat() if last_message_at is not None else None,
        "t": created_at.isoformat(),
        "i": conversation_id,
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def decode_conversation_cursor(token: str) -> ConversationCursor:
    try:
        raw = base64.urlsafe_b64decode(token.encode("ascii"))
        payload = json.loads(raw)
    except (binascii.Error, ValueError, UnicodeError) as exc:
        raise ValueError(f"malformed cursor token: {exc}") from exc

    if not isinstance(payload, dict) or not {"p", "m", "t", "i"} <= payload.keys():
        raise ValueError("cursor payload missing required fields")

    # Type validation: p must be bool, i must be str
    if not isinstance(payload["p"], bool):
        raise ValueError(
            f"invalid cursor field: 'p' must be bool, got {type(payload['p']).__name__}"
        )
    if not isinstance(payload["i"], str):
        raise ValueError(
            f"invalid cursor field: 'i' must be str, got {type(payload['i']).__name__}"
        )

    try:
        return ConversationCursor(
            is_pinned=payload["p"],
            last_message_at=(
                datetime.fromisoformat(payload["m"])
                if payload["m"] is not None
                else None
            ),
            created_at=datetime.fromisoformat(payload["t"]),
            conversation_id=payload["i"],
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid cursor field: {exc}") from exc
