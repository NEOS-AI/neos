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
import time
from typing import Dict, Tuple

import ray

logger = logging.getLogger(__name__)

NAMED_ACTOR_KEY = "neos_cost_accumulator"

# 사용 기록이 없으면 이 시간(초) 이후 세션 정리 (메모리 누수 방지)
_SESSION_TTL_SEC = 3600  # 1시간


@ray.remote(num_cpus=0)
class CostAccumulatorActor:
    """세션별 누적 비용을 관리하는 Named Actor.

    num_cpus=0: 단순 key-value dict 연산에 CPU를 소비하지 않음.
    모든 메서드가 직렬화되어 스레드 안전(thread-safe).
    TTL 기반 자동 정리로 장기 운영 시 메모리 누수 방지.
    """

    def __init__(self):
        # {session_id: (cost_float, last_access_timestamp)}
        self._costs: Dict[str, Tuple[float, float]] = {}
        logger.info("[CostAccumulatorActor] Initialized")

    def add(self, session_id: str, cost: float) -> float:
        """비용을 세션에 누적하고 현재 총액을 반환."""
        self._evict_expired()
        prev_cost, _ = self._costs.get(session_id, (0.0, 0.0))
        new_cost = prev_cost + cost
        self._costs[session_id] = (new_cost, time.monotonic())
        return new_cost

    def get(self, session_id: str) -> float:
        """세션의 현재 누적 비용 반환."""
        entry = self._costs.get(session_id)
        if entry is None:
            return 0.0
        cost, _ = entry
        self._costs[session_id] = (cost, time.monotonic())
        return cost

    def check_budget(self, session_id: str, budget_cap: float) -> bool:
        """예산 한도 이내이면 True 반환."""
        entry = self._costs.get(session_id)
        cost = entry[0] if entry is not None else 0.0
        return cost < budget_cap

    def reset(self, session_id: str) -> None:
        """세션 종료 시 누적 비용 초기화."""
        self._costs.pop(session_id, None)

    def all_costs(self) -> Dict[str, float]:
        """현재 모든 세션의 비용 스냅샷 반환 (디버깅용)."""
        return {sid: entry[0] for sid, entry in self._costs.items()}

    def _evict_expired(self) -> None:
        """TTL이 만료된 세션 항목 정리 (호출 시 lazy eviction)."""
        now = time.monotonic()
        expired = [
            sid
            for sid, (_, last_access) in self._costs.items()
            if now - last_access > _SESSION_TTL_SEC
        ]
        for sid in expired:
            del self._costs[sid]
        if expired:
            logger.debug(f"[CostAccumulatorActor] Evicted {len(expired)} expired sessions")


def get_or_create_cost_accumulator() -> "ray.actor.ActorHandle":
    """Named Actor를 가져오거나 없으면 새로 생성."""
    try:
        return ray.get_actor(NAMED_ACTOR_KEY)
    except ValueError:
        return CostAccumulatorActor.options(name=NAMED_ACTOR_KEY).remote()
