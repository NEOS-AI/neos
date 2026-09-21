from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Mapping
from typing import Any
from uuid import uuid4

import httpx

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


class OllamaCodingModel:
    def __init__(
        self,
        client: Any,
        *,
        base_url: str,
        max_tool_input_bytes: int = 65_536,
        max_tool_input_depth: int = 16,
    ) -> None:
        if max_tool_input_bytes < 1 or max_tool_input_depth < 1:
            raise ValueError("tool input limits must be positive")
        if not base_url:
            raise ValueError("ollama base_url is required")
        self._client = client
        self._base_url = base_url.rstrip("/")
        self._max_tool_input_bytes = max_tool_input_bytes
        self._max_tool_input_depth = max_tool_input_depth

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelEvent]:
        buffers: dict[str, ToolArgumentBuffer] = {}
        seen_text = ""
        finish_reason: str | None = None
        usage: ModelUsage | None = None
        try:
            async with asyncio.timeout(request.limits.timeout_sec):
                async with self._client.stream(
                    "POST",
                    f"{self._base_url}/api/chat",
                    json=_to_ollama_request(request),
                ) as response:
                    if response.status_code == 413:
                        raise CodingModelError("prompt_too_long", retryable=True)
                    if response.status_code == 401:
                        raise CodingModelError(
                            "model_authentication_failed", retryable=False
                        )
                    if response.status_code >= 500:
                        raise CodingModelError(
                            "model_provider_failed", retryable=True
                        )
                    if response.status_code >= 400:
                        raise CodingModelError(
                            "model_provider_failed", retryable=False
                        )
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        payload = json.loads(line)
                        message = payload.get("message") or {}
                        content = str(message.get("content") or "")
                        if content.startswith(seen_text):
                            delta = content[len(seen_text) :]
                            seen_text = content
                        else:
                            delta = content
                            seen_text += content
                        if delta:
                            yield TextDelta(delta)
                        for call in message.get("tool_calls") or ():
                            async for event in self._consume_call(buffers, call):
                                yield event
                        if payload.get("done"):
                            finish_reason = str(
                                payload.get("done_reason") or "stop"
                            )
                            if (
                                "prompt_eval_count" in payload
                                or "eval_count" in payload
                            ):
                                usage = ModelUsage(
                                    input_tokens=int(
                                        payload.get("prompt_eval_count") or 0
                                    ),
                                    output_tokens=int(
                                        payload.get("eval_count") or 0
                                    ),
                                )
        except CodingModelError:
            raise
        except TimeoutError as error:
            raise CodingModelError("model_timeout", retryable=True) from error
        except httpx.TimeoutException as error:
            raise CodingModelError("model_timeout", retryable=True) from error
        except httpx.HTTPError as error:
            raise CodingModelError(
                "model_transport_failed", retryable=True
            ) from error

        for buffer in buffers.values():
            yield complete_tool_buffer(
                buffer, max_depth=self._max_tool_input_depth
            )
        yield ModelCompleted(
            stop_reason=normalize_stop_reason(
                finish_reason, has_tool_calls=bool(buffers)
            ),
            usage=usage,
        )

    async def _consume_call(
        self,
        buffers: dict[str, ToolArgumentBuffer],
        call: Mapping[str, object],
    ) -> AsyncIterator[ModelEvent]:
        function = call.get("function") if isinstance(call.get("function"), Mapping) else {}
        name = str(function.get("name") or call.get("name") or "")
        call_id = str(call.get("id") or f"ollama_{uuid4().hex}")
        if not name:
            raise CodingModelError("tool_input_without_start", retryable=False)
        arguments = function.get("arguments", call.get("arguments", {}))
        if isinstance(arguments, str):
            fragment = arguments
        else:
            fragment = json.dumps(dict(arguments or {}), separators=(",", ":"))
        buffer = buffers.get(call_id)
        if buffer is None:
            buffer = ToolArgumentBuffer(tool_call_id=call_id, name=name)
            buffers[call_id] = buffer
        yield ToolInputDelta(
            buffer.tool_call_id,
            buffer.name,
            buffer.append(fragment, max_bytes=self._max_tool_input_bytes),
        )


def _to_ollama_request(request: ModelRequest) -> dict[str, object]:
    messages: list[dict[str, object]] = [
        {"role": "system", "content": request.system}
    ]
    for message in request.messages:
        messages.extend(_message_to_ollama(message))
    payload: dict[str, object] = {
        "model": request.model,
        "messages": messages,
        "stream": True,
        "options": {"num_predict": request.limits.max_output_tokens},
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
    return payload


def _message_to_ollama(message: CanonicalMessage) -> list[dict[str, object]]:
    if message.role == "system":
        # See the OpenAI adapter: a reveal-only message has no text form
        # here, and an empty user turn is worse than no turn at all.
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
                "content": json.dumps(dict(item.content), separators=(",", ":")),
            }
            for item in message.content
            if isinstance(item, ToolResultContent)
        ]
    texts = [
        item.text for item in message.content if isinstance(item, TextContent)
    ]
    tools = [
        item for item in message.content if isinstance(item, ToolUseContent)
    ]
    payload: dict[str, object] = {
        "role": "user" if message.role == "user" else "assistant",
        "content": "".join(texts),
    }
    if tools:
        payload["tool_calls"] = [
            {
                "id": item.tool_call_id,
                "function": {
                    "name": item.name,
                    "arguments": dict(item.input),
                },
            }
            for item in tools
        ]
    return [payload]
