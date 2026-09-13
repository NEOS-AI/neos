"""Postgres adapter for subagent_runs / subagent_checkpoints (same CAS as memory)."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, Mapping

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from neos.subagent.identity import (
    new_checkpoint_id,
    new_run_id,
    persist_payload,
    strip_channel_keys,
)
from neos.subagent.store import (
    PLACEHOLDER_STATE,
    CasReservation,
    CheckpointWrite,
    RunRecord,
    SubagentNotFound,
    is_placeholder,
)
from neos.subagent.types import (
    LineageKind,
    ParentKind,
    SandboxMode,
    SubagentStatus,
    SubagentTicket,
)

SessionFactory = Callable[[], Awaitable[AsyncSession]]

_TERMINAL = frozenset(
    {SubagentStatus.COMPLETED, SubagentStatus.FAILED, SubagentStatus.KILLED}
)

_SELECT_RUN = text(
    """
    SELECT run_id, parent_kind, parent_id, parent_run_id, parent_tool_call_id,
           lineage_kind, spec, status, provider, model, max_turns, turn_count,
           tool_count, input_tokens, output_tokens, cost_micros, briefing_json,
           error_code, sandbox_mode, created_at, updated_at, completed_at
      FROM subagent_runs
     WHERE run_id = :run_id
    """
)
_SELECT_RUN_FOR_UPDATE = text(
    """
    SELECT run_id, parent_kind, parent_id, parent_run_id, parent_tool_call_id,
           lineage_kind, spec, status, provider, model, max_turns, turn_count,
           tool_count, input_tokens, output_tokens, cost_micros, briefing_json,
           error_code, sandbox_mode, created_at, updated_at, completed_at
      FROM subagent_runs
     WHERE run_id = :run_id
     FOR UPDATE
    """
)
_SELECT_BY_PARENT = text(
    """
    SELECT run_id, parent_kind, parent_id, parent_run_id, parent_tool_call_id,
           lineage_kind, spec, status, provider, model, max_turns, turn_count,
           tool_count, input_tokens, output_tokens, cost_micros, briefing_json,
           error_code, sandbox_mode, created_at, updated_at, completed_at
      FROM subagent_runs
     WHERE parent_kind = :parent_kind
       AND parent_id = :parent_id
       AND parent_tool_call_id = :parent_tool_call_id
    """
)
_INSERT_RUN = text(
    """
    INSERT INTO subagent_runs (
        run_id, parent_kind, parent_id, parent_run_id, parent_tool_call_id,
        lineage_kind, spec, status, provider, model, max_turns, turn_count,
        tool_count, input_tokens, output_tokens, cost_micros, briefing_json,
        error_code, sandbox_mode, created_at, updated_at, completed_at
    ) VALUES (
        :run_id, :parent_kind, :parent_id, :parent_run_id, :parent_tool_call_id,
        :lineage_kind, :spec, :status, :provider, :model, :max_turns, 0,
        0, 0, 0, 0, CAST(:briefing_json AS JSONB),
        :error_code, :sandbox_mode, :created_at, :updated_at, NULL
    )
    ON CONFLICT (parent_kind, parent_id, parent_tool_call_id) DO NOTHING
    """
)
_LATEST_CHECKPOINT = text(
    """
    SELECT checkpoint_id, seq, loop_state_json
      FROM subagent_checkpoints
     WHERE run_id = :run_id
     ORDER BY seq DESC
     LIMIT 1
    """
)
_RESTORE_CHECKPOINT = text(
    """
    SELECT loop_state_json
      FROM subagent_checkpoints
     WHERE run_id = :run_id
       AND NOT (loop_state_json @> CAST(:placeholder AS JSONB))
     ORDER BY seq DESC
     LIMIT 1
    """
)
_INSERT_CHECKPOINT = text(
    """
    INSERT INTO subagent_checkpoints (
        checkpoint_id, run_id, seq, loop_state_json, created_at
    ) VALUES (
        :checkpoint_id, :run_id, :seq, CAST(:loop_state_json AS JSONB), :created_at
    )
    """
)
_UPDATE_CHECKPOINT = text(
    """
    UPDATE subagent_checkpoints
       SET loop_state_json = CAST(:loop_state_json AS JSONB)
     WHERE run_id = :run_id
       AND seq = :seq
    """
)
_UPDATE_RUN = text(
    """
    UPDATE subagent_runs
       SET status = :status,
           turn_count = :turn_count,
           tool_count = :tool_count,
           input_tokens = :input_tokens,
           output_tokens = :output_tokens,
           cost_micros = :cost_micros,
           error_code = :error_code,
           updated_at = :updated_at,
           completed_at = :completed_at
     WHERE run_id = :run_id
    """
)
_UPDATE_RUN_IF_LIVE = text(
    """
    UPDATE subagent_runs
       SET status = :status,
           turn_count = :turn_count,
           tool_count = :tool_count,
           input_tokens = :input_tokens,
           output_tokens = :output_tokens,
           cost_micros = :cost_micros,
           error_code = :error_code,
           updated_at = :updated_at,
           completed_at = :completed_at
     WHERE run_id = :run_id
       AND status NOT IN ('completed', 'failed', 'killed')
    """
)
_LIST_PARENT = text(
    """
    SELECT run_id
      FROM subagent_runs
     WHERE parent_kind = :parent_kind
       AND parent_id = :parent_id
    """
)
_LIST_PARENT_RUN = text(
    """
    SELECT run_id, parent_kind, parent_id, parent_run_id, parent_tool_call_id,
           lineage_kind, spec, status, provider, model, max_turns, turn_count,
           tool_count, input_tokens, output_tokens, cost_micros, briefing_json,
           error_code, sandbox_mode, created_at, updated_at, completed_at
      FROM subagent_runs
     WHERE parent_run_id = :parent_run_id
    """
)
_DELETE_PARENT = text(
    """
    DELETE FROM subagent_runs
     WHERE parent_kind = :parent_kind
       AND parent_id = :parent_id
    """
)


def _now() -> datetime:
    return datetime.now(UTC)


def _json(value: Mapping[str, Any] | dict[str, Any]) -> str:
    return json.dumps(persist_payload(dict(value)))


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        loaded = json.loads(value)
        return dict(loaded) if isinstance(loaded, Mapping) else {}
    return {}


def _record(row: Any, *, latest_id: str | None = None, latest_seq: int = 0) -> RunRecord:
    return RunRecord(
        run_id=row.run_id,
        parent_kind=ParentKind(row.parent_kind),
        parent_id=row.parent_id,
        parent_run_id=row.parent_run_id,
        parent_tool_call_id=row.parent_tool_call_id,
        lineage_kind=LineageKind(row.lineage_kind),
        spec=row.spec,
        status=SubagentStatus(row.status),
        provider=row.provider,
        model=row.model,
        max_turns=int(row.max_turns),
        turn_count=int(row.turn_count),
        tool_count=int(row.tool_count),
        input_tokens=int(row.input_tokens),
        output_tokens=int(row.output_tokens),
        cost_micros=int(row.cost_micros),
        briefing=strip_channel_keys(_mapping(row.briefing_json)),
        error_code=row.error_code or "",
        sandbox_mode=SandboxMode(row.sandbox_mode),
        created_at=row.created_at,
        updated_at=row.updated_at,
        completed_at=row.completed_at,
        latest_checkpoint_id=latest_id,
        latest_seq=latest_seq,
    )


class PostgresSubagentStore:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def resolve_or_create(self, ticket: SubagentTicket) -> RunRecord:
        async with await self._session_factory() as session:
            async with session.begin():
                if ticket.run_id:
                    row = (
                        await session.execute(
                            _SELECT_RUN, {"run_id": ticket.run_id}
                        )
                    ).first()
                    if row is None:
                        raise SubagentNotFound(ticket.run_id)
                    return await self._with_latest(session, row)
                parent = {
                    "parent_kind": ticket.parent_kind.value,
                    "parent_id": ticket.parent_id,
                    "parent_tool_call_id": ticket.parent_tool_call_id,
                }
                existing = (await session.execute(_SELECT_BY_PARENT, parent)).first()
                if existing is not None:
                    return await self._with_latest(session, existing)
                now = _now()
                run_id = new_run_id()
                briefing = persist_payload(
                    {
                        "goal": ticket.briefing.goal,
                        "why": ticket.briefing.why,
                        "already_tried": list(ticket.briefing.already_tried),
                        "scope": ticket.briefing.scope,
                        "success": ticket.briefing.success,
                        "report_budget_chars": ticket.briefing.report_budget_chars,
                    }
                )
                await session.execute(
                    _INSERT_RUN,
                    {
                        "run_id": run_id,
                        **parent,
                        "parent_run_id": ticket.parent_run_id,
                        "lineage_kind": ticket.lineage_kind.value,
                        "spec": ticket.spec,
                        "status": SubagentStatus.PENDING.value,
                        "provider": ticket.model.provider,
                        "model": ticket.model.model,
                        "max_turns": ticket.max_turns,
                        "briefing_json": json.dumps(briefing),
                        "error_code": "",
                        "sandbox_mode": ticket.sandbox_mode.value,
                        "created_at": now,
                        "updated_at": now,
                    },
                )
                row = (await session.execute(_SELECT_BY_PARENT, parent)).first()
                if row is None:
                    raise SubagentNotFound(run_id)
                return await self._with_latest(session, row)

    async def get(self, run_id: str) -> RunRecord:
        async with await self._session_factory() as session:
            async with session.begin():
                row = (await session.execute(_SELECT_RUN, {"run_id": run_id})).first()
                if row is None:
                    raise SubagentNotFound(run_id)
                return await self._with_latest(session, row)

    async def get_loop_state(self, run_id: str) -> Mapping[str, Any]:
        async with await self._session_factory() as session:
            async with session.begin():
                latest = (
                    await session.execute(_LATEST_CHECKPOINT, {"run_id": run_id})
                ).first()
                if latest is None:
                    return {}
                return _mapping(latest.loop_state_json)

    async def reserve(self, run_id: str, expected: str | None) -> CasReservation:
        async with await self._session_factory() as session:
            async with session.begin():
                row = (
                    await session.execute(_SELECT_RUN_FOR_UPDATE, {"run_id": run_id})
                ).first()
                if row is None:
                    raise SubagentNotFound(run_id)
                latest = (
                    await session.execute(_LATEST_CHECKPOINT, {"run_id": run_id})
                ).first()
                restore_row = (
                    await session.execute(
                        _RESTORE_CHECKPOINT,
                        {
                            "run_id": run_id,
                            "placeholder": json.dumps(PLACEHOLDER_STATE),
                        },
                    )
                ).first()
                restore = _mapping(restore_row.loop_state_json) if restore_row else {}
                latest_id = None if latest is None else str(latest.checkpoint_id)
                latest_state = None if latest is None else _mapping(latest.loop_state_json)
                latest_seq = 0 if latest is None else int(latest.seq)
                run = _record(row, latest_id=latest_id, latest_seq=latest_seq)
                placeholder = is_placeholder(latest_state)

                if placeholder and (expected is None or expected == latest_id):
                    return CasReservation(
                        matched=True,
                        takeover=True,
                        run=run,
                        seq=latest_seq,
                        checkpoint_id=str(latest_id),
                        loop_state=dict(latest_state or {}),
                        restore_state=restore,
                    )

                expected_matches = latest_id == expected
                if expected_matches and not placeholder:
                    seq = latest_seq + 1 if latest is not None else 1
                    checkpoint_id = new_checkpoint_id()
                    try:
                        async with session.begin_nested():
                            await session.execute(
                                _INSERT_CHECKPOINT,
                                {
                                    "checkpoint_id": checkpoint_id,
                                    "run_id": run_id,
                                    "seq": seq,
                                    "loop_state_json": json.dumps(PLACEHOLDER_STATE),
                                    "created_at": _now(),
                                },
                            )
                    except IntegrityError:
                        latest = (
                            await session.execute(
                                _LATEST_CHECKPOINT, {"run_id": run_id}
                            )
                        ).first()
                        return self._mismatch(run, latest, restore)
                    return CasReservation(
                        matched=True,
                        takeover=False,
                        run=replace(
                            run,
                            latest_checkpoint_id=checkpoint_id,
                            latest_seq=seq,
                        ),
                        seq=seq,
                        checkpoint_id=checkpoint_id,
                        loop_state=dict(PLACEHOLDER_STATE),
                        restore_state=restore,
                    )
                return self._mismatch(run, latest, restore)

    async def commit(
        self, reservation: CasReservation, write: CheckpointWrite
    ) -> RunRecord:
        async with await self._session_factory() as session:
            async with session.begin():
                row = (
                    await session.execute(
                        _SELECT_RUN_FOR_UPDATE,
                        {"run_id": reservation.run.run_id},
                    )
                ).first()
                if row is None:
                    raise SubagentNotFound(reservation.run.run_id)
                now = _now()
                await session.execute(
                    _UPDATE_CHECKPOINT,
                    {
                        "run_id": reservation.run.run_id,
                        "seq": reservation.seq,
                        "loop_state_json": _json(write.loop_state),
                    },
                )
                if SubagentStatus(row.status) not in _TERMINAL:
                    completed_at = (
                        now if write.status in _TERMINAL else row.completed_at
                    )
                    await session.execute(
                        _UPDATE_RUN_IF_LIVE,
                        {
                            "run_id": reservation.run.run_id,
                            "status": write.status.value,
                            "turn_count": write.turn_count,
                            "tool_count": write.tool_count,
                            "input_tokens": write.input_tokens,
                            "output_tokens": write.output_tokens,
                            "cost_micros": write.cost_micros,
                            "error_code": write.error_code,
                            "updated_at": now,
                            "completed_at": completed_at,
                        },
                    )
        return await self.get(reservation.run.run_id)

    async def cancel(self, run_id: str, reason: str) -> RunRecord:
        async with await self._session_factory() as session:
            async with session.begin():
                return await self._mark_terminal_in_session(
                    session, run_id, SubagentStatus.KILLED, reason
                )

    async def fail(self, run_id: str, error_code: str) -> RunRecord:
        async with await self._session_factory() as session:
            async with session.begin():
                return await self._mark_terminal_in_session(
                    session, run_id, SubagentStatus.FAILED, error_code
                )

    async def cancel_for_parent(
        self, parent_kind: ParentKind, parent_id: str, reason: str
    ) -> tuple[RunRecord, ...]:
        async with await self._session_factory() as session:
            async with session.begin():
                rows = (
                    await session.execute(
                        _LIST_PARENT,
                        {
                            "parent_kind": parent_kind.value,
                            "parent_id": parent_id,
                        },
                    )
                ).all()
                return tuple(
                    [
                        await self._mark_terminal_in_session(
                            session, row.run_id, SubagentStatus.KILLED, reason
                        )
                        for row in rows
                    ]
                )

    async def list_for_parent_run(self, parent_run_id: str) -> tuple[RunRecord, ...]:
        async with await self._session_factory() as session:
            async with session.begin():
                rows = (
                    await session.execute(
                        _LIST_PARENT_RUN, {"parent_run_id": parent_run_id}
                    )
                ).all()
                return tuple(
                    [await self._with_latest(session, row) for row in rows]
                )

    async def delete_for_parent(
        self, parent_kind: ParentKind, parent_id: str
    ) -> int:
        async with await self._session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    _DELETE_PARENT,
                    {
                        "parent_kind": parent_kind.value,
                        "parent_id": parent_id,
                    },
                )
        return int(result.rowcount or 0)

    async def _mark_terminal_in_session(
        self,
        session: AsyncSession,
        run_id: str,
        status: SubagentStatus,
        error_code: str,
    ) -> RunRecord:
        row = (
            await session.execute(_SELECT_RUN_FOR_UPDATE, {"run_id": run_id})
        ).first()
        if row is None:
            raise SubagentNotFound(run_id)
        run = await self._with_latest(session, row)
        if run.status in _TERMINAL:
            return run
        now = _now()
        await session.execute(
            _UPDATE_RUN,
            {
                "run_id": run_id,
                "status": status.value,
                "turn_count": run.turn_count,
                "tool_count": run.tool_count,
                "input_tokens": run.input_tokens,
                "output_tokens": run.output_tokens,
                "cost_micros": run.cost_micros,
                "error_code": error_code,
                "updated_at": now,
                "completed_at": now,
            },
        )
        latest = (
            await session.execute(_LATEST_CHECKPOINT, {"run_id": run_id})
        ).first()
        refreshed = (
            await session.execute(_SELECT_RUN, {"run_id": run_id})
        ).first()
        return _with_checkpoint(refreshed, latest)

    async def _with_latest(self, session: AsyncSession, row: Any) -> RunRecord:
        latest = (
            await session.execute(_LATEST_CHECKPOINT, {"run_id": row.run_id})
        ).first()
        return _with_checkpoint(row, latest)

    def _mismatch(
        self, run: RunRecord, latest: Any, restore: Mapping[str, Any]
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
            seq=int(latest.seq),
            checkpoint_id=str(latest.checkpoint_id),
            loop_state=_mapping(latest.loop_state_json),
            restore_state=dict(restore),
        )


def _with_checkpoint(row: Any, latest: Any) -> RunRecord:
    latest_id = None if latest is None else str(latest.checkpoint_id)
    latest_seq = 0 if latest is None else int(latest.seq)
    return _record(row, latest_id=latest_id, latest_seq=latest_seq)
