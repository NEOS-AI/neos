from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


class MissionStatus(str, Enum):
    PLANNED = "planned"
    AWAITING_APPROVAL = "awaiting_approval"
    RUNNING = "running"
    VALIDATING = "validating"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"


class MissionType(str, Enum):
    STANDARD = "standard"
    RECURSIVE = "recursive"
    HYPER_DEEP = "hyper_deep"
    ARTIFACT = "artifact"
    SCHEDULED = "scheduled"


class MissionTaskStatus(str, Enum):
    PLANNED = "planned"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class MissionTask(BaseModel):
    task_id: str
    mission_id: str
    parent_task_id: Optional[str] = None
    description: str
    required_capability: str
    suggested_agent: Optional[str] = None
    inputs: Dict[str, Any] = Field(default_factory=dict)
    depends_on: List[str] = Field(default_factory=list)
    expected_output_type: str
    expected_artifact: str
    risk_level: RiskLevel = RiskLevel.LOW
    status: MissionTaskStatus = MissionTaskStatus.PLANNED
    result_ref: Optional[str] = None
    error: Optional[str] = None

    def to_state(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")


class MissionPlan(BaseModel):
    mission_id: str
    objective: str
    assumptions: List[str] = Field(default_factory=list)
    constraints: List[str] = Field(default_factory=list)
    tasks: List[MissionTask] = Field(default_factory=list)
    execution_policy: Dict[str, Any] = Field(default_factory=dict)
    budget: Dict[str, Any] = Field(default_factory=dict)
    timeout: int = 300
    user_visible_summary: str

    def to_state(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")

    def plan_hash(self) -> str:
        return _stable_hash(self.to_state())


class ValidationContract(BaseModel):
    contract_id: str
    mission_id: str
    success_criteria: List[str]
    required_sources: int = 0
    freshness_requirement: Optional[str] = None
    citation_requirement: Optional[str] = None
    factuality_checks: List[str] = Field(default_factory=list)
    coverage_checks: List[str] = Field(default_factory=list)
    artifact_checks: List[str] = Field(default_factory=list)
    safety_checks: List[str] = Field(default_factory=list)
    min_quality_score: float = 0.8
    allowed_repair_attempts: int = 1
    failure_policy: str = "return_partial"

    def to_state(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")

    def contract_hash(self) -> str:
        return _stable_hash(self.to_state())


class ValidatorRun(BaseModel):
    validator_run_id: str
    mission_id: str
    task_id: Optional[str] = None
    validator_type: str
    status: str
    score: float
    findings: List[str] = Field(default_factory=list)
    repair_suggestion: Optional[str] = None
    created_at: str = Field(default_factory=_utc_now_iso)

    def to_state(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")


class Mission(BaseModel):
    mission_id: str
    session_id: str
    user_id: str
    original_query: str
    intent: str
    autonomy_level: int
    status: MissionStatus
    mission_type: MissionType
    plan_hash: Optional[str] = None
    validation_contract_hash: Optional[str] = None
    created_at: str = Field(default_factory=_utc_now_iso)
    updated_at: str = Field(default_factory=_utc_now_iso)

    def to_state(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")


def _stable_hash(data: Dict[str, Any]) -> str:
    encoded = json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(encoded).hexdigest()
