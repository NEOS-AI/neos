"""In-memory SubagentStore with the same CAS rules as the SQL adapter."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, Mapping

from neos.subagent.identity import (
    new_checkpoint_id,
    new_run_id,
    persist_payload,
)
from neos.subagent.store import (
    PLACEHOLDER_STATE,
    CasReservation,
    CheckpointWrite,
    RunRecord,
    SubagentNotFound,
    is_placeholder,
)
from neos.subagent.types import ParentKind, SubagentStatus, SubagentTicket

_TERMINAL = frozenset(
    {SubagentStatus.COMPLETED, SubagentStatus.FAILED, SubagentStatus.KILLED}
)


class CrashAfterInsert(RuntimeError):
    """Test hook: reservation inserted a placeholder and then died."""


def _now() -> datetime:
    return datetime.now(UTC)


def _briefing_payload(ticket: SubagentTicket) -> dict[str, Any]:
    return persist_payload(
        {
            "goal": ticket.briefing.goal,
            "why": ticket.briefing.why,
            "already_tried": list(ticket.briefing.already_tried),
            "scope": ticket.briefing.scope,
            "success": ticket.briefing.success,
            "report_budget_chars": ticket.briefing.report_budget_chars,
        }
    )


class InMemorySubagentStore:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._runs: dict[str, RunRecord] = {}
        self._by_parent: dict[tuple[str, str, str], str] = {}
        self._checkpoints: dict[str, list[dict[str, Any]]] = {}
        self.crash_after_insert = False

    async def resolve_or_create(self, ticket: SubagentTicket) -> RunRecord:
        async with self._lock:
            if ticket.run_id:
                return self._require(ticket.run_id)
            key = (
                ticket.parent_kind.value,
                ticket.parent_id,
                ticket.parent_tool_call_id,
            )
            existing = self._by_parent.get(key)
            if existing is not None:
                return self._require(existing)
            now = _now()
            run = RunRecord(
                run_id=new_run_id(),
                parent_kind=ticket.parent_kind,
                parent_id=ticket.parent_id,
                parent_run_id=ticket.parent_run_id,
                parent_tool_call_id=ticket.parent_tool_call_id,
                lineage_kind=ticket.lineage_kind,
                spec=ticket.spec,
                status=SubagentStatus.PENDING,
                provider=ticket.model.provider,
                model=ticket.model.model,
                max_turns=ticket.max_turns,
                turn_count=0,
                tool_count=0,
                input_tokens=0,
                output_tokens=0,
                cost_micros=0,
                briefing=_briefing_payload(ticket),
                error_code="",
                sandbox_mode=ticket.sandbox_mode,
                created_at=now,
                updated_at=now,
                completed_at=None,
                latest_checkpoint_id=None,
                latest_seq=0,
            )
            self._runs[run.run_id] = run
            self._by_parent[key] = run.run_id
            self._checkpoints[run.run_id] = []
            return run

    async def get(self, run_id: str) -> RunRecord:
        async with self._lock:
            return self._require(run_id)

    async def get_loop_state(self, run_id: str) -> Mapping[str, Any]:
        async with self._lock:
            self._require(run_id)
            latest = self._latest(run_id)
            if latest is None:
                return {}
            return deepcopy(latest["loop_state"])

    async def reserve(self, run_id: str, expected: str | None) -> CasReservation:
        async with self._lock:
            run = self._require(run_id)
            latest = self._latest(run_id)
            restore = self._restore_state(run_id)
            latest_id = None if latest is None else latest["checkpoint_id"]
            latest_state = None if latest is None else latest["loop_state"]
            placeholder = is_placeholder(latest_state)

            if placeholder and (expected is None or expected == latest_id):
                return CasReservation(
                    matched=True,
                    takeover=True,
                    run=run,
                    seq=int(latest["seq"]),
                    checkpoint_id=str(latest_id),
                    loop_state=deepcopy(latest_state),
                    restore_state=restore,
                )

            expected_matches = latest_id == expected
            if expected_matches and not placeholder:
                seq = 1 if latest is None else int(latest["seq"]) + 1
                if any(item["seq"] == seq for item in self._checkpoints[run_id]):
                    return self._mismatch(run, latest, restore)
                checkpoint_id = new_checkpoint_id()
                row = {
                    "checkpoint_id": checkpoint_id,
                    "seq": seq,
                    "loop_state": dict(PLACEHOLDER_STATE),
                }
                self._checkpoints[run_id].append(row)
                self._runs[run_id] = replace(
                    run,
                    latest_checkpoint_id=checkpoint_id,
                    latest_seq=seq,
                    updated_at=_now(),
                )
                if self.crash_after_insert:
                    raise CrashAfterInsert(checkpoint_id)
                return CasReservation(
                    matched=True,
                    takeover=False,
                    run=self._runs[run_id],
                    seq=seq,
                    checkpoint_id=checkpoint_id,
                    loop_state=dict(PLACEHOLDER_STATE),
                    restore_state=restore,
                )

            return self._mismatch(run, latest, restore)

    async def commit(
        self, reservation: CasReservation, write: CheckpointWrite
    ) -> RunRecord:
        async with self._lock:
            run = self._require(reservation.run.run_id)
            row = self._row(reservation.run.run_id, reservation.seq)
            if row is None:
                raise SubagentNotFound(reservation.run.run_id)
            state = persist_payload(dict(write.loop_state))
            row["loop_state"] = state
            if run.status in _TERMINAL:
                return run
            now = _now()
            completed_at = (
                now if write.status in _TERMINAL else run.completed_at
            )
            updated = replace(
                run,
                status=write.status,
                turn_count=write.turn_count,
                tool_count=write.tool_count,
                input_tokens=write.input_tokens,
                output_tokens=write.output_tokens,
                cost_micros=write.cost_micros,
                error_code=write.error_code,
                latest_checkpoint_id=reservation.checkpoint_id,
                latest_seq=reservation.seq,
                updated_at=now,
                completed_at=completed_at,
            )
            self._runs[run.run_id] = updated
            return updated

    async def cancel(self, run_id: str, reason: str) -> RunRecord:
        async with self._lock:
            return self._mark_terminal_locked(
                run_id, SubagentStatus.KILLED, reason
            )

    async def fail(self, run_id: str, error_code: str) -> RunRecord:
        async with self._lock:
            return self._mark_terminal_locked(
                run_id, SubagentStatus.FAILED, error_code
            )

    async def cancel_for_parent(
        self, parent_kind: ParentKind, parent_id: str, reason: str
    ) -> tuple[RunRecord, ...]:
        async with self._lock:
            children = [
                run
                for run in self._runs.values()
                if run.parent_kind is parent_kind and run.parent_id == parent_id
            ]
            return tuple(
                self._mark_terminal_locked(
                    run.run_id, SubagentStatus.KILLED, reason
                )
                for run in children
            )

    async def delete_for_parent(
        self, parent_kind: ParentKind, parent_id: str
    ) -> int:
        async with self._lock:
            victims = [
                run
                for run in self._runs.values()
                if run.parent_kind is parent_kind and run.parent_id == parent_id
            ]
            for run in victims:
                self._runs.pop(run.run_id, None)
                self._checkpoints.pop(run.run_id, None)
                self._by_parent.pop(
                    (
                        run.parent_kind.value,
                        run.parent_id,
                        run.parent_tool_call_id,
                    ),
                    None,
                )
            return len(victims)

    def _mark_terminal_locked(
        self, run_id: str, status: SubagentStatus, error_code: str
    ) -> RunRecord:
        run = self._require(run_id)
        if run.status in _TERMINAL:
            return run
        now = _now()
        updated = replace(
            run,
            status=status,
            error_code=error_code,
            updated_at=now,
            completed_at=now,
        )
        self._runs[run_id] = updated
        return updated

    def _require(self, run_id: str) -> RunRecord:
        try:
            return self._runs[run_id]
        except KeyError as exc:
            raise SubagentNotFound(run_id) from exc

    def _latest(self, run_id: str) -> dict[str, Any] | None:
        rows = self._checkpoints.get(run_id) or []
        if not rows:
            return None
        return max(rows, key=lambda item: int(item["seq"]))

    def _row(self, run_id: str, seq: int) -> dict[str, Any] | None:
        for item in self._checkpoints.get(run_id, []):
            if int(item["seq"]) == seq:
                return item
        return None

    def _restore_state(self, run_id: str) -> dict[str, Any]:
        rows = sorted(
            self._checkpoints.get(run_id, []),
            key=lambda item: int(item["seq"]),
            reverse=True,
        )
        for item in rows:
            if not is_placeholder(item["loop_state"]):
                return deepcopy(item["loop_state"])
        return {}

    def _mismatch(
        self,
        run: RunRecord,
        latest: dict[str, Any] | None,
        restore: Mapping[str, Any],
    ) -> CasReservation:
        if latest is None:
            return CasReservation(
                matched=False,
                takeover=False,
                run=run,
                seq=0,
                checkpoint_id="",
                loop_state={},
                restore_state=dict(restore),
            )
        return CasReservation(
            matched=False,
            takeover=False,
            run=run,
            seq=int(latest["seq"]),
            checkpoint_id=str(latest["checkpoint_id"]),
            loop_state=deepcopy(latest["loop_state"]),
            restore_state=dict(restore),
        )
