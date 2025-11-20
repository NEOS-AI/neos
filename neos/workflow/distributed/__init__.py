"""
분산 멀티에이전트 시스템 모듈

진정한 분산 처리를 위한 핵심 컴포넌트들:
- 이벤트 기반 메시지 버스
- 동적 에이전트 레지스트리
- 계층적 상태 관리
- 에이전트 협력 프로토콜
- 작업 큐 및 부하 분산
- Supervisor 패턴
- 분산 트랜잭션
"""

from .message_bus import MessageBus, Event, EventHandler
from .agent_registry import DistributedAgentRegistry, AgentMetadata, AgentCapability
from .state_manager import HierarchicalStateManager, AgentLocalState
from .collaboration import CollaborationProtocol, ContractNetProtocol
from .work_queue import DistributedWorkQueue, Task, TaskPriority
from .supervisor import AgentSupervisor, SupervisorStrategy
from .transaction import DistributedTransaction, SagaOrchestrator

__all__ = [
    # Message Bus
    "MessageBus",
    "Event",
    "EventHandler",

    # Agent Registry
    "DistributedAgentRegistry",
    "AgentMetadata",
    "AgentCapability",

    # State Management
    "HierarchicalStateManager",
    "AgentLocalState",

    # Collaboration
    "CollaborationProtocol",
    "ContractNetProtocol",

    # Work Queue
    "DistributedWorkQueue",
    "Task",
    "TaskPriority",

    # Supervisor
    "AgentSupervisor",
    "SupervisorStrategy",

    # Transaction
    "DistributedTransaction",
    "SagaOrchestrator",
]
