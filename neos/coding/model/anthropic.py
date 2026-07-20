from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import Any

import anthropic

from neos.coding.model.base import (
    CanonicalMessage,
    ModelCompleted,
    ModelEvent,
    ModelRequest,
    ModelUsage,
    TextContent,
    TextDelta,
    ToolCallCompleted,
    ToolInputDelta,
    ToolResultContent,
    ToolUseContent,
)


class CodingModelError(RuntimeError):
    def __init__(self, code: str, *, retryable: bool) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


@dataclass(slots=True)
class _ToolBuffer:
    tool_call_id: str
    name: str
    fragments: list[str]
    size_bytes: int = 0


class AnthropicCodingModel:
    def __init__(
        self,
        client: Any,
        *,
        max_tool_input_bytes: int = 65_536,
        max_tool_input_depth: int = 16,
    ) -> None:
        if max_tool_input_bytes < 1 or max_tool_input_depth < 1:
            raise ValueError("tool input limits must be positive")
        self._client = client
        self._max_tool_input_bytes = max_tool_input_bytes
        self._max_tool_input_depth = max_tool_input_depth

    async def stream(
        self, request: ModelRequest
    ) -> AsyncIterator[ModelEvent]:
        buffers: dict[int, _ToolBuffer] = {}
        input_tokens = 0
        try:
            async with asyncio.timeout(request.limits.timeout_sec):
                async with self._client.messages.stream(
                    **_to_anthropic_request(request)
                ) as stream:
                    async for raw in stream:
                        event_type = getattr(raw, "type", "")
                        if event_type == "message_start":
                            usage = getattr(raw.message, "usage", None)
                            input_tokens = int(
                                getattr(usage, "input_tokens", 0)
                            )
                            continue
                        if event_type == "content_block_start":
                            block = raw.content_block
                            if getattr(block, "type", "") == "tool_use":
                                buffers[int(raw.index)] = _ToolBuffer(
                                    tool_call_id=str(block.id),
                                    name=str(block.name),
                                    fragments=[],
                                )
                            continue
                        if event_type == "content_block_delta":
                            delta = raw.delta
                            if getattr(delta, "type", "") == "text_delta":
                                yield TextDelta(str(delta.text))
                                continue
                            if getattr(delta, "type", "") == "input_json_delta":
                                buffer = buffers.get(int(raw.index))
                                if buffer is None:
                                    raise CodingModelError(
                                        "tool_input_without_start",
                                        retryable=False,
                                    )
                                fragment = str(delta.partial_json)
                                buffer.size_bytes += len(fragment.encode("utf-8"))
                                if buffer.size_bytes > self._max_tool_input_bytes:
                                    raise CodingModelError(
                                        "tool_input_too_large", retryable=False
                                    )
                                buffer.fragments.append(fragment)
                                yield ToolInputDelta(
                                    buffer.tool_call_id,
                                    buffer.name,
                                    fragment,
                                )
                            continue
                        if event_type == "content_block_stop":
                            buffer = buffers.pop(int(raw.index), None)
                            if buffer is not None:
                                yield self._complete_tool(buffer)
                            continue
                        if event_type == "message_delta":
                            usage = getattr(raw, "usage", None)
                            output_tokens = int(
                                getattr(usage, "output_tokens", 0)
                            )
                            stop_reason = getattr(raw.delta, "stop_reason", None)
                            yield ModelCompleted(
                                stop_reason=str(stop_reason or "unknown"),
                                usage=ModelUsage(
                                    input_tokens=input_tokens,
                                    output_tokens=output_tokens,
                                ),
                            )
        except CodingModelError:
            raise
        except (TimeoutError, anthropic.APITimeoutError) as error:
            raise CodingModelError("model_timeout", retryable=True) from error
        except anthropic.RateLimitError as error:
            raise CodingModelError(
                "model_rate_limited", retryable=True
            ) from error
        except anthropic.AuthenticationError as error:
            raise CodingModelError(
                "model_authentication_failed", retryable=False
            ) from error
        except anthropic.APIConnectionError as error:
            raise CodingModelError(
                "model_transport_failed", retryable=True
            ) from error
        except anthropic.APIStatusError as error:
            raise CodingModelError(
                "model_provider_failed", retryable=error.status_code >= 500
            ) from error

    def _complete_tool(self, buffer: _ToolBuffer) -> ToolCallCompleted:
        try:
            value = json.loads("".join(buffer.fragments))
        except (json.JSONDecodeError, UnicodeError) as error:
            raise CodingModelError(
                "tool_input_invalid", retryable=False
            ) from error
        if not isinstance(value, Mapping):
            raise CodingModelError("tool_input_invalid", retryable=False)
        if _json_depth(value) > self._max_tool_input_depth:
            raise CodingModelError("tool_input_too_deep", retryable=False)
        return ToolCallCompleted(
            tool_call_id=buffer.tool_call_id,
            name=buffer.name,
            input=dict(value),
        )


def _to_anthropic_request(request: ModelRequest) -> dict[str, object]:
    return {
        "model": request.model,
        "system": request.system,
        "messages": [_message_to_anthropic(item) for item in request.messages],
        "tools": [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": dict(tool.input_schema),
            }
            for tool in request.tools
        ],
        "max_tokens": request.limits.max_output_tokens,
    }


def _message_to_anthropic(message: CanonicalMessage) -> dict[str, object]:
    role = "user" if message.role == "tool" else message.role
    return {
        "role": role,
        "content": [_content_to_anthropic(item) for item in message.content],
    }


def _content_to_anthropic(content: object) -> dict[str, object]:
    if isinstance(content, TextContent):
        return {"type": "text", "text": content.text}
    if isinstance(content, ToolUseContent):
        return {
            "type": "tool_use",
            "id": content.tool_call_id,
            "name": content.name,
            "input": dict(content.input),
        }
    if isinstance(content, ToolResultContent):
        return {
            "type": "tool_result",
            "tool_use_id": content.tool_call_id,
            "content": json.dumps(dict(content.content), separators=(",", ":")),
            "is_error": content.status != "ok",
        }
    raise TypeError("unsupported canonical content")


def _json_depth(value: object) -> int:
    if isinstance(value, Mapping):
        if not value:
            return 1
        return 1 + max(_json_depth(item) for item in value.values())
    if isinstance(value, list):
        if not value:
            return 1
        return 1 + max(_json_depth(item) for item in value)
    return 0
