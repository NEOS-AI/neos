"""Partition coding tool calls for durable batch execution."""

from __future__ import annotations

from collections.abc import Sequence

from neos.coding.tools.registry import ToolRisk, ValidatedToolCall

DEFAULT_READONLY_BATCH = 10


def speculation_safe(call: ValidatedToolCall) -> bool:
    """앞질러(배치·프리페치) 돌려도 되는 호출인가. 두 자리가 **이 판정 하나**를 쓴다.

    금고의 비밀을 푸는 호출(트랙 Q6·Q11a)은 READ_ONLY 여도 아니다 -- 앞지르는 길에는
    소유자의 금고가 묶여 있지 않고, 비밀을 쓰는 호출은 게이트의 본 판정만 지난다.
    """
    from neos.coding.secrets import carries_secret_refs

    return call.risk is ToolRisk.READ_ONLY and not carries_secret_refs(call)


def partition_leading_readonly(
    calls: Sequence[ValidatedToolCall],
    *,
    max_batch: int = DEFAULT_READONLY_BATCH,
) -> tuple[tuple[ValidatedToolCall, ...], tuple[ValidatedToolCall, ...]]:
    if max_batch < 1:
        raise ValueError("max_batch must be positive")
    batch: list[ValidatedToolCall] = []
    for call in calls:
        if not speculation_safe(call) or len(batch) >= max_batch:
            break
        batch.append(call)
    return tuple(batch), tuple(calls[len(batch) :])
