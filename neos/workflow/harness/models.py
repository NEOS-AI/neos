from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Literal


class HarnessMode(str, Enum):
    OFF = "off"
    ADVISORY = "advisory"
    GATE = "gate"
    AUTO = "auto"


class HarnessVerdict(str, Enum):
    PASS = "pass"
    ADVISORY_PASS = "advisory_pass"
    NEEDS_REPAIR = "needs_repair"
    FAIL = "fail"
    SKIPPED = "skipped"


class HarnessRiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class HarnessPolicyDecision:
    mode: HarnessMode
    risk_level: HarnessRiskLevel
    reason: str
    min_score: float
    max_repair_attempts: int


@dataclass
class HarnessContract:
    mode: HarnessMode
    risk_level: HarnessRiskLevel
    min_score: float
    min_sources: int = 3
    min_citation_coverage: float = 0.75
    min_source_diversity: float = 0.60
    freshness_required: bool = False
    freshness_window_days: int | None = None
    required_sources: list[str] = field(default_factory=list)
    required_checks: list[str] = field(default_factory=list)
    optional_checks: list[str] = field(default_factory=list)
    blocked_domains: list[str] = field(default_factory=list)
    preferred_domains: list[str] = field(default_factory=list)
    high_risk_categories: list[str] = field(default_factory=list)
    max_repair_attempts: int = 1
    failure_policy: Literal["block", "warn", "partial"] = "block"
    created_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["mode"] = self.mode.value
        data["risk_level"] = self.risk_level.value
        if self.created_at is not None:
            data["created_at"] = self.created_at.isoformat()
        return data


@dataclass
class HarnessCheckResult:
    name: str
    passed: bool
    score: float
    severity: str
    summary: str
    evidence: list[dict[str, Any]] = field(default_factory=list)
    failed_items: list[dict[str, Any]] = field(default_factory=list)
    repairable: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class HarnessRun:
    run_id: str
    mode: HarnessMode
    verdict: HarnessVerdict
    score: float
    checks: list[HarnessCheckResult]
    failed_checks: list[str]
    repair_attempts: int
    started_at: datetime
    completed_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["mode"] = self.mode.value
        data["verdict"] = self.verdict.value
        data["checks"] = [check.to_dict() for check in self.checks]
        data["started_at"] = self.started_at.isoformat()
        if self.completed_at is not None:
            data["completed_at"] = self.completed_at.isoformat()
        return data


@dataclass
class HarnessRepairAction:
    action_type: str
    target_check: str
    reason: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class HarnessRepairPlan:
    attempt: int
    actions: list[HarnessRepairAction]
    max_attempts: int
    budget_seconds: int
    budget_tokens: int | None = None

