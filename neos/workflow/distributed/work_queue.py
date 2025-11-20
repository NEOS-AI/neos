"""
분산 작업 큐 및 부하 분산

우선순위 기반 작업 큐와 동적 워커 풀을 제공하여
효율적인 작업 분배와 부하 분산을 지원.
"""

import asyncio
import logging
import uuid
from typing import Dict, Any, List, Optional, Callable, Awaitable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from heapq import heappush, heappop

from .message_bus import MessageBus, Event, EventType, get_message_bus
from .agent_registry import (
    DistributedAgentRegistry,
    AgentCapability,
    AgentStatus,
    get_agent_registry
)

logger = logging.getLogger(__name__)


class TaskPriority(int, Enum):
    """작업 우선순위 (낮을수록 높은 우선순위)"""
    CRITICAL = 1
    HIGH = 2
    NORMAL = 5
    LOW = 7
    BACKGROUND = 10


class TaskStatus(str, Enum):
    """작업 상태"""
    PENDING = "pending"
    QUEUED = "queued"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(order=True)
class Task:
    """작업 데이터 클래스"""
    priority: int = field(compare=True)
    task_id: str = field(compare=False)
    description: str = field(default="", compare=False)
    required_capability: Optional[AgentCapability] = field(default=None, compare=False)
    payload: Dict[str, Any] = field(default_factory=dict, compare=False)
    requester: Optional[str] = field(default=None, compare=False)
    status: TaskStatus = field(default=TaskStatus.PENDING, compare=False)
    assigned_to: Optional[str] = field(default=None, compare=False)
    created_at: datetime = field(default_factory=datetime.utcnow, compare=False)
    started_at: Optional[datetime] = field(default=None, compare=False)
    completed_at: Optional[datetime] = field(default=None, compare=False)
    result: Optional[Dict[str, Any]] = field(default=None, compare=False)
    error: Optional[str] = field(default=None, compare=False)
    retry_count: int = field(default=0, compare=False)
    max_retries: int = field(default=3, compare=False)

    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환"""
        return {
            "task_id": self.task_id,
            "description": self.description,
            "priority": self.priority,
            "required_capability": (
                self.required_capability.value if self.required_capability else None
            ),
            "payload": self.payload,
            "requester": self.requester,
            "status": self.status.value,
            "assigned_to": self.assigned_to,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries
        }


class DistributedWorkQueue:
    """
    분산 작업 큐

    Features:
    - 우선순위 기반 작업 큐
    - 동적 워커 풀
    - 에이전트 능력 기반 작업 할당
    - 자동 재시도
    - 부하 분산
    """

    def __init__(
        self,
        message_bus: Optional[MessageBus] = None,
        registry: Optional[DistributedAgentRegistry] = None,
        num_workers: int = 5
    ):
        self.message_bus = message_bus
        self.registry = registry
        self.num_workers = num_workers

        # 우선순위 큐 (힙)
        self.task_heap: List[Task] = []

        # 작업 레지스트리 (ID로 빠른 조회)
        self.tasks: Dict[str, Task] = {}

        # 워커 풀
        self.workers: List[asyncio.Task] = []

        # 실행 중인 작업
        self.running_tasks: Dict[str, Task] = {}

        # 완료된 작업 (최근 100개만 보관)
        self.completed_tasks: List[Task] = []
        self.max_completed = 100

        # 통계
        self.stats = {
            "total_submitted": 0,
            "total_completed": 0,
            "total_failed": 0,
            "total_retried": 0
        }

        self.is_running = False
        self.initialized = False

    async def initialize(self):
        """작업 큐 초기화"""
        if self.initialized:
            return

        logger.info("[WorkQueue] Initializing work queue...")

        if self.message_bus is None:
            self.message_bus = await get_message_bus()

        if self.registry is None:
            self.registry = await get_agent_registry()

        # 이벤트 구독
        await self._setup_subscriptions()

        self.initialized = True
        logger.info("[WorkQueue] Work queue initialized")

    async def _setup_subscriptions(self):
        """이벤트 구독 설정"""
        await self.message_bus.subscribe(
            EventType.TASK_COMPLETED,
            self._handle_task_completed
        )
        await self.message_bus.subscribe(
            EventType.TASK_FAILED,
            self._handle_task_failed
        )

    async def start(self):
        """워커 풀 시작"""
        if self.is_running:
            logger.warning("[WorkQueue] Work queue is already running")
            return

        logger.info(f"[WorkQueue] Starting {self.num_workers} workers...")
        self.is_running = True

        # 워커 시작
        self.workers = [
            asyncio.create_task(self._worker(f"worker-{i}"))
            for i in range(self.num_workers)
        ]

        logger.info(f"[WorkQueue] {self.num_workers} workers started")

    async def stop(self):
        """워커 풀 중지"""
        logger.info("[WorkQueue] Stopping work queue...")
        self.is_running = False

        # 모든 워커 취소
        for worker in self.workers:
            worker.cancel()

        # 워커 종료 대기
        await asyncio.gather(*self.workers, return_exceptions=True)

        self.workers.clear()
        logger.info("[WorkQueue] Work queue stopped")

    async def submit_task(self, task: Task) -> str:
        """
        작업 제출

        Args:
            task: 제출할 작업

        Returns:
            작업 ID
        """
        logger.info(
            f"[WorkQueue] Submitting task {task.task_id} "
            f"with priority {task.priority}"
        )

        # 큐에 추가
        task.status = TaskStatus.QUEUED
        heappush(self.task_heap, task)
        self.tasks[task.task_id] = task

        self.stats["total_submitted"] += 1

        # 작업 제출 이벤트
        await self.message_bus.publish(Event(
            event_id=f"submit-{task.task_id}",
            event_type=EventType.TASK_SUBMITTED,
            source="work_queue",
            data=task.to_dict()
        ))

        logger.debug(
            f"[WorkQueue] Task {task.task_id} queued "
            f"(queue size: {len(self.task_heap)})"
        )

        return task.task_id

    async def submit_simple_task(
        self,
        description: str,
        capability: AgentCapability,
        payload: Dict[str, Any],
        priority: TaskPriority = TaskPriority.NORMAL,
        requester: Optional[str] = None
    ) -> str:
        """
        간단한 작업 제출

        Args:
            description: 작업 설명
            capability: 필요한 능력
            payload: 작업 데이터
            priority: 우선순위
            requester: 요청자

        Returns:
            작업 ID
        """
        task = Task(
            task_id=f"task-{uuid.uuid4().hex[:8]}",
            description=description,
            priority=priority.value,
            required_capability=capability,
            payload=payload,
            requester=requester
        )

        return await self.submit_task(task)

    async def _worker(self, worker_id: str):
        """워커 루프"""
        logger.info(f"[WorkQueue] Worker {worker_id} started")

        while self.is_running:
            try:
                # 큐에서 작업 가져오기
                task = await self._get_next_task()

                if task is None:
                    # 큐가 비었으면 대기
                    await asyncio.sleep(0.5)
                    continue

                # 작업 실행
                await self._execute_task(task, worker_id)

            except asyncio.CancelledError:
                logger.info(f"[WorkQueue] Worker {worker_id} cancelled")
                break
            except Exception as e:
                logger.error(f"[WorkQueue] Worker {worker_id} error: {e}", exc_info=True)
                await asyncio.sleep(1)

        logger.info(f"[WorkQueue] Worker {worker_id} ended")

    async def _get_next_task(self) -> Optional[Task]:
        """다음 작업 가져오기 (우선순위 순)"""
        if not self.task_heap:
            return None

        # 힙에서 최고 우선순위 작업 추출
        task = heappop(self.task_heap)

        # 상태 업데이트
        task.status = TaskStatus.ASSIGNED

        return task

    async def _execute_task(self, task: Task, worker_id: str):
        """작업 실행"""
        logger.info(
            f"[WorkQueue] Worker {worker_id} executing task {task.task_id}"
        )

        # 적절한 에이전트 선택
        if task.required_capability:
            agent = await self.registry.select_best_agent(
                task.required_capability,
                strategy="least_loaded"
            )

            if not agent:
                logger.warning(
                    f"[WorkQueue] No available agent for capability "
                    f"{task.required_capability.value}"
                )
                # 재시도
                await self._retry_task(task)
                return

            task.assigned_to = agent.agent_id
            logger.info(
                f"[WorkQueue] Task {task.task_id} assigned to {agent.agent_id}"
            )

        # 작업 시작
        task.status = TaskStatus.IN_PROGRESS
        task.started_at = datetime.utcnow()
        self.running_tasks[task.task_id] = task

        # 작업 시작 이벤트
        await self.message_bus.publish(Event(
            event_id=f"start-{task.task_id}",
            event_type=EventType.TASK_STARTED,
            source=worker_id,
            data=task.to_dict()
        ))

        # 작업이 실제로 실행되길 대기 (에이전트가 처리)
        # 여기서는 이벤트 기반으로 완료/실패를 대기

    async def _retry_task(self, task: Task):
        """작업 재시도"""
        if task.retry_count >= task.max_retries:
            logger.warning(
                f"[WorkQueue] Task {task.task_id} exceeded max retries, marking as failed"
            )
            task.status = TaskStatus.FAILED
            self.stats["total_failed"] += 1
            return

        task.retry_count += 1
        task.status = TaskStatus.QUEUED
        self.stats["total_retried"] += 1

        logger.info(
            f"[WorkQueue] Retrying task {task.task_id} "
            f"(attempt {task.retry_count}/{task.max_retries})"
        )

        # 다시 큐에 추가
        heappush(self.task_heap, task)

    async def _handle_task_completed(self, event: Event):
        """작업 완료 이벤트 처리"""
        task_id = event.data.get("task_id")

        if task_id and task_id in self.running_tasks:
            task = self.running_tasks[task_id]
            task.status = TaskStatus.COMPLETED
            task.completed_at = datetime.utcnow()
            task.result = event.data.get("result")

            # 실행 중 목록에서 제거
            del self.running_tasks[task_id]

            # 완료 목록에 추가
            self.completed_tasks.append(task)
            if len(self.completed_tasks) > self.max_completed:
                self.completed_tasks = self.completed_tasks[-self.max_completed:]

            self.stats["total_completed"] += 1

            logger.info(
                f"[WorkQueue] Task {task_id} completed by {event.source}"
            )

    async def _handle_task_failed(self, event: Event):
        """작업 실패 이벤트 처리"""
        task_id = event.data.get("task_id")

        if task_id and task_id in self.running_tasks:
            task = self.running_tasks[task_id]
            task.error = event.data.get("error")

            # 실행 중 목록에서 제거
            del self.running_tasks[task_id]

            # 재시도
            await self._retry_task(task)

            logger.warning(
                f"[WorkQueue] Task {task_id} failed: {task.error}"
            )

    def get_task(self, task_id: str) -> Optional[Task]:
        """작업 조회"""
        return self.tasks.get(task_id)

    def get_queue_size(self) -> int:
        """큐 크기 조회"""
        return len(self.task_heap)

    def get_running_tasks(self) -> List[Task]:
        """실행 중인 작업 조회"""
        return list(self.running_tasks.values())

    def get_statistics(self) -> Dict[str, Any]:
        """통계 조회"""
        return {
            **self.stats,
            "queue_size": len(self.task_heap),
            "running_tasks": len(self.running_tasks),
            "workers": len(self.workers),
            "average_wait_time": self._calculate_average_wait_time()
        }

    def _calculate_average_wait_time(self) -> float:
        """평균 대기 시간 계산"""
        if not self.completed_tasks:
            return 0.0

        total_wait = sum(
            (task.started_at - task.created_at).total_seconds()
            for task in self.completed_tasks
            if task.started_at
        )

        return total_wait / len(self.completed_tasks)


# 전역 작업 큐 싱글톤
_work_queue: Optional[DistributedWorkQueue] = None


async def get_work_queue() -> DistributedWorkQueue:
    """전역 작업 큐 인스턴스 가져오기"""
    global _work_queue

    if _work_queue is None:
        _work_queue = DistributedWorkQueue()
        await _work_queue.initialize()

    return _work_queue
