"""
자율 에이전트 베이스 클래스

작업을 스스로 발견하고, 다른 에이전트와 협력하며, 자율적으로 실행하는 에이전트.
기존 BaseAgent를 확장하여 분산 환경에 적합한 자율성 부여.
"""

import asyncio
import logging
import uuid
from typing import Dict, Any, List, Optional, Set
from datetime import datetime
from abc import abstractmethod

from neos.agents.base import BaseAgent
from neos.workflow.distributed import (
    MessageBus,
    Event,
    EventType,
    DistributedAgentRegistry,
    AgentMetadata,
    AgentCapability,
    AgentStatus,
    HierarchicalStateManager,
    get_message_bus,
    get_agent_registry,
    get_state_manager
)

logger = logging.getLogger(__name__)


class AutonomousAgent(BaseAgent):
    """
    자율 에이전트 베이스 클래스

    Features:
    - 작업 자동 발견 (메시지 버스 구독)
    - 능력 기반 작업 필터링
    - 다른 에이전트와 협력 요청/응답
    - 자율적 실행 루프
    - 상태 관리 및 공유
    """

    def __init__(
        self,
        name: str,
        llm,
        role: str,
        goal: str,
        backstory: str,
        capabilities: List[AgentCapability]
    ):
        super().__init__(name, llm, role, goal, backstory)

        # 에이전트 고유 ID
        self.agent_id = f"{name}-{uuid.uuid4().hex[:8]}"

        # 능력
        self.capabilities = capabilities

        # 분산 시스템 컴포넌트
        self.message_bus: Optional[MessageBus] = None
        self.registry: Optional[DistributedAgentRegistry] = None
        self.state_manager: Optional[HierarchicalStateManager] = None

        # 실행 상태
        self.status = AgentStatus.INITIALIZING
        self.is_running = False
        self.current_task = None

        # 작업 큐 (발견된 작업들)
        self.task_queue: asyncio.Queue = asyncio.Queue()

        # 실행 루프 태스크
        self.execution_loop_task: Optional[asyncio.Task] = None
        self.heartbeat_task: Optional[asyncio.Task] = None

        # 성능 메트릭
        self.tasks_completed = 0
        self.tasks_failed = 0
        self.total_response_time = 0.0

    async def initialize(self):
        """에이전트 초기화"""
        logger.info(f"[{self.name}] Initializing autonomous agent...")

        # 분산 시스템 컴포넌트 초기화
        self.message_bus = await get_message_bus()
        self.registry = await get_agent_registry()
        self.state_manager = await get_state_manager()

        # 레지스트리에 등록
        metadata = AgentMetadata(
            agent_id=self.agent_id,
            name=self.name,
            capabilities=self.capabilities,
            status=AgentStatus.AVAILABLE
        )
        await self.registry.register_agent(metadata)

        # 이벤트 구독 설정
        await self._setup_subscriptions()

        # 상태 초기화
        await self.state_manager.get_agent_state(self.agent_id)

        self.status = AgentStatus.AVAILABLE
        logger.info(f"[{self.name}] Autonomous agent initialized with ID: {self.agent_id}")

    async def _setup_subscriptions(self):
        """이벤트 구독 설정"""
        # 작업 제출 이벤트 구독
        await self.message_bus.subscribe(
            EventType.TASK_SUBMITTED,
            self._handle_task_submitted
        )

        # 협력 요청 이벤트 구독
        await self.message_bus.subscribe(
            EventType.COLLABORATION_REQUEST,
            self._handle_collaboration_request
        )

        logger.debug(f"[{self.name}] Event subscriptions set up")

    async def start(self):
        """에이전트 실행 시작"""
        if self.is_running:
            logger.warning(f"[{self.name}] Agent is already running")
            return

        logger.info(f"[{self.name}] Starting autonomous agent...")
        self.is_running = True

        # 실행 루프 시작
        self.execution_loop_task = asyncio.create_task(self._execution_loop())

        # Heartbeat 시작
        self.heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        logger.info(f"[{self.name}] Autonomous agent started")

    async def stop(self):
        """에이전트 중지"""
        logger.info(f"[{self.name}] Stopping autonomous agent...")
        self.is_running = False

        # 태스크 취소
        if self.execution_loop_task:
            self.execution_loop_task.cancel()
            try:
                await self.execution_loop_task
            except asyncio.CancelledError:
                pass

        if self.heartbeat_task:
            self.heartbeat_task.cancel()
            try:
                await self.heartbeat_task
            except asyncio.CancelledError:
                pass

        # 레지스트리에서 해제
        await self.registry.unregister_agent(self.agent_id)

        logger.info(f"[{self.name}] Autonomous agent stopped")

    async def _execution_loop(self):
        """자율 실행 루프"""
        logger.info(f"[{self.name}] Execution loop started")

        while self.is_running:
            try:
                # 작업 큐에서 작업 가져오기 (1초 타임아웃)
                try:
                    task_data = await asyncio.wait_for(
                        self.task_queue.get(),
                        timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue

                # 작업 실행
                await self._execute_task(task_data)

            except asyncio.CancelledError:
                logger.info(f"[{self.name}] Execution loop cancelled")
                break
            except Exception as e:
                logger.error(f"[{self.name}] Error in execution loop: {e}", exc_info=True)
                await asyncio.sleep(1)

        logger.info(f"[{self.name}] Execution loop ended")

    async def _execute_task(self, task_data: Dict[str, Any]):
        """작업 실행"""
        task_id = task_data.get("task_id", "unknown")
        logger.info(f"[{self.name}] Executing task: {task_id}")

        start_time = datetime.utcnow()
        self.current_task = task_id
        self.status = AgentStatus.BUSY

        # 상태 업데이트
        await self.state_manager.update_agent_state(
            self.agent_id,
            {"current_task": task_id, "progress": 0.0},
            broadcast=True
        )

        # 작업 시작 이벤트
        await self.message_bus.publish(Event(
            event_id=f"task-start-{task_id}",
            event_type=EventType.TASK_STARTED,
            source=self.agent_id,
            data={"task_id": task_id, "agent_id": self.agent_id}
        ))

        try:
            # 실제 작업 실행 (하위 클래스에서 구현)
            result = await self.execute_autonomous_task(task_data)

            # 성공 처리
            execution_time = (datetime.utcnow() - start_time).total_seconds()
            self.tasks_completed += 1
            self.total_response_time += execution_time

            # 작업 완료 이벤트
            await self.message_bus.publish(Event(
                event_id=f"task-complete-{task_id}",
                event_type=EventType.TASK_COMPLETED,
                source=self.agent_id,
                data={
                    "task_id": task_id,
                    "agent_id": self.agent_id,
                    "result": result,
                    "response_time": execution_time
                }
            ))

            logger.info(f"[{self.name}] Task {task_id} completed in {execution_time:.2f}s")

        except Exception as e:
            # 실패 처리
            self.tasks_failed += 1
            logger.error(f"[{self.name}] Task {task_id} failed: {e}", exc_info=True)

            # 작업 실패 이벤트
            await self.message_bus.publish(Event(
                event_id=f"task-failed-{task_id}",
                event_type=EventType.TASK_FAILED,
                source=self.agent_id,
                data={
                    "task_id": task_id,
                    "agent_id": self.agent_id,
                    "error": str(e)
                }
            ))

        finally:
            # 상태 복구
            self.current_task = None
            self.status = AgentStatus.AVAILABLE

            await self.state_manager.update_agent_state(
                self.agent_id,
                {"current_task": None, "progress": 1.0},
                broadcast=True
            )

    @abstractmethod
    async def execute_autonomous_task(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        자율 작업 실행 (하위 클래스에서 구현)

        Args:
            task_data: 작업 데이터

        Returns:
            실행 결과
        """
        pass

    async def _handle_task_submitted(self, event: Event):
        """작업 제출 이벤트 핸들러"""
        task_data = event.data

        # 내 능력으로 처리 가능한지 확인
        required_capability = task_data.get("required_capability")

        if required_capability:
            # 문자열인 경우 AgentCapability로 변환
            if isinstance(required_capability, str):
                try:
                    required_capability = AgentCapability(required_capability)
                except ValueError:
                    logger.warning(
                        f"[{self.name}] Unknown capability: {required_capability}"
                    )
                    return

            if required_capability not in self.capabilities:
                logger.debug(
                    f"[{self.name}] Task requires {required_capability}, skipping"
                )
                return

        # 작업 큐에 추가
        await self.task_queue.put(task_data)
        logger.info(
            f"[{self.name}] Task {task_data.get('task_id')} added to queue "
            f"(queue size: {self.task_queue.qsize()})"
        )

    async def _handle_collaboration_request(self, event: Event):
        """협력 요청 이벤트 핸들러"""
        request_data = event.data
        required_capability = request_data.get("required_capability")

        # 내 능력으로 도움을 줄 수 있는지 확인
        if isinstance(required_capability, str):
            try:
                required_capability = AgentCapability(required_capability)
            except ValueError:
                return

        if required_capability in self.capabilities:
            logger.info(
                f"[{self.name}] Received collaboration request for {required_capability}"
            )

            # 협력 응답 처리 (하위 클래스에서 오버라이드 가능)
            response = await self.handle_collaboration_request(request_data)

            if response:
                # 응답 전송
                await self.message_bus.reply(event, response, self.agent_id)

    async def handle_collaboration_request(
        self,
        request_data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        협력 요청 처리 (하위 클래스에서 오버라이드)

        Args:
            request_data: 요청 데이터

        Returns:
            응답 데이터 또는 None
        """
        # 기본 구현: 간단한 확인 응답
        return {
            "agent_id": self.agent_id,
            "can_help": True,
            "message": f"{self.name} is available to help"
        }

    async def request_collaboration(
        self,
        capability: AgentCapability,
        request_data: Dict[str, Any],
        timeout: float = 30.0
    ) -> Optional[Dict[str, Any]]:
        """
        다른 에이전트에게 협력 요청

        Args:
            capability: 필요한 능력
            request_data: 요청 데이터
            timeout: 타임아웃 (초)

        Returns:
            응답 데이터 또는 None
        """
        logger.info(f"[{self.name}] Requesting collaboration for {capability.value}")

        # 협력 요청 이벤트 생성
        request_event = Event(
            event_id=f"collab-req-{uuid.uuid4().hex[:8]}",
            event_type=EventType.COLLABORATION_REQUEST,
            source=self.agent_id,
            data={
                **request_data,
                "required_capability": capability.value,
                "requester": self.agent_id
            }
        )

        # 요청-응답 패턴 사용
        response_event = await self.message_bus.request(request_event, timeout=timeout)

        if response_event:
            logger.info(f"[{self.name}] Received collaboration response")
            return response_event.data
        else:
            logger.warning(f"[{self.name}] Collaboration request timed out")
            return None

    async def _heartbeat_loop(self):
        """Heartbeat 루프"""
        logger.info(f"[{self.name}] Heartbeat loop started")

        while self.is_running:
            try:
                await asyncio.sleep(30)  # 30초마다 heartbeat

                # Heartbeat 이벤트 발행
                await self.message_bus.publish(Event(
                    event_id=f"heartbeat-{self.agent_id}-{datetime.utcnow().timestamp()}",
                    event_type=EventType.AGENT_HEARTBEAT,
                    source=self.agent_id,
                    data={
                        "agent_id": self.agent_id,
                        "status": self.status.value,
                        "tasks_completed": self.tasks_completed,
                        "tasks_failed": self.tasks_failed
                    }
                ))

                logger.debug(f"[{self.name}] Heartbeat sent")

            except asyncio.CancelledError:
                logger.info(f"[{self.name}] Heartbeat loop cancelled")
                break
            except Exception as e:
                logger.error(f"[{self.name}] Error in heartbeat loop: {e}")

        logger.info(f"[{self.name}] Heartbeat loop ended")

    def get_metrics(self) -> Dict[str, Any]:
        """성능 메트릭 조회"""
        total_tasks = self.tasks_completed + self.tasks_failed
        success_rate = (
            self.tasks_completed / total_tasks if total_tasks > 0 else 0.0
        )
        avg_response_time = (
            self.total_response_time / self.tasks_completed
            if self.tasks_completed > 0 else 0.0
        )

        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "status": self.status.value,
            "capabilities": [c.value for c in self.capabilities],
            "tasks_completed": self.tasks_completed,
            "tasks_failed": self.tasks_failed,
            "success_rate": success_rate,
            "average_response_time": avg_response_time,
            "current_task": self.current_task,
            "queue_size": self.task_queue.qsize()
        }
