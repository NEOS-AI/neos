"""Ray 기반 HyperDeepResearchAgent 병렬 실행 풀.

HyperDeepWorkerActor: Actor당 독립 프로세스에서 HyperDeepResearchAgent를 실행.
RayExecutorPool: 라운드로빈 방식으로 Worker Actor 풀을 관리.

핵심 설계 원칙:
- max_concurrency=1: Actor당 동시 요청 1개 → 상태 충돌 방지
- 각 Actor는 독립 프로세스 → GIL 없는 완전 병렬 실행
- _stream_callback은 Ray pickle 직렬화 불가 → context에서 제외 (SSE 스트리밍 손실 — Phase 4에서 StreamBridgeActor로 보완)
- asyncio.wrap_future() 패턴: ray.get() 직접 호출 시 asyncio event loop 블로킹 방지
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List

import ray

logger = logging.getLogger(__name__)


@ray.remote(num_cpus=0.5, num_gpus=0, max_concurrency=1)
class HyperDeepWorkerActor:
    """독립 프로세스에서 HyperDeepResearchAgent를 실행하는 Ray Actor.

    max_concurrency=1: 요청당 완전 격리 실행 (내부 상태 충돌 방지).
    Actor 재사용 시 _reset_agent_state()로 이전 실행 잔류 상태 제거.
    """

    def __init__(self):
        from neos.agents.search_agents.hyper_deep_research.agent import HyperDeepResearchAgent
        self._agent = HyperDeepResearchAgent()
        logger.info("[HyperDeepWorkerActor] HyperDeepResearchAgent initialized")

    def ping(self) -> bool:
        """warm-up 체크용. RayExecutorPool.warmup()에서 사용."""
        return True

    def _reset_agent_state(self) -> None:
        """각 태스크 실행 전 agent 내부 상태 초기화.

        HyperDeepResearchAgent.reset()에 위임하여 agent 내부 상태 목록과
        동기화 문제를 방지한다. agent에 새 필드가 추가되어도 자동으로 반영됨.
        """
        self._agent.reset()

    async def execute(self, task_dict: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """atomic subtask를 HyperDeepResearchAgent로 실행.

        Args:
            task_dict: RecursiveTaskNode.to_dict() 직렬화 결과.
            context: 실행 컨텍스트.
                - session_id, user_id: 전달됨
                - _stream_callback: Ray pickle 불가이므로 Worker 내부에서 사용 불가
                - prior_results_summary: 이전 레벨 결과 요약 문자열

        Returns:
            {
                "result": str,   # 리포트 마크다운
                "cost": float,   # 비용 (현재 0.0 — HDR agent가 비용 반환 시 추출 예정)
                "task_id": str,
                "status": "completed" | "failed",
            }
        """
        from neos.workflow.recursive.models import RecursiveTaskNode, TaskStatus

        task = RecursiveTaskNode.from_dict(task_dict)
        task.status = TaskStatus.IN_PROGRESS
        start = time.time()

        logger.info(
            f"[HyperDeepWorkerActor] Executing: {task.description[:60]}"
        )

        try:
            self._reset_agent_state()

            # _stream_callback은 Ray 직렬화 불가 → 제외 (SSE Phase 이벤트 손실)
            agent_context: Dict[str, Any] = {
                "session_id": context.get("session_id", ""),
                "user_id": context.get("user_id", ""),
            }

            # prior_results 요약을 agent context에 포함 (다음 레벨 태스크의 경우)
            prior_summary = context.get("prior_results_summary", "")
            if prior_summary:
                agent_context["prior_research_context"] = prior_summary

            output = await self._agent.execute(
                query=task.description,
                context=agent_context,
            )

            content = self._extract_content(output)
            if not content:
                logger.warning(
                    f"[HyperDeepWorkerActor] Empty result: {task.description[:50]}"
                )
                content = (
                    f"[HyperDeep 실패: '{task.description[:40]}' 연구 결과를 가져올 수 없습니다. "
                    f"Tavily API 가용 여부를 확인하세요.]"
                )

            elapsed_ms = int((time.time() - start) * 1000)
            logger.info(
                f"[HyperDeepWorkerActor] Completed ({elapsed_ms}ms, {len(content)} chars)"
            )

            return {
                "result": content,
                "cost": 0.0,  # TODO: HDR agent가 비용을 반환하면 추출
                "task_id": task.task_id,
                "status": "completed",
            }

        except Exception as e:
            elapsed_ms = int((time.time() - start) * 1000)
            logger.error(
                f"[HyperDeepWorkerActor] Failed ({elapsed_ms}ms): {task.description[:50]} | {e}"
            )
            return {
                "result": (
                    f"[HyperDeep 실행 오류: {task.description[:40]}] "
                    f"오류: {str(e)[:100]}"
                ),
                "cost": 0.0,
                "task_id": task.task_id,
                "status": "failed",
            }

    def _extract_content(self, output: Dict[str, Any]) -> str:
        """HyperDeepResearchAgent.execute() 반환값에서 본문 텍스트 추출."""
        if not output or not output.get("success"):
            return ""

        results = output.get("results", [])
        if not results:
            return ""

        first = results[0]
        if hasattr(first, "content"):
            return first.content or ""
        if isinstance(first, dict):
            return first.get("content", "")
        return str(first)


class RayExecutorPool:
    """HyperDeepWorkerActor 풀 관리자.

    pool_size는 HYPER_DEEP_MAX_TASKS_PER_LEVEL과 동일하게 설정하면
    모든 leaf 노드를 동시에 실행할 수 있다.

    사용 예:
        pool = RayExecutorPool(pool_size=3)
        await pool.warmup()
        future = pool.submit(task.to_dict(), context)
        result = await asyncio.wrap_future(future.future())
    """

    def __init__(self, pool_size: int = 3):
        self._pool_size = pool_size
        self._actors: List[HyperDeepWorkerActor] = [
            HyperDeepWorkerActor.remote()
            for _ in range(pool_size)
        ]
        self._next_idx = 0
        logger.info(f"[RayExecutorPool] Initialized with pool_size={pool_size}")

    async def warmup(self) -> None:
        """모든 Worker Actor의 초기화 완료를 대기.

        HyperDeepResearchAgent.__init__이 무거우므로
        첫 요청 전 warmup()을 호출하여 대기 시간 제거.
        """
        futures = [actor.ping.remote() for actor in self._actors]
        results = await asyncio.gather(*[
            asyncio.wrap_future(f.future()) for f in futures
        ])
        if not all(results):
            raise RuntimeError("일부 Worker Actor warmup 실패")
        logger.info(f"[RayExecutorPool] All {self._pool_size} workers ready")

    def submit(self, task_dict: Dict[str, Any], context: Dict[str, Any]) -> ray.ObjectRef:
        """라운드로빈으로 Actor를 선택하여 태스크를 제출.

        Returns:
            ray.ObjectRef — await asyncio.wrap_future(ref.future())로 결과 수신.
        """
        actor = self._actors[self._next_idx % self._pool_size]
        self._next_idx += 1
        return actor.execute.remote(task_dict, context)

    async def execute_all_parallel(
        self,
        tasks: List[Dict[str, Any]],
        context: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """독립 태스크 리스트를 Pool Worker들에게 병렬 제출 후 결과 반환.

        Args:
            tasks: RecursiveTaskNode.to_dict() 리스트 (모두 독립 — 동일 레벨)
            context: 공통 실행 컨텍스트

        Returns:
            각 태스크의 실행 결과 dict 리스트 (입력 순서와 동일)
        """
        futures = [
            self._actors[(self._next_idx + i) % self._pool_size].execute.remote(task, context)
            for i, task in enumerate(tasks)
        ]
        self._next_idx = (self._next_idx + len(tasks)) % self._pool_size
        return await asyncio.gather(*[
            asyncio.wrap_future(f.future()) for f in futures
        ])

    # Ray는 클러스터 종료 시 Actor를 자동으로 정리한다.
    # __del__에서 ray.kill()을 호출하면 인터프리터 종료 시 Ray가 이미
    # shutdown된 상태일 수 있어 불필요한 예외가 발생할 수 있으므로 생략.
