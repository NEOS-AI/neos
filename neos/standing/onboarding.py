"""상시 에이전트의 자기소개(온보딩) -- 트랙 Q13f (설계 §8, dots 의 온보딩).

만들어질 때 `background` 태스크 하나를 연다(`start_onboarding`). 그 태스크가 **성공으로**
끝나면 최종 답이 자기소개 메모가 된다(`finish_onboarding`, `CodingRunService` 의 완료 훅).

- 태스크는 메모를 **직접 쓰지 않는다.** background 천장은 READ_ONLY 라 쓰는 도구가
  없고, 메모 도구를 READ_ONLY 로 달면 위험을 속이는 것이다. 모델은 답만 하고, 답을
  메모로 옮기는 것은 플랫폼이다(`write_agent_memo` -- 항상 STAGED).
- 채널·스킬 목록은 플랫폼이 프롬프트에 넣는다. 이름과 설명뿐이다 -- 토큰·주소·허용
  목록 같은 설정값은 넣지 않는다.
- 실패·취소된 자기소개는 메모를 남기지 않는다. 완료 훅이 두 번 불려도 메모는 하나다
  (`claim_onboarded`, 마이그레이션 073).
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from neos.coding.domain.models import CodingTask, CodingTaskMode
from neos.learn.lessons import Lesson
from neos.standing.budget import AgentBudgetEnvelope
from neos.standing.memos import AgentMemoRefused, write_agent_memo
from neos.standing.models import StandingAgent
from neos.standing.resolve import resolve_agent
from neos.standing.store import StandingAgentStore
from neos.standing.tasks import TaskOpener, open_agent_task

logger = logging.getLogger(__name__)

ONBOARDING_MEMO_TITLE = "자기소개"
CHANNEL_PLATFORMS = ("telegram", "discord", "slack")
MAX_SKILLS = 40
MAX_SKILL_DESCRIPTION = 200


def available_channels(owner_id: str, channels: Any) -> list[str]:
    """이 소유자에게 닿는 채널 이름. `principals` 가 있으면 그 소유자에게 매핑된
    플랫폼만이다 -- 남에게 매핑된 채널을 자기 것으로 소개하지 않게."""
    names = []
    principals = list(getattr(channels, "principals", None) or ())
    for platform in CHANNEL_PLATFORMS:
        config = getattr(channels, platform, None)
        if config is None or not getattr(config, "enabled", False):
            continue
        if principals and not any(
            str(p.platform).lower() == platform and p.user_id == owner_id for p in principals
        ):
            continue
        names.append(platform)
    return names


def skill_lines(skills: Iterable[Any]) -> list[str]:
    """모델이 부를 수 있는 스킬만, 이름과 설명 한 줄씩."""
    lines = []
    for skill in skills:
        if getattr(skill, "disable_model_invocation", False):
            continue
        description = " ".join(str(getattr(skill, "description", "") or "").split())
        lines.append(f"- {skill.name}: {description[:MAX_SKILL_DESCRIPTION]}")
        if len(lines) >= MAX_SKILLS:
            break
    return lines


def onboarding_prompt(agent: StandingAgent, channels: Sequence[str], skills: Sequence[str]) -> str:
    channel_text = ", ".join(channels) if channels else "(none connected yet)"
    skill_text = "\n".join(skills) if skills else "- (none)"
    return (
        f"You are {agent.name}, a standing agent that works for one person over time.\n"
        "This is your first task: introduce yourself to them.\n\n"
        f"Channels you can reach them on: {channel_text}\n"
        f"Skills you can use:\n{skill_text}\n\n"
        "You may look around the workspace with read-only tools, but do not change "
        "anything -- this task cannot write. Your final answer becomes your "
        "self-introduction note, which they will review before it is kept. In a few "
        "short paragraphs say who you are, what you can help with given the channels "
        "and skills above, and what you cannot do yet. Describe; do not give orders."
    )


async def start_onboarding(
    agents: StandingAgentStore,
    coding: TaskOpener,
    agent: StandingAgent,
    *,
    channels: Sequence[str],
    skills: Sequence[str],
    envelope: AgentBudgetEnvelope | None = None,
) -> CodingTask:
    task = await open_agent_task(
        agents,
        coding,
        owner_id=agent.owner_id,
        agent_id=agent.agent_id,
        prompt=onboarding_prompt(agent, channels, skills),
        mode=CodingTaskMode.BACKGROUND,
        envelope=envelope,
    )
    await agents.set_onboarding_task(agent.owner_id, agent.agent_id, task.task_id)
    return task


def final_answer(loop_state: Mapping[str, Any] | None) -> str:
    """마지막 assistant 메시지의 텍스트. 체크포인트의 transcript 에서 읽는다 --
    메모리·Postgres 가 같은 체크포인트를 쓰므로 원천이 하나다."""
    for message in reversed(list((loop_state or {}).get("transcript") or ())):
        if message.get("role") != "assistant":
            continue
        return "\n".join(
            str(item.get("text") or "")
            for item in message.get("content") or ()
            if item.get("type") == "text"
        ).strip()
    return ""


async def finish_onboarding(
    agents: StandingAgentStore, task: CodingTask, answer: str
) -> Lesson | None:
    """성공으로 끝난 태스크 하나에 대해 부른다. 자기소개가 아니면 아무것도 안 한다."""
    if task.agent_id is None or not answer.strip():
        return None
    agent = await resolve_agent(agents, task.owner_id, task.agent_id)
    if agent is None:
        return None
    # "이 태스크가 자기소개인가"는 claim 의 조건이 정본이다(한 문장, 073).
    if not await agents.claim_onboarded(agent.owner_id, agent.agent_id, task.task_id):
        return None
    try:
        return await write_agent_memo(
            agents,
            owner_id=agent.owner_id,
            agent_id=agent.agent_id,
            body=answer,
            title=ONBOARDING_MEMO_TITLE,
        )
    except AgentMemoRefused as refused:
        logger.warning(
            "standing agent onboarding memo refused reason=%s agent_id=%s",
            refused.reason,
            agent.agent_id,
        )
        return None
