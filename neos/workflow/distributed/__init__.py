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

from .message_bus import (
    MessageBus,
    Event,
    EventHandler,
    EventType,
    get_message_bus
)
from .agent_registry import (
    DistributedAgentRegistry,
    AgentMetadata,
    AgentCapability,
    AgentStatus,
    get_agent_registry
)
from .state_manager import (
    HierarchicalStateManager,
    AgentLocalState,
    get_state_manager
)
from .collaboration import (
    CollaborationProtocol,
    ContractNetProtocol,
    get_collaboration_protocol
)
from .work_queue import (
    DistributedWorkQueue,
    Task,
    TaskPriority,
    TaskStatus,
    get_work_queue
)
from .supervisor import (
    AgentSupervisor,
    SupervisorStrategy,
    get_supervisor
)
from .transaction import (
    DistributedTransaction,
    SagaOrchestrator,
    get_saga_orchestrator
)

__all__ = [
    # Message Bus
    "MessageBus",
    "Event",
    "EventHandler",
    "EventType",
    "get_message_bus",

    # Agent Registry
    "DistributedAgentRegistry",
    "AgentMetadata",
    "AgentCapability",
    "AgentStatus",
    "get_agent_registry",

    # State Management
    "HierarchicalStateManager",
    "AgentLocalState",
    "get_state_manager",

    # Collaboration
    "CollaborationProtocol",
    "ContractNetProtocol",
    "get_collaboration_protocol",

    # Work Queue
    "DistributedWorkQueue",
    "Task",
    "TaskPriority",
    "TaskStatus",
    "get_work_queue",

    # Supervisor
    "AgentSupervisor",
    "SupervisorStrategy",
    "get_supervisor",

    # Transaction
    "DistributedTransaction",
    "SagaOrchestrator",
    "get_saga_orchestrator",
]
