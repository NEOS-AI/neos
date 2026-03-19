"""CostAccumulatorActor: Ray Named Actor 기반 세션별 비용 추적.

단일 Ray Named Actor 인스턴스가 모든 Worker Actor의 비용을 중앙 집계.
Phase 1의 _cost_accumulator (mutable list, 프로세스 경계 불가) 한계를
Named Actor로 보완하여 실시간 예산 오버플로우 감지 가능.

사용법:
    # main.py lifespan startup (ray.init() 이후):
    CostAccumulatorActor.options(name="neos_cost_accumulator").remote()

    # 사용처:
    cost_actor = ray.get_actor("neos_cost_accumulator")
    await asyncio.wrap_future(cost_actor.add.remote("session123", 0.05).future())
    over_budget = await asyncio.wrap_future(
        cost_actor.check_budget.remote("session123", 5.0).future()
    )
"""

from __future__ import annotations

import logging
from typing import Dict

import ray

logger = logging.getLogger(__name__)

NAMED_ACTOR_KEY = "neos_cost_accumulator"


@ray.remote
class CostAccumulatorActor:
    """세션별 누적 비용을 관리하는 Named Actor.

    ray.remote 데코레이터는 Actor당 1개 CPU, max_concurrency=1 기본값.
    모든 메서드가 직렬화되어 스레드 안전(thread-safe).
    """

    def __init__(self):
        self._costs: Dict[str, float] = {}
        logger.info("[CostAccumulatorActor] Initialized")

    def add(self, session_id: str, cost: float) -> float:
        """비용을 세션에 누적하고 현재 총액을 반환."""
        self._costs[session_id] = self._costs.get(session_id, 0.0) + cost
        return self._costs[session_id]

    def get(self, session_id: str) -> float:
        """세션의 현재 누적 비용 반환."""
        return self._costs.get(session_id, 0.0)

    def check_budget(self, session_id: str, budget_cap: float) -> bool:
        """예산 한도 이내이면 True 반환."""
        return self._costs.get(session_id, 0.0) < budget_cap

    def reset(self, session_id: str) -> None:
        """세션 종료 시 누적 비용 초기화."""
        self._costs.pop(session_id, None)

    def all_costs(self) -> Dict[str, float]:
        """현재 모든 세션의 비용 스냅샷 반환 (디버깅용)."""
        return dict(self._costs)


def get_or_create_cost_accumulator() -> "ray.actor.ActorHandle":
    """Named Actor를 가져오거나 없으면 새로 생성."""
    try:
        return ray.get_actor(NAMED_ACTOR_KEY)
    except ValueError:
        return CostAccumulatorActor.options(name=NAMED_ACTOR_KEY).remote()
