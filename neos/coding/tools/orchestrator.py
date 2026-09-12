"""Partition coding tool calls for durable batch execution."""

from __future__ import annotations

from collections.abc import Sequence

from neos.coding.tools.registry import ToolRisk, ValidatedToolCall

DEFAULT_READONLY_BATCH = 10


def partition_leading_readonly(
    calls: Sequence[ValidatedToolCall],
    *,
    max_batch: int = DEFAULT_READONLY_BATCH,
) -> tuple[tuple[ValidatedToolCall, ...], tuple[ValidatedToolCall, ...]]:
    if max_batch < 1:
        raise ValueError("max_batch must be positive")
    batch: list[ValidatedToolCall] = []
    for call in calls:
        if call.risk is not ToolRisk.READ_ONLY or len(batch) >= max_batch:
            break
        batch.append(call)
    return tuple(batch), tuple(calls[len(batch) :])
