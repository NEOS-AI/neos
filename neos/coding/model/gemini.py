from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from neos.coding.model.base import (
    CanonicalMessage,
    ModelCompleted,
    ModelEvent,
    ModelRequest,
    ModelUsage,
    TextContent,
    TextDelta,
    ToolInputDelta,
    ToolResultContent,
    ToolUseContent,
)
from neos.coding.model.buffers import ToolArgumentBuffer, complete_tool_buffer
from neos.coding.model.errors import CodingModelError
from neos.coding.model.stop import normalize_stop_reason


class GeminiCodingModel:
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

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelEvent]:
        buffers: dict[str, ToolArgumentBuffer] = {}
        input_tokens = 0
        output_tokens = 0
        finish_reason: str | None = None
        try:
            async with asyncio.timeout(request.limits.timeout_sec):
                stream = self._client.aio.models.generate_content_stream(
                    **_to_gemini_request(request)
                )
                if hasattr(stream, "__await__"):
                    stream = await stream
                async for raw in stream:
                    usage = getattr(raw, "usage_metadata", None)
                    if usage is not None:
                        input_tokens = int(
                            getattr(usage, "prompt_token_count", 0) or 0
                        )
                        output_tokens = int(
                            getattr(usage, "candidates_token_count", 0) or 0
                        )
                    candidate = _first_candidate(raw)
                    if candidate is not None:
                        reason = getattr(candidate, "finish_reason", None)
                        if reason:
                            finish_reason = str(
                                getattr(reason, "name", reason)
                            )
                    text = getattr(raw, "text", None)
                    if text:
                        yield TextDelta(str(text))
                    for call in _function_calls(raw):
                        async for event in self._consume_call(buffers, call):
                            yield event
        except CodingModelError:
            raise
        except TimeoutError as error:
            raise CodingModelError("model_timeout", retryable=True) from error
        except Exception as error:
            mapped = _map_gemini_error(error)
            if mapped is not None:
                raise mapped from error
            raise CodingModelError(
                "model_provider_failed", retryable=True
            ) from error

        for buffer in buffers.values():
            yield complete_tool_buffer(
                buffer, max_depth=self._max_tool_input_depth
            )
        yield ModelCompleted(
            stop_reason=normalize_stop_reason(
                finish_reason, has_tool_calls=bool(buffers)
            ),
            usage=ModelUsage(
                input_tokens=input_tokens, output_tokens=output_tokens
            ),
        )

    async def _consume_call(
        self,
        buffers: dict[str, ToolArgumentBuffer],
        call: object,
    ) -> AsyncIterator[ModelEvent]:
        name = str(getattr(call, "name", "") or "")
        call_id = str(
            getattr(call, "id", "") or getattr(call, "call_id", "") or name
        )
        if not name:
            raise CodingModelError("tool_input_without_start", retryable=False)
        args = getattr(call, "args", None)
        if args is None:
            args = getattr(call, "arguments", {}) or {}
        if isinstance(args, str):
            fragment = args
        else:
            fragment = json.dumps(dict(args), separators=(",", ":"))
        buffer = buffers.get(call_id)
        if buffer is None:
            buffer = ToolArgumentBuffer(tool_call_id=call_id, name=name)
            buffers[call_id] = buffer
        yield ToolInputDelta(
            buffer.tool_call_id,
            buffer.name,
            buffer.append(fragment, max_bytes=self._max_tool_input_bytes),
        )


def _to_gemini_request(request: ModelRequest) -> dict[str, object]:
    return {
        "model": request.model,
        "contents": _messages_to_gemini(request.messages),
        "config": {
            "system_instruction": request.system,
            "max_output_tokens": request.limits.max_output_tokens,
            "tools": _tools_to_gemini(request.tools),
        },
    }


def _tools_to_gemini(tools: tuple[Any, ...]) -> list[dict[str, object]]:
    if not tools:
        return []
    return [
        {
            "function_declarations": [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": dict(tool.input_schema),
                }
                for tool in tools
            ]
        }
    ]


def _messages_to_gemini(
    messages: tuple[CanonicalMessage, ...]
) -> list[dict[str, object]]:
    contents: list[dict[str, object]] = []
    for message in messages:
        if message.role == "tool":
            contents.append(
                {
                    "role": "user",
                    "parts": [
                        {
                            "function_response": {
                                "name": item.tool_call_id,
                                "response": dict(item.content),
                            }
                        }
                        for item in message.content
                        if isinstance(item, ToolResultContent)
                    ],
                }
            )
            continue
        role = "user" if message.role == "user" else "model"
        parts: list[dict[str, object]] = []
        for item in message.content:
            if isinstance(item, TextContent):
                parts.append({"text": item.text})
            elif isinstance(item, ToolUseContent):
                parts.append(
                    {
                        "function_call": {
                            "name": item.name,
                            "args": dict(item.input),
                            "id": item.tool_call_id,
                        }
                    }
                )
        contents.append({"role": role, "parts": parts})
    return contents


def _first_candidate(raw: object) -> object | None:
    candidates = getattr(raw, "candidates", None) or ()
    if not candidates:
        return None
    return candidates[0]


def _function_calls(raw: object) -> tuple[object, ...]:
    calls = getattr(raw, "function_calls", None)
    if calls:
        return tuple(calls)
    candidate = _first_candidate(raw)
    content = getattr(candidate, "content", None)
    parts = getattr(content, "parts", None) or ()
    found = []
    for part in parts:
        call = getattr(part, "function_call", None)
        if call is not None:
            found.append(call)
    return tuple(found)


def _map_gemini_error(error: Exception) -> CodingModelError | None:
    status = int(getattr(error, "status_code", 0) or getattr(error, "code", 0) or 0)
    text = str(error).lower()
    if status == 413 or ("token" in text and "limit" in text) or "too long" in text:
        return CodingModelError("prompt_too_long", retryable=True)
    if status == 429 or "resource exhausted" in text or "rate" in text:
        return CodingModelError("model_rate_limited", retryable=True)
    if status in {401, 403} or "api key" in text or "permission" in text:
        return CodingModelError("model_authentication_failed", retryable=False)
    if status >= 500:
        return CodingModelError("model_provider_failed", retryable=True)
    return None
