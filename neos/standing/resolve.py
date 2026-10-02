"""요청이 어떤 에이전트에 닿는가 (Q13 설계 §6).

**호출자는 전부 이 함수 하나를 부른다**(API · 채널 게이트웨이 · 스케줄러).
에이전트를 찾는 조회가 둘이 되면 여럿으로 늘릴 때 한쪽만 고쳐진다.
"""

from __future__ import annotations

from neos.standing.models import StandingAgent
from neos.standing.store import StandingAgentStore


async def resolve_agent(
    store: StandingAgentStore, owner_id: str, agent_id: str | None = None
) -> StandingAgent | None:
    """`agent_id` 가 없으면 소유자의 (유일한) 에이전트. 있으면 그 에이전트.

    소유자가 아닌 `agent_id` 는 없는 것과 구별되지 않는다(None).
    """
    if agent_id is not None:
        return await store.get_owned(owner_id, agent_id)
    agents = await store.list_for_owner(owner_id)
    # 사용자당 하나(결정 6)라 둘 이상은 아직 불가능하다. 여럿이 되는 날
    # `agent_id=None` 의 뜻은 그때 정한다(설계 §6) -- 조용히 첫째를 고르지 않는다.
    if len(agents) > 1:
        raise LookupError("owner has several agents; pass agent_id")
    return agents[0] if agents else None
