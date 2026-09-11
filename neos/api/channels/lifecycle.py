"""Bound-thread coding lifecycle cards. No housekeeping progress."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol

from neos.api.channels.session_bind import ChannelCodingBinding

HOUSEKEEPING_TOOLS = frozenset(
    {
        "todo_write.v1",
        "load_skill.v1",
        "search_tools.v1",
        "set_phase.v1",
        "spawn_agent.v1",
    }
)
_PUSH_STATUSES = frozenset(
    {"waiting_approval", "completed", "failed", "cancelled"}
)


class ChannelLifecycleSink(Protocol):
    async def publish(self, binding: ChannelCodingBinding, text: str) -> None: ...


class NullChannelLifecycleSink:
    async def publish(self, binding: ChannelCodingBinding, text: str) -> None:
        del binding, text


def format_lifecycle_card(
    task_id: str,
    status: str,
    *,
    approval_id: str | None = None,
    tool_name: str | None = None,
) -> str | None:
    if tool_name in HOUSEKEEPING_TOOLS:
        return None
    if status not in _PUSH_STATUSES:
        return None
    if status == "waiting_approval":
        parts = [task_id, "waiting_approval"]
        if approval_id:
            parts.append(approval_id)
            if tool_name:
                parts.append(tool_name)
        return " ".join(parts)
    return f"{task_id} {status}"


async def push_bound_lifecycle(
    *,
    get_binding: Callable[[str], Awaitable[ChannelCodingBinding | None]],
    sink: ChannelLifecycleSink,
    task_id: str,
    status: str,
    approval_id: str | None = None,
    tool_name: str | None = None,
) -> str | None:
    text = format_lifecycle_card(
        task_id, status, approval_id=approval_id, tool_name=tool_name
    )
    if text is None:
        return None
    binding = await get_binding(task_id)
    if binding is None:
        return None
    await sink.publish(binding, text)
    return text
