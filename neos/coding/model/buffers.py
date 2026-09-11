from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field

from neos.coding.model.base import ToolCallCompleted
from neos.coding.model.errors import CodingModelError


@dataclass(slots=True)
class ToolArgumentBuffer:
    tool_call_id: str
    name: str
    fragments: list[str] = field(default_factory=list)
    size_bytes: int = 0

    def append(self, fragment: str, *, max_bytes: int) -> str:
        encoded = fragment.encode("utf-8")
        self.size_bytes += len(encoded)
        if self.size_bytes > max_bytes:
            raise CodingModelError("tool_input_too_large", retryable=False)
        self.fragments.append(fragment)
        return fragment


def complete_tool_buffer(
    buffer: ToolArgumentBuffer, *, max_depth: int
) -> ToolCallCompleted:
    try:
        value = json.loads("".join(buffer.fragments) or "{}")
    except (json.JSONDecodeError, UnicodeError) as error:
        raise CodingModelError("tool_input_invalid", retryable=False) from error
    if not isinstance(value, Mapping):
        raise CodingModelError("tool_input_invalid", retryable=False)
    if json_depth(value) > max_depth:
        raise CodingModelError("tool_input_too_deep", retryable=False)
    return ToolCallCompleted(
        tool_call_id=buffer.tool_call_id,
        name=buffer.name,
        input=dict(value),
    )


def json_depth(value: object) -> int:
    if isinstance(value, Mapping):
        if not value:
            return 1
        return 1 + max(json_depth(item) for item in value.values())
    if isinstance(value, list):
        if not value:
            return 1
        return 1 + max(json_depth(item) for item in value)
    return 0
