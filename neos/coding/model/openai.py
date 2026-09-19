from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Mapping
from typing import Any

import openai

from neos.coding.model.base import (
    CanonicalMessage,
    ModelCompleted,
    ModelEvent,
    ModelRequest,
    ModelUsage,
    SystemNoteContent,
    TextContent,
    TextDelta,
    ToolInputDelta,
    ToolResultContent,
    ToolUseContent,
)
from neos.coding.model.buffers import ToolArgumentBuffer, complete_tool_buffer
from neos.coding.model.errors import CodingModelError
from neos.coding.model.stop import normalize_stop_reason

_COMPLETION_TOKEN_PREFIXES = ("gpt-5", "gpt-6", "o1", "o3", "o4")


class OpenAICodingModel:
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
        buffers: dict[int, ToolArgumentBuffer] = {}
        input_tokens = 0
        output_tokens = 0
        seen_usage = False
        finish_reason: str | None = None
        try:
            async with asyncio.timeout(request.limits.timeout_sec):
                stream = await self._client.chat.completions.create(
                    **_to_openai_request(request)
                )
                async for raw in stream:
                    usage = getattr(raw, "usage", None)
                    if usage is not None:
                        seen_usage = True
                        input_tokens = int(
                            getattr(usage, "prompt_tokens", 0)
                            or getattr(usage, "input_tokens", 0)
                            or 0
                        )
                        output_tokens = int(
                            getattr(usage, "completion_tokens", 0)
                            or getattr(usage, "output_tokens", 0)
                            or 0
                        )
                    choice = _first_choice(raw)
                    if choice is None:
                        continue
                    reason = getattr(choice, "finish_reason", None)
                    if reason:
                        finish_reason = str(reason)
                    delta = getattr(choice, "delta", None)
                    if delta is None:
                        continue
                    text = getattr(delta, "content", None)
                    if text:
                        yield TextDelta(str(text))
                    for call in getattr(delta, "tool_calls", None) or ():
                        async for event in self._consume_tool_delta(buffers, call):
                            yield event
        except CodingModelError:
            raise
        except (TimeoutError, openai.APITimeoutError) as error:
            raise CodingModelError("model_timeout", retryable=True) from error
        except openai.RateLimitError as error:
            raise CodingModelError("model_rate_limited", retryable=True) from error
        except openai.AuthenticationError as error:
            raise CodingModelError(
                "model_authentication_failed", retryable=False
            ) from error
        except openai.APIConnectionError as error:
            raise CodingModelError("model_transport_failed", retryable=True) from error
        except openai.APIStatusError as error:
            if _is_prompt_too_long(error):
                raise CodingModelError("prompt_too_long", retryable=True) from error
            status = int(getattr(error, "status_code", 0) or 0)
            raise CodingModelError(
                "model_provider_failed", retryable=status >= 500
            ) from error

        for buffer in buffers.values():
            yield complete_tool_buffer(
                buffer, max_depth=self._max_tool_input_depth
            )
        yield ModelCompleted(
            stop_reason=normalize_stop_reason(
                finish_reason, has_tool_calls=bool(buffers)
            ),
            usage=(
                ModelUsage(
                    input_tokens=input_tokens, output_tokens=output_tokens
                )
                if seen_usage
                else None
            ),
        )

    async def _consume_tool_delta(
        self,
        buffers: dict[int, ToolArgumentBuffer],
        call: object,
    ) -> AsyncIterator[ModelEvent]:
        index = int(getattr(call, "index", 0) or 0)
        function = getattr(call, "function", None)
        name = str(getattr(function, "name", "") or "")
        call_id = str(getattr(call, "id", "") or "")
        buffer = buffers.get(index)
        if buffer is None:
            if not call_id or not name:
                raise CodingModelError("tool_input_without_start", retryable=False)
            buffer = ToolArgumentBuffer(tool_call_id=call_id, name=name)
            buffers[index] = buffer
        elif call_id and not buffer.tool_call_id:
            buffer.tool_call_id = call_id
        elif name and not buffer.name:
            buffer.name = name
        fragment = str(getattr(function, "arguments", "") or "")
        if not fragment:
            return
        yield ToolInputDelta(
            buffer.tool_call_id,
            buffer.name,
            buffer.append(fragment, max_bytes=self._max_tool_input_bytes),
        )


def _first_choice(raw: object) -> object | None:
    choices = getattr(raw, "choices", None) or ()
    if not choices:
        return None
    return choices[0]


def _uses_max_completion_tokens(model: str) -> bool:
    lowered = model.lower()
    return lowered.startswith(_COMPLETION_TOKEN_PREFIXES)


def _to_openai_request(request: ModelRequest) -> dict[str, object]:
    messages: list[dict[str, object]] = [
        {"role": "system", "content": request.system}
    ]
    for message in request.messages:
        messages.extend(_message_to_openai(message))
    payload: dict[str, object] = {
        "model": request.model,
        "messages": messages,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if request.tools:
        payload["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": dict(tool.input_schema),
                },
            }
            for tool in request.tools
        ]
    if _uses_max_completion_tokens(request.model):
        payload["max_completion_tokens"] = request.limits.max_output_tokens
    else:
        payload["max_tokens"] = request.limits.max_output_tokens
    return payload


def _message_to_openai(message: CanonicalMessage) -> list[dict[str, object]]:
    if message.role == "system":
        # Tool reveals have no text form here: this provider has no
        # mid-conversation tool changes, so its array was never made
        # constant and nothing needs announcing. Dropping the message beats
        # sending an empty user turn, which the API rejects.
        text = "".join(
            item.text
            for item in message.content
            if isinstance(item, SystemNoteContent)
        )
        return [{"role": "user", "content": text}] if text else []
    if message.role == "tool":
        return [
            {
                "role": "tool",
                "tool_call_id": item.tool_call_id,
                "content": json.dumps(dict(item.content), separators=(",", ":")),
            }
            for item in message.content
            if isinstance(item, ToolResultContent)
        ]
    if message.role == "user":
        return [
            {
                "role": "user",
                "content": "".join(
                    item.text
                    for item in message.content
                    if isinstance(item, TextContent)
                ),
            }
        ]
    texts = [
        item.text for item in message.content if isinstance(item, TextContent)
    ]
    tools = [
        item for item in message.content if isinstance(item, ToolUseContent)
    ]
    payload: dict[str, object] = {
        "role": "assistant",
        "content": "".join(texts) or None,
    }
    if tools:
        payload["tool_calls"] = [
            {
                "id": item.tool_call_id,
                "type": "function",
                "function": {
                    "name": item.name,
                    "arguments": json.dumps(
                        dict(item.input), separators=(",", ":")
                    ),
                },
            }
            for item in tools
        ]
    return [payload]


def _is_prompt_too_long(error: openai.APIStatusError) -> bool:
    if int(getattr(error, "status_code", 0) or 0) == 413:
        return True
    body = getattr(error, "body", None)
    code = ""
    if isinstance(body, Mapping):
        err = body.get("error")
        if isinstance(err, Mapping):
            code = str(err.get("code") or "")
    text = f"{code} {error}"
    return any(
        token in text
        for token in (
            "context_length_exceeded",
            "string_above_max_length",
            "prompt is too long",
            "maximum context length",
        )
    )
