"""
RecursiveOrchestrator: ROMA 메인 실행 엔진

Python 재귀 방식으로 ROMA 패턴을 구현합니다.
LangGraph 노드로 사용되며, 내부적으로 Atomizer → Planner → Executor → Aggregator → Verifier
5단계를 재귀적으로 수행합니다.

안전 장치:
- 최대 깊이 (RECURSIVE_MAX_DEPTH)
- 비용 한도 (RECURSIVE_BUDGET_CAP) — R-01: _cost_accumulator로 실제 추적
- 순환 참조 감지 (설명 해시 중복)
- 재계획 횟수 제한 (1회)
"""

import logging
import time
import uuid
from typing import Any, Dict, List, Optional, Set

from neos.config.settings import settings

from .aggregator import RecursiveAggregator
from .atomizer import RecursiveAtomizer
from .executor import RecursiveExecutor
from .models import RecursiveTaskNode, TaskAtomicity, TaskStatus
from .planner import RecursivePlanner
from .verifier import RecursiveVerifier

logger = logging.getLogger(__name__)


class RecursiveOrchestrator:
    """ROMA(Recursive Open Meta-Agent) 메인 실행 엔진.

    사용 방법:
        orchestrator = RecursiveOrchestrator()
        result = await orchestrator.execute(state)

    반환 형식:
        {
            "final_response": str,
            "recursive_task_tree": Dict,   # 직렬화된 RecursiveTaskNode 트리
            "recursive_mode": True,
            "recursive_current_depth": int, # R-09: 실제 최대 도달 깊이
            "recursive_completed_tasks": List[Dict],  # R-03: 완료된 태스크 목록
            "cumulative_cost": float,
        }
    """

    def __init__(
        self,
        agents: Optional[Dict[str, Any]] = None,
        executor=None,
        max_depth: Optional[int] = None,
        budget_cap: Optional[float] = None,
        max_tasks_per_level: Optional[int] = None,
    ):
        self._agents = agents or {}
        self._atomizer = RecursiveAtomizer()
        self._planner = RecursivePlanner(
            max_tasks_per_level=max_tasks_per_level,
        )
        self._executor = executor if executor is not None else RecursiveExecutor(agents=agents)
        self._aggregator = RecursiveAggregator()
        self._verifier = RecursiveVerifier()

        self._max_depth = max_depth if max_depth is not None else settings.RECURSIVE_MAX_DEPTH
        self._budget_cap = budget_cap if budget_cap is not None else settings.RECURSIVE_BUDGET_CAP
        # R-09: 실행마다 초기화되는 최대 도달 깊이 추적
        self._max_reached_depth: int = 0

    async def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """ROMA 워크플로우 진입점 (LangGraph 노드 인터페이스).

        Args:
            state: AgentState 딕셔너리

        Returns:
            업데이트된 state 필드 딕셔너리
        """
        original_query = state.get("original_query", "")
        logger.info(f"[RecursiveOrchestrator] Starting ROMA for: {original_query[:60]}")
        start_time = time.time()

        # R-09: 최대 도달 깊이 초기화
        self._max_reached_depth = 0

        context = self._build_context(state)
        seen_hashes: Set[str] = set()

        root_task = RecursiveTaskNode(
            task_id=str(uuid.uuid4()),
            parent_id=None,
            depth=0,
            description=original_query,
        )

        try:
            result = await self._recursive_solve(root_task, context, seen_hashes)
        except Exception as e:
            logger.error(f"[RecursiveOrchestrator] Fatal error: {e}", exc_info=True)
            result = f"재귀적 분석 중 오류가 발생했습니다: {str(e)}"
            root_task.status = TaskStatus.FAILED

        elapsed_ms = int((time.time() - start_time) * 1000)
        total_cost = root_task.total_cost()

        logger.info(
            f"[RecursiveOrchestrator] Completed in {elapsed_ms}ms, "
            f"cost=${total_cost:.4f}, max_depth={self._max_reached_depth}"
        )

        return {
            "final_response": result,
            "recursive_task_tree": root_task.to_dict(),
            "recursive_mode": True,
            # R-09: 항상 0이던 값을 실제 최대 도달 깊이로 교체
            "recursive_current_depth": self._max_reached_depth,
            "recursive_budget_remaining": self._budget_cap - total_cost,
            # R-03: recursive_completed_tasks 실제 채우기
            "recursive_completed_tasks": self._collect_completed_tasks(root_task),
            "cumulative_cost": state.get("cumulative_cost", 0.0) + total_cost,
            "execution_steps": state.get("execution_steps", []) + [{
                "step": "recursive_orchestrator",
                "result": (
                    f"ROMA completed: max_depth={self._max_reached_depth}, "
                    f"cost=${total_cost:.4f}"
                ),
                "execution_time_ms": elapsed_ms,
            }],
        }

    async def _recursive_solve(
        self,
        task: RecursiveTaskNode,
        context: Dict[str, Any],
        seen_hashes: Set[str],
        replan_count: int = 0,
    ) -> str:
        """ROMA 핵심 재귀 로직.

        Args:
            task: 현재 처리할 태스크
            context: 실행 컨텍스트
            seen_hashes: 순환 참조 감지용 해시 집합
            replan_count: 현재까지 재계획 횟수 (최대 1회)

        Returns:
            태스크 실행 결과 문자열
        """
        # R-09: 최대 도달 깊이 갱신
        if task.depth > self._max_reached_depth:
            self._max_reached_depth = task.depth

        # 1. 비용 한도 체크 — R-01: _cost_accumulator로 실제 누적 비용 확인
        cost_acc = context.get("_cost_accumulator")
        if cost_acc is not None and cost_acc[0] >= self._budget_cap:
            logger.warning(
                f"[RecursiveOrchestrator] Budget cap reached "
                f"(${cost_acc[0]:.4f} >= ${self._budget_cap}) at depth={task.depth}"
            )
            return await self._graceful_degrade(task, context)

        # 2. 순환 참조 감지
        task_hash = task.description_hash()
        if task_hash in seen_hashes:
            logger.warning(f"[RecursiveOrchestrator] Circular reference detected: {task.description[:50]}")
            return f"순환 참조 감지: 이 태스크는 이미 처리 중입니다."
        seen_hashes = seen_hashes | {task_hash}  # 불변 복사 (재귀 호출 간 격리)

        # 3. 원자성 판별
        task.status = TaskStatus.IN_PROGRESS
        atomicity = await self._atomizer.assess(task, context)
        task.atomicity = atomicity

        logger.debug(
            f"[RecursiveOrchestrator] depth={task.depth} atomicity={atomicity.value}: "
            f"{task.description[:50]}"
        )

        # 4. ATOMIC → 직접 실행
        if atomicity == TaskAtomicity.ATOMIC:
            result = await self._executor.execute(task, context)
            task.status = TaskStatus.COMPLETED
            task.result = result
            return result

        # 5. DECOMPOSABLE → 분해 후 재귀 실행
        subtasks = await self._planner.decompose(task, context)

        if not subtasks:
            # 분해 실패 시 직접 실행으로 fallback
            logger.warning(f"[RecursiveOrchestrator] Decomposition failed, falling back to direct execution")
            return await self._executor.execute(task, context)

        task.children = subtasks

        # 6. 하위 태스크 순차 실행 (CLAUDE.md 순차 원칙 준수)
        prior_results: Dict[str, str] = {}
        # R-11: 태스크 설명 맵 — executor가 prior_results의 출처를 파악할 수 있도록
        prior_task_descriptions: Dict[str, str] = {}
        child_context = {
            **context,
            "prior_results": prior_results,
            "prior_task_descriptions": prior_task_descriptions,
        }

        for subtask in subtasks:
            subtask_result = await self._recursive_solve(subtask, child_context, seen_hashes)
            subtask.result = subtask_result
            prior_results[subtask.task_id] = subtask_result
            prior_task_descriptions[subtask.task_id] = subtask.description[:80]
            # R-05: completed_task_descriptions 갱신 — Atomizer 컨텍스트에서 중복 방지에 활용
            completed_descs = context.get("completed_task_descriptions")
            if completed_descs is not None:
                completed_descs.append(subtask.description[:100])
            # 컨텍스트 업데이트 (다음 하위 태스크가 이전 결과 활용 가능)
            child_context = {
                **child_context,
                "prior_results": prior_results,
                "prior_task_descriptions": prior_task_descriptions,
            }

        # 7. 결과 통합 (Aggregation)
        aggregated = await self._aggregator.aggregate(task, subtasks, context)
        task.result = aggregated

        # 8. 검증 (Verification)
        verification = await self._verifier.verify(task, aggregated, context)
        logger.info(
            f"[RecursiveOrchestrator] Verification: satisfied={verification['satisfied']} "
            f"score={verification['score']:.2f} depth={task.depth}"
        )

        # 9. 검증 실패 시 재계획 (최대 1회)
        if not verification["satisfied"] and replan_count < 1 and task.depth < self._max_depth - 1:
            logger.info(f"[RecursiveOrchestrator] Replanning at depth={task.depth} (gaps: {verification['gaps']})")
            replan_result = await self._replan_and_solve(
                task=task,
                aggregated=aggregated,
                gaps=verification["gaps"],
                context=context,
                seen_hashes=seen_hashes,
            )
            if replan_result:
                task.result = replan_result
                return replan_result

        task.status = TaskStatus.COMPLETED
        return aggregated

    async def _replan_and_solve(
        self,
        task: RecursiveTaskNode,
        aggregated: str,
        gaps: List[str],
        context: Dict[str, Any],
        seen_hashes: Set[str],
    ) -> Optional[str]:
        """갭을 채우기 위한 재계획 실행.

        재계획 결과 + 기존 결과를 통합하여 반환합니다.
        """
        replan_tasks = await self._planner.replan(
            task=task,
            previous_result=aggregated,
            gaps=gaps,
            context=context,
        )

        if not replan_tasks:
            logger.info("[RecursiveOrchestrator] Replan produced no tasks, keeping original result")
            return None

        # 재계획 태스크 순차 실행
        # R-07: replan_task.depth 중복 설정 제거 — planner._build_subtask_nodes에서 이미 설정됨
        replan_results: Dict[str, str] = {}
        for replan_task in replan_tasks:
            result = await self._recursive_solve(replan_task, context, seen_hashes, replan_count=1)
            replan_task.result = result
            replan_results[replan_task.task_id] = result

        # 기존 결과 + 재계획 결과 통합
        all_children = list(task.children) + replan_tasks
        final_result = await self._aggregator.aggregate(task, all_children, context)
        return final_result

    async def _graceful_degrade(self, task: RecursiveTaskNode, context: Dict[str, Any]) -> str:
        """비용 한도 초과 시 현재 정보로 최선 답변 생성."""
        completed_children = [c for c in task.children if c.result and c.status == TaskStatus.COMPLETED]
        if completed_children:
            return await self._aggregator.aggregate(task, completed_children, context)
        # 자식 결과도 없으면 직접 실행 시도
        return await self._executor.execute(task, context)

    def _build_context(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """AgentState에서 재귀 실행 컨텍스트 구성."""
        return {
            "original_query": state.get("original_query", ""),
            "session_id": state.get("session_id", ""),
            "user_id": state.get("user_id", ""),
            "detected_language": state.get("detected_language", "ko"),
            "search_synthesis": state.get("search_synthesis", ""),
            "conversation_context": state.get("conversation_context", ""),
            # R-05: 재귀 루프에서 갱신되는 완료 태스크 설명 목록 (Atomizer 컨텍스트에 활용)
            "completed_task_descriptions": [],
            "total_cost": state.get("cumulative_cost", 0.0),
            "prior_results": {},
            "prior_task_descriptions": {},
            # R-01: mutable list로 생성 — shallow copy({**context, ...}) 시에도 참조가 공유되어
            # 재귀 레벨 전체에 걸쳐 누적 비용을 실시간으로 추적할 수 있음
            "_cost_accumulator": [0.0],
        }

    def _collect_completed_tasks(self, node: RecursiveTaskNode) -> List[Dict[str, Any]]:
        """R-03: 완료된 태스크 목록을 수집하여 AgentState에 저장."""
        result: List[Dict[str, Any]] = []
        if node.status == TaskStatus.COMPLETED:
            result.append({
                "task_id": node.task_id,
                "description": node.description[:100],
                "depth": node.depth,
            })
        for child in node.children:
            result.extend(self._collect_completed_tasks(child))
        return result
