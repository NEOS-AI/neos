"""Workflow quality and retry routing decisions."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from neos.workflow.autonomy.middleware import get_policy_from_state

if TYPE_CHECKING:
    from neos.workflow.state import AgentState

logger = logging.getLogger(__name__)


class QualityRouter:
    """Route quality validation, replanning, and refinement loops."""

    def should_refine_or_continue(self, state: "AgentState") -> str:
        if state.get("is_continuation"):
            return "continue_research"
        if state.get("needs_refinement", False):
            return "refine_query"
        return "skip_refinement"

    def should_process_context(self, state: "AgentState") -> str:
        return "process_context"

    def should_regenerate(self, state: "AgentState", quality_validator) -> str:
        return quality_validator.should_regenerate(state)

    def should_replan(self, state: "AgentState") -> str:
        policy = get_policy_from_state(state)
        if not policy.allows_autonomous_replan():
            return "skip_replan"

        classification = state.get("query_classification") or {}
        sub_topics = classification.get("sub_topics", [])
        search_results = state.get("search_results", [])
        replan_count = state.get("replan_count", 0)

        if sub_topics and len(search_results) < 10 and replan_count < 2:
            logger.info(
                "[Replanner] Triggered (results=%s, replan #%s)",
                len(search_results),
                replan_count + 1,
            )
            return "replan"

        return "skip_replan"

    def should_continue_research(self, state: "AgentState") -> str:
        remaining = state.get("remaining_questions", [])
        if remaining:
            logger.info("[Replanner] %s gaps found, looping to search", len(remaining))
            return "continue_search"
        return "proceed"
