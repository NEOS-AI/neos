"""Q6: the Postgres vault -- same contract as memory, and the row holds no plaintext.

conftest deletes `test%@%` users before and after; their secrets go with them
(ON DELETE CASCADE).
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from neos.coding.managed.crypto import ProviderReferenceCipherError
from neos.coding.secrets import (
    PostgresSecretStore,
    SecretLimit,
    SecretNotFound,
    build_secret_source,
    derive_secret_key,
)
from neos.database.connection import db_manager

ALICE = "test_secret_store_alice"
BOB = "test_secret_store_bob"
TOKEN = "ghp_live_0123456789abcdefghij"
KEY = derive_secret_key("m" * 32)


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
    return PostgresSecretStore(db_manager.get_session, key=KEY, max_secrets=2)


@pytest.mark.asyncio
async def test_put_list_resolve_delete(store) -> None:
    created = await store.put(ALICE, "github", env_name="GH_TOKEN", value=TOKEN)
    replaced = await store.put(ALICE, "github", env_name="GH_TOKEN", value=TOKEN + "2")

    [listed] = await store.list_for_user(ALICE)
    resolved = await store.resolve(ALICE, ["github"])

    assert (listed.name, listed.env_name) == ("github", "GH_TOKEN")
    assert replaced.created_at == created.created_at
    assert replaced.updated_at >= created.updated_at
    assert resolved.values["github"].value == TOKEN + "2"
    assert await store.list_for_user(BOB) == []
    with pytest.raises(SecretNotFound):
        await store.resolve(BOB, ["github"])
    assert await store.delete(BOB, "github") is False
    assert await store.delete(ALICE, "github") is True
    with pytest.raises(SecretNotFound):
        await store.resolve(ALICE, ["github"])


@pytest.mark.asyncio
async def test_the_limit_counts_names_not_writes(store) -> None:
    await store.put(ALICE, "a1", env_name="A_TOKEN", value=TOKEN)
    await store.put(ALICE, "a2", env_name="B_TOKEN", value=TOKEN)
    await store.put(ALICE, "a2", env_name="B_TOKEN", value=TOKEN + "x")

    with pytest.raises(SecretLimit):
        await store.put(ALICE, "a3", env_name="C_TOKEN", value=TOKEN)


@pytest.mark.asyncio
async def test_the_row_is_sealed_and_bound_to_its_owner(store) -> None:
    """S5: no plaintext in the table, and a row moved to another user will not open."""
    await store.put(ALICE, "github", env_name="GH_TOKEN", value=TOKEN)
    async with await db_manager.get_session() as session:
        raw = (
            await session.execute(
                text("SELECT ciphertext FROM user_secrets WHERE user_id = :u"), {"u": ALICE}
            )
        ).scalar_one()
        assert TOKEN.encode() not in bytes(raw)
        await session.execute(
            text(
                "INSERT INTO user_secrets (user_id, name, env_name, ciphertext) "
                "VALUES (:u, 'github', 'GH_TOKEN', :c)"
            ),
            {"u": BOB, "c": bytes(raw)},
        )
        await session.commit()

    with pytest.raises(ProviderReferenceCipherError):
        await store.resolve(BOB, ["github"])
    other_key = PostgresSecretStore(db_manager.get_session, key=derive_secret_key("n" * 32))
    with pytest.raises(ProviderReferenceCipherError):
        await other_key.resolve(ALICE, ["github"])


def test_the_source_is_off_unless_the_flag_is_on() -> None:
    from types import SimpleNamespace

    off = SimpleNamespace(secret_broker=False, secret_broker_max=50)
    on = SimpleNamespace(secret_broker=True, secret_broker_max=50)
    keys = SimpleNamespace(secret_broker_key="m" * 32)

    assert build_secret_source(off, keys, db_manager.get_session) is None
    assert isinstance(build_secret_source(on, keys, db_manager.get_session), PostgresSecretStore)
    with pytest.raises(ValueError):
        build_secret_source(on, SimpleNamespace(secret_broker_key=None), db_manager.get_session)
