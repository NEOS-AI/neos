"""Tickets, snapshots, outcomes, briefing, and lineage."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal, Mapping, Protocol


class ParentKind(StrEnum):
    CODING = "coding"
    DEEP_ANALYSIS = "deep_analysis"


class LineageKind(StrEnum):
    DELEGATE = "delegate"  # P1 only
    COMPRESSION = "compression"  # reserved; do not write
    BRANCH = "branch"  # reserved; do not write


class SubagentStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    KILLED = "killed"


class StepKind(StrEnum):
    CONTINUING = "continuing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SandboxMode(StrEnum):
    NONE = "none"  # DA P1 / explore default
    PARENT_RO = "parent_ro"  # coding explore: reuse parent binding, RO tools only


@dataclass(frozen=True, slots=True)
class ParentBriefing:
    goal: str
    why: str = ""
    already_tried: tuple[str, ...] = ()
    scope: str = ""
    success: str = ""
    report_budget_chars: int = 4000

    def __post_init__(self) -> None:
        if not self.goal.strip():
            raise ValueError("briefing.goal is required")
        if self.report_budget_chars < 256 or self.report_budget_chars > 16_384:
            raise ValueError("report_budget_chars out of range")


@dataclass(frozen=True, slots=True)
class ModelPin:
    provider: Literal["anthropic", "openai", "gemini", "ollama"]
    model: str
    # optional same-provider alias; empty means inherit parent model
    alias: str = ""

    def __post_init__(self) -> None:
        if not self.provider or not self.model:
            raise ValueError("model pin required")


@dataclass(frozen=True, slots=True)
class SubagentTicket:
    """Parent-issued work item. No channel/peer keys by construction."""

    parent_kind: ParentKind
    parent_id: str  # coding task_id or DA run_id
    parent_run_id: str  # coding run_id or DA run_id
    parent_tool_call_id: str
    spec: str  # must be registered; P1 == "explore"
    briefing: ParentBriefing
    model: ModelPin
    max_turns: int = 4
    sandbox_mode: SandboxMode = SandboxMode.NONE
    expected_checkpoint_id: str | None = None
    run_id: str | None = None  # set on resume
    lineage_kind: LineageKind = LineageKind.DELEGATE

    def __post_init__(self) -> None:
        if self.lineage_kind is not LineageKind.DELEGATE:
            raise ValueError("P1 lineage_kind must be delegate")
        if not 1 <= self.max_turns <= 8:
            raise ValueError("max_turns must be 1–8")
        # Identity fence is structural: these names are not fields.
        # Do not hasattr-check them — a frozen slots dataclass will
        # never have them. Strip happens in identity.py on JSON write.


@dataclass(frozen=True, slots=True)
class StepOutcome:
    kind: StepKind
    run_id: str
    checkpoint_id: str | None
    status: SubagentStatus
    turn_count: int
    tool_count: int
    error_code: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    tokens_delta: int = 0


@dataclass(frozen=True, slots=True)
class SubagentSnapshot:
    run_id: str
    status: SubagentStatus
    spec: str
    parent_kind: ParentKind
    parent_id: str
    parent_tool_call_id: str
    checkpoint_id: str | None
    turn_count: int
    max_turns: int
    input_tokens: int
    output_tokens: int
    cost_micros: int
    error_code: str = ""


@dataclass(frozen=True, slots=True)
class FoldedResult:
    run_id: str
    status: SubagentStatus
    summary: str
    truncated: bool
    citations: tuple[str, ...] = ()  # paths or URLs as strings; not verified claims
    turn_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_micros: int = 0


class ToolPort(Protocol):
    def definitions(self) -> tuple[Any, ...]: ...
    async def execute(self, name: str, input: Mapping[str, object]) -> Mapping[str, Any]: ...


class SubagentEventSink(Protocol):
    async def emit(self, event_type: str, payload: Mapping[str, Any]) -> None: ...
