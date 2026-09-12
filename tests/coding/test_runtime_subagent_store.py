from __future__ import annotations

import pytest

from neos.coding.runtime import (
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


def test_flag_off_after_factory_fallback_uses_postgres_store() -> None:
    runtime = _runtime(
        session_factory=_resolve_coding_session_factory(None),
        enabled=False,
    )
    assert isinstance(runtime._store, PostgresSubagentStore)
    factory = runtime._store._session_factory
    assert factory.__self__ is db_manager
    assert factory.__func__ is type(db_manager).get_session
