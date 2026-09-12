"""Subagent persistence protocol and CAS records."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Protocol

from neos.subagent.types import (
    LineageKind,
    ParentKind,
    SandboxMode,
    SubagentSnapshot,
    SubagentStatus,
    SubagentTicket,
)

PLACEHOLDER_STATE: dict[str, Any] = {"_placeholder": True}


class SubagentNotFound(KeyError):
    def __init__(self, run_id: str) -> None:
        super().__init__(run_id)
        self.run_id = run_id


def is_placeholder(state: Mapping[str, Any] | None) -> bool:
    return bool(state) and state.get("_placeholder") is True


@dataclass(frozen=True, slots=True)
class RunRecord:
    run_id: str
    parent_kind: ParentKind
    parent_id: str
    parent_run_id: str
    parent_tool_call_id: str
    lineage_kind: LineageKind
    spec: str
    status: SubagentStatus
    provider: str
    model: str
    max_turns: int
    turn_count: int
    tool_count: int
    input_tokens: int
    output_tokens: int
    cost_micros: int
    briefing: Mapping[str, Any]
    error_code: str
    sandbox_mode: SandboxMode
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    latest_checkpoint_id: str | None
    latest_seq: int

    def snapshot(self) -> SubagentSnapshot:
        return SubagentSnapshot(
            run_id=self.run_id,
            status=self.status,
            spec=self.spec,
            parent_kind=self.parent_kind,
            parent_id=self.parent_id,
            parent_tool_call_id=self.parent_tool_call_id,
            checkpoint_id=self.latest_checkpoint_id,
            turn_count=self.turn_count,
            max_turns=self.max_turns,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            cost_micros=self.cost_micros,
            error_code=self.error_code,
        )


@dataclass(frozen=True, slots=True)
class CasReservation:
    matched: bool
    takeover: bool
    run: RunRecord
    seq: int
    checkpoint_id: str
    loop_state: Mapping[str, Any]
    restore_state: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CheckpointWrite:
    loop_state: Mapping[str, Any]
    status: SubagentStatus
    turn_count: int
    tool_count: int
    input_tokens: int = 0
    output_tokens: int = 0
    cost_micros: int = 0
    error_code: str = ""


class SubagentStore(Protocol):
    async def resolve_or_create(self, ticket: SubagentTicket) -> RunRecord: ...

    async def get(self, run_id: str) -> RunRecord: ...

    async def get_loop_state(self, run_id: str) -> Mapping[str, Any]: ...

    async def reserve(self, run_id: str, expected: str | None) -> CasReservation: ...

    async def commit(
        self, reservation: CasReservation, write: CheckpointWrite
    ) -> RunRecord: ...

    async def cancel(self, run_id: str, reason: str) -> RunRecord: ...

    async def fail(self, run_id: str, error_code: str) -> RunRecord: ...

    async def cancel_for_parent(
        self, parent_kind: ParentKind, parent_id: str, reason: str
    ) -> tuple[RunRecord, ...]: ...
