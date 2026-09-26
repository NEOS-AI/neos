"""실제 DB 로 쓰기가 커밋되는지 본다 (fetch_one 은 INSERT 를 커밋하지 않는다).

conftest 가 `<name>_test` DB 에 ORM + 마이그레이션(063 포함)을 세우고,
`test%@%` 사용자를 앞뒤로 지운다 -- 선호는 ON DELETE CASCADE 로 함께 간다.
"""

import pytest
from sqlalchemy import text

from neos.database.connection import db_manager
from neos.database.repositories.model_preference_repository import (
    ModelPreferenceRepository as Repo,
)

USER = "test_effort_user"
CONV = "test_effort_conv"


async def _seed() -> None:
    async with await db_manager.get_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (user_id, email) VALUES (:u, 'test_effort@example.com') "
                "ON CONFLICT DO NOTHING"
            ),
            {"u": USER},
        )
        await session.execute(
            text(
                "INSERT INTO conversations (conversation_id, user_id, title) "
                "VALUES (:c, :u, 't') ON CONFLICT DO NOTHING"
            ),
            {"c": CONV, "u": USER},
        )
        await session.commit()


@pytest.mark.asyncio
async def test_upsert_read_delete_round_trip() -> None:
    await _seed()

    await Repo.upsert_effort(USER, "claude-opus-5-5", "high")
    assert await Repo.get_effort(USER, "claude-opus-5-5") == "high"
    assert await Repo.get_effort_for_conversation(CONV, "claude-opus-5-5") == "high"

    await Repo.upsert_effort(USER, "claude-opus-5-5", "low")
    assert await Repo.get_effort(USER, "claude-opus-5-5") == "low"
    assert [p.effort for p in await Repo.list_for_user(USER)] == ["low"]

    assert await Repo.delete(USER, "claude-opus-5-5") is True
    assert await Repo.get_effort(USER, "claude-opus-5-5") is None
    assert await Repo.delete(USER, "claude-opus-5-5") is False
