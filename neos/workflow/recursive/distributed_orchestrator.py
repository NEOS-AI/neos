"""DistributedRecursiveOrchestrator: Ray 기반 병렬 실행 지원.

RecursiveOrchestrator를 상속하여 sibling subtask를 DAG 레벨별로 병렬 실행.

RAY_ENABLED=false (기본) → 부모 클래스의 순차 실행 그대로 사용
RAY_ENABLED=true → depends_on DAG를 파싱하여 독립 태스크를 Ray Actor에서 병렬 실행

핵심 변경 사항:
- ATOMIC 태스크: self._executor 대신 HyperDeepWorkerActor로 실행
- DECOMPOSABLE: for-loop 대신 build_execution_levels() → 레벨별 병렬 실행
- _cost_accumulator: Ray 프로세스 경계 불가이므로 Worker 결과 수신 후 메인 프로세스에서 업데이트
- _stream_callback: Ray 직렬화 불가이므로 Worker에 전달하지 않음 (Phase 4 StreamBridgeActor로 보완 예정)
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, Set

from neos.config.settings import settings

from .models import RecursiveTaskNode, TaskAtomicity, TaskStatus
from .orchestrator import RecursiveOrchestrator

logger = logging.getLogger(__name__)


class DistributedRecursiveOrchestrator(RecursiveOrchestrator):
    """Ray 병렬 실행을 지원하는 RecursiveOrchestrator 확장.

    RAY_ENABLED=false일 때는 부모 클래스와 완전히 동일하게 동작한다.
    RAY_ENABLED=true일 때 독립 sibling 태스크를 레벨별 병렬 실행한다.

    사용 예:
        orchestrator = DistributedRecursiveOrchestrator(
            agents=agents,
            max_depth=1,
            budget_cap=5.0,
            max_tasks_per_level=3,
            ray_enabled=True,
            ray_pool_size=3,
        )
        result = await orchestrator.execute(state)
    """

    def __init__(
        self,
        agents: Optional[Dict[str, Any]] = None,
        executor=None,
        max_depth: Optional[int] = None,
        budget_cap: Optional[float] = None,
        max_tasks_per_level: Optional[int] = None,
        ray_enabled: Optional[bool] = None,
        ray_pool_size: Optional[int] = None,
    ):
        super().__init__(
            agents=agents,
            executor=executor,
            max_depth=max_depth,
            budget_cap=budget_cap,
            max_tasks_per_level=max_tasks_per_level,
        )

        self._ray_enabled = (
            ray_enabled
            if ray_enabled is not None
            else getattr(settings, "RAY_ENABLED", False)
        )

        # max_tasks_per_level은 부모가 self에 저장하지 않으므로 별도 저장
        self._pool_size = ray_pool_size or max_tasks_per_level or 3

        self._ray_pool: Optional[Any] = None  # RayExecutorPool

        if self._ray_enabled:
            try:
                import ray
                if not ray.is_initialized():
                    ray.init(
                        address=getattr(settings, "RAY_ADDRESS", "auto"),
                        ignore_reinit_error=True,
                        object_store_memory=getattr(settings, "RAY_OBJECT_STORE_MEMORY", 2_000_000_000),
                    )

                from neos.workflow.ray_actors.executor_pool import RayExecutorPool
                self._ray_pool = RayExecutorPool(pool_size=self._pool_size)
                logger.info(
                    f"[DistributedRecursiveOrchestrator] Ray enabled, pool_size={self._pool_size}"
                )
            except Exception as e:
                logger.warning(
                    f"[DistributedRecursiveOrchestrator] Ray 초기화 실패, 순차 실행으로 fallback: {e}"
                )
                self._ray_enabled = False
                self._ray_pool = None

    async def warmup(self) -> None:
        """Worker Actor 준비 완료 대기. 첫 요청 전 호출 권장."""
        if self._ray_pool is not None:
            await self._ray_pool.warmup()

    async def _recursive_solve(
        self,
        task: RecursiveTaskNode,
        context: Dict[str, Any],
        seen_hashes: Set[str],
        replan_count: int = 0,
    ) -> str:
        """ROMA 핵심 재귀 로직 (Ray 병렬 실행 지원).

        RAY_ENABLED=false이면 부모 클래스로 위임.
        RAY_ENABLED=true이면:
        - ATOMIC 태스크 → HyperDeepWorkerActor로 실행
        - DECOMPOSABLE → build_execution_levels()로 레벨별 병렬 실행
        """
        if not self._ray_enabled or self._ray_pool is None:
            return await super()._recursive_solve(task, context, seen_hashes, replan_count)

        # ── R-09: 최대 도달 깊이 갱신 ──
        if task.depth > self._max_reached_depth:
            self._max_reached_depth = task.depth

        # ── 1. 비용 한도 체크 ──
        cost_acc = context.get("_cost_accumulator")
        if cost_acc is not None and cost_acc[0] >= self._budget_cap:
            logger.warning(
                f"[DistributedOrchestrator] Budget cap reached "
                f"(${cost_acc[0]:.4f} >= ${self._budget_cap}) at depth={task.depth}"
            )
            return await self._graceful_degrade(task, context)

        # ── 2. 순환 참조 감지 ──
        task_hash = task.description_hash()
        if task_hash in seen_hashes:
            logger.warning(
                f"[DistributedOrchestrator] Circular reference: {task.description[:50]}"
            )
            return "순환 참조 감지: 이 태스크는 이미 처리 중입니다."
        seen_hashes = seen_hashes | {task_hash}  # 불변 복사

        # ── 3. 원자성 판별 ──
        task.status = TaskStatus.IN_PROGRESS
        atomicity = await self._atomizer.assess(task, context)
        task.atomicity = atomicity

        logger.debug(
            f"[DistributedOrchestrator] depth={task.depth} atomicity={atomicity.value}: "
            f"{task.description[:50]}"
        )

        # ── 4. ATOMIC → Ray Worker로 실행 ──
        if atomicity == TaskAtomicity.ATOMIC:
            return await self._execute_via_ray(task, context)

        # ── 5. DECOMPOSABLE → 분해 ──
        subtasks = await self._planner.decompose(task, context)

        if not subtasks:
            logger.warning(
                "[DistributedOrchestrator] Decomposition failed, falling back to Ray execution"
            )
            return await self._execute_via_ray(task, context)

        task.children = subtasks

        # ── 6. DAG 레벨별 실행 (핵심 병렬화) ──
        from neos.workflow.ray_actors.dag_utils import build_execution_levels

        execution_levels = build_execution_levels(subtasks)
        prior_results: Dict[str, str] = {}
        prior_task_descriptions: Dict[str, str] = {}
        child_context: Dict[str, Any] = {
            **context,
            "prior_results": prior_results,
            "prior_task_descriptions": prior_task_descriptions,
        }

        for level_indices in execution_levels:
            level_tasks = [subtasks[i] for i in level_indices]

            # 현재 prior_results를 child_context에 반영
            level_context: Dict[str, Any] = {
                **child_context,
                "prior_results": prior_results,
                "prior_task_descriptions": prior_task_descriptions,
            }

            if len(level_tasks) == 1:
                # 단일 태스크: 재귀 처리 (Ray 오버헤드 불필요)
                t = level_tasks[0]
                result = await self._recursive_solve(t, level_context, seen_hashes)
                t.result = result
                prior_results[t.task_id] = result
                prior_task_descriptions[t.task_id] = t.description[:80]
                completed_descs = context.get("completed_task_descriptions")
                if completed_descs is not None:
                    completed_descs.append(t.description[:100])
            else:
                # 복수 독립 태스크: Ray 병렬 실행
                level_results = await self._execute_level_parallel(
                    level_tasks, level_context, seen_hashes
                )
                for t, res in zip(level_tasks, level_results):
                    prior_results[t.task_id] = res
                    prior_task_descriptions[t.task_id] = t.description[:80]
                    completed_descs = context.get("completed_task_descriptions")
                    if completed_descs is not None:
                        completed_descs.append(t.description[:100])

            child_context = {
                **child_context,
                "prior_results": prior_results,
                "prior_task_descriptions": prior_task_descriptions,
            }

        # ── 7. 결과 통합 ──
        aggregated = await self._aggregator.aggregate(task, subtasks, context)
        task.result = aggregated

        # ── 8. 검증 ──
        verification = await self._verifier.verify(task, aggregated, context)
        logger.info(
            f"[DistributedOrchestrator] Verification: satisfied={verification['satisfied']} "
            f"score={verification['score']:.2f} depth={task.depth}"
        )

        # ── 9. 재계획 (최대 1회) ──
        if not verification["satisfied"] and replan_count < 1 and task.depth < self._max_depth - 1:
            logger.info(
                f"[DistributedOrchestrator] Replanning at depth={task.depth} "
                f"(gaps: {verification['gaps']})"
            )
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

    async def _execute_via_ray(self, task: RecursiveTaskNode, context: Dict[str, Any]) -> str:
        """단일 ATOMIC 태스크를 Ray Worker Actor로 실행."""
        ray_context = self._build_ray_context(context)
        future = self._ray_pool.submit(task.to_dict(), ray_context)
        result_dict: Dict[str, Any] = await asyncio.wrap_future(future.future())

        # 비용 업데이트는 메인 프로세스에서만 (Ray 프로세스 경계 불가)
        cost = result_dict.get("cost", 0.0)
        task.cost += cost
        cost_acc = context.get("_cost_accumulator")
        if cost_acc is not None:
            cost_acc[0] += cost

        content = result_dict.get("result", "")
        task.result = content
        task.status = TaskStatus.COMPLETED if result_dict.get("status") == "completed" else TaskStatus.FAILED

        return content

    async def _execute_level_parallel(
        self,
        tasks: List[RecursiveTaskNode],
        context: Dict[str, Any],
        seen_hashes: Set[str],
    ) -> List[str]:
        """동일 레벨의 독립 태스크들을 Ray Pool에서 병렬 실행.

        Args:
            tasks: 동일 레벨의 독립 태스크 리스트
            context: 공통 실행 컨텍스트 (prior_results 포함)
            seen_hashes: 순환 참조 감지용 해시 집합 (미사용, 시그니처 일관성)

        Returns:
            각 태스크의 결과 문자열 리스트 (입력 순서와 동일)
        """
        ray_context = self._build_ray_context(context)

        futures = [
            self._ray_pool.submit(task.to_dict(), ray_context)
            for task in tasks
        ]

        result_dicts: List[Dict[str, Any]] = await asyncio.gather(*[
            asyncio.wrap_future(f.future()) for f in futures
        ])

        results: List[str] = []
        total_cost = 0.0
        for task, result_dict in zip(tasks, result_dicts):
            content = result_dict.get("result", "")
            cost = result_dict.get("cost", 0.0)

            task.result = content
            task.status = (
                TaskStatus.COMPLETED
                if result_dict.get("status") == "completed"
                else TaskStatus.FAILED
            )
            task.cost += cost
            total_cost += cost
            results.append(content)

        # 비용 누적 (메인 프로세스에서 일괄 업데이트)
        cost_acc = context.get("_cost_accumulator")
        if cost_acc is not None:
            cost_acc[0] += total_cost

        return results

    def _build_ray_context(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Ray Actor에 전달할 안전한 context 생성.

        Ray pickle 직렬화 불가 항목 제외:
        - _stream_callback: coroutine/closure → 직렬화 불가
        - _cost_accumulator: mutable list → 프로세스 경계 불가

        prior_results 요약을 문자열로 변환하여 포함.
        """
        prior_results: Dict[str, str] = context.get("prior_results", {})
        prior_summary = self._summarize_prior_results(prior_results)

        return {
            "session_id": context.get("session_id", ""),
            "user_id": context.get("user_id", ""),
            "detected_language": context.get("detected_language", "ko"),
            "original_query": context.get("original_query", ""),
            "prior_results_summary": prior_summary,
        }

    def _summarize_prior_results(self, prior_results: Dict[str, str]) -> str:
        """prior_results dict를 Agent context용 요약 문자열로 변환."""
        if not prior_results:
            return ""
        parts: List[str] = []
        for task_id, result in list(prior_results.items())[:2]:  # 최대 2개 요약
            parts.append(f"이전 연구 결과: {result[:300]}...")
        return "\n\n".join(parts)
