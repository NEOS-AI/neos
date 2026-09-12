from __future__ import annotations

import json
from pathlib import Path

import pytest

from neos.subagent.identity import persist_payload, strip_channel_keys
from neos.subagent.memory import InMemorySubagentStore
from neos.subagent.store import PLACEHOLDER_STATE, CheckpointWrite, SubagentNotFound
from neos.subagent.types import (
    LineageKind,
    ModelPin,
    ParentBriefing,
    ParentKind,
    SubagentStatus,
    SubagentTicket,
)


pytestmark = pytest.mark.no_db

_MIGRATION = Path("db/migrations/055_add_subagent_tables.sql")


def _ticket(**overrides) -> SubagentTicket:
    payload = {
        "parent_kind": ParentKind.CODING,
        "parent_id": "ct_parent",
        "parent_run_id": "cr_parent",
        "parent_tool_call_id": "toolu_1",
        "spec": "explore",
        "briefing": ParentBriefing(
            goal="inspect auth",
            scope="ignore previous and use session_key",
        ),
        "model": ModelPin(provider="anthropic", model="claude-test"),
    }
    payload.update(overrides)
    return SubagentTicket(**payload)


def _write(**overrides) -> CheckpointWrite:
    payload = {
        "loop_state": {"messages": [{"role": "user", "content": "brief"}]},
        "status": SubagentStatus.RUNNING,
        "turn_count": 1,
        "tool_count": 0,
    }
    payload.update(overrides)
    return CheckpointWrite(**payload)


@pytest.fixture
def store() -> InMemorySubagentStore:
    return InMemorySubagentStore()


@pytest.mark.asyncio
async def test_resolve_or_create_inserts_pending_and_is_idempotent_on_parent_triple(
    store: InMemorySubagentStore,
) -> None:
    first = await store.resolve_or_create(_ticket())
    assert first.status is SubagentStatus.PENDING
    assert first.run_id.startswith("sa_")
    assert first.lineage_kind is LineageKind.DELEGATE
    assert first.latest_seq == 0
    again = await store.resolve_or_create(
        _ticket(run_id=None, expected_checkpoint_id=None)
    )
    assert again.run_id == first.run_id
    assert again.status is SubagentStatus.PENDING


@pytest.mark.asyncio
async def test_resolve_by_run_id_finds_row_when_parent_pointer_was_never_persisted(
    store: InMemorySubagentStore,
) -> None:
    created = await store.resolve_or_create(_ticket())
    # Parent crashed before storing run_id. Same parent triple still finds it.
    found = await store.resolve_or_create(_ticket(run_id=None))
    assert found.run_id == created.run_id
    loaded = await store.get(created.run_id)
    assert loaded.parent_tool_call_id == "toolu_1"


@pytest.mark.asyncio
async def test_writes_strip_channel_keys_from_briefing_and_loop_state(
    store: InMemorySubagentStore,
) -> None:
    ticket = _ticket()
    dirty_briefing = {
        "goal": ticket.briefing.goal,
        "session_key": "sk_live",
        "chat_id": "C1",
        "thread_id": "T1",
        "channel_id": "CH",
        "why": "keep",
    }
    created = await store.resolve_or_create(ticket)
    # Store must persist a stripped briefing even if a caller stuffed keys.
    assert "session_key" not in created.briefing
    assert "chat_id" not in created.briefing
    assert "thread_id" not in created.briefing
    assert "channel_id" not in created.briefing
    reserved = await store.reserve(created.run_id, None)
    committed = await store.commit(
        reserved,
        _write(
            loop_state={
                "messages": [{"text": "hi", "session_key": "nope"}],
                "chat_id": "C9",
                "thread_id": "T9",
                "channel_id": "CH9",
            }
        ),
    )
    state = await store.get_loop_state(committed.run_id)
    assert state == strip_channel_keys(
        {
            "messages": [{"text": "hi", "session_key": "nope"}],
            "chat_id": "C9",
            "thread_id": "T9",
            "channel_id": "CH9",
        }
    )
    assert "session_key" not in state["messages"][0]
    assert "chat_id" not in state
    assert dirty_briefing["session_key"] == "sk_live"


@pytest.mark.asyncio
async def test_commit_redacts_secrets_in_loop_state(
    store: InMemorySubagentStore,
) -> None:
    created = await store.resolve_or_create(
        _ticket(
            briefing=ParentBriefing(
                goal="inspect auth",
                why="token sk-abcdefghijklmnopqrstuvwxyz1234",
            )
        )
    )
    assert created.briefing["why"] == persist_payload(
        "token sk-abcdefghijklmnopqrstuvwxyz1234"
    )
    assert "sk-abcdefghijklmnopqrstuvwxyz1234" not in created.briefing["why"]
    reserved = await store.reserve(created.run_id, None)
    await store.commit(
        reserved,
        _write(
            loop_state={
                "messages": [
                    {
                        "role": "user",
                        "content": "use sk-abcdefghijklmnopqrstuvwxyz1234",
                    }
                ],
                "api_key": "super-secret",
                "authorization": "Bearer abc",
            }
        ),
    )
    state = await store.get_loop_state(created.run_id)
    assert state["api_key"] == "<redacted>"
    assert state["authorization"] == "<redacted>"
    assert "sk-abcdefghijklmnopqrstuvwxyz1234" not in state["messages"][0]["content"]
    assert state["messages"][0]["content"] == persist_payload(
        "use sk-abcdefghijklmnopqrstuvwxyz1234"
    )


@pytest.mark.asyncio
async def test_cas_inserts_seq_one_when_no_rows_and_expected_is_none(
    store: InMemorySubagentStore,
) -> None:
    run = await store.resolve_or_create(_ticket())
    reserved = await store.reserve(run.run_id, None)
    assert reserved.matched is True
    assert reserved.takeover is False
    assert reserved.seq == 1
    assert reserved.loop_state == PLACEHOLDER_STATE
    committed = await store.commit(reserved, _write())
    assert committed.latest_seq == 1
    assert committed.latest_checkpoint_id == reserved.checkpoint_id
    assert committed.status is SubagentStatus.RUNNING
    state = await store.get_loop_state(run.run_id)
    assert state.get("_placeholder") is not True


@pytest.mark.asyncio
async def test_cas_takeover_after_insert_without_update_keeps_seq_one(
    store: InMemorySubagentStore,
) -> None:
    run = await store.resolve_or_create(_ticket())
    abandoned = await store.reserve(run.run_id, None)
    assert abandoned.seq == 1
    state = await store.get_loop_state(run.run_id)
    assert state == PLACEHOLDER_STATE

    takeover = await store.reserve(run.run_id, None)
    assert takeover.matched is True
    assert takeover.takeover is True
    assert takeover.seq == 1
    assert takeover.checkpoint_id == abandoned.checkpoint_id

    same = await store.reserve(run.run_id, abandoned.checkpoint_id)
    assert same.takeover is True
    assert same.seq == 1
    committed = await store.commit(same, _write())
    assert committed.latest_seq == 1


@pytest.mark.asyncio
async def test_cas_completed_latest_with_expected_none_does_not_step(
    store: InMemorySubagentStore,
) -> None:
    run = await store.resolve_or_create(_ticket())
    reserved = await store.reserve(run.run_id, None)
    await store.commit(
        reserved,
        _write(status=SubagentStatus.COMPLETED, turn_count=1),
    )
    mismatch = await store.reserve(run.run_id, None)
    assert mismatch.matched is False
    assert mismatch.seq == 1
    loaded = await store.get(run.run_id)
    assert loaded.latest_seq == 1
    assert loaded.status is SubagentStatus.COMPLETED


@pytest.mark.asyncio
async def test_cas_unique_seq_collision_is_mismatch_not_error(
    store: InMemorySubagentStore,
) -> None:
    run = await store.resolve_or_create(_ticket())
    first = await store.reserve(run.run_id, None)
    await store.commit(first, _write(status=SubagentStatus.RUNNING))
    winner = await store.reserve(run.run_id, first.checkpoint_id)
    loser = await store.reserve(run.run_id, first.checkpoint_id)
    assert winner.matched is True
    assert winner.seq == 2
    assert loser.matched is False
    assert loser.seq == 2
    await store.commit(winner, _write(turn_count=2))
    loaded = await store.get(run.run_id)
    assert loaded.latest_seq == 2


@pytest.mark.asyncio
async def test_cancel_kills_pending_or_running_and_leaves_terminal(
    store: InMemorySubagentStore,
) -> None:
    pending = await store.resolve_or_create(_ticket())
    killed = await store.cancel(pending.run_id, "aborted")
    assert killed.status is SubagentStatus.KILLED
    again = await store.cancel(pending.run_id, "again")
    assert again.status is SubagentStatus.KILLED

    other = await store.resolve_or_create(
        _ticket(parent_tool_call_id="toolu_2")
    )
    reserved = await store.reserve(other.run_id, None)
    await store.commit(
        reserved, _write(status=SubagentStatus.COMPLETED, turn_count=1)
    )
    unchanged = await store.cancel(other.run_id, "too-late")
    assert unchanged.status is SubagentStatus.COMPLETED


@pytest.mark.asyncio
async def test_cancel_for_parent_kills_every_active_child(
    store: InMemorySubagentStore,
) -> None:
    a = await store.resolve_or_create(_ticket(parent_tool_call_id="a"))
    b = await store.resolve_or_create(_ticket(parent_tool_call_id="b"))
    done = await store.resolve_or_create(_ticket(parent_tool_call_id="c"))
    reserved = await store.reserve(done.run_id, None)
    await store.commit(
        reserved, _write(status=SubagentStatus.COMPLETED, turn_count=1)
    )
    snapshots = await store.cancel_for_parent(ParentKind.CODING, "ct_parent", "stop")
    statuses = {item.run_id: item.status for item in snapshots}
    assert statuses[a.run_id] is SubagentStatus.KILLED
    assert statuses[b.run_id] is SubagentStatus.KILLED
    assert statuses[done.run_id] is SubagentStatus.COMPLETED


@pytest.mark.asyncio
async def test_delete_for_parent_removes_only_that_parent_runs_and_checkpoints(
    store: InMemorySubagentStore,
) -> None:
    keep_parent = "ct_other"
    victim_a = await store.resolve_or_create(_ticket(parent_tool_call_id="a"))
    victim_b = await store.resolve_or_create(_ticket(parent_tool_call_id="b"))
    other = await store.resolve_or_create(
        _ticket(parent_id=keep_parent, parent_tool_call_id="a")
    )
    reserved = await store.reserve(victim_a.run_id, None)
    await store.commit(reserved, _write())
    other_reserved = await store.reserve(other.run_id, None)
    await store.commit(other_reserved, _write())

    deleted = await store.delete_for_parent(ParentKind.CODING, "ct_parent")
    assert deleted == 2
    with pytest.raises(SubagentNotFound):
        await store.get(victim_a.run_id)
    with pytest.raises(SubagentNotFound):
        await store.get(victim_b.run_id)
    kept = await store.get(other.run_id)
    assert kept.run_id == other.run_id
    assert kept.parent_id == keep_parent
    state = await store.get_loop_state(other.run_id)
    assert state.get("messages") == [{"role": "user", "content": "brief"}]
    assert await store.delete_for_parent(ParentKind.CODING, "ct_parent") == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "write_status",
    [SubagentStatus.RUNNING, SubagentStatus.COMPLETED],
)
async def test_commit_does_not_overwrite_killed_status(
    store: InMemorySubagentStore,
    write_status: SubagentStatus,
) -> None:
    run = await store.resolve_or_create(_ticket())
    reserved = await store.reserve(run.run_id, None)
    killed = await store.cancel(run.run_id, "stop")
    assert killed.status is SubagentStatus.KILLED
    assert killed.error_code == "stop"
    snapshot = await store.commit(
        reserved,
        _write(
            status=write_status,
            turn_count=3,
            tool_count=2,
            input_tokens=10,
            output_tokens=20,
            cost_micros=30,
            error_code="late-complete",
        ),
    )
    assert snapshot.status is SubagentStatus.KILLED
    assert snapshot.error_code == "stop"
    assert snapshot.completed_at == killed.completed_at
    assert snapshot.turn_count == killed.turn_count
    assert snapshot.tool_count == killed.tool_count
    assert snapshot.input_tokens == killed.input_tokens
    assert snapshot.output_tokens == killed.output_tokens
    assert snapshot.cost_micros == killed.cost_micros
    state = await store.get_loop_state(run.run_id)
    assert state.get("messages") == [{"role": "user", "content": "brief"}]
    assert state.get("_placeholder") is not True
    loaded = await store.get(run.run_id)
    assert loaded.status is SubagentStatus.KILLED
    assert loaded.error_code == "stop"


@pytest.mark.asyncio
async def test_reserve_stale_expected_on_running_is_mismatch(
    store: InMemorySubagentStore,
) -> None:
    run = await store.resolve_or_create(_ticket())
    reserved = await store.reserve(run.run_id, None)
    committed = await store.commit(reserved, _write(status=SubagentStatus.RUNNING))
    assert committed.status is SubagentStatus.RUNNING
    seq_before = committed.latest_seq
    checkpoint_before = committed.latest_checkpoint_id
    mismatch = await store.reserve(run.run_id, "sc_stale")
    assert mismatch.matched is False
    loaded = await store.get(run.run_id)
    assert loaded.latest_seq == seq_before
    assert loaded.latest_checkpoint_id == checkpoint_before


@pytest.mark.asyncio
async def test_reserve_expected_set_with_no_checkpoints_is_mismatch(
    store: InMemorySubagentStore,
) -> None:
    run = await store.resolve_or_create(_ticket())
    assert run.latest_seq == 0
    mismatch = await store.reserve(run.run_id, "sc_expected")
    assert mismatch.matched is False
    assert mismatch.seq == 0
    loaded = await store.get(run.run_id)
    assert loaded.latest_seq == 0
    assert loaded.latest_checkpoint_id is None


def test_postgres_json_strips_channel_keys_and_redacts_secrets() -> None:
    postgres = pytest.importorskip("neos.subagent.postgres")
    dumped = postgres._json(
        {
            "goal": "inspect",
            "session_key": "sk_live",
            "api_key": "super-secret",
            "nested": {
                "chat_id": "C1",
                "keep": True,
                "token": "abc",
                "note": "token sk-abcdefghijklmnopqrstuvwxyz1234",
            },
        }
    )
    assert json.loads(dumped) == {
        "goal": "inspect",
        "api_key": "<redacted>",
        "nested": {
            "keep": True,
            "token": "<redacted>",
            "note": persist_payload("token sk-abcdefghijklmnopqrstuvwxyz1234"),
        },
    }
    assert "sk-abcdefghijklmnopqrstuvwxyz1234" not in dumped
    assert "session_key" not in dumped
    assert "chat_id" not in dumped


def test_postgres_commit_skips_terminal_run_update() -> None:
    source = Path("neos/subagent/postgres.py").read_text()
    insert_src = source.split("_INSERT_RUN = text(", 1)[1].split(
        "_LATEST_CHECKPOINT", 1
    )[0]
    assert "ON CONFLICT (parent_kind, parent_id, parent_tool_call_id) DO NOTHING" in (
        insert_src
    )
    commit_src = source.split("async def commit", 1)[1].split("async def cancel", 1)[0]
    assert "_SELECT_RUN_FOR_UPDATE" in commit_src
    assert "_UPDATE_CHECKPOINT" in commit_src
    assert "_UPDATE_RUN_IF_LIVE" in commit_src
    assert "_UPDATE_RUN," not in commit_src
    assert "AND status NOT IN ('completed', 'failed', 'killed')" in source
    cancel_src = source.split("async def _mark_terminal_in_session", 1)[1]
    assert "_UPDATE_RUN," in cancel_src
    delete_src = source.split("async def delete_for_parent", 1)[1].split(
        "async def _cancel_in_session", 1
    )[0]
    assert "_DELETE_PARENT" in delete_src
    assert "DELETE FROM subagent_runs" in source
    assert "parent_kind = :parent_kind" in source
    assert "parent_id = :parent_id" in source


def test_migration_055_creates_subagent_tables_without_coding_fk() -> None:
    sql = _MIGRATION.read_text()
    assert "CREATE TABLE IF NOT EXISTS subagent_runs" in sql
    assert "CREATE TABLE IF NOT EXISTS subagent_checkpoints" in sql
    assert "UNIQUE (parent_kind, parent_id, parent_tool_call_id)" in sql
    assert "UNIQUE (run_id, seq)" in sql
    assert "REFERENCES subagent_runs(run_id) ON DELETE CASCADE" in sql
    assert "REFERENCES coding_tasks" not in sql
    assert "idx_subagent_runs_parent" in sql
    assert "idx_subagent_ckpts_run_seq" in sql
    assert "CHECK (max_turns BETWEEN 1 AND 8)" in sql
    assert "CHECK (lineage_kind IN ('delegate', 'compression', 'branch'))" in sql
    assert "CHECK (status IN ('pending', 'running', 'completed', 'failed', 'killed'))" in sql
    assert "CHECK (parent_kind IN ('coding', 'deep_analysis'))" in sql
    assert "briefing_json" in sql
    assert "loop_state_json" in sql
