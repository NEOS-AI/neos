"""Stateless Ray Named Actors: Atomizer, Planner, Aggregator, Verifier 공유 인스턴스.

단일 Named Actor 인스턴스를 여러 요청이 공유하여 메모리 절약.
상태 없음(stateless)이므로 max_concurrency 높게 설정 가능.

직렬화 규칙:
- 입력: task.to_dict() (RecursiveTaskNode → dict)
- 출력: result.value (Enum → str), [s.to_dict() for s in subtasks]
- context: _stream_callback, _cost_accumulator 반드시 제외

Named Actor 키 상수:
- ATOMIZER_KEY = "neos_atomizer"
- PLANNER_KEY  = "neos_planner"
- AGGREGATOR_KEY = "neos_aggregator"
- VERIFIER_KEY = "neos_verifier"

초기화 (main.py lifespan):
    from neos.workflow.ray_actors.stateless_actors import create_all_named_actors
    create_all_named_actors()
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

import ray

logger = logging.getLogger(__name__)

ATOMIZER_KEY = "neos_atomizer"
PLANNER_KEY = "neos_planner"
AGGREGATOR_KEY = "neos_aggregator"
VERIFIER_KEY = "neos_verifier"

# Ray pickle 직렬화 불가 항목 — context에서 반드시 제외
_NON_SERIALIZABLE_KEYS = frozenset(["_stream_callback", "_cost_accumulator"])


def _safe_context(context: Dict[str, Any]) -> Dict[str, Any]:
    """Ray Actor에 전달할 안전한 context 생성 (직렬화 불가 항목 제외)."""
    return {k: v for k, v in context.items() if k not in _NON_SERIALIZABLE_KEYS}


@ray.remote(num_cpus=0.25, max_concurrency=10)
class RayAtomizerActor:
    """RecursiveAtomizer의 Named Actor 래퍼.

    상태 없음 → max_concurrency=10으로 높은 동시성 허용.
    Haiku 모델 기반이므로 빠른 응답 가능.
    """

    def __init__(self):
        from neos.workflow.recursive.atomizer import RecursiveAtomizer
        self._atomizer = RecursiveAtomizer()
        logger.info("[RayAtomizerActor] Initialized")

    async def assess(self, task_dict: Dict[str, Any], context: Dict[str, Any]) -> str:
        """태스크 원자성 판별.

        Returns:
            TaskAtomicity.value 문자열 ("atomic" | "decomposable")
        """
        from neos.workflow.recursive.models import RecursiveTaskNode
        task = RecursiveTaskNode.from_dict(task_dict)
        result = await self._atomizer.assess(task, _safe_context(context))
        return result.value


@ray.remote(num_cpus=0.5, max_concurrency=5)
class RayPlannerActor:
    """RecursivePlanner의 Named Actor 래퍼.

    depth=0은 Opus, depth>0은 Haiku 사용 (내부 planner 로직 그대로).
    """

    def __init__(self, max_tasks_per_level: Optional[int] = None):
        from neos.workflow.recursive.planner import RecursivePlanner
        self._planner = RecursivePlanner(max_tasks_per_level=max_tasks_per_level)
        logger.info("[RayPlannerActor] Initialized")

    async def decompose(
        self,
        task_dict: Dict[str, Any],
        context: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """태스크를 subtask 리스트로 분해.

        Returns:
            RecursiveTaskNode.to_dict() 리스트
        """
        from neos.workflow.recursive.models import RecursiveTaskNode
        task = RecursiveTaskNode.from_dict(task_dict)
        subtasks = await self._planner.decompose(task, _safe_context(context))
        return [s.to_dict() for s in subtasks]

    async def replan(
        self,
        task_dict: Dict[str, Any],
        previous_result: str,
        gaps: List[str],
        context: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """검증 실패 시 갭을 채우기 위한 재계획.

        Returns:
            RecursiveTaskNode.to_dict() 리스트
        """
        from neos.workflow.recursive.models import RecursiveTaskNode
        task = RecursiveTaskNode.from_dict(task_dict)
        subtasks = await self._planner.replan(
            task, previous_result, gaps, _safe_context(context)
        )
        return [s.to_dict() for s in subtasks]


@ray.remote(num_cpus=0.25, max_concurrency=10)
class RayAggregatorActor:
    """RecursiveAggregator의 Named Actor 래퍼."""

    def __init__(self):
        from neos.workflow.recursive.aggregator import RecursiveAggregator
        self._aggregator = RecursiveAggregator()
        logger.info("[RayAggregatorActor] Initialized")

    async def aggregate(
        self,
        parent_dict: Dict[str, Any],
        children_dicts: List[Dict[str, Any]],
        context: Dict[str, Any],
    ) -> Tuple[str, Dict[str, Any]]:
        """자식 태스크 결과를 통합.

        Returns:
            (aggregated_result, updated_parent_dict)
        """
        from neos.workflow.recursive.models import RecursiveTaskNode
        parent = RecursiveTaskNode.from_dict(parent_dict)
        children = [RecursiveTaskNode.from_dict(c) for c in children_dicts]
        result = await self._aggregator.aggregate(parent, children, _safe_context(context))
        return result, parent.to_dict()


@ray.remote(num_cpus=0.25, max_concurrency=10)
class RayVerifierActor:
    """RecursiveVerifier의 Named Actor 래퍼."""

    def __init__(self):
        from neos.workflow.recursive.verifier import RecursiveVerifier
        self._verifier = RecursiveVerifier()
        logger.info("[RayVerifierActor] Initialized")

    async def verify(
        self,
        task_dict: Dict[str, Any],
        aggregated_result: str,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """통합 결과의 충족도 검증.

        Returns:
            {"satisfied": bool, "score": float, "gaps": List[str]}
        """
        from neos.workflow.recursive.models import RecursiveTaskNode
        task = RecursiveTaskNode.from_dict(task_dict)
        return await self._verifier.verify(task, aggregated_result, _safe_context(context))


def create_all_named_actors(max_tasks_per_level: Optional[int] = None) -> None:
    """모든 Named Actor를 생성하거나 기존 Actor 재사용.

    main.py lifespan startup에서 ray.init() 직후 호출.
    이미 존재하는 Named Actor는 재사용.
    """
    actors = {
        ATOMIZER_KEY: RayAtomizerActor,
        PLANNER_KEY: RayPlannerActor,
        AGGREGATOR_KEY: RayAggregatorActor,
        VERIFIER_KEY: RayVerifierActor,
    }

    for name, actor_cls in actors.items():
        try:
            ray.get_actor(name)
            logger.info(f"[StatelessActors] Reusing existing Named Actor: {name}")
        except ValueError:
            if name == PLANNER_KEY:
                actor_cls.options(name=name).remote(
                    max_tasks_per_level=max_tasks_per_level
                )
            else:
                actor_cls.options(name=name).remote()
            logger.info(f"[StatelessActors] Created Named Actor: {name}")
