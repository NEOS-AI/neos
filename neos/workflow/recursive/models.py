"""
ROMA 재귀 에이전트 데이터 모델

RecursiveTaskNode: 재귀 태스크 트리의 단일 노드
TaskAtomicity: 태스크 원자성 판별 결과 Enum
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class TaskAtomicity(Enum):
    ATOMIC = "atomic"           # 직접 실행 가능
    DECOMPOSABLE = "decomposable"  # 분해 필요
    UNKNOWN = "unknown"         # 미판별


class TaskStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class RecursiveTaskNode:
    """재귀 태스크 트리의 단일 노드.

    PostgreSQL 체크포인터와의 호환을 위해 JSON 직렬화 가능한 형태로 설계됨.
    실제 객체는 실행 중에만 메모리에 유지되고, 상태 저장 시 to_dict()로 직렬화.
    """
    description: str                          # 태스크 설명
    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    parent_id: Optional[str] = None           # 부모 태스크 ID (루트는 None)
    depth: int = 0                            # 재귀 깊이 (루트=0)
    atomicity: TaskAtomicity = TaskAtomicity.UNKNOWN
    status: TaskStatus = TaskStatus.PENDING
    result: Optional[str] = None             # 실행 결과
    children: List[RecursiveTaskNode] = field(default_factory=list)
    depends_on: List[str] = field(default_factory=list)
    artifact_ref: Optional[str] = None
    attempts: int = 0
    harness_run_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    cost: float = 0.0                        # 실행 비용 (USD)
    execution_time_ms: int = 0

    def description_hash(self) -> str:
        """순환 참조 감지를 위한 태스크 설명 해시."""
        return hashlib.md5(
            self.description.strip().lower().encode(), usedforsecurity=False
        ).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        """JSON 직렬화 (PostgreSQL 체크포인터 호환)."""
        return {
            "task_id": self.task_id,
            "parent_id": self.parent_id,
            "depth": self.depth,
            "description": self.description,
            "atomicity": self.atomicity.value,
            "status": self.status.value,
            "result": self.result,
            "children": [c.to_dict() for c in self.children],
            "depends_on": self.depends_on,
            "artifact_ref": self.artifact_ref,
            "attempts": self.attempts,
            "harness_run_id": self.harness_run_id,
            "metadata": self.metadata,
            "cost": self.cost,
            "execution_time_ms": self.execution_time_ms,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> RecursiveTaskNode:
        """JSON 역직렬화."""
        node = cls(
            task_id=data["task_id"],
            parent_id=data.get("parent_id"),
            depth=data.get("depth", 0),
            description=data["description"],
            atomicity=TaskAtomicity(data.get("atomicity", TaskAtomicity.UNKNOWN.value)),
            status=TaskStatus(data.get("status", TaskStatus.PENDING.value)),
            result=data.get("result"),
            depends_on=data.get("depends_on", []),
            artifact_ref=data.get("artifact_ref"),
            attempts=data.get("attempts", 0),
            harness_run_id=data.get("harness_run_id"),
            metadata=data.get("metadata", {}),
            cost=data.get("cost", 0.0),
            execution_time_ms=data.get("execution_time_ms", 0),
        )
        node.children = [cls.from_dict(c) for c in data.get("children", [])]
        return node

    def total_cost(self) -> float:
        """이 노드와 모든 자식 노드의 누적 비용."""
        return self.cost + sum(c.total_cost() for c in self.children)

    def is_leaf(self) -> bool:
        return len(self.children) == 0


def extract_llm_cost(response: Any, model: str, provider: str = "anthropic") -> float:
    """LLM 응답에서 토큰 사용량을 파싱하여 USD 비용을 계산합니다.

    usage_metadata가 없거나 가격 정보가 없으면 0.0을 반환합니다.
    모든 ROMA 컴포넌트에서 공통으로 사용하는 비용 추출 유틸리티입니다.
    """
    usage = getattr(response, "usage_metadata", None) or {}
    input_tokens: int = usage.get("input_tokens", 0)
    output_tokens: int = usage.get("output_tokens", 0)
    if input_tokens == 0 and output_tokens == 0:
        return 0.0
    try:
        from neos.utils.cost_calculator import CostCalculator
        pricing = CostCalculator._get_default_pricing(provider, model)
        if not pricing:
            return 0.0
        return (
            input_tokens * float(pricing["input"])
            + output_tokens * float(pricing["output"])
        ) / 1_000_000
    except Exception:
        return 0.0
