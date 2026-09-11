"""Collect one CodingModel stream into a vendor-neutral turn."""

from __future__ import annotations

import inspect
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass

from neos.coding.model.base import (
    CodingModel,
    ModelCompleted,
    ModelEvent,
    ModelRequest,
    TextDelta,
    ToolCallCompleted,
)


@dataclass(frozen=True, slots=True)
class ModelTurn:
    text_parts: tuple[str, ...]
    tool_calls: tuple[ToolCallCompleted, ...]
    completion: ModelCompleted | None


async def iter_model_turn(
    model: CodingModel, request: ModelRequest
) -> AsyncIterator[ModelEvent]:
    """Yield each event of one model turn as it arrives.

    Durable loops must iterate this (not ``collect_model_turn``) so text
    deltas can be persisted and streamed before the provider finishes.
    ``CodingModelError`` and ``CancelledError`` propagate unchanged.
    This is the reuse point for non-coding workflows such as deep analysis:
    lease, sandbox, and checkpoint stay with the caller.
    """
    async for event in model.stream(request):
        yield event


def fold_model_event(
    event: ModelEvent,
    *,
    text_parts: list[str],
    tool_calls: list[ToolCallCompleted],
) -> ModelCompleted | None:
    if isinstance(event, TextDelta):
        text_parts.append(event.text)
        return None
    if isinstance(event, ToolCallCompleted):
        tool_calls.append(event)
        return None
    if isinstance(event, ModelCompleted):
        return event
    return None


async def collect_model_turn(
    model: CodingModel,
    request: ModelRequest,
    *,
    on_event: Callable[[ModelEvent], Awaitable[object] | object] | None = None,
) -> ModelTurn:
    """Collect one vendor-neutral model turn from ``iter_model_turn``.

    Convenience wrapper for callers that only need the finished turn.
    Live coding must use ``iter_model_turn`` so events can be yielded
    mid-stream.
    """
    text_parts: list[str] = []
    tool_calls: list[ToolCallCompleted] = []
    completion: ModelCompleted | None = None
    async for event in iter_model_turn(model, request):
        if on_event is not None:
            result = on_event(event)
            if inspect.isawaitable(result):
                await result
        folded = fold_model_event(
            event, text_parts=text_parts, tool_calls=tool_calls
        )
        if folded is not None:
            completion = folded
    return ModelTurn(
        text_parts=tuple(text_parts),
        tool_calls=tuple(tool_calls),
        completion=completion,
    )
