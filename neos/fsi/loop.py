from __future__ import annotations

from dataclasses import replace

from neos.coding.model.base import CodingModel
from neos.subagent.catalog import SpecRegistry
from neos.subagent.memory import InMemorySubagentStore
from neos.subagent.ports import SystemClock
from neos.subagent.runtime import SubagentRuntime
from neos.subagent.stepper import ChildStepper
from neos.subagent.types import FoldedResult, StepKind, SubagentTicket, ToolPort


class _NullSink:
    async def emit(self, event_type: str, payload) -> None:
        return None


def make_fsi_runtime(
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
    return await runtime.fold(outcome.run_id)
