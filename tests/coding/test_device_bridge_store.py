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


WRITES_MIGRATION = MIGRATION.with_name("083_add_device_bridge_writes.sql")


#: Not `test%@%` -- the shared test DB's cleanup of those users races with other suites;
#: this test owns these two rows and removes them itself.
WRITER, OTHER = "q16b_bridge_writer", "q16b_bridge_other"


@pytest.fixture
async def writer_store():
    async with await db_manager.get_session() as session:
        for user_id in (WRITER, OTHER):
            await session.execute(
                text("INSERT INTO users (user_id, email) VALUES (:u, :e) ON CONFLICT DO NOTHING"),
                {"u": user_id, "e": f"{user_id}@example.org"},
            )
        await session.commit()
    yield PostgresBridgeCredentialStore(db_manager.get_session, max_bridges=2)
    async with await db_manager.get_session() as session:
        await session.execute(
            text("DELETE FROM users WHERE user_id IN (:a, :b)"), {"a": WRITER, "b": OTHER}
        )
        await session.commit()


@pytest.mark.asyncio
async def test_the_writes_migration_applies_twice_and_defaults_off(writer_store) -> None:
    """Q16b, 083. A bridge made before 083 (or without the flag) cannot declare writes."""
    from tests.conftest import _run_sql_file

    store = writer_store

    await _run_sql_file(WRITES_MIGRATION)
    await _run_sql_file(WRITES_MIGRATION)
    async with await db_manager.get_session() as session:
        column = (
            await session.execute(
                text(
                    "SELECT is_nullable, column_default FROM information_schema.columns "
                    "WHERE table_name = 'device_bridges' AND column_name = 'allow_writes'"
                )
            )
        ).one()
    assert column.is_nullable == "NO" and column.column_default == "false"

    info, token = await store.create(WRITER, "writer")
    assert info.allow_writes is False
    flipped = await store.set_writes(WRITER, info.bridge_id, True)
    assert flipped is not None and flipped.allow_writes is True
    assert flipped.allow_unattended is False  # the two settings are separate
    assert (await store.authenticate(token)).allow_writes is True
    assert await store.set_writes(OTHER, info.bridge_id, False) is None
    made_on = (await store.create(WRITER, "both", allow_writes=True))[0]
    assert made_on.allow_writes is True


@pytest.mark.asyncio
async def test_deleting_the_user_deletes_their_bridges(store) -> None:
    _info, token = await store.create(ALICE, "gone")
    async with await db_manager.get_session() as session:
        await session.execute(text("DELETE FROM users WHERE user_id = :u"), {"u": ALICE})
        await session.commit()
    assert await store.authenticate(token) is None


COMMANDS_MIGRATION = MIGRATION.with_name("090_add_device_bridge_commands.sql")

#: Owned by this test (same reason as the Q16b pair). Emails do not start with `test` so the
#: shared `test%@%` cleanup of other suites never races these rows.
COMMANDER, STRANGER = "test_q16c_bridge_commander", "test_q16c_bridge_stranger"


@pytest.fixture
async def commander_store():
    async with await db_manager.get_session() as session:
        for user_id in (COMMANDER, STRANGER):
            await session.execute(
                text("INSERT INTO users (user_id, email) VALUES (:u, :e) ON CONFLICT DO NOTHING"),
                {"u": user_id, "e": f"q16c-{user_id[-9:]}@example.org"},
            )
        await session.commit()
    yield PostgresBridgeCredentialStore(db_manager.get_session, max_bridges=2)
    async with await db_manager.get_session() as session:
        await session.execute(
            text("DELETE FROM users WHERE user_id IN (:a, :b)"), {"a": COMMANDER, "b": STRANGER}
        )
        await session.commit()


@pytest.mark.asyncio
async def test_the_commands_migration_applies_twice_and_defaults_off(commander_store) -> None:
    """Q16c, 090. A bridge made before 090 (or without the flag) cannot declare commands, and
    the three settings are separate columns."""
    from tests.conftest import _run_sql_file

    store = commander_store

    await _run_sql_file(COMMANDS_MIGRATION)
    await _run_sql_file(COMMANDS_MIGRATION)
    async with await db_manager.get_session() as session:
        column = (
            await session.execute(
                text(
                    "SELECT is_nullable, column_default FROM information_schema.columns "
                    "WHERE table_name = 'device_bridges' AND column_name = 'allow_commands'"
                )
            )
        ).one()
    assert column.is_nullable == "NO" and column.column_default == "false"

    info, token = await store.create(COMMANDER, "commander")
    assert info.allow_commands is False
    flipped = await store.set_commands(COMMANDER, info.bridge_id, True)
    assert flipped is not None and flipped.allow_commands is True
    assert (flipped.allow_writes, flipped.allow_unattended) == (False, False)
    assert (await store.authenticate(token)).allow_commands is True
    assert await store.set_commands(STRANGER, info.bridge_id, False) is None
    made_on = (await store.create(COMMANDER, "both", allow_commands=True))[0]
    assert made_on.allow_commands is True and made_on.allow_writes is False
