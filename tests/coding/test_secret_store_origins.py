"""Q14b: browser origins in the Postgres vault -- migration 081, the same contract as
memory, and the binding sealed into the AAD.

conftest deletes `test%@%` users before and after; their secrets go with them.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text

from neos.coding.managed.crypto import ProviderReferenceCipherError
from neos.coding.secrets import PostgresSecretStore, _cipher, derive_secret_key
from neos.database.connection import db_manager
from tests.coding.test_agent_browser_origins import LOGIN, TOKEN, origin_contract

ALICE = "test_q14b_origins_alice"
BOB = "test_q14b_origins_bob"
KEY = derive_secret_key("q" * 32)
MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "db"
    / "migrations"
    / "081_add_user_secret_browser_origins.sql"
)


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
    return PostgresSecretStore(db_manager.get_session, key=KEY)


@pytest.mark.asyncio
async def test_the_migration_applies_twice_and_old_rows_are_unbound() -> None:
    """X1 fail closed + 077 compatibility. In one rolled-back transaction: drop the
    column, keep a 077-shape row, apply 081 twice. The row reads back unbound and its
    ciphertext opens with the unchanged 077 AAD. Mutation: `DEFAULT '{...}'` naming an
    origin (or no NOT NULL) -> old rows come back bound / NULL."""
    await _seed_users()
    sealed = _cipher(KEY, ALICE, "legacy").encrypt(TOKEN)
    sql = MIGRATION.read_text(encoding="utf-8")
    async with db_manager.engine.connect() as conn:
        raw = (await conn.get_raw_connection()).driver_connection
        transaction = raw.transaction()
        await transaction.start()
        try:
            await raw.execute("ALTER TABLE user_secrets DROP COLUMN IF EXISTS browser_origins")
            await raw.execute(
                "INSERT INTO user_secrets (user_id, name, env_name, ciphertext) "
                "VALUES ($1, 'legacy', 'LEGACY_TOKEN', $2)",
                ALICE,
                sealed,
            )
            await raw.execute(sql)
            await raw.execute(sql)
            row = await raw.fetchrow(
                "SELECT browser_origins, ciphertext FROM user_secrets "
                "WHERE user_id = $1 AND name = 'legacy'",
                ALICE,
            )
            column = await raw.fetchrow(
                "SELECT is_nullable, column_default, data_type FROM information_schema.columns "
                "WHERE table_name = 'user_secrets' AND column_name = 'browser_origins'"
            )
            checks = await raw.fetch(
                "SELECT pg_get_constraintdef(oid) AS def FROM pg_constraint "
                "WHERE conrelid = 'user_secrets'::regclass AND contype = 'c' "
                "AND pg_get_constraintdef(oid) LIKE '%browser_origins%'"
            )
        finally:
            await transaction.rollback()

    assert list(row["browser_origins"]) == []
    assert _cipher(KEY, ALICE, "legacy").decrypt(bytes(row["ciphertext"])) == TOKEN
    assert (column["is_nullable"], column["data_type"]) == ("NO", "ARRAY")
    assert column["column_default"].startswith("'{}'")
    assert [c["def"] for c in checks] == ["CHECK ((cardinality(browser_origins) <= 8))"]


@pytest.mark.asyncio
async def test_the_postgres_vault_keeps_the_origin_contract(store) -> None:
    """Same contract as memory (`origin_contract`), including cross-owner isolation.
    Mutation: drop `user_id = :user_id` from `resolve` -> bob's lookup reads alice's row."""
    await origin_contract(store, ALICE, BOB)


@pytest.mark.asyncio
async def test_widening_the_origins_without_the_key_does_not_open(store) -> None:
    """X3: the binding is in the AAD. Someone who can write the table but has no key
    cannot add their own origin to a secret. Mutation: leave origins out of `_cipher`'s
    AAD -> the tampered row resolves with the attacker's origin."""
    await store.put(ALICE, "site", env_name="SITE_PASSWORD", value=TOKEN, browser_origins=[LOGIN])
    async with await db_manager.get_session() as session:
        await session.execute(
            text(
                "UPDATE user_secrets SET browser_origins = ARRAY[:a, :b]::text[] "
                "WHERE user_id = :u AND name = 'site'"
            ),
            {"a": "https://evil.example.com", "b": LOGIN, "u": ALICE},
        )
        await session.commit()

    with pytest.raises(ProviderReferenceCipherError):
        await store.resolve(ALICE, ["site"])


@pytest.mark.asyncio
async def test_the_table_refuses_more_than_eight_origins(store) -> None:
    await store.put(ALICE, "site", env_name="SITE_PASSWORD", value=TOKEN)
    nine = [f"https://h{i}.example.com" for i in range(9)]
    with pytest.raises(Exception, match="check"):
        async with await db_manager.get_session() as session:
            await session.execute(
                text("UPDATE user_secrets SET browser_origins = :o WHERE user_id = :u"),
                {"o": nine, "u": ALICE},
            )
            await session.commit()
