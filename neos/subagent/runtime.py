"""Parent-driven 1-step subagent facade."""

from __future__ import annotations

from datetime import UTC, datetime

from neos.subagent.catalog import SpecRegistry
from neos.subagent.fold import fold_run
from neos.subagent.ports import Clock
from neos.subagent.stepper import ChildStepper
from neos.subagent.store import RunRecord, SubagentStore
from neos.subagent.types import (
    FoldedResult,
    ParentKind,
    StepKind,
    StepOutcome,
    SubagentEventSink,
    SubagentSnapshot,
    SubagentStatus,
    SubagentTicket,
)

# Conservative default: max_turns=8 * model_timeout=120s + slack.
DEFAULT_STALE_AFTER_SEC = 8 * 120 + 30
_LIVE = frozenset({SubagentStatus.PENDING, SubagentStatus.RUNNING})

_TERMINAL = frozenset(
    {SubagentStatus.COMPLETED, SubagentStatus.FAILED, SubagentStatus.KILLED}
)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _step_kind(status: SubagentStatus) -> StepKind:
    if status is SubagentStatus.COMPLETED:
        return StepKind.COMPLETED
    if status is SubagentStatus.FAILED:
        return StepKind.FAILED
    if status is SubagentStatus.KILLED:
        return StepKind.CANCELLED
    return StepKind.CONTINUING


def _outcome(record: RunRecord, *, tokens_delta: int = 0) -> StepOutcome:
    return StepOutcome(
        kind=_step_kind(record.status),
        run_id=record.run_id,
        checkpoint_id=record.latest_checkpoint_id,
        status=record.status,
        turn_count=record.turn_count,
        tool_count=record.tool_count,
        error_code=record.error_code,
        input_tokens=record.input_tokens,
        output_tokens=record.output_tokens,
        tokens_delta=max(0, tokens_delta),
    )


class SubagentRuntime:
    def __init__(
        self,
        *,
        store: SubagentStore,
        catalog: SpecRegistry,
        stepper: ChildStepper,
        events: SubagentEventSink,
        clock: Clock,
    ) -> None:
        self._store = store
        self._catalog = catalog
        self._stepper = stepper
        self._events = events
        self._clock = clock

    async def advance(self, ticket: SubagentTicket) -> StepOutcome:
        spec = self._catalog.lookup_spec(ticket.spec)
        record = await self._store.resolve_or_create(ticket)
        if record.status is SubagentStatus.PENDING and record.latest_seq == 0:
            await self._events.emit(
                "subagent.started",
                {
                    "run_id": record.run_id,
                    "spec": record.spec,
                    "parent_kind": record.parent_kind.value,
                    "parent_id": record.parent_id,
                    "parent_run_id": record.parent_run_id,
                    "parent_tool_call_id": record.parent_tool_call_id,
                    "status": record.status.value,
                    "turn_count": record.turn_count,
                    "tool_count": record.tool_count,
                    "model": record.model,
                    "provider": record.provider,
                    "max_turns": record.max_turns,
                },
            )
        if record.status in _TERMINAL:
            return _outcome(record)
        reservation = await self._store.reserve(
            record.run_id, ticket.expected_checkpoint_id
        )
        if not reservation.matched:
            await self._events.emit(
                "subagent.cas_mismatch",
                {
                    "run_id": record.run_id,
                    "parent_kind": record.parent_kind.value,
                    "spec": record.spec,
                },
            )
            return _outcome(reservation.run)
        before_tokens = record.input_tokens + record.output_tokens
        write = await self._stepper.step(
            ticket=ticket, spec=spec, reservation=reservation
        )
        committed = await self._store.commit(reservation, write)
        kind = _step_kind(committed.status)
        tokens_delta = max(
            0,
            committed.input_tokens
            + committed.output_tokens
            - before_tokens,
        )
        await self._events.emit(
            "subagent.step",
            {
                "run_id": committed.run_id,
                "checkpoint_id": committed.latest_checkpoint_id,
                "turn_count": committed.turn_count,
                "tool_count": committed.tool_count,
                "step_kind": kind.value,
                "spec": committed.spec,
                "parent_kind": committed.parent_kind.value,
                "parent_id": committed.parent_id,
                "parent_run_id": committed.parent_run_id,
                "parent_tool_call_id": committed.parent_tool_call_id,
                "status": committed.status.value,
            },
        )
        if committed.status is SubagentStatus.COMPLETED:
            await self._events.emit(
                "subagent.completed",
                {
                    "run_id": committed.run_id,
                    "turn_count": committed.turn_count,
                    "tool_count": committed.tool_count,
                    "input_tokens": committed.input_tokens,
                    "output_tokens": committed.output_tokens,
                    "cost_micros": committed.cost_micros,
                    "spec": committed.spec,
                    "parent_kind": committed.parent_kind.value,
                    "parent_id": committed.parent_id,
                    "parent_run_id": committed.parent_run_id,
                    "parent_tool_call_id": committed.parent_tool_call_id,
                    "status": committed.status.value,
                    "step_kind": kind.value,
                    "provider": committed.provider,
                },
            )
        elif committed.status is SubagentStatus.FAILED:
            await self._events.emit(
                "subagent.failed",
                {
                    "run_id": committed.run_id,
                    "error_code": committed.error_code,
                    "spec": committed.spec,
                    "parent_kind": committed.parent_kind.value,
                },
            )
        return _outcome(committed, tokens_delta=tokens_delta)

    async def status(self, run_id: str) -> SubagentSnapshot:
        return (await self._store.get(run_id)).snapshot()

    async def fail_if_stale(
        self,
        run_id: str,
        *,
        now: datetime,
        stale_after_sec: float = DEFAULT_STALE_AFTER_SEC,
    ) -> SubagentSnapshot:
        record = await self._store.get(run_id)
        if record.status not in _LIVE:
            return record.snapshot()
        # <= 0: parent already decided stale (last_advanced_at vs parent clock
        # can disagree with store updated_at, which uses wall time).
        if stale_after_sec > 0:
            age = (_aware(now) - _aware(record.updated_at)).total_seconds()
            if age < stale_after_sec:
                return record.snapshot()
        failed = await self._store.fail(run_id, "stalled")
        if failed.status is SubagentStatus.FAILED and failed.error_code == "stalled":
            await self._events.emit(
                "subagent.failed",
                {
                    "run_id": failed.run_id,
                    "error_code": failed.error_code,
                    "spec": failed.spec,
                    "parent_kind": failed.parent_kind.value,
                },
            )
        return failed.snapshot()

    async def cancel(self, run_id: str, reason: str) -> SubagentSnapshot:
        record = await self._store.cancel(run_id, reason)
        if record.status is SubagentStatus.KILLED:
            await self._events.emit(
                "subagent.cancelled",
                {"run_id": record.run_id, "reason": reason},
            )
        return record.snapshot()

    async def cancel_for_parent(
        self, parent_kind: ParentKind, parent_id: str, reason: str
    ) -> tuple[SubagentSnapshot, ...]:
        records = await self._store.cancel_for_parent(parent_kind, parent_id, reason)
        snapshots: list[SubagentSnapshot] = []
        for record in records:
            if record.status is SubagentStatus.KILLED:
                await self._events.emit(
                    "subagent.cancelled",
                    {"run_id": record.run_id, "reason": reason},
                )
            snapshots.append(record.snapshot())
        return tuple(snapshots)

    async def delete_for_parent(
        self, parent_kind: ParentKind, parent_id: str
    ) -> int:
        return await self._store.delete_for_parent(parent_kind, parent_id)

    async def fold(
        self,
        run_id: str,
        *,
        parent_headroom_chars: int | None = None,
        sibling_count: int | None = None,
    ) -> FoldedResult:
        record = await self._store.get(run_id)
        state = await self._store.get_loop_state(run_id)
        return fold_run(
            record,
            state,
            parent_headroom_chars=parent_headroom_chars,
            sibling_count=sibling_count,
        )
