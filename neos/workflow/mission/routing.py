from __future__ import annotations

from typing import Any, Mapping

from neos.config.settings import settings
from neos.workflow.enums import AutonomyLevel, IntentType


MISSION_INTENTS = {
    IntentType.DEEP_RESEARCH.value,
    IntentType.COMPLEX_ANALYSIS.value,
    IntentType.RECURSIVE_RESEARCH.value,
    IntentType.HYPER_DEEP_RESEARCH.value,
}

MISSION_KEYWORDS = (
    "계획하고 실행",
    "비교 분석",
    "문서 기반 보고서",
    "여러 출처",
    "검증",
    "compare and analyze",
    "multi-source",
    "validated report",
)


MISSION_CACHE_HINT_KEYWORDS = MISSION_KEYWORDS + (
    "deep research",
    "hyper deep",
    "recursive research",
    "several sources",
    "multiple sources",
    "source-backed",
    "validated",
    "report",
    "여러 단계",
    "출처",
    "보고서",
)


def has_mission_request_hint(request: Mapping[str, Any]) -> bool:
    preferences = request.get("preferences") or {}
    if preferences.get("use_mission_runtime"):
        return True

    query = (
        request.get("query")
        or request.get("original_query")
        or request.get("refined_query")
        or ""
    ).lower()
    return any(keyword in query for keyword in MISSION_CACHE_HINT_KEYWORDS)


def should_use_mission_runtime(state: Mapping[str, Any]) -> bool:
    intent = state.get("query_intent", "")
    classification = state.get("query_classification") or {}
    complexity = float(classification.get("complexity_score", 0.0) or 0.0)
    required_agents = state.get("required_agents") or []
    selected_tools = state.get("selected_tools") or []
    query = (state.get("original_query") or "").lower()
    autonomy_level = state.get("autonomy_level")

    if state.get("use_mission_runtime") is True:
        return True
    if intent == IntentType.RECURSIVE_RESEARCH.value and not settings.RECURSIVE_AGENT_ENABLED:
        return False
    if (
        intent == IntentType.HYPER_DEEP_RESEARCH.value
        and not settings.HYPER_DEEP_AGENT_ENABLED
    ):
        return False
    if intent in MISSION_INTENTS:
        return True
    if complexity >= 0.7:
        return True
    if len(required_agents) >= 2:
        return True
    if autonomy_level == AutonomyLevel.MANUAL.value and (required_agents or selected_tools):
        return True
    return any(keyword in query for keyword in MISSION_KEYWORDS)
