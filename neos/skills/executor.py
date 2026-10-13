"""빌트인 스킬 공통 실행기 (spec 2026-10-11-builtin-skill-executor §2.1, §4).

상태를 모른다 -- 그래프 노드(`MultiAgentWorkflow._skill_executor_node`)가 상태에서
`skill_calls` 를 읽어 넘기고 결과를 상태에 쓴다. 그래서 그래프 없이 시험할 수 있다.

1단계: 후처리 스킬이 아닌 호출을 병렬로 돌린다. 스킬마다 타임아웃.
2단계: 후처리 스킬(research-assistant)이 선택됐고 1단계 결과가 있으면 그 본문을
       `content` 로 넣어 돌린다.
실패·타임아웃은 그 스킬만 건너뛴다. `asyncio.CancelledError` 는 삼키지 않는다.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Protocol

from neos.skills.base import SkillResult
from neos.skills.base.search_results import SKILL_EXECUTOR_VIA
from neos.workflow.state import SearchResult

logger = logging.getLogger(__name__)

POST_PROCESSING_SKILLS = frozenset({"research-assistant"})

#: 2단계 스킬에 넘길 본문 상한. 1단계 상한(스킬 수 × 결과 수 × 길이)보다 작게 둔다.
_STAGE2_CONTENT_CAP = 20_000


class _Skill(Protocol):
    def to_search_results(self, result: SkillResult) -> list[SearchResult]: ...


class _Registry(Protocol):
    def get_skill(self, skill_name: str) -> _Skill | None: ...


class SkillRunner(Protocol):
    registry: _Registry

    async def execute_skill(self, skill_name: str, params: dict[str, Any]) -> SkillResult: ...


@dataclass(frozen=True, slots=True)
class SkillExecutionLimits:
    timeout_seconds: float
    max_results_per_skill: int
    max_content_chars: int


@dataclass(frozen=True, slots=True)
class SkillStep:
    skill: str
    status: str
    reason_code: str
    duration_ms: int
    result_count: int

    def to_execution_step(self) -> dict[str, Any]:
        return {
            "step": "skill_execution",
            "skill": self.skill,
            "status": self.status,
            "reason_code": self.reason_code,
            "duration_ms": self.duration_ms,
            "result_count": self.result_count,
            "timestamp": datetime.now().isoformat(),
        }


@dataclass(frozen=True, slots=True)
class SkillExecutionOutcome:
    results: tuple[SearchResult, ...]
    steps: tuple[SkillStep, ...]


async def execute_skill_calls(
    calls: Sequence[Mapping[str, Any]],
    *,
    runner: SkillRunner,
    limits: SkillExecutionLimits,
) -> SkillExecutionOutcome:
    first = [call for call in calls if call.get("name") not in POST_PROCESSING_SKILLS]
    post = [call for call in calls if call.get("name") in POST_PROCESSING_SKILLS]

    stage_one = await asyncio.gather(*(_run_one(call, runner=runner, limits=limits) for call in first))
    results = [item for items, _ in stage_one for item in items]
    steps = [step for _, step in stage_one]

    for call in post:
        name = str(call.get("name", ""))
        if not results:
            steps.append(SkillStep(name, "skipped", "no_input", 0, 0))
            continue
        params = {"action": "summarize", **dict(call.get("params") or {}), "content": _stage_two_content(results)}
        items, step = await _run_one({**call, "params": params}, runner=runner, limits=limits)
        results.extend(items)
        steps.append(step)

    return SkillExecutionOutcome(results=tuple(results), steps=tuple(steps))


async def _run_one(
    call: Mapping[str, Any],
    *,
    runner: SkillRunner,
    limits: SkillExecutionLimits,
) -> tuple[list[SearchResult], SkillStep]:
    name = str(call.get("name", ""))
    params = dict(call.get("params") or {})
    started = time.monotonic()

    def step(status: str, reason_code: str, count: int = 0) -> SkillStep:
        return SkillStep(name, status, reason_code, int((time.monotonic() - started) * 1000), count)

    skill = runner.registry.get_skill(name)
    if skill is None:
        return [], step("failed", "unknown_skill")

    try:
        result = await asyncio.wait_for(runner.execute_skill(name, params), timeout=limits.timeout_seconds)
    except TimeoutError:
        logger.warning("[SkillExecutor] %s timed out after %ss", name, limits.timeout_seconds)
        return [], step("failed", "timeout")
    except Exception as error:  # noqa: BLE001 -- 스킬 하나의 실패가 턴을 죽이지 않는다
        logger.warning("[SkillExecutor] %s raised: %s", name, error)
        return [], step("failed", "error")

    if not result.success:
        logger.info("[SkillExecutor] %s failed: %s", name, result.error)
        return [], step("failed", "skill_failed")

    try:
        converted = skill.to_search_results(result)
    except Exception as error:  # noqa: BLE001
        logger.warning("[SkillExecutor] %s result conversion failed: %s", name, error)
        return [], step("failed", "error")

    bounded = [_bound(item, name, limits) for item in converted[: limits.max_results_per_skill]]
    return bounded, step("ok", "ok", len(bounded))


def _bound(item: SearchResult, skill: str, limits: SkillExecutionLimits) -> SearchResult:
    content = item.content or ""
    if len(content) > limits.max_content_chars:
        content = content[: limits.max_content_chars].rstrip() + "…"
    return replace(item, content=content, metadata={**(item.metadata or {}), "skill": skill, "via": SKILL_EXECUTOR_VIA})


def _stage_two_content(results: Sequence[SearchResult]) -> str:
    text = "\n\n".join(f"{item.title}\n{item.content}" for item in results)
    return text[:_STAGE2_CONTENT_CAP]
