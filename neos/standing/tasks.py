"""상시 에이전트가 코딩 태스크를 연다 -- 트랙 Q13c (설계 §4.2 · §5).

- 에이전트는 `resolve_agent` 로만 찾는다(§9: 에이전트를 찾는 조회는 하나).
- 태스크의 `owner_id` 는 **에이전트의 소유자**다. 소유 검사는 지금처럼
  `owner_id` 하나로 하고 `agent_id` 는 권한에 쓰지 않는다 -- 에이전트 경로가
  소유 검사를 따로 가지면 우회 경로가 된다(N8).
- 모드는 기본 `background`(아무도 시키지 않은 일, READ_ONLY 천장), 사용자가 맡긴
  일이면 `autonomous`. `interactive` 는 사람이 보고 있다는 뜻이라 거절한다(§9).
- 멈춘(paused)·은퇴한(retired) 에이전트는 새 태스크를 열지 않는다. 이미 도는
  태스크는 건드리지 않는다(결정 2) -- 여기는 새 일을 여는 입구일 뿐이다.
"""

from __future__ import annotations

from typing import Protocol

from neos.coding.domain.models import CodingTask, CodingTaskMode
from neos.standing.models import StandingAgentStatus
from neos.standing.resolve import resolve_agent
from neos.standing.store import StandingAgentStore

AGENT_TASK_MODES = frozenset({CodingTaskMode.BACKGROUND, CodingTaskMode.AUTONOMOUS})


class TaskOpener(Protocol):
    """`CodingTaskService` 와 `PostgresCodingService` 가 함께 가진 입구."""

    async def create_task(
        self,
        *,
        owner_id: str,
        prompt: str,
        task_id: str | None = None,
        mode: CodingTaskMode = CodingTaskMode.INTERACTIVE,
        agent_id: str | None = None,
    ) -> CodingTask: ...


class AgentTaskRefused(Exception):
    """에이전트가 태스크를 열 수 없다. `reason` 은 안정된 코드다."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


async def open_agent_task(
    agents: StandingAgentStore,
    coding: TaskOpener,
    *,
    owner_id: str,
    prompt: str,
    agent_id: str | None = None,
    mode: CodingTaskMode = CodingTaskMode.BACKGROUND,
) -> CodingTask:
    if mode not in AGENT_TASK_MODES:
        raise AgentTaskRefused("interactive_mode")
    agent = await resolve_agent(agents, owner_id, agent_id)
    if agent is None:
        # 남의 에이전트도 여기로 온다 -- 존재를 확인해 주지 않는다(§6).
        raise AgentTaskRefused("agent_not_found")
    if agent.status is not StandingAgentStatus.ACTIVE:
        raise AgentTaskRefused(f"agent_{agent.status.value}")
    return await coding.create_task(
        owner_id=agent.owner_id,
        prompt=prompt,
        mode=mode,
        agent_id=agent.agent_id,
    )
