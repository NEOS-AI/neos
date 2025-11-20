"""
분산 트랜잭션 지원 (Saga 패턴)

여러 에이전트가 협력하는 복잡한 워크플로우에서
데이터 일관성을 보장하기 위한 Saga 패턴 구현.
"""

import asyncio
import logging
import uuid
from typing import Dict, Any, List, Optional, Callable, Awaitable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from .message_bus import MessageBus, Event, EventType, get_message_bus

logger = logging.getLogger(__name__)


class SagaStatus(str, Enum):
    """Saga 상태"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPENSATING = "compensating"  # 롤백 중
    COMPLETED = "completed"
    FAILED = "failed"
    COMPENSATED = "compensated"  # 롤백 완료


class StepStatus(str, Enum):
    """Saga 단계 상태"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    COMPENSATING = "compensating"
    COMPENSATED = "compensated"


@dataclass
class SagaStep:
    """Saga 단계"""
    step_id: str
    name: str
    execute: Callable[..., Awaitable[Dict[str, Any]]]  # 실행 함수
    compensate: Callable[..., Awaitable[None]]  # 보상 트랜잭션 (롤백)
    payload: Dict[str, Any] = field(default_factory=dict)
    status: StepStatus = StepStatus.PENDING
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_id": self.step_id,
            "name": self.name,
            "payload": self.payload,
            "status": self.status.value,
            "result": self.result,
            "error": self.error,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None
        }


@dataclass
class Saga:
    """Saga 트랜잭션"""
    saga_id: str
    name: str
    steps: List[SagaStep]
    status: SagaStatus = SagaStatus.PENDING
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    current_step_index: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "saga_id": self.saga_id,
            "name": self.name,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "current_step_index": self.current_step_index,
            "total_steps": len(self.steps),
            "steps": [step.to_dict() for step in self.steps],
            "metadata": self.metadata
        }


class SagaOrchestrator:
    """
    Saga 오케스트레이터

    Features:
    - Forward recovery: 단계별 실행
    - Backward recovery: 실패 시 보상 트랜잭션으로 롤백
    - 이벤트 기반 상태 추적
    - 병렬 단계 실행 지원
    """

    def __init__(self, message_bus: Optional[MessageBus] = None):
        self.message_bus = message_bus

        # 실행 중인 Saga들
        self.running_sagas: Dict[str, Saga] = {}

        # 완료된 Saga들 (최근 100개)
        self.completed_sagas: List[Saga] = []
        self.max_completed = 100

        # 통계
        self.stats = {
            "total_started": 0,
            "total_completed": 0,
            "total_failed": 0,
            "total_compensated": 0
        }

        self.initialized = False

    async def initialize(self):
        """오케스트레이터 초기화"""
        if self.initialized:
            return

        logger.info("[SagaOrchestrator] Initializing Saga orchestrator...")

        if self.message_bus is None:
            self.message_bus = await get_message_bus()

        self.initialized = True
        logger.info("[SagaOrchestrator] Saga orchestrator initialized")

    async def execute_saga(self, saga: Saga) -> bool:
        """
        Saga 실행

        Args:
            saga: 실행할 Saga

        Returns:
            성공 여부
        """
        logger.info(f"[SagaOrchestrator] Starting Saga {saga.saga_id}: {saga.name}")

        saga.status = SagaStatus.IN_PROGRESS
        saga.started_at = datetime.utcnow()
        self.running_sagas[saga.saga_id] = saga
        self.stats["total_started"] += 1

        # Saga 시작 이벤트
        await self.message_bus.publish(Event(
            event_id=f"saga-start-{saga.saga_id}",
            event_type=EventType.WORKFLOW_STARTED,
            source="saga_orchestrator",
            data={
                "saga_id": saga.saga_id,
                "name": saga.name,
                "total_steps": len(saga.steps)
            }
        ))

        try:
            # Forward recovery: 단계별 실행
            for i, step in enumerate(saga.steps):
                saga.current_step_index = i

                success = await self._execute_step(saga, step)

                if not success:
                    # 실패 시 보상 트랜잭션 실행
                    logger.error(
                        f"[SagaOrchestrator] Step {step.name} failed, "
                        f"starting compensation"
                    )
                    await self._compensate_saga(saga, i)
                    saga.status = SagaStatus.COMPENSATED
                    self.stats["total_compensated"] += 1
                    return False

            # 모든 단계 성공
            saga.status = SagaStatus.COMPLETED
            saga.completed_at = datetime.utcnow()
            self.stats["total_completed"] += 1

            logger.info(
                f"[SagaOrchestrator] Saga {saga.saga_id} completed successfully"
            )

            # Saga 완료 이벤트
            await self.message_bus.publish(Event(
                event_id=f"saga-complete-{saga.saga_id}",
                event_type=EventType.WORKFLOW_COMPLETED,
                source="saga_orchestrator",
                data=saga.to_dict()
            ))

            return True

        except Exception as e:
            logger.error(f"[SagaOrchestrator] Saga {saga.saga_id} failed: {e}", exc_info=True)

            # 예외 발생 시에도 보상 트랜잭션 실행
            await self._compensate_saga(saga, saga.current_step_index)
            saga.status = SagaStatus.FAILED
            self.stats["total_failed"] += 1

            # Saga 실패 이벤트
            await self.message_bus.publish(Event(
                event_id=f"saga-failed-{saga.saga_id}",
                event_type=EventType.WORKFLOW_FAILED,
                source="saga_orchestrator",
                data={
                    **saga.to_dict(),
                    "error": str(e)
                }
            ))

            return False

        finally:
            # 실행 중 목록에서 제거
            if saga.saga_id in self.running_sagas:
                del self.running_sagas[saga.saga_id]

            # 완료 목록에 추가
            self.completed_sagas.append(saga)
            if len(self.completed_sagas) > self.max_completed:
                self.completed_sagas = self.completed_sagas[-self.max_completed:]

    async def _execute_step(self, saga: Saga, step: SagaStep) -> bool:
        """Saga 단계 실행"""
        logger.info(
            f"[SagaOrchestrator] Executing step {step.name} in Saga {saga.saga_id}"
        )

        step.status = StepStatus.IN_PROGRESS
        step.started_at = datetime.utcnow()

        # 단계 시작 이벤트
        await self.message_bus.publish(Event(
            event_id=f"saga-step-start-{step.step_id}",
            event_type=EventType.WORKFLOW_STEP_COMPLETED,
            source="saga_orchestrator",
            data={
                "saga_id": saga.saga_id,
                "step_id": step.step_id,
                "step_name": step.name,
                "status": "started"
            }
        ))

        try:
            # 단계 실행
            result = await step.execute(**step.payload)

            step.status = StepStatus.COMPLETED
            step.result = result
            step.completed_at = datetime.utcnow()

            logger.info(
                f"[SagaOrchestrator] Step {step.name} completed "
                f"in {(step.completed_at - step.started_at).total_seconds():.2f}s"
            )

            # 단계 완료 이벤트
            await self.message_bus.publish(Event(
                event_id=f"saga-step-complete-{step.step_id}",
                event_type=EventType.WORKFLOW_STEP_COMPLETED,
                source="saga_orchestrator",
                data={
                    "saga_id": saga.saga_id,
                    "step_id": step.step_id,
                    "step_name": step.name,
                    "status": "completed",
                    "result": result
                }
            ))

            return True

        except Exception as e:
            step.status = StepStatus.FAILED
            step.error = str(e)
            step.completed_at = datetime.utcnow()

            logger.error(
                f"[SagaOrchestrator] Step {step.name} failed: {e}",
                exc_info=True
            )

            return False

    async def _compensate_saga(self, saga: Saga, failed_step_index: int):
        """
        Saga 보상 (롤백)

        실패한 단계 이전의 모든 단계를 역순으로 보상 트랜잭션 실행

        Args:
            saga: Saga 트랜잭션
            failed_step_index: 실패한 단계 인덱스
        """
        logger.info(
            f"[SagaOrchestrator] Compensating Saga {saga.saga_id} "
            f"from step {failed_step_index}"
        )

        saga.status = SagaStatus.COMPENSATING

        # 실패한 단계 이전의 성공한 단계들을 역순으로 보상
        for i in range(failed_step_index - 1, -1, -1):
            step = saga.steps[i]

            if step.status != StepStatus.COMPLETED:
                continue

            logger.info(
                f"[SagaOrchestrator] Compensating step {step.name}"
            )

            step.status = StepStatus.COMPENSATING

            try:
                # 보상 트랜잭션 실행
                await step.compensate(**step.payload)

                step.status = StepStatus.COMPENSATED

                logger.info(f"[SagaOrchestrator] Step {step.name} compensated")

            except Exception as e:
                logger.error(
                    f"[SagaOrchestrator] Failed to compensate step {step.name}: {e}",
                    exc_info=True
                )
                # 보상 실패는 로그만 남기고 계속 진행

        logger.info(f"[SagaOrchestrator] Saga {saga.saga_id} compensation completed")

    def get_saga(self, saga_id: str) -> Optional[Saga]:
        """Saga 조회"""
        # 실행 중인 Saga
        if saga_id in self.running_sagas:
            return self.running_sagas[saga_id]

        # 완료된 Saga
        for saga in self.completed_sagas:
            if saga.saga_id == saga_id:
                return saga

        return None

    def get_running_sagas(self) -> List[Saga]:
        """실행 중인 Saga 목록"""
        return list(self.running_sagas.values())

    def get_statistics(self) -> Dict[str, Any]:
        """통계 조회"""
        return {
            **self.stats,
            "running_sagas": len(self.running_sagas),
            "success_rate": (
                self.stats["total_completed"] / self.stats["total_started"]
                if self.stats["total_started"] > 0 else 0.0
            )
        }


class DistributedTransaction:
    """
    분산 트랜잭션 헬퍼

    Saga 패턴을 사용한 분산 트랜잭션 구축을 쉽게 해주는 헬퍼 클래스
    """

    def __init__(self, name: str, orchestrator: Optional[SagaOrchestrator] = None):
        self.name = name
        self.orchestrator = orchestrator
        self.steps: List[SagaStep] = []

    async def initialize(self):
        """초기화"""
        if self.orchestrator is None:
            self.orchestrator = await get_saga_orchestrator()

    def add_step(
        self,
        name: str,
        execute: Callable,
        compensate: Callable,
        payload: Optional[Dict[str, Any]] = None
    ) -> "DistributedTransaction":
        """
        Saga 단계 추가

        Args:
            name: 단계 이름
            execute: 실행 함수
            compensate: 보상 트랜잭션 함수
            payload: 페이로드

        Returns:
            자기 자신 (체이닝 가능)
        """
        step = SagaStep(
            step_id=f"step-{uuid.uuid4().hex[:8]}",
            name=name,
            execute=execute,
            compensate=compensate,
            payload=payload or {}
        )

        self.steps.append(step)
        return self

    async def execute(self) -> bool:
        """트랜잭션 실행"""
        if not self.orchestrator:
            await self.initialize()

        saga = Saga(
            saga_id=f"saga-{uuid.uuid4().hex[:8]}",
            name=self.name,
            steps=self.steps
        )

        return await self.orchestrator.execute_saga(saga)


# 전역 Saga 오케스트레이터 싱글톤
_saga_orchestrator: Optional[SagaOrchestrator] = None


async def get_saga_orchestrator() -> SagaOrchestrator:
    """전역 Saga 오케스트레이터 인스턴스 가져오기"""
    global _saga_orchestrator

    if _saga_orchestrator is None:
        _saga_orchestrator = SagaOrchestrator()
        await _saga_orchestrator.initialize()

    return _saga_orchestrator
