from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from neos.coding.model.base import CodingModel
from neos.fsi.profile import compile_leaf_spec
from neos.fsi.schemas import validate_child_fold
from neos.subagent.catalog import SpecRegistry
from neos.subagent.memory import InMemorySubagentStore
from neos.subagent.ports import SystemClock
from neos.subagent.runtime import SubagentRuntime
from neos.subagent.stepper import ChildStepper
from neos.subagent.types import (
    FoldedResult,
    ModelPin,
    ParentBriefing,
    ParentKind,
    StepKind,
    SubagentTicket,
    ToolPort,
)


class FlagDisabled(RuntimeError):
    pass


class _NullSink:
    async def emit(self, event_type: str, payload) -> None:
        return None


def overlay_catalog(profile: Mapping[str, object]) -> SpecRegistry:
    """Register every compiled leaf on a fresh overlay. Do not touch module _SPECS."""
    overlay = SpecRegistry({})
    leaves = profile.get("leaves")
    if isinstance(leaves, list):
        for leaf in leaves:
            if isinstance(leaf, dict) and isinstance(leaf.get("name"), str):
                overlay.register(compile_leaf_spec(profile, leaf["name"]))
    return overlay


async def run_parent_spawn(
    *,
    runtime: SubagentRuntime,
    profile: Mapping[str, object],
    spec: str,
    briefing: ParentBriefing,
    parent_id: str,
    parent_run_id: str,
    parent_tool_call_id: str,
    model: ModelPin,
    enabled: bool,
) -> FoldedResult:
    if not enabled:
        raise FlagDisabled("flag_disabled")
    overlay_catalog(profile).lookup_spec(spec)
    ticket = SubagentTicket(
        parent_kind=ParentKind.FSI,
        parent_id=parent_id,
        parent_run_id=parent_run_id,
        parent_tool_call_id=parent_tool_call_id,
        spec=spec,
        briefing=briefing,
        model=model,
    )
    return await run_leaf(runtime=runtime, ticket=ticket)


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
    folded = await runtime.fold(outcome.run_id)
    if folded.exit_reason == "completed":
        text = folded.full_summary if folded.truncated else folded.summary
        validate_child_fold(ticket.spec, text)
    return folded


async def cancel_fsi_children(
    runtime: SubagentRuntime, parent_id: str, *, enabled: bool
) -> list:
    if enabled:
        return []
    snaps = await runtime.cancel_for_parent(ParentKind.FSI, parent_id, "flag_disabled")
    return list(snaps)
