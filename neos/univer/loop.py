from __future__ import annotations

from dataclasses import replace

from neos.coding.model.base import CodingModel
from neos.subagent.catalog import SpecRegistry
from neos.subagent.memory import InMemorySubagentStore
from neos.subagent.ports import SystemClock
from neos.subagent.runtime import SubagentRuntime
from neos.subagent.stepper import ChildStepper
from neos.subagent.types import (
    FoldedResult,
    ParentKind,
    StepKind,
    SubagentTicket,
    ToolPort,
)
from neos.univer.schemas import validate_child_fold


class _NullSink:
    async def emit(self, event_type: str, payload) -> None:
        return None


def make_univer_runtime(
    *, model: CodingModel, tools: ToolPort, catalog: SpecRegistry
) -> SubagentRuntime:
    return SubagentRuntime(
        store=InMemorySubagentStore(),
        catalog=catalog,
        stepper=ChildStepper(model=model, tools=tools, nested_spawn=None),
        events=_NullSink(),
        clock=SystemClock(),
    )


async def run_leaf(*, runtime: SubagentRuntime, ticket: SubagentTicket) -> FoldedResult:
    outcome = await runtime.advance(ticket)
    while outcome.kind is StepKind.CONTINUING:
        outcome = await runtime.advance(
            replace(
                ticket,
                run_id=outcome.run_id,
                expected_checkpoint_id=outcome.checkpoint_id,
            )
        )
    folded = await runtime.fold(outcome.run_id)
    if folded.exit_reason == "completed":
        text = folded.full_summary if folded.truncated else folded.summary
        validate_child_fold(ticket.spec, text)
    return folded


async def cancel_univer_children(
    runtime: SubagentRuntime, parent_id: str, *, enabled: bool
) -> list:
    if enabled:
        return []
    snaps = await runtime.cancel_for_parent(ParentKind.UNIVER, parent_id, "flag_disabled")
    return list(snaps)


def artifact_status_for(folded: FoldedResult, spec: str) -> str | None:
    if folded.exit_reason == "completed" and spec == "univer-writer":
        from neos.univer.safety import SUCCESS_ARTIFACT_STATUS
        return SUCCESS_ARTIFACT_STATUS
    return None
