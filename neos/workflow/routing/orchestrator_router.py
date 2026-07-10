"""Workflow orchestrator routing decisions."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from neos.config.settings import settings
from neos.workflow.autonomy.middleware import get_policy_from_state
from neos.workflow.enums import IntentType, WorkflowPathway

if TYPE_CHECKING:
    from neos.workflow.state import AgentState

logger = logging.getLogger(__name__)

_PRIORITY_ROUTING_MAP: dict[str, str] = {
    IntentType.TASK_SCHEDULING.value: "task_scheduling",
}

_REALTIME_KEYWORDS = [
    "최신",
    "현재",
    "지금",
    "오늘",
    "실시간",
    "current",
    "latest",
    "now",
    "today",
    "real-time",
]
_ANALYSIS_KEYWORDS = [
    "비교",
    "분석",
    "대비",
    "차이",
    "검토",
    "평가",
    "compare",
    "analysis",
    "versus",
    "vs",
    "difference",
    "review",
]
_DATA_KEYWORDS = [
    "얼마",
    "몇",
    "수치",
    "데이터",
    "통계",
    "가격",
    "주가",
    "환율",
    "how much",
    "how many",
    "price",
    "rate",
    "statistics",
    "data",
]
_QUESTION_WORDS_KO = ["어디", "언제", "누가", "누구", "무엇", "뭐", "왜", "어떻게", "어느"]
_QUESTION_WORDS_EN = ["where", "when", "who", "what", "why", "how", "which"]
_ALWAYS_SEARCH_INTENTS = [
    IntentType.REALTIME_INFO.value,
    IntentType.FINANCIAL_ANALYSIS.value,
    IntentType.DATA_ANALYSIS.value,
    IntentType.COMPARISON.value,
    IntentType.DEEP_RESEARCH.value,
    IntentType.COMPLEX_ANALYSIS.value,
    IntentType.HYPER_DEEP_RESEARCH.value,
    IntentType.RECURSIVE_RESEARCH.value,
]


class OrchestratorRouter:
    """Route from skill selection to recursive or standard orchestrators."""

    def route(self, state: "AgentState") -> str:
        policy = get_policy_from_state(state)

        if settings.A2UI_ENABLED and state.get("needs_ui") and not state.get("ui_submission"):
            return "ui_frame"

        priority = _PRIORITY_ROUTING_MAP.get(state.get("query_intent", ""))
        if priority:
            return priority

        if settings.EXECUTION_APPROVAL_ENABLED:
            if state.get("pending_approvals") and state.get("approval_decision") is None:
                return "needs_approval"

        classification = state.get("query_classification") or {}
        complexity = classification.get("complexity_score", 0.0)
        intent = state.get("query_intent", "")

        if settings.DEEP_ANALYSIS_ENABLED and policy.allows_recursive_research():
            if intent == IntentType.DEEP_ANALYSIS.value:
                return "deep_analysis"

            da_intents = (
                IntentType.DEEP_RESEARCH.value,
                IntentType.COMPLEX_ANALYSIS.value,
            )
            if complexity >= settings.DEEP_ANALYSIS_COMPLEXITY_THRESHOLD and intent in da_intents:
                return "deep_analysis"

        if settings.HYPER_DEEP_AGENT_ENABLED and policy.allows_recursive_research():
            if intent == IntentType.HYPER_DEEP_RESEARCH.value:
                return "hyper_deep"

            hyper_deep_intents = (
                IntentType.DEEP_RESEARCH.value,
                IntentType.COMPLEX_ANALYSIS.value,
            )
            if complexity >= settings.HYPER_DEEP_COMPLEXITY_THRESHOLD and intent in hyper_deep_intents:
                return "hyper_deep"

        if settings.RECURSIVE_AGENT_ENABLED and policy.allows_recursive_research():
            if intent == IntentType.RECURSIVE_RESEARCH.value:
                return "recursive"

            roma_intents = (
                IntentType.DEEP_RESEARCH.value,
                IntentType.COMPLEX_ANALYSIS.value,
            )
            if complexity >= settings.RECURSIVE_COMPLEXITY_THRESHOLD and intent in roma_intents:
                return "recursive"

        return self.base_route(state)

    def base_route(self, state: "AgentState") -> str:
        priority = _PRIORITY_ROUTING_MAP.get(state.get("query_intent", ""))
        if priority:
            return priority

        required_agents = state.get("required_agents", [])
        selected_tools = state.get("selected_tools", [])
        if required_agents or selected_tools:
            return WorkflowPathway.USE_ORCHESTRATORS.value

        query_intent = state.get("query_intent", "")
        query_classification = state.get("query_classification") or {}
        complexity_score = query_classification.get("complexity_score", 0.0)
        query = state.get("refined_query", state.get("original_query", ""))

        if query_intent in _ALWAYS_SEARCH_INTENTS:
            return WorkflowPathway.USE_ORCHESTRATORS.value
        if complexity_score >= 0.5:
            return WorkflowPathway.USE_ORCHESTRATORS.value
        if self.is_question_query(query):
            return WorkflowPathway.USE_ORCHESTRATORS.value
        if self.requires_search_keywords(query):
            return WorkflowPathway.USE_ORCHESTRATORS.value

        return WorkflowPathway.SKIP_ORCHESTRATORS.value

    def is_question_query(self, query: str) -> bool:
        if not query:
            return False
        if "?" in query or "？" in query:
            return True

        query_lower = query.lower()
        return any(word in query_lower for word in _QUESTION_WORDS_KO + _QUESTION_WORDS_EN)

    def requires_search_keywords(self, query: str) -> bool:
        if not query:
            return False

        query_lower = query.lower()
        keywords = _REALTIME_KEYWORDS + _ANALYSIS_KEYWORDS + _DATA_KEYWORDS
        return any(keyword in query_lower for keyword in keywords)
