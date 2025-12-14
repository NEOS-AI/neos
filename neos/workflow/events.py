"""
워크플로우 이벤트 핸들러 - Dependency Injection 패턴

Observer Pattern을 사용하여 워크플로우 실행 중 이벤트를 처리합니다.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from datetime import datetime


# ============================================================================
# Observer Pattern: 이벤트 핸들러 인터페이스
# ============================================================================

class WorkflowEventHandler(ABC):
    """
    워크플로우 이벤트 핸들러 인터페이스

    워크플로우 실행 중 발생하는 이벤트를 처리하는 추상 클래스입니다.
    Dependency Injection 패턴을 통해 워크플로우에 주입됩니다.
    """

    @abstractmethod
    async def on_workflow_start(self, workflow_input: Dict[str, Any]):
        """워크플로우 시작"""
        pass

    @abstractmethod
    async def on_node_start(self, node_name: str, step: int, total_steps: int):
        """노드 시작"""
        pass

    @abstractmethod
    async def on_node_progress(self, node_name: str, message: str, progress: int = 0):
        """노드 진행 상황"""
        pass

    @abstractmethod
    async def on_node_complete(self, node_name: str, result: Dict[str, Any]):
        """노드 완료"""
        pass

    @abstractmethod
    async def on_workflow_complete(self, result: Dict[str, Any]):
        """워크플로우 완료"""
        pass

    @abstractmethod
    async def on_workflow_error(self, error: Exception, node_name: Optional[str] = None):
        """워크플로우 에러"""
        pass


# ============================================================================
# Null Object Pattern: 기본 핸들러 (아무 동작도 하지 않음)
# ============================================================================

class NullEventHandler(WorkflowEventHandler):
    """
    Null Object Pattern 구현

    이벤트 핸들러가 제공되지 않았을 때 사용하는 기본 핸들러입니다.
    모든 메서드가 아무 동작도 하지 않으므로 성능 오버헤드가 없습니다.
    """

    async def on_workflow_start(self, workflow_input: Dict[str, Any]):
        pass

    async def on_node_start(self, node_name: str, step: int, total_steps: int):
        pass

    async def on_node_progress(self, node_name: str, message: str, progress: int = 0):
        pass

    async def on_node_complete(self, node_name: str, result: Dict[str, Any]):
        pass

    async def on_workflow_complete(self, result: Dict[str, Any]):
        pass

    async def on_workflow_error(self, error: Exception, node_name: Optional[str] = None):
        pass


# ============================================================================
# Composite Pattern: 여러 핸들러를 하나로 결합
# ============================================================================

class CompositeEventHandler(WorkflowEventHandler):
    """
    여러 이벤트 핸들러를 하나로 결합하는 Composite 핸들러

    여러 옵저버가 동시에 이벤트를 수신해야 할 때 사용합니다.
    예: 로깅 + 메트릭 수집 + UI 업데이트
    """

    def __init__(self, handlers: list[WorkflowEventHandler]):
        self.handlers = handlers

    async def on_workflow_start(self, workflow_input: Dict[str, Any]):
        for handler in self.handlers:
            await handler.on_workflow_start(workflow_input)

    async def on_node_start(self, node_name: str, step: int, total_steps: int):
        for handler in self.handlers:
            await handler.on_node_start(node_name, step, total_steps)

    async def on_node_progress(self, node_name: str, message: str, progress: int = 0):
        for handler in self.handlers:
            await handler.on_node_progress(node_name, message, progress)

    async def on_node_complete(self, node_name: str, result: Dict[str, Any]):
        for handler in self.handlers:
            await handler.on_node_complete(node_name, result)

    async def on_workflow_complete(self, result: Dict[str, Any]):
        for handler in self.handlers:
            await handler.on_workflow_complete(result)

    async def on_workflow_error(self, error: Exception, node_name: Optional[str] = None):
        for handler in self.handlers:
            await handler.on_workflow_error(error, node_name)


# ============================================================================
# 로깅 핸들러 예제
# ============================================================================

class LoggingEventHandler(WorkflowEventHandler):
    """
    로깅 전용 이벤트 핸들러

    워크플로우 이벤트를 로그로 기록합니다.
    """

    def __init__(self, logger=None):
        self.logger = logger
        self.start_time = None

    async def on_workflow_start(self, workflow_input: Dict[str, Any]):
        self.start_time = datetime.utcnow()
        if self.logger:
            self.logger.info(f"Workflow started: {workflow_input.get('query', 'N/A')[:100]}")

    async def on_node_start(self, node_name: str, step: int, total_steps: int):
        if self.logger:
            self.logger.info(f"Node started: {node_name} (step {step}/{total_steps})")

    async def on_node_progress(self, node_name: str, message: str, progress: int = 0):
        if self.logger:
            self.logger.debug(f"Node progress: {node_name} - {message} ({progress}%)")

    async def on_node_complete(self, node_name: str, result: Dict[str, Any]):
        if self.logger:
            self.logger.info(f"Node completed: {node_name}")

    async def on_workflow_complete(self, result: Dict[str, Any]):
        if self.logger and self.start_time:
            elapsed = (datetime.utcnow() - self.start_time).total_seconds()
            self.logger.info(f"Workflow completed in {elapsed:.2f}s")

    async def on_workflow_error(self, error: Exception, node_name: Optional[str] = None):
        if self.logger:
            self.logger.error(f"Workflow error at {node_name}: {str(error)}")
