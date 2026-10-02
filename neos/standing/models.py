"""상시 에이전트 도메인 (Q13 설계 §4.1)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import uuid4


class StandingAgentStatus(StrEnum):
    """에이전트 단위 상태. 태스크의 `PAUSED`(감시자·예산의 출구)와 다르다 --
    `paused` 에이전트는 새 태스크를 만들지 않을 뿐 진행 중 태스크는 건드리지
    않는다(Q13 결정 2)."""

    ACTIVE = "active"
    PAUSED = "paused"
    RETIRED = "retired"


@dataclass(frozen=True, slots=True)
class StandingAgent:
    agent_id: str
    owner_id: str
    name: str
    status: StandingAgentStatus
    created_at: datetime
    updated_at: datetime
    #: Q13f -- 자기소개 태스크와, 그 메모를 남긴 시각(마이그레이션 073).
    onboarding_task_id: str | None = None
    onboarded_at: datetime | None = None


class StandingAgentConflict(Exception):
    """만들 수 없다. `reason` 은 어느 인덱스가 막았는지다.

    - `one_per_owner` -- 소유자에게 이미 에이전트가 있다(결정 6)
    - `name_taken` -- 같은 소유자 안에 같은 이름이 있다(Q13 결정 3)
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def normalize_agent_name(name: str) -> str:
    """저장하는 이름. 앞뒤 공백만 걷는다 -- 길이 제한은 없다(Q13 결정 3)."""
    stripped = (name or "").strip()
    if not stripped:
        raise ValueError("agent name must not be empty")
    return stripped


def agent_name_key(name: str) -> str:
    """중복을 가리는 열쇠. DB 인덱스의 `lower(btrim(name))` 과 같은 뜻이다."""
    return normalize_agent_name(name).lower()


def new_agent_id() -> str:
    return f"sa_{uuid4().hex}"
