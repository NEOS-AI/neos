"""user_model_preferences 저장소 (사용자 × 모델 effort).

쓰기는 `execute_in_transaction` 으로 한다 -- `fetch_one` 은 INSERT/DELETE 를
커밋하지 않는다 (`connection.py` 의 fetch_one 은 `create_` 를 부르는 SELECT
만 커밋한다). RETURNING 행은 그 결과에서 읽는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from neos.database.connection import db_manager


@dataclass(frozen=True, slots=True)
class ModelPreference:
    model_pin: str
    effort: str
    updated_at: datetime


class ModelPreferenceRepository:
    @staticmethod
    async def get_effort(user_id: str, model_pin: str) -> str | None:
        row = await db_manager.fetch_one(
            "SELECT effort FROM user_model_preferences "
            "WHERE user_id = $1 AND model_pin = $2",
            user_id,
            model_pin,
        )
        return row[0] if row else None

    @staticmethod
    async def get_effort_for_conversation(
        conversation_id: str, model_pin: str
    ) -> str | None:
        """채팅 턴 전용. 소유자 조회를 따로 하지 않도록 조인 한 번으로 끝낸다.

        첨부 없는 턴이 `ChatRepository.get_conversation` 을 부르지 않는다는
        보장(Fix round 2 Item 2)을 지키기 위해서다.
        """
        row = await db_manager.fetch_one(
            """
            SELECT p.effort
            FROM conversations c
            JOIN user_model_preferences p
              ON p.user_id = c.user_id AND p.model_pin = $2
            WHERE c.conversation_id = $1 AND c.deleted_at IS NULL
            """,
            conversation_id,
            model_pin,
        )
        return row[0] if row else None

    @staticmethod
    async def list_for_user(user_id: str) -> list[ModelPreference]:
        rows = await db_manager.fetch_all(
            "SELECT model_pin, effort, updated_at FROM user_model_preferences "
            "WHERE user_id = $1 ORDER BY model_pin",
            user_id,
        )
        return [ModelPreference(r[0], r[1], r[2]) for r in rows]

    @staticmethod
    async def upsert_effort(
        user_id: str, model_pin: str, effort: str
    ) -> ModelPreference:
        result = await db_manager.execute_in_transaction(
            """
            INSERT INTO user_model_preferences (user_id, model_pin, effort)
            VALUES ($1, $2, $3)
            ON CONFLICT (user_id, model_pin) DO UPDATE
                SET effort = EXCLUDED.effort, updated_at = now()
            RETURNING model_pin, effort, updated_at
            """,
            user_id,
            model_pin,
            effort,
        )
        row = result.fetchone()
        return ModelPreference(row[0], row[1], row[2])

    @staticmethod
    async def delete(user_id: str, model_pin: str) -> bool:
        result = await db_manager.execute_in_transaction(
            "DELETE FROM user_model_preferences "
            "WHERE user_id = $1 AND model_pin = $2 RETURNING model_pin",
            user_id,
            model_pin,
        )
        return result.fetchone() is not None
