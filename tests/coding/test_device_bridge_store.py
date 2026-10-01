"""Q16a: pairing credentials in Postgres -- same contract as memory, only a hash stored.

conftest deletes `test%@%` users before and after; their bridges go with them
(ON DELETE CASCADE, migration 080).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text

from neos.coding.bridge.credentials import (
    BridgeLimit,
    BridgeNameTaken,
    PostgresBridgeCredentialStore,
    token_hash,
)
from neos.database.connection import db_manager

ALICE = "test_device_bridge_alice"
BOB = "test_device_bridge_bob"
MIGRATION = Path(__file__).resolve().parents[2] / "db" / "migrations" / "080_add_device_bridges.sql"


async def _seed_users() -> None:
    async with await db_manager.get_session() as session:
        for user_id in (ALICE, BOB):
            await session.execute(
                text("INSERT INTO users (user_id, email) VALUES (:u, :e) ON CONFLICT DO NOTHING"),
                {"u": user_id, "e": f"{user_id}@example.com"},
            )
        await session.commit()


@pytest.fixture
async def store():
    await _seed_users()
    return PostgresBridgeCredentialStore(db_manager.get_session, max_bridges=2)


@pytest.mark.asyncio
async def test_the_migration_applies_twice() -> None:
    from tests.conftest import _run_sql_file

    await _run_sql_file(MIGRATION)
    await _run_sql_file(MIGRATION)
    async with await db_manager.get_session() as session:
        rule = await session.execute(
            text(
                "SELECT rc.delete_rule FROM information_schema.referential_constraints rc "
                "JOIN information_schema.table_constraints tc "
                "  ON tc.constraint_name = rc.constraint_name "
                "WHERE tc.table_name = 'device_bridges'"
            )
        )
        assert [row.delete_rule for row in rule] == ["CASCADE"]


@pytest.mark.asyncio
async def test_create_authenticate_update_delete(store) -> None:
    info, token = await store.create(ALICE, "laptop")

    authed = await store.authenticate(token)
    [listed] = await store.list_for_user(ALICE)
    flipped = await store.set_unattended(ALICE, info.bridge_id, True)

    assert authed is not None and authed.user_id == ALICE and authed.last_connected_at is not None
    assert listed.bridge_id == info.bridge_id and listed.allow_unattended is False
    assert flipped is not None and flipped.allow_unattended is True
    assert await store.authenticate(token[:-1] + ("A" if token[-1] != "A" else "B")) is None
    assert await store.get(BOB, info.bridge_id) is None
    assert await store.set_unattended(BOB, info.bridge_id, False) is None
    assert await store.delete(BOB, info.bridge_id) is False
    assert await store.delete(ALICE, info.bridge_id) is True
    assert await store.authenticate(token) is None  # revoked is gone


@pytest.mark.asyncio
async def test_the_row_holds_only_the_hash(store) -> None:
    info, token = await store.create(ALICE, "desk")
    async with await db_manager.get_session() as session:
        row = (
            await session.execute(
                text("SELECT * FROM device_bridges WHERE bridge_id = :b"), {"b": info.bridge_id}
            )
        ).one()
    assert token not in repr(tuple(row))
    assert row.token_hash == token_hash(token)


@pytest.mark.asyncio
async def test_limits_and_names_are_per_user(store) -> None:
    await store.create(ALICE, "one")
    with pytest.raises(BridgeNameTaken):
        await store.create(ALICE, "one")
    await store.create(ALICE, "two")
    with pytest.raises(BridgeLimit):
        await store.create(ALICE, "three")
    await store.create(BOB, "one")  # same name, other user


@pytest.mark.asyncio
async def test_deleting_the_user_deletes_their_bridges(store) -> None:
    _info, token = await store.create(ALICE, "gone")
    async with await db_manager.get_session() as session:
        await session.execute(text("DELETE FROM users WHERE user_id = :u"), {"u": ALICE})
        await session.commit()
    assert await store.authenticate(token) is None
