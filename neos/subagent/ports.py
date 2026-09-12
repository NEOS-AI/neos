"""Injected ports. ToolPort and the event sink live on types for the public surface."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

from neos.subagent.types import SubagentEventSink, ToolPort

__all__ = ["Clock", "SubagentEventSink", "SystemClock", "ToolPort"]


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)
