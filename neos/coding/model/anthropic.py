from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
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
    ThinkingCompleted,
    ThinkingContent,
    ToolAdditionContent,
    ToolDefinition,
    ToolInputDelta,
    ToolResultContent,
    ToolUseContent,
)
from neos.coding.model.buffers import ToolArgumentBuffer, complete_tool_buffer
from neos.coding.model.errors import CodingModelError
from neos.coding.model.stop import normalize_stop_reason
from neos.coding.prompts import SYSTEM_PROMPT_DYNAMIC_BOUNDARY

__all__ = ["AnthropicCodingModel", "CodingModelError"]

CLEAR_AT_BETA = "mid-conversation-system-clear-at-2026-08-21"
TOOL_CHANGES_BETA = "mid-conversation-tool-changes-2026-07-01"


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
        buffers: dict[int, ToolArgumentBuffer] = {}
        thinking_buffers: dict[int, list[str]] = {}
        input_tokens = 0
        cache_read_tokens = 0
        cache_write_tokens = 0
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
                                getattr(usage, "input_tokens", 0) or 0
                            )
                            cache_read_tokens = int(
                                getattr(usage, "cache_read_input_tokens", 0) or 0
                            )
                            cache_write_tokens = int(
                                getattr(usage, "cache_creation_input_tokens", 0)
                                or 0
                            )
                            continue
                        if event_type == "content_block_start":
                            block = raw.content_block
                            if getattr(block, "type", "") == "tool_use":
                                buffers[int(raw.index)] = ToolArgumentBuffer(
                                    tool_call_id=str(block.id),
                                    name=str(block.name),
                                )
                            elif getattr(block, "type", "") == "thinking":
                                thinking_buffers[int(raw.index)] = [
                                    str(getattr(block, "thinking", "") or ""),
                                    str(getattr(block, "signature", "") or ""),
                                ]
                            continue
                        if event_type == "content_block_delta":
                            delta = raw.delta
                            if getattr(delta, "type", "") == "text_delta":
                                yield TextDelta(str(delta.text))
                                continue
                            if getattr(delta, "type", "") in {
                                "thinking_delta",
                                "signature_delta",
                            }:
                                thinking = thinking_buffers.get(int(raw.index))
                                if thinking is not None:
                                    if delta.type == "thinking_delta":
                                        thinking[0] += str(delta.thinking)
                                    else:
                                        thinking[1] += str(delta.signature)
                                continue
                            if getattr(delta, "type", "") == "input_json_delta":
                                buffer = buffers.get(int(raw.index))
                                if buffer is None:
                                    raise CodingModelError(
                                        "tool_input_without_start",
                                        retryable=False,
                                    )
                                fragment = buffer.append(
                                    str(delta.partial_json),
                                    max_bytes=self._max_tool_input_bytes,
                                )
                                yield ToolInputDelta(
                                    buffer.tool_call_id,
                                    buffer.name,
                                    fragment,
                                )
                            continue
                        if event_type == "content_block_stop":
                            thinking = thinking_buffers.pop(int(raw.index), None)
                            if thinking is not None and thinking[1]:
                                yield ThinkingCompleted(thinking[0], thinking[1])
                            buffer = buffers.pop(int(raw.index), None)
                            if buffer is not None:
                                yield complete_tool_buffer(
                                    buffer,
                                    max_depth=self._max_tool_input_depth,
                                )
                            continue
                        if event_type == "message_delta":
                            usage = getattr(raw, "usage", None)
                            output_tokens = int(
                                getattr(usage, "output_tokens", 0)
                            )
                            stop_reason = getattr(raw.delta, "stop_reason", None)
                            normalized = normalize_stop_reason(stop_reason)
                            details = getattr(raw.delta, "stop_details", None)
                            category = getattr(details, "category", None)
                            yield ModelCompleted(
                                stop_reason=normalized,
                                stop_category=(
                                    str(category)
                                    if normalized == "refusal" and category
                                    else ""
                                ),
                                usage=ModelUsage(
                                    input_tokens=input_tokens,
                                    output_tokens=output_tokens,
                                    cache_read_tokens=cache_read_tokens,
                                    cache_write_tokens=cache_write_tokens,
                                    reasoning_tokens=int(
                                        getattr(usage, "reasoning_tokens", 0)
                                        or getattr(usage, "thinking_tokens", 0)
                                        or 0
                                    ),
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
            if error.status_code == 413:
                raise CodingModelError(
                    "prompt_too_long", retryable=True
                ) from error
            raise CodingModelError(
                "model_provider_failed", retryable=error.status_code >= 500
            ) from error


def _tool_to_anthropic(tool: ToolDefinition) -> dict[str, object]:
    rendered: dict[str, object] = {
        "name": tool.name,
        "description": tool.description,
        "input_schema": dict(tool.input_schema),
    }
    if tool.deferred:
        # Declared but not offered until a tool_addition names it. The key
        # is omitted entirely when false so the payload is byte-identical
        # to what providers without tool changes receive.
        rendered["defer_loading"] = True
    return rendered


def _to_anthropic_request(request: ModelRequest) -> dict[str, object]:
    messages, betas = _messages_to_anthropic(request.model, request.messages)
    payload: dict[str, object] = {
        "model": request.model,
        "system": _system_to_anthropic(request.system),
        "messages": messages,
        "tools": [_tool_to_anthropic(tool) for tool in request.tools],
        "max_tokens": request.limits.max_output_tokens,
    }
    if any(tool.deferred for tool in request.tools):
        betas.add(TOOL_CHANGES_BETA)
    if betas:
        payload["extra_headers"] = {"anthropic-beta": ",".join(sorted(betas))}
    return payload


def _messages_to_anthropic(
    model: str, messages: tuple[CanonicalMessage, ...]
) -> tuple[list[dict[str, object]], set[str]]:
    """Render system notes natively where the model and placement allow.

    A mid-conversation system message must follow a user turn and be last
    or followed by an assistant turn. Anywhere else, and on models without
    support, the note is a text block after the tool results — the
    documented fallback. Both forms are a pure function of the transcript,
    so an appended history renders as an appended payload.
    """
    from neos.config.model_config import supports_mid_conversation_system

    native = supports_mid_conversation_system(model)
    rendered: list[dict[str, object]] = []
    betas: set[str] = set()
    for index, message in enumerate(messages):
        if message.role != "system":
            rendered.append(_message_to_anthropic(message))
            continue
        if all(isinstance(item, ToolAdditionContent) for item in message.content):
            # A reveal never degrades to prose. A tool announced as text is
            # a tool the model was never actually offered, so the reveal
            # would silently not happen -- worse than failing loudly.
            rendered.append(
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "tool_addition",
                            "tool": {"type": "tool_reference", "name": item.name},
                        }
                        for item in message.content
                    ],
                }
            )
            betas.add(TOOL_CHANGES_BETA)
            continue
        note = message.content[0]
        previous = messages[index - 1] if index > 0 else None
        following = messages[index + 1] if index + 1 < len(messages) else None
        placeable = (
            previous is not None
            and previous.role in {"user", "tool"}
            and (following is None or following.role == "assistant")
        )
        if native and placeable:
            item: dict[str, object] = {"role": "system", "content": note.text}
            if note.clear_at != "never":
                item["clear_at"] = note.clear_at
                betas.add(CLEAR_AT_BETA)
            rendered.append(item)
        else:
            rendered.append(
                {"role": "user", "content": [{"type": "text", "text": note.text}]}
            )
    return rendered, betas


def _system_to_anthropic(system: str) -> str | list[dict[str, object]]:
    if SYSTEM_PROMPT_DYNAMIC_BOUNDARY not in system:
        return system
    static, dynamic = system.split(SYSTEM_PROMPT_DYNAMIC_BOUNDARY, 1)
    return [
        {
            "type": "text",
            "text": static,
            "cache_control": {"type": "ephemeral"},
        },
        {"type": "text", "text": dynamic},
    ]


def _message_to_anthropic(message: CanonicalMessage) -> dict[str, object]:
    role = "user" if message.role == "tool" else message.role
    return {
        "role": role,
        "content": [_content_to_anthropic(item) for item in message.content],
    }


def _content_to_anthropic(content: object) -> dict[str, object]:
    if isinstance(content, ThinkingContent):
        return {
            "type": "thinking",
            "thinking": content.thinking,
            "signature": content.signature,
        }
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
