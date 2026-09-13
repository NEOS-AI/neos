"""1-step nested spawn host. Explore children only; no inner while-loop."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from neos.subagent.catalog import lookup_spec
from neos.subagent.types import (
    ModelPin,
    ParentBriefing,
    SandboxMode,
    StepKind,
    SubagentTicket,
)


class RuntimeNestedSpawn:
    def __init__(self, runtime_factory: Callable[[], Any]) -> None:
        self._runtime_factory = runtime_factory

    async def spawn(
        self, parent: SubagentTicket, call: Mapping[str, object]
    ) -> Mapping[str, Any]:
        spec_name = str(call.get("spec") or "explore")
        if spec_name != "explore":
            return {"error": "nested_spec_must_be_explore"}
        try:
            lookup_spec(spec_name)
        except Exception:
            return {"error": "policy_unknown_spec"}
        goal = str(call.get("prompt") or "").strip()
        if not goal:
            return {"error": "policy_schema_invalid"}
        try:
            max_turns = int(call.get("max_turns", 4))
        except (TypeError, ValueError):
            max_turns = 4
        max_turns = max(1, min(8, max_turns))
        runtime = self._runtime_factory()
        resume = str(call.get("run_id") or "").strip()
        expected = None
        if resume:
            snapshot = await runtime.status(resume)
            expected = snapshot.checkpoint_id
        nested_call = str(call.get("tool_call_id") or "nested")
        ticket = SubagentTicket(
            parent_kind=parent.parent_kind,
            parent_id=parent.parent_id,
            parent_run_id=parent.run_id or parent.parent_run_id,
            parent_tool_call_id=f"{parent.parent_tool_call_id}:{nested_call}",
            spec="explore",
            briefing=ParentBriefing(goal=goal),
            model=parent.model
            if isinstance(parent.model, ModelPin)
            else ModelPin(provider="anthropic", model="claude-test"),
            max_turns=max_turns,
            sandbox_mode=SandboxMode.PARENT_RO,
            expected_checkpoint_id=expected,
            run_id=resume or None,
            spawn_depth=min(1, parent.spawn_depth + 1),
        )
        outcome = await runtime.advance(ticket)
        if outcome.kind is StepKind.CONTINUING:
            return {
                "ok": True,
                "status": "continuing",
                "nested_run_id": outcome.run_id,
                "checkpoint_id": outcome.checkpoint_id,
            }
        folded = await runtime.fold(outcome.run_id)
        return {
            "ok": True,
            "status": folded.status.value,
            "nested_run_id": outcome.run_id,
            "summary": folded.summary,
        }
