"""상시 에이전트의 메모 -- 트랙 Q13e (설계 §2 · §8, dots F7 · F18).

- 네임스페이스는 `agent:{agent_id}`(`learned_lessons.namespace` 는 문자열이라 스키마
  변경이 없다). 소유자의 `owner:{id}` 와 섞이지 않는다 -- 소유자 네임스페이스를 읽는
  주입 경로(코딩 교훈)에 에이전트 메모가 끼지 않는다.
- **STAGED 로만** 쓴다. `memory_gate.stage_memo` 를 거치고 `write_approval` 을 보지
  않는다(`maybe_learn_ltm` 은 그 스위치가 꺼지면 장기 메모리에 바로 쓴다).
- 학습 데이터가 아니다(F18). GEPA 는 `agent:` 네임스페이스로 런을 만들지 않는다.
- 멈춘·은퇴한 에이전트도 쓸 수 있다: 그 에이전트의 진행 중 태스크는 계속 돈다
  (결정 2). 메모는 STAGED 라 사람이 올리기 전에는 어디에도 주입되지 않는다.
- 명령형 메모("always ...", "never ...")는 거절한다 -- `policy.is_imperative`,
  다른 교훈과 같은 규칙이다.
"""

from __future__ import annotations

from neos.learn.lessons import Lesson
from neos.learn.memory_gate import stage_memo
from neos.learn.policy import agent_namespace, clip_knowledge, is_imperative
from neos.standing.resolve import resolve_agent
from neos.standing.store import StandingAgentStore

MEMO_KIND = "agent_memo"


class AgentMemoRefused(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


async def write_agent_memo(
    agents: StandingAgentStore,
    *,
    owner_id: str,
    body: str,
    agent_id: str | None = None,
    title: str | None = None,
) -> Lesson:
    text = clip_knowledge(body or "")
    if not text:
        raise AgentMemoRefused("empty")
    if is_imperative(text):
        raise AgentMemoRefused("imperative")
    agent = await resolve_agent(agents, owner_id, agent_id)
    if agent is None:
        raise AgentMemoRefused("agent_not_found")
    label = (title or "").strip() or text.split("\n", 1)[0]
    return await stage_memo(
        namespace=agent_namespace(agent.agent_id),
        title=label[:60],
        body=text,
        kind=MEMO_KIND,
    )
