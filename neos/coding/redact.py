"""Redact secret-keyed values and clip long strings before persist."""

from __future__ import annotations

import re
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
_SECRET_VALUE_RE = re.compile(
    "|".join(
        (
            r"sk-[A-Za-z0-9_-]{20,}",
            r"github_pat_[A-Za-z0-9_]+",
            r"ghp_[A-Za-z0-9_]+",
            r"gho_[A-Za-z0-9_]+",
            r"AKIA[A-Z0-9]{16,}",
            r"xox[bpa]-[A-Za-z0-9-]+",
            r"xai-[A-Za-z0-9_-]+",
            r"Bearer\s+\S+",
        )
    )
)


_BINARY_PAYLOAD_KEYS = frozenset({"data_b64"})


def strip_binary_payloads(value: Any, *, depth: int = 0) -> Any:
    """Drop base64 payloads before a tool result is replayed (roadmap K6).

    Nothing in the coding path turns one into an image block, so the model
    cannot decode it -- it only pays for it, on every later turn. Clipping is
    not enough: a 400-character fragment still reads as data. The marker keeps
    the one fact worth replaying, that a payload was there.

    Applied where the result mapping is built, not where it is returned: that
    site has two exits, and a filter on one of them is the copy this
    repository keeps rediscovering.
    """
    if depth >= _MAX_DEPTH:
        return value
    if isinstance(value, Mapping):
        stripped: dict[Any, Any] = {}
        for key, child in value.items():
            if key in _BINARY_PAYLOAD_KEYS:
                stripped[f"{key}_omitted"] = True
                continue
            stripped[key] = strip_binary_payloads(child, depth=depth + 1)
        return stripped
    if isinstance(value, list):
        return [strip_binary_payloads(item, depth=depth + 1) for item in value]
    if isinstance(value, tuple):
        return tuple(strip_binary_payloads(item, depth=depth + 1) for item in value)
    return value


def _is_secret_key(key: object) -> bool:
    if not isinstance(key, str):
        return False
    lowered = key.lower()
    return lowered in _SECRET_KEYS or lowered.endswith(_SECRET_SUFFIXES)


def _redact_secret_values(text: str) -> str:
    return _SECRET_VALUE_RE.sub(_REDACTED, text)


def redact_sensitive(value: Any, *, depth: int = 0, clip: bool = True) -> Any:
    if depth >= _MAX_DEPTH:
        return _REDACTED
    if isinstance(value, Mapping):
        redacted: dict[Any, Any] = {}
        for key, child in value.items():
            if _is_secret_key(key):
                redacted[key] = _REDACTED
            else:
                redacted[key] = redact_sensitive(
                    child, depth=depth + 1, clip=clip
                )
        return redacted
    if isinstance(value, list):
        return [
            redact_sensitive(item, depth=depth + 1, clip=clip) for item in value
        ]
    if isinstance(value, tuple):
        return tuple(
            redact_sensitive(item, depth=depth + 1, clip=clip) for item in value
        )
    if isinstance(value, str):
        value = _redact_secret_values(value)
        if clip and len(value) > _MAX_STRING:
            return value[:_MAX_STRING] + "…"
        return value
    return value
