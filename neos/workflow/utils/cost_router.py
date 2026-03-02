"""Cost-Aware Workflow Routing (Phase 2.7)

각 에이전트/전략의 예상 비용을 추적하고,
예산 부족 시 자동으로 저렴한 전략으로 다운그레이드합니다.

기존 CostOptimizer (HyperDeepResearch)의 패턴을 일반화한 구현입니다.
"""

import logging
from typing import Dict, Any, Optional

from neos.config.settings import settings

logger = logging.getLogger(__name__)


# 전략별 예상 비용 (USD) - 대략적 추정치
STRATEGY_COST_MAP = {
    "standard_search": 0.01,
    "multi_query_search": 0.05,
    "multi_hop_search": 0.10,
    "iterative_search": 0.15,
    "deep_research": 0.50,
    "hyper_deep_research": 2.00,
}

# 다운그레이드 체인: 비용 초과 시 대체 전략
DOWNGRADE_CHAIN = {
    "hyper_deep_research": "deep_research",
    "deep_research": "iterative_search",
    "iterative_search": "multi_hop_search",
    "multi_hop_search": "standard_search",
    "multi_query_search": "standard_search",
}


class CostAwareRouter:
    """비용 인식 워크플로우 라우터

    - 전략별 예상 비용 테이블
    - 예산 부족 시 자동 다운그레이드
    - 누적 비용 추적
    - API 응답 메타데이터에 비용 포함
    """

    def select_strategy(
        self,
        preferred: str,
        remaining_budget: Optional[float] = None,
    ) -> str:
        """예산을 고려하여 실행 전략 선택

        Args:
            preferred: 선호하는 전략 이름
            remaining_budget: 남은 예산 (None이면 무제한)

        Returns:
            실제 사용할 전략 이름 (다운그레이드 가능)
        """
        if not getattr(settings, "COST_AWARE_ROUTING_ENABLED", False):
            return preferred

        if remaining_budget is None:
            return preferred

        estimated = STRATEGY_COST_MAP.get(preferred, 0.01)

        if estimated <= remaining_budget:
            return preferred

        # 다운그레이드 시도
        current = preferred
        while current in DOWNGRADE_CHAIN:
            downgraded = DOWNGRADE_CHAIN[current]
            downgraded_cost = STRATEGY_COST_MAP.get(downgraded, 0.01)
            if downgraded_cost <= remaining_budget:
                logger.info(
                    f"Cost-aware downgrade: {preferred} -> {downgraded} "
                    f"(budget: ${remaining_budget:.2f}, estimated: ${estimated:.2f})"
                )
                return downgraded
            current = downgraded

        # 모든 다운그레이드 실패 시 가장 저렴한 전략
        logger.warning(
            f"Budget exhausted (${remaining_budget:.2f}), using standard_search"
        )
        return "standard_search"

    @staticmethod
    def estimate_cost(strategy: str) -> float:
        """전략의 예상 비용 반환"""
        return STRATEGY_COST_MAP.get(strategy, 0.01)

    @staticmethod
    def track_cost(state: Dict[str, Any], step: str, cost: float) -> None:
        """상태에 비용 추적 정보 추가"""
        if state.get("cumulative_cost") is None:
            state["cumulative_cost"] = 0.0
        if state.get("cost_tracking") is None:
            state["cost_tracking"] = {}

        state["cumulative_cost"] = state["cumulative_cost"] + cost
        state["cost_tracking"][step] = cost

    @staticmethod
    def get_remaining_budget(state: Dict[str, Any]) -> Optional[float]:
        """남은 예산 계산"""
        budget = state.get("cost_budget")
        if budget is None:
            budget = getattr(settings, "DEFAULT_COST_BUDGET", None)
        if budget is None:
            return None

        cumulative = state.get("cumulative_cost", 0.0)
        return max(0.0, budget - cumulative)

    @staticmethod
    def check_budget(state: Dict[str, Any]) -> bool:
        """예산이 남아있는지 확인"""
        budget = state.get("cost_budget")
        if budget is None:
            return True  # 예산 미설정 시 항상 허용

        cumulative = state.get("cumulative_cost", 0.0)
        return cumulative < budget


# 전역 인스턴스
cost_router = CostAwareRouter()
