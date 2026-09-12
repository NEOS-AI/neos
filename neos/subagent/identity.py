"""sa_/sc_ ids and the channel-key identity fence."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from neos.coding.redact import redact_sensitive

_CHANNEL_KEYS = frozenset({"session_key", "chat_id", "thread_id", "channel_id"})


def new_run_id() -> str:
    return f"sa_{uuid4().hex}"


def new_checkpoint_id() -> str:
    return f"sc_{uuid4().hex}"


def strip_channel_keys(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: strip_channel_keys(item)
            for key, item in value.items()
            if key not in _CHANNEL_KEYS
        }
    if isinstance(value, list):
        return [strip_channel_keys(item) for item in value]
    if isinstance(value, tuple):
        return tuple(strip_channel_keys(item) for item in value)
    return value


def persist_payload(value: Any) -> Any:
    # Child fold/steer read this back; do not clip last_assistant_text.
    return redact_sensitive(strip_channel_keys(value), clip=False)
