"""Q2: the user rule store -- one contract over memory and Postgres (real DB).

conftest deletes `test%@%` users before and after; their rules go with them
(ON DELETE CASCADE).
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from neos.coding.application.user_rules import (
    InMemoryUserRuleStore,
    PostgresUserRuleStore,
    UserRuleConflict,
    UserRuleLimit,
    build_user_rule_source,
)
from neos.coding.domain.approvals import UserRuleEffect
from neos.database.connection import db_manager

ALICE = "test_user_rules_alice"
BOB = "test_user_rules_bob"


async def _seed_users() -> None:
    async with await db_manager.get_session() as session:
        for user_id in (ALICE, BOB):
            await session.execute(
                text("INSERT INTO users (user_id, email) VALUES (:u, :e) ON CONFLICT DO NOTHING"),
                {"u": user_id, "e": f"{user_id}@example.com"},
            )
        await session.commit()


@pytest.fixture(params=["memory", "postgres"])
async def store(request):
    if request.param == "memory":
        return InMemoryUserRuleStore(max_rules=3)
    await _seed_users()
    return PostgresUserRuleStore(db_manager.get_session, max_rules=3)


@pytest.mark.asyncio
async def test_rules_are_the_users_own_in_creation_order(store) -> None:
    first = await store.create(ALICE, effect="block", tool="execute.v1", argv_prefix=["git", "push"])
    second = await store.create(ALICE, effect="allow", tool="write_file.v1")
    await store.create(BOB, effect="require", tool="execute.v1")

    mine = await store.list_for_user(ALICE)

    assert [r.rule_id for r in mine] == [first.rule_id, second.rule_id]
    assert mine[0].effect is UserRuleEffect.BLOCK
    assert mine[0].argv_prefix == ("git", "push")
    assert mine[1].argv_prefix == ()
    assert first.rule_id.startswith("ur_")


@pytest.mark.asyncio
async def test_only_the_owner_deletes(store) -> None:
    rule = await store.create(ALICE, effect="block", tool="execute.v1")

    assert await store.delete(BOB, rule.rule_id) is False
    assert await store.delete(ALICE, rule.rule_id) is True
    assert await store.delete(ALICE, rule.rule_id) is False
    assert await store.list_for_user(ALICE) == []


@pytest.mark.asyncio
async def test_the_same_rule_twice_is_a_conflict_but_another_effect_is_not(store) -> None:
    await store.create(ALICE, effect="block", tool="execute.v1", argv_prefix=["git"])

    with pytest.raises(UserRuleConflict):
        await store.create(ALICE, effect="block", tool="execute.v1", argv_prefix=["git"])
    await store.create(ALICE, effect="allow", tool="execute.v1", argv_prefix=["git"])
    await store.create(BOB, effect="block", tool="execute.v1", argv_prefix=["git"])


@pytest.mark.asyncio
async def test_the_limit_is_per_user(store) -> None:
    for tool in ("a.v1", "b.v1", "c.v1"):
        await store.create(ALICE, effect="block", tool=tool)

    with pytest.raises(UserRuleLimit):
        await store.create(ALICE, effect="block", tool="d.v1")
    await store.create(BOB, effect="block", tool="d.v1")
    assert len(await store.list_for_user(ALICE)) == 3


@pytest.mark.asyncio
async def test_malformed_rules_never_reach_the_table(store) -> None:
    with pytest.raises(ValueError):
        await store.create(ALICE, effect="block", tool="write_file.v1", argv_prefix=["x"])
    assert await store.list_for_user(ALICE) == []


@pytest.mark.asyncio
async def test_deleting_the_user_deletes_the_rules() -> None:
    await _seed_users()
    store = PostgresUserRuleStore(db_manager.get_session)
    await store.create(ALICE, effect="block", tool="execute.v1")

    async with await db_manager.get_session() as session:
        await session.execute(text("DELETE FROM users WHERE user_id = :u"), {"u": ALICE})
        await session.commit()

    assert await store.list_for_user(ALICE) == []


def test_off_builds_no_source() -> None:
    from neos.config.schema import CodingModelConfig

    assert CodingModelConfig().approval_user_rules is False
    assert build_user_rule_source(CodingModelConfig(), lambda: None) is None
    on = CodingModelConfig(approval_user_rules=True, approval_user_rules_max=7)
    built = build_user_rule_source(on, lambda: None)
    assert isinstance(built, PostgresUserRuleStore)
    assert built._max == 7
