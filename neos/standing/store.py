"""상시 에이전트 저장소 (Q13a). 메모리 구현과 Postgres 구현이 **같은 계약**을 지킨다 --
`tests/standing/test_standing_store_contract.py` 가 같은 시나리오를 둘 다에 돌린다.

읽기는 전부 소유자로 거른다. 소유자가 아닌 id 는 없는 것과 구별되지 않는다
(N8 의 교훈: 존재를 확인해 주지 않는다).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from neos.standing.models import (
    StandingAgent,
    StandingAgentConflict,
    StandingAgentStatus,
    agent_name_key,
    new_agent_id,
    normalize_agent_name,
)

#: 인덱스 이름 -> 충돌 사유. 마이그레이션 070 의 이름과 **정확히** 같아야 한다.
_CONFLICTS = {
    "uq_standing_agents_one_per_owner": "one_per_owner",
    "uq_standing_agents_name_per_owner": "name_taken",
}


class StandingAgentStore(Protocol):
    async def create(self, owner_id: str, name: str) -> StandingAgent: ...

    async def get_owned(self, owner_id: str, agent_id: str) -> StandingAgent | None: ...

    async def list_for_owner(self, owner_id: str) -> list[StandingAgent]: ...

    async def update(
        self,
        owner_id: str,
        agent_id: str,
        *,
        name: str | None = None,
        status: StandingAgentStatus | None = None,
    ) -> StandingAgent | None: ...

    async def delete(self, owner_id: str, agent_id: str) -> bool: ...

    async def set_onboarding_task(self, owner_id: str, agent_id: str, task_id: str) -> bool:
        """자기소개 태스크를 적는다. 이미 있으면 덮어쓰지 않고 False."""
        ...

    async def claim_onboarded(self, owner_id: str, agent_id: str, task_id: str) -> bool:
        """이 태스크가 자기소개이고 아직 메모가 없으면 표시하고 True -- 한 번만."""
        ...


class InMemoryStandingAgentStore:
    """테스트와 로컬용. 두 인덱스를 코드로 흉내 낸다 -- 순서도 DB 와 같다."""

    def __init__(self, *, clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self._live: dict[str, StandingAgent] = {}
        self._clock = clock

    async def create(self, owner_id: str, name: str) -> StandingAgent:
        stored = normalize_agent_name(name)
        mine = [agent for agent in self._live.values() if agent.owner_id == owner_id]
        if mine:
            raise StandingAgentConflict("one_per_owner")
        # 사용자당 하나인 동안에는 닿지 않는다 -- 위 검사가 먼저 막는다. 이름 인덱스를
        # 흉내 내는 자리로 남긴다: 하나 제약을 지우는 날 이 검사가 이미 서 있어야 한다.
        if any(agent_name_key(agent.name) == agent_name_key(stored) for agent in mine):
            raise StandingAgentConflict("name_taken")
        now = self._clock()
        agent = StandingAgent(
            agent_id=new_agent_id(),
            owner_id=owner_id,
            name=stored,
            status=StandingAgentStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )
        self._live[agent.agent_id] = agent
        return agent

    async def get_owned(self, owner_id: str, agent_id: str) -> StandingAgent | None:
        agent = self._live.get(agent_id)
        return agent if agent is not None and agent.owner_id == owner_id else None

    async def list_for_owner(self, owner_id: str) -> list[StandingAgent]:
        return sorted(
            (agent for agent in self._live.values() if agent.owner_id == owner_id),
            key=lambda agent: agent.created_at,
        )

    async def update(
        self,
        owner_id: str,
        agent_id: str,
        *,
        name: str | None = None,
        status: StandingAgentStatus | None = None,
    ) -> StandingAgent | None:
        current = await self.get_owned(owner_id, agent_id)
        if current is None:
            return None
        stored = normalize_agent_name(name) if name is not None else current.name
        if any(
            other.agent_id != agent_id and agent_name_key(other.name) == agent_name_key(stored)
            for other in await self.list_for_owner(owner_id)
        ):
            raise StandingAgentConflict("name_taken")
        updated = replace(
            current,
            name=stored,
            status=status if status is not None else current.status,
            updated_at=self._clock(),
        )
        self._live[agent_id] = updated
        return updated

    async def delete(self, owner_id: str, agent_id: str) -> bool:
        if await self.get_owned(owner_id, agent_id) is None:
            return False
        del self._live[agent_id]
        return True

    async def set_onboarding_task(self, owner_id: str, agent_id: str, task_id: str) -> bool:
        current = await self.get_owned(owner_id, agent_id)
        if current is None or current.onboarding_task_id is not None:
            return False
        self._live[agent_id] = replace(current, onboarding_task_id=task_id)
        return True

    async def claim_onboarded(self, owner_id: str, agent_id: str, task_id: str) -> bool:
        current = await self.get_owned(owner_id, agent_id)
        if (
            current is None
            or current.onboarding_task_id != task_id
            or current.onboarded_at is not None
        ):
            return False
        self._live[agent_id] = replace(current, onboarded_at=self._clock())
        return True


class PostgresStandingAgentStore:
    def __init__(
        self,
        session_factory: Callable[[], Awaitable[Any]],
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock

    async def create(self, owner_id: str, name: str) -> StandingAgent:
        stored = normalize_agent_name(name)
        now = self._clock()
        agent = StandingAgent(
            agent_id=new_agent_id(),
            owner_id=owner_id,
            name=stored,
            status=StandingAgentStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )
        try:
            async with await self._session_factory() as session:
                async with session.begin():
                    await session.execute(
                        text(
                            """
                            INSERT INTO standing_agents
                                (agent_id, owner_id, name, status, created_at, updated_at)
                            VALUES (:agent_id, :owner_id, :name, :status, :now, :now)
                            """
                        ),
                        {
                            "agent_id": agent.agent_id,
                            "owner_id": owner_id,
                            "name": stored,
                            "status": agent.status.value,
                            "now": now,
                        },
                    )
        except IntegrityError as error:
            _raise_conflict(error)
        return agent

    async def get_owned(self, owner_id: str, agent_id: str) -> StandingAgent | None:
        rows = await self._select(
            "WHERE owner_id = :owner_id AND agent_id = :agent_id AND deleted_at IS NULL",
            {"owner_id": owner_id, "agent_id": agent_id},
        )
        return rows[0] if rows else None

    async def list_for_owner(self, owner_id: str) -> list[StandingAgent]:
        return await self._select(
            "WHERE owner_id = :owner_id AND deleted_at IS NULL ORDER BY created_at",
            {"owner_id": owner_id},
        )

    async def update(
        self,
        owner_id: str,
        agent_id: str,
        *,
        name: str | None = None,
        status: StandingAgentStatus | None = None,
    ) -> StandingAgent | None:
        stored = normalize_agent_name(name) if name is not None else None
        try:
            async with await self._session_factory() as session:
                async with session.begin():
                    result = await session.execute(
                        text(
                            """
                            UPDATE standing_agents
                            SET name = COALESCE(:name, name),
                                status = COALESCE(:status, status),
                                updated_at = :now
                            WHERE owner_id = :owner_id AND agent_id = :agent_id
                              AND deleted_at IS NULL
                            RETURNING agent_id
                            """
                        ),
                        {
                            "name": stored,
                            "status": status.value if status is not None else None,
                            "now": self._clock(),
                            "owner_id": owner_id,
                            "agent_id": agent_id,
                        },
                    )
                    changed = result.first() is not None
        except IntegrityError as error:
            _raise_conflict(error)
        return await self.get_owned(owner_id, agent_id) if changed else None

    async def delete(self, owner_id: str, agent_id: str) -> bool:
        async with await self._session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    text(
                        """
                        UPDATE standing_agents
                        SET deleted_at = :now, updated_at = :now
                        WHERE owner_id = :owner_id AND agent_id = :agent_id
                          AND deleted_at IS NULL
                        """
                    ),
                    {"owner_id": owner_id, "agent_id": agent_id, "now": self._clock()},
                )
        return bool(result.rowcount)

    async def set_onboarding_task(self, owner_id: str, agent_id: str, task_id: str) -> bool:
        return await self._set_once(
            "onboarding_task_id = :task_id",
            "onboarding_task_id IS NULL",
            owner_id, agent_id, task_id,
        )

    async def claim_onboarded(self, owner_id: str, agent_id: str, task_id: str) -> bool:
        return await self._set_once(
            "onboarded_at = :now",
            "onboarding_task_id = :task_id AND onboarded_at IS NULL",
            owner_id, agent_id, task_id,
        )

    async def _set_once(
        self, assignment: str, condition: str, owner_id: str, agent_id: str, task_id: str
    ) -> bool:
        """조건부 UPDATE 한 문장 -- 둘이 동시에 불러도 한쪽만 True 다."""
        async with await self._session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    text(
                        f"""
                        UPDATE standing_agents
                        SET {assignment}, updated_at = :now
                        WHERE owner_id = :owner_id AND agent_id = :agent_id
                          AND deleted_at IS NULL AND {condition}
                        """
                    ),
                    {
                        "owner_id": owner_id,
                        "agent_id": agent_id,
                        "task_id": task_id,
                        "now": self._clock(),
                    },
                )
        return bool(result.rowcount)

    async def _select(self, where: str, params: dict[str, Any]) -> list[StandingAgent]:
        async with await self._session_factory() as session:
            result = await session.execute(
                text(
                    "SELECT agent_id, owner_id, name, status, created_at, updated_at, "
                    "onboarding_task_id, onboarded_at "
                    f"FROM standing_agents {where}"
                ),
                params,
            )
            return [
                StandingAgent(
                    agent_id=row.agent_id,
                    owner_id=row.owner_id,
                    name=row.name,
                    status=StandingAgentStatus(row.status),
                    created_at=row.created_at,
                    updated_at=row.updated_at,
                    onboarding_task_id=row.onboarding_task_id,
                    onboarded_at=row.onboarded_at,
                )
                for row in result
            ]


def _raise_conflict(error: IntegrityError) -> None:
    """어느 인덱스가 막았는지를 사유로. 모르는 무결성 오류는 그대로 올린다."""
    message = str(error)
    for index, reason in _CONFLICTS.items():
        if index in message:
            raise StandingAgentConflict(reason) from error
    raise error
