"""No-op hook ports for the coding loop (Phase 2)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal, NotRequired, Protocol, TypedDict

from neos.coding.model.base import CanonicalMessage
from neos.coding.tools.registry import ValidatedToolCall


class HookDecision(TypedDict):
    decision: Literal["allow", "deny", "retry", "prevent"]
    reason: NotRequired[str]
    updatedInput: NotRequired[Mapping[str, Any]]


class StopDecision(TypedDict):
    decision: Literal["allow", "prevent", "retry"]
    reason: NotRequired[str]


def post_tool_prevented(value: object) -> bool:
    return isinstance(value, Mapping) and value.get("decision") == "prevent"


class CodingHookPort(Protocol):
    async def pre_tool(self, call: ValidatedToolCall) -> HookDecision | None: ...

    async def post_tool(
        self, call: ValidatedToolCall, result: Mapping[str, Any]
    ) -> Mapping[str, Any] | None: ...

    async def stop(self, reason: str) -> StopDecision | None: ...

    async def compact(
        self,
        before: Sequence[CanonicalMessage],
        after: Sequence[CanonicalMessage],
    ) -> None: ...


class NullCodingHooks:
    async def pre_tool(self, call: ValidatedToolCall) -> HookDecision | None:
        return None

    async def post_tool(
        self, call: ValidatedToolCall, result: Mapping[str, Any]
    ) -> Mapping[str, Any] | None:
        return None

    async def stop(self, reason: str) -> StopDecision | None:
        return None

    async def compact(
        self,
        before: Sequence[CanonicalMessage],
        after: Sequence[CanonicalMessage],
    ) -> None:
        return None
