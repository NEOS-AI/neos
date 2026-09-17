"""Bridge deep-analysis live calls onto the vendor-neutral coding harness.

Lease, checkpoint, and DurableCodingLoop stay out of this module.
Injected SDK fakes never enter here — `llm._call_provider` keeps them.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from neos.coding.harness import collect_model_turn
from neos.coding.model.base import (
    CanonicalMessage,
    ModelLimits,
    ModelRequest,
    TextContent,
    ThinkingContent,
    ToolDefinition,
    ToolResultContent,
    ToolUseContent,
)
from neos.utils.llm_factory import create_coding_model


def da_provider_for_model(model: str) -> str:
    from neos.config.model_config import provider_for_model

    provider = provider_for_model(model)
    if provider is not None:
        return provider
    return "anthropic" if model.startswith("claude") else "openai"


def looks_like_coding_model(client: object) -> bool:
    return hasattr(client, "stream") and callable(getattr(client, "stream"))


def _text_content(value: object) -> TextContent:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    if not text:
        text = " "
    return TextContent(text)


def _tool_result_content(block: dict[str, Any]) -> ToolResultContent:
    raw = block.get("content", "")
    if isinstance(raw, dict):
        payload: dict[str, object] = dict(raw)
    else:
        payload = {"text": str(raw)}
    status = "error" if block.get("is_error") else "ok"
    return ToolResultContent(
        tool_call_id=str(block.get("tool_use_id") or block.get("id") or "tool"),
        status=status,
        content=payload,
    )


def messages_to_canonical(
    messages: list[dict[str, Any]],
) -> tuple[CanonicalMessage, ...]:
    converted: list[CanonicalMessage] = []
    for message in messages:
        role = str(message.get("role") or "user")
        content = message.get("content")
        if isinstance(content, str):
            mapped_role = "user" if role == "user" else "assistant"
            converted.append(
                CanonicalMessage(mapped_role, (_text_content(content),))
            )
            continue
        blocks = list(content or [])
        if role == "user" and blocks and all(
            isinstance(item, dict) and item.get("type") == "tool_result"
            for item in blocks
        ):
            converted.append(
                CanonicalMessage(
                    "tool",
                    tuple(_tool_result_content(item) for item in blocks),
                )
            )
            continue
        parts: list[TextContent | ToolUseContent | ThinkingContent] = []
        for item in blocks:
            if not isinstance(item, dict):
                parts.append(_text_content(item))
                continue
            kind = item.get("type")
            if kind == "thinking":
                # Replayed verbatim when signed; an unsigned block cannot be
                # replayed at all, and must not become prose.
                signature = str(item.get("signature") or "")
                if signature:
                    parts.append(
                        ThinkingContent(str(item.get("thinking") or ""), signature)
                    )
                continue
            if kind == "tool_use":
                parts.append(
                    ToolUseContent(
                        tool_call_id=str(item.get("id") or "tool"),
                        name=str(item.get("name") or "unknown"),
                        input=dict(item.get("input") or {}),
                    )
                )
            elif kind == "text":
                parts.append(_text_content(item.get("text") or " "))
            else:
                parts.append(_text_content(item))
        if all(isinstance(item, ThinkingContent) for item in parts):
            parts.append(_text_content(" "))
        converted.append(
            CanonicalMessage(
                "assistant" if role == "assistant" else "user",
                tuple(parts),
            )
        )
    return tuple(converted)


def tools_to_definitions(
    tools: list[dict[str, Any]] | None,
) -> tuple[ToolDefinition, ...]:
    if not tools:
        return ()
    defined: list[ToolDefinition] = []
    for tool in tools:
        schema = tool.get("input_schema") or {"type": "object", "properties": {}}
        defined.append(
            ToolDefinition(
                name=str(tool.get("name") or "tool"),
                description=str(tool.get("description") or tool.get("name") or "tool"),
                input_schema=dict(schema),
            )
        )
    return tuple(defined)


def turn_to_llm_response(model: str, turn):
    from neos.workflow.deep_analysis.llm import LLMResponse

    text = "".join(turn.text_parts)
    blocks: list[dict[str, Any]] = [
        {
            "type": "thinking",
            "thinking": block.thinking,
            "signature": block.signature,
        }
        for block in getattr(turn, "thinking", ())
    ]
    if text:
        blocks.append({"type": "text", "text": text})
    for call in turn.tool_calls:
        blocks.append(
            {
                "type": "tool_use",
                "id": call.tool_call_id,
                "name": call.name,
                "input": dict(call.input),
            }
        )
    usage = turn.completion.usage if turn.completion is not None else None
    stop = (
        turn.completion.stop_reason if turn.completion is not None else "unknown"
    )
    return LLMResponse(
        text=text,
        input_tokens=0 if usage is None else usage.input_tokens,
        output_tokens=0 if usage is None else usage.output_tokens,
        model=model,
        content=blocks,
        stop_reason=stop,
    )


async def call_via_harness(
    model: str,
    messages: list[dict[str, Any]],
    *,
    max_tokens: int,
    client=None,
    tools: list[dict[str, Any]] | None = None,
    stage: str = "llm",
):
    adapter = client if looks_like_coding_model(client) else None
    if adapter is None:
        adapter = create_coding_model(provider=da_provider_for_model(model))
    request = ModelRequest(
        system="Follow the user instructions.",
        messages=messages_to_canonical(messages),
        tools=tools_to_definitions(tools),
        model=model,
        limits=ModelLimits(max_output_tokens=max_tokens, timeout_sec=120),
        task_id="da",
        run_id="da",
        turn_id=f"{stage}_{uuid4().hex}",
    )
    turn = await collect_model_turn(adapter, request)
    return turn_to_llm_response(model, turn)
