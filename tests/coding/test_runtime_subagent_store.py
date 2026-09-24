from __future__ import annotations

import pytest

from neos.coding.runtime import (
    ParentSubagentEventAdapter,
    _build_subagent_runtime,
    _resolve_coding_session_factory,
)
from neos.database.connection import db_manager
from neos.subagent.memory import InMemorySubagentStore
from neos.subagent.postgres import PostgresSubagentStore


pytestmark = pytest.mark.no_db


async def fake_factory():
    raise AssertionError("session factory must not be opened")


def _runtime(*, session_factory, enabled: bool):
    return _build_subagent_runtime(
        model=object(),
        tools=object(),
        executor=object(),
        session_factory=session_factory,
        enabled=enabled,
    )


def test_flag_off_with_session_factory_uses_postgres_store() -> None:
    runtime = _runtime(session_factory=fake_factory, enabled=False)
    assert isinstance(runtime._store, PostgresSubagentStore)
    assert runtime._store._session_factory is fake_factory


def test_flag_off_without_session_factory_uses_in_memory_store() -> None:
    runtime = _runtime(session_factory=None, enabled=False)
    assert isinstance(runtime._store, InMemorySubagentStore)


def test_flag_on_with_session_factory_uses_postgres_store() -> None:
    runtime = _runtime(session_factory=fake_factory, enabled=True)
    assert isinstance(runtime._store, PostgresSubagentStore)
    assert runtime._store._session_factory is fake_factory


def test_real_loop_factory_fallback_is_db_manager() -> None:
    resolved = _resolve_coding_session_factory(None)
    assert resolved.__self__ is db_manager
    assert resolved.__func__ is type(db_manager).get_session
    assert _resolve_coding_session_factory(fake_factory) is fake_factory


class _RecordingParentSink:
    def __init__(self) -> None:
        self.items: list[dict] = []

    async def append(self, *, task_id, event_type, payload, **ids) -> None:
        self.items.append(
            {
                "task_id": task_id,
                "event_type": event_type,
                "payload": dict(payload),
                "ids": ids,
            }
        )


@pytest.mark.asyncio
async def test_parent_sink_adapter_forwards_allowlisted_payload_only() -> None:
    parent = _RecordingParentSink()
    adapter = ParentSubagentEventAdapter(parent)
    await adapter.emit(
        "subagent.started",
        {
            "run_id": "sa_1",
            "spec": "explore",
            "parent_kind": "coding",
            "parent_id": "ct_1",
            "parent_run_id": "cr_1",
            "parent_tool_call_id": "s1",
            "status": "pending",
            "turn_count": 0,
            "tool_count": 0,
            "brief": "secret brief",
            "transcript": [{"role": "user", "text": "leak"}],
            "body": "file body",
        },
    )
    await adapter.emit(
        "subagent.step",
        {
            "run_id": "sa_1",
            "spec": "explore",
            "parent_kind": "coding",
            "parent_id": "ct_1",
            "parent_tool_call_id": "s1",
            "step_kind": "continuing",
            "turn_count": 1,
            "tool_count": 2,
            "status": "running",
            "checkpoint_id": "sc_hidden",
        },
    )
    await adapter.emit("subagent.failed", {"run_id": "sa_1", "brief": "nope"})
    assert [item["event_type"] for item in parent.items] == [
        "subagent.started",
        "subagent.step",
    ]
    started = parent.items[0]
    assert started["task_id"] == "ct_1"
    assert started["ids"]["run_id"] == "cr_1"
    assert started["ids"]["tool_call_id"] == "s1"
    assert started["payload"] == {
        "run_id": "sa_1",
        "spec": "explore",
        "parent_kind": "coding",
        "parent_id": "ct_1",
        "parent_tool_call_id": "s1",
        "status": "pending",
        "turn_count": 0,
        "tool_count": 0,
    }
    assert "brief" not in started["payload"]
    assert "transcript" not in started["payload"]
    assert "body" not in started["payload"]
    step = parent.items[1]["payload"]
    assert step["step_kind"] == "continuing"
    assert "checkpoint_id" not in step


@pytest.mark.asyncio
async def test_parent_sink_adapter_forwards_terminal_child_events() -> None:
    """A stall or a cancel ends a child without a `subagent.step`.

    Before these two were forwarded, a detached child that stalled stayed
    "running" in the parent's ledger -- and so on screen -- forever.
    """
    parent = _RecordingParentSink()
    adapter = ParentSubagentEventAdapter(parent)
    common = {
        "spec": "explore",
        "parent_kind": "coding",
        "parent_id": "ct_1",
        "parent_run_id": "cr_1",
        "parent_tool_call_id": "s1",
        "turn_count": 3,
        "tool_count": 4,
    }
    await adapter.emit(
        "subagent.failed",
        {**common, "run_id": "sa_1", "status": "failed", "error_code": "stalled"},
    )
    await adapter.emit(
        "subagent.cancelled",
        {
            **common,
            "run_id": "sa_2",
            "status": "killed",
            "reason": "cancelled",
            "brief": "secret brief",
        },
    )
    assert [item["event_type"] for item in parent.items] == [
        "subagent.failed",
        "subagent.cancelled",
    ]
    failed, cancelled = (item["payload"] for item in parent.items)
    assert failed["error_code"] == "stalled"
    assert failed["status"] == "failed"
    assert cancelled["reason"] == "cancelled"
    assert "brief" not in cancelled
    assert parent.items[1]["task_id"] == "ct_1"
    assert parent.items[1]["ids"]["tool_call_id"] == "s1"


class _BoomParentSink:
    async def append(self, **kwargs) -> None:
        raise RuntimeError("sink down")


@pytest.mark.asyncio
async def test_parent_sink_adapter_swallows_append_failure() -> None:
    adapter = ParentSubagentEventAdapter(_BoomParentSink())
    await adapter.emit(
        "subagent.step",
        {
            "run_id": "sa_1",
            "spec": "explore",
            "parent_kind": "coding",
            "parent_id": "ct_1",
            "parent_run_id": "cr_1",
            "parent_tool_call_id": "s1",
            "step_kind": "continuing",
            "status": "running",
        },
    )


def test_build_runtime_wires_parent_sink_adapter() -> None:
    parent = _RecordingParentSink()
    runtime = _build_subagent_runtime(
        model=object(),
        tools=object(),
        executor=object(),
        session_factory=None,
        enabled=False,
        parent_events=parent,
    )
    inner = runtime._events
    assert inner._inner.__class__.__name__ == "ParentSubagentEventAdapter"
    assert inner._inner._parent is parent


def test_flag_off_after_factory_fallback_uses_postgres_store() -> None:
    runtime = _runtime(
        session_factory=_resolve_coding_session_factory(None),
        enabled=False,
    )
    assert isinstance(runtime._store, PostgresSubagentStore)
    factory = runtime._store._session_factory
    assert factory.__self__ is db_manager
    assert factory.__func__ is type(db_manager).get_session
