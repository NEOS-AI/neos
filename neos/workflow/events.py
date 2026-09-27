"""
워크플로우 이벤트 핸들러 - Dependency Injection 패턴

Observer Pattern을 사용하여 워크플로우 실행 중 이벤트를 처리합니다.
"""

import logging
import statistics
import time
from abc import ABC, abstractmethod
from collections import defaultdict, deque
from collections.abc import Sequence
from typing import Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

# ============================================================================
# 노드별 메타데이터 (SSE 진행 상황 이벤트용)
# ============================================================================

NODE_LABELS: Dict[str, str] = {
    "refinement_checker": "Checking query clarity",
    "query_refinement_agent": "Refining query",
    "conversation_context_processor": "Processing conversation context",
    "query_classifier": "Classifying intent",
    "skill_tool_selector": "Selecting tools and skills",
    "search_orchestrator": "Searching sources",
    "analysis_orchestrator": "Analyzing results",
    "generation_orchestrator": "Generating content",
    "result_integrator": "Integrating results",
    "fact_check": "Verifying facts",
    "quality_validator": "Validating quality",
    "mission_planner": "Planning mission",
    "mission_approval": "Waiting for mission approval",
    "mission_executor": "Executing mission",
    "mission_validator": "Validating mission",
    "mission_integrator": "Integrating mission results",
    "response_generator": "Generating response",
    # 트랙 I 서브에이전트 템플릿 노드 (neos/workflow/subagent_nodes.py). 이 모듈은
    # 템플릿 레지스트리를 import 하지 않는다(neos.subagent 가 따라 올라온다) --
    # 대신 `tests/workflow/test_subagent_node_labels.py` 가 **양방향으로** 짝을 건다:
    # 템플릿마다 라벨이 있고 `template.label` 과 같으며, 템플릿도 정적 노드도 아닌
    # 라벨은 없다. 라벨이 없으면 진행 이벤트가 노드 이름을 title-case 로 보여 준다.
    "explore_web": "Investigating with a subagent",
}

# 노드별 예상 소요 시간 (초) — 초기 정적 값 (히스토리가 없을 때 fallback)
_STATIC_DURATIONS: Dict[str, float] = {
    "refinement_checker": 1.0,
    "query_refinement_agent": 3.0,
    "conversation_context_processor": 2.0,
    "query_classifier": 2.0,
    "skill_tool_selector": 1.5,
    "search_orchestrator": 15.0,
    "analysis_orchestrator": 8.0,
    "generation_orchestrator": 5.0,
    "result_integrator": 3.0,
    "fact_check": 6.0,
    "quality_validator": 2.0,
    "mission_planner": 2.0,
    "mission_approval": 1.0,
    "mission_executor": 15.0,
    "mission_validator": 3.0,
    "mission_integrator": 1.0,
    "response_generator": 4.0,
}

# 하위 호환성을 위해 기존 이름 유지
NODE_ESTIMATED_DURATIONS = _STATIC_DURATIONS

# 워크플로우에서 추적하는 노드 순서 (ETA 계산에 사용)
WORKFLOW_NODE_ORDER = list(_STATIC_DURATIONS.keys())


# ============================================================================
# 동적 ETA: in-memory 실행 시간 추적 (L-3 해결)
# ============================================================================

# 노드별 최근 실행 시간 히스토리 (프로세스 수명 동안 유지)
_HISTORY_MAX_SIZE = 50
_node_duration_history: Dict[str, deque] = defaultdict(
    lambda: deque(maxlen=_HISTORY_MAX_SIZE)
)
# 현재 실행 중인 노드의 시작 시간
_node_start_times: Dict[str, float] = {}
# 동적 ETA 사용을 위한 최소 히스토리 수
_MIN_HISTORY_FOR_DYNAMIC = 3


def record_node_start(node_name: str, workflow_id: str = "") -> None:
    """노드 실행 시작 시간을 기록합니다.

    Args:
        node_name: 노드 이름
        workflow_id: 워크플로우(세션) ID. 동시 실행 시 타이밍 격리를 위해 사용.
    """
    key = f"{workflow_id}:{node_name}" if workflow_id else node_name
    _node_start_times[key] = time.monotonic()


def record_node_end(node_name: str, workflow_id: str = "") -> Optional[float]:
    """노드 실행 완료를 기록하고 소요 시간을 반환합니다.

    Args:
        node_name: 노드 이름
        workflow_id: 워크플로우(세션) ID. record_node_start와 동일한 값 사용.

    Returns:
        소요 시간(초), 시작 시간이 없으면 None
    """
    key = f"{workflow_id}:{node_name}" if workflow_id else node_name
    start = _node_start_times.pop(key, None)
    if start is None:
        return None

    duration = time.monotonic() - start
    _node_duration_history[node_name].append(duration)
    logger.debug(
        f"[ETA] Node {node_name} took {duration:.2f}s "
        f"(history size: {len(_node_duration_history[node_name])})"
    )
    return duration


def get_estimated_duration(node_name: str) -> float:
    """노드의 예상 소요 시간을 반환합니다.

    히스토리가 충분하면 중앙값(median)을 사용하고,
    그렇지 않으면 정적 기본값으로 fallback합니다.
    """
    history = _node_duration_history.get(node_name)
    if history and len(history) >= _MIN_HISTORY_FOR_DYNAMIC:
        return statistics.median(history)
    return _STATIC_DURATIONS.get(node_name, 3.0)


def get_node_label(node_name: str) -> str:
    """노드 이름에 대한 사람이 읽을 수 있는 레이블을 반환합니다."""
    return NODE_LABELS.get(node_name, node_name.replace("_", " ").title())


def estimate_remaining_time(
    current_node: str, *, candidates: Sequence[str]
) -> float:
    """아직 도달하지 않은 노드들의 예상 소요 시간 합.

    `candidates` 를 호출자가 넘기는 이유: 옛 구현은 모듈 전역
    `WORKFLOW_NODE_ORDER` 를 기준으로 `index(current_node)` 이후를 셌다.
    그 목록에 없는 노드에는 `ValueError` 를 잡아 **0.0** 을 돌려줬는데,
    설계된 그래프(`graph_design_enabled`)의 노드는 전부 그 목록 밖이라
    사용자가 매 단계 "남은 시간 0초" 를 보게 된다. 이벤트가 아예 안 나가는
    것보다 나쁘다 -- 사용자는 틀린 값을 안다고 믿는다.

    ⚠️ **여전히 과대추정이다.** 조건부 분기로 실제로는 가지 않을 노드가
    `candidates` 에 섞여 있다. 정확히 하려면 런타임 상태에 의존하는 분기
    조건을 실행 전에 알아야 하는데 그럴 수 없다. 이 값은 **상한**이며,
    지금과 달라진 것은 (a) 이 그래프에 없는 노드가 빠지고 (b) 0 이라
    거짓말하지 않는다는 두 가지다.
    """

    return sum(get_estimated_duration(node) for node in candidates)


def get_duration_stats() -> Dict[str, Any]:
    """ETA 추적 통계를 반환합니다 (디버깅/모니터링용)."""
    stats = {}
    for node_name in WORKFLOW_NODE_ORDER:
        history = _node_duration_history.get(node_name)
        if history and len(history) > 0:
            hist_list = list(history)
            stats[node_name] = {
                "static": _STATIC_DURATIONS.get(node_name, 3.0),
                "dynamic": statistics.median(hist_list),
                "min": min(hist_list),
                "max": max(hist_list),
                "samples": len(hist_list),
                "using": "dynamic" if len(hist_list) >= _MIN_HISTORY_FOR_DYNAMIC else "static",
            }
        else:
            stats[node_name] = {
                "static": _STATIC_DURATIONS.get(node_name, 3.0),
                "samples": 0,
                "using": "static",
            }
    return stats


def forward_graph_subagent_event(
    handler: Any, kind: str, payload: Dict[str, Any]
) -> None:
    """설계 그래프 서브에이전트 노드의 진행을 스트림 핸들러로 넘긴다.

    서브에이전트 호스트의 `emit` 은 **동기**이고 노드 코루틴 한가운데서 불린다.
    그래서 핸들러 쪽 훅(`on_graph_subagent_event`)도 동기다 -- 비동기 태스크로
    띄우면 뒤따르는 `node_completed` 보다 늦게 도착할 수 있다.

    훅이 없는 핸들러(`NullEventHandler` 등)는 조용히 넘어가고, 훅이 던져도 삼킨다:
    진행 표시는 버려도 되는 정보이고 그래프 실행을 멈출 이유가 아니다.
    """
    hook = getattr(handler, "on_graph_subagent_event", None)
    if hook is None:
        return
    try:
        hook(kind, payload)
    except Exception:  # noqa: BLE001
        logger.warning("graph subagent stream forward failed kind=%s", kind, exc_info=True)


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
    async def on_node_start(
        self,
        node_name: str,
        step: int,
        total_steps: int,
        step_name: Optional[str] = None,
        estimated_remaining_s: Optional[float] = None,
    ):
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

    @abstractmethod
    async def on_approval_request(
        self,
        pending_approvals: list,
        session_id: str,
    ) -> None:
        """interrupt_before=EXECUTION_APPROVAL 발동 시 승인 요청 이벤트.

        클라이언트는 이 이벤트를 받으면 POST /api/v1/approval/respond를 호출해야 한다.
        """
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

    async def on_node_start(
        self,
        node_name: str,
        step: int,
        total_steps: int,
        step_name: Optional[str] = None,
        estimated_remaining_s: Optional[float] = None,
    ):
        pass

    async def on_node_progress(self, node_name: str, message: str, progress: int = 0):
        pass

    async def on_node_complete(self, node_name: str, result: Dict[str, Any]):
        pass

    async def on_workflow_complete(self, result: Dict[str, Any]):
        pass

    async def on_workflow_error(self, error: Exception, node_name: Optional[str] = None):
        pass

    async def on_approval_request(self, pending_approvals: list, session_id: str) -> None:
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

    async def on_node_start(
        self,
        node_name: str,
        step: int,
        total_steps: int,
        step_name: Optional[str] = None,
        estimated_remaining_s: Optional[float] = None,
    ):
        for handler in self.handlers:
            await handler.on_node_start(node_name, step, total_steps, step_name, estimated_remaining_s)

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

    async def on_approval_request(self, pending_approvals: list, session_id: str) -> None:
        for handler in self.handlers:
            await handler.on_approval_request(pending_approvals, session_id)


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
        self.start_time = datetime.now()
        if self.logger:
            self.logger.info(f"Workflow started: {workflow_input.get('query', 'N/A')[:100]}")

    async def on_node_start(
        self,
        node_name: str,
        step: int,
        total_steps: int,
        step_name: Optional[str] = None,
        estimated_remaining_s: Optional[float] = None,
    ):
        if self.logger:
            label = step_name or node_name
            self.logger.info(f"Node started: {label} (step {step}/{total_steps})")

    async def on_node_progress(self, node_name: str, message: str, progress: int = 0):
        if self.logger:
            self.logger.debug(f"Node progress: {node_name} - {message} ({progress}%)")

    async def on_node_complete(self, node_name: str, result: Dict[str, Any]):
        if self.logger:
            self.logger.info(f"Node completed: {node_name}")

    async def on_workflow_complete(self, result: Dict[str, Any]):
        if self.logger and self.start_time:
            elapsed = (datetime.now() - self.start_time).total_seconds()
            self.logger.info(f"Workflow completed in {elapsed:.2f}s")

    async def on_workflow_error(self, error: Exception, node_name: Optional[str] = None):
        if self.logger:
            self.logger.error(f"Workflow error at {node_name}: {str(error)}")
