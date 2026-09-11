"""Redact secret-keyed values and clip long strings before persist."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

_SECRET_KEYS = frozenset(
    {
        "password",
        "token",
        "api_key",
        "secret",
        "authorization",
        "access_token",
        "refresh_token",
    }
)
_SECRET_SUFFIXES = ("_key", "_token", "_secret", "_password")
_MAX_DEPTH = 6
_MAX_STRING = 400
_REDACTED = "<redacted>"


def _is_secret_key(key: object) -> bool:
    if not isinstance(key, str):
        return False
    lowered = key.lower()
    return lowered in _SECRET_KEYS or lowered.endswith(_SECRET_SUFFIXES)


def redact_sensitive(value: Any, *, depth: int = 0) -> Any:
    if depth >= _MAX_DEPTH:
        return _REDACTED
    if isinstance(value, Mapping):
        redacted: dict[Any, Any] = {}
        for key, child in value.items():
            if _is_secret_key(key):
                redacted[key] = _REDACTED
            else:
                redacted[key] = redact_sensitive(child, depth=depth + 1)
        return redacted
    if isinstance(value, list):
        return [redact_sensitive(item, depth=depth + 1) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_sensitive(item, depth=depth + 1) for item in value)
    if isinstance(value, str) and len(value) > _MAX_STRING:
        return value[:_MAX_STRING] + "…"
    return value
