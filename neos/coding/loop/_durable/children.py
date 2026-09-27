"""Live child-run bookkeeping: which child to step, and how refs are kept.

Pure functions over `AgentLoopState`. The loop has two ways to name its live
children -- `active_children` and, from before K3, the `active_child_*`
scalars -- and every reader here goes through `_live_children` so an old
checkpoint with only the scalars still reads as one live child.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from neos.coding.model.base import ToolCallCompleted
from neos.coding.loop._durable.state import (
    ActiveChildRef,
    AgentLoopState,
    DelegatedSpawn,
    SpawnWork,
)
from neos.coding.loop._durable.transcript import _tool_result_ids

#: Unknown last-advance, not age 0. See `_stamp_is_stale`.
_EPOCH_STAMP = "1970-01-01T00:00:00+00:00"
_STALE_SLACK_SEC = 30.0


def _subagent_max_active(config) -> int:
    return min(4, max(1, getattr(config, "subagent_max_active", 1)))


def _legacy_single(state) -> tuple[ActiveChildRef, ...]:
    run_id = getattr(state, "active_child_run_id", None)
    if not run_id:
        return ()
    tool_call_id = getattr(state, "active_child_tool_call_id", None) or ""
    return (
        ActiveChildRef(
            run_id=run_id,
            checkpoint_id=getattr(state, "active_child_checkpoint_id", None),
            tool_call_id=tool_call_id,
            last_advanced_at=_EPOCH_STAMP,
        ),
    )


def _live_children(state) -> tuple[ActiveChildRef, ...]:
    return state.active_children or _legacy_single(state)


def _detached_children(state) -> list[ActiveChildRef]:
    return [child for child in state.active_children if child.detached]


def _child_ref(state, tool_call_id: str) -> ActiveChildRef | None:
    for child in state.active_children:
        if child.tool_call_id == tool_call_id:
            return child
    return None


def _child_ref_by_run(state, run_id: str) -> ActiveChildRef | None:
    for child in _live_children(state):
        if child.run_id == run_id:
            return child
    return None


def _sync_active_children(
    state, children: tuple[ActiveChildRef, ...]
) -> AgentLoopState:
    """Set the list and re-mirror the legacy scalars from its head."""
    head = children[0] if children else None
    return replace(
        state,
        active_children=children,
        active_child_run_id=head.run_id if head else None,
        active_child_checkpoint_id=head.checkpoint_id if head else None,
        active_child_tool_call_id=head.tool_call_id if head else None,
    )


def _upsert_active_child(state, child: ActiveChildRef) -> AgentLoopState:
    children = list(_live_children(state))
    for index, existing in enumerate(children):
        if existing.tool_call_id == child.tool_call_id:
            children[index] = child
            break
    else:
        children.append(child)
    return _sync_active_children(state, tuple(children))


def _without_child(state, tool_call_id: str) -> AgentLoopState:
    return _sync_active_children(
        state,
        tuple(
            child
            for child in state.active_children
            if child.tool_call_id != tool_call_id
        ),
    )


def _drain_completed_prefix(state: AgentLoopState) -> AgentLoopState:
    done = _tool_result_ids(state.transcript)
    index = state.pending_tool_index
    while index < len(state.pending_tool_calls):
        if state.pending_tool_calls[index].tool_call_id not in done:
            break
        index += 1
    if index == state.pending_tool_index:
        return state
    return replace(state, pending_tool_index=index)


def _is_pending_head(state: AgentLoopState, tool_call_id: str) -> bool:
    """Whether a result for `tool_call_id` should advance `pending_tool_index`.

    Spawn resumes can deliver a result for a call that is not at the head,
    and advancing then would skip the head without an answer.
    """
    return (
        state.has_pending_tool
        and state.pending_tool_calls[state.pending_tool_index].tool_call_id
        == tool_call_id
    )


def _unrolled_child_usage(
    child: ActiveChildRef | None, input_tokens: int, output_tokens: int
) -> tuple[int, int, int, int]:
    """Usage not yet charged to the parent, and the new rolled totals."""
    rolled_in = child.rolled_input_tokens if child is not None else 0
    rolled_out = child.rolled_output_tokens if child is not None else 0
    in_delta = max(0, int(input_tokens or 0) - rolled_in)
    out_delta = max(0, int(output_tokens or 0) - rolled_out)
    return in_delta, out_delta, rolled_in + in_delta, rolled_out + out_delta


def _parked_child_ref(
    existing: ActiveChildRef | None,
    parked: DelegatedSpawn,
    *,
    tool_call_id: str,
    stamp: str,
    rolled_in: int,
    rolled_out: int,
) -> ActiveChildRef:
    """The ref after a park: what the step reported, else what we had."""

    def keep(new, old_attr: str, default):
        if new:
            return new
        return getattr(existing, old_attr) if existing else default

    return ActiveChildRef(
        run_id=parked.run_id,
        checkpoint_id=parked.checkpoint_id,
        tool_call_id=tool_call_id,
        last_advanced_at=stamp,
        rolled_input_tokens=rolled_in,
        rolled_output_tokens=rolled_out,
        pending_steer=existing.pending_steer if existing else "",
        spec=keep(parked.spec, "spec", "explore"),
        spawn_depth=keep(parked.spawn_depth, "spawn_depth", 0),
        worktree_repo=keep(parked.worktree_repo, "worktree_repo", ""),
        worktree_path=keep(parked.worktree_path, "worktree_path", ""),
        worktree_branch=keep(parked.worktree_branch, "worktree_branch", ""),
        worktree_base_sha=keep(parked.worktree_base_sha, "worktree_base_sha", ""),
        # park 이 자식의 배달 방식을 바꾸지는 않는다.
        delivery=existing.delivery if existing else "tool_result",
    )


def _spawn_window(state) -> tuple[ToolCallCompleted, ...]:
    window: list[ToolCallCompleted] = []
    for call in state.pending_tool_calls[state.pending_tool_index :]:
        if call.name != "spawn_agent.v1":
            break
        window.append(call)
    return tuple(window)


def _pending_by_id(state, tool_call_id: str) -> ToolCallCompleted | None:
    for call in state.pending_tool_calls:
        if call.tool_call_id == tool_call_id:
            return call
    return None


def _select_spawn_work(state, *, max_active: int) -> SpawnWork | None:
    window = _spawn_window(state)
    live = list(_live_children(state))
    live_ids = {child.tool_call_id for child in live}
    # Detached children (K3) have no pending call to resume through -- the
    # parent's safe point advances them. They still count against `max_active`,
    # which is a cap on live children, not on parked ones.
    parked = [child for child in live if not child.detached]
    done = _tool_result_ids(state.transcript)
    unstarted = [
        call
        for call in window
        if call.tool_call_id not in live_ids and call.tool_call_id not in done
    ]
    if len(live) < max_active and unstarted:
        return SpawnWork(kind="start", call=unstarted[0], child=None)
    if parked:
        picked = min(
            parked, key=lambda child: (child.last_advanced_at, child.tool_call_id)
        )
        call = _pending_by_id(state, picked.tool_call_id)
        return SpawnWork(kind="resume", call=call, child=picked)
    return None


def _parse_utc_stamp(stamp: str) -> datetime | None:
    text = (stamp or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _stamp_is_stale(stamp: str, now: datetime, stale_after_sec: float) -> bool:
    # Epoch is unknown last-advance, not age 0.
    if stamp == _EPOCH_STAMP:
        return False
    parsed = _parse_utc_stamp(stamp)
    if parsed is None:
        return False
    age = (now.astimezone(UTC) - parsed).total_seconds()
    return age >= stale_after_sec
