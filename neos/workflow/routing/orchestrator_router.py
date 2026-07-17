"""Workflow orchestrator routing decisions."""

from __future__ import annotations

import logging
from dataclasses import dataclass
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
    IntentType.DEEP_ANALYSIS.value,
]


@dataclass(frozen=True)
class DeepEngine:
    """deep 엔진 하나를 라우팅 관점에서 기술한다.

    route()는 이 표만 읽는다 — 엔진을 추가·제거해도 분기 코드는 늘지 않는다.
    엔진별 if-블록을 복제하던 구조가 R1(임계값 역전)을 낳았다: 세 블록이 같은
    intent를 두고 경쟁하는데 우선순위(deep_analysis→hyper_deep→recursive)와
    임계값(0.5→0.85→0.8)이 역전돼, 뒤 두 엔진의 complexity 경로가 도달 불가능한
    죽은 코드가 됐다. 테이블화는 그 복제를 구조적으로 불가능하게 만든다.
    """

    name: str  # 라우팅 키. graph.py `_routing_map`의 키와 일치해야 한다
    intent: str  # 이 엔진을 지목하는 전용 유형 intent
    enabled_flag: str  # settings의 활성 플래그 속성명
    threshold_attr: str  # settings의 complexity 게이트 속성명


# 스펙 §4.1 — 임계값이 아니라 "작업의 형태"가 엔진을 고른다.
#   deep_analysis : 검증형 분석 — "이 주장이 사실인가" (인용·충돌해소·검증된 클레임)
#   hyper_deep    : 장문 리포트 — "긴 보고서를 써라" (Ralph 정제 루프, 섹션 품질)
#   recursive     : 일반 태스크 분해 — "여러 단계 작업을 수행하라" (Ray 병렬)
#
# 튜플 순서 = 유형을 지목하지 않는 레거시 intent(_GENERIC_DEEP_INTENTS)의
# fallback 우선순위. 현행 동작(deep_analysis 1순위)과 동일하게 두어 무회귀를 지킨다.
_DEEP_ENGINES: tuple[DeepEngine, ...] = (
    DeepEngine(
        name="deep_analysis",
        intent=IntentType.DEEP_ANALYSIS.value,
        enabled_flag="DEEP_ANALYSIS_ENABLED",
        threshold_attr="DEEP_ANALYSIS_COMPLEXITY_THRESHOLD",
    ),
    DeepEngine(
        name="hyper_deep",
        intent=IntentType.HYPER_DEEP_RESEARCH.value,
        enabled_flag="HYPER_DEEP_AGENT_ENABLED",
        threshold_attr="HYPER_DEEP_COMPLEXITY_THRESHOLD",
    ),
    DeepEngine(
        name="recursive",
        intent=IntentType.RECURSIVE_RESEARCH.value,
        enabled_flag="RECURSIVE_AGENT_ENABLED",
        threshold_attr="RECURSIVE_COMPLEXITY_THRESHOLD",
    ),
)

# 유형을 지목하지 않는 레거시 research intent. complexity 게이트를 통과하면
# _DEEP_ENGINES 순서상 처음으로 활성화된 엔진이 받는다.
_GENERIC_DEEP_INTENTS = frozenset(
    {
        IntentType.DEEP_RESEARCH.value,
        IntentType.COMPLEX_ANALYSIS.value,
    }
)


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

        if policy.allows_recursive_research():
            classification = state.get("query_classification") or {}
            engine = self.select_deep_engine(
                intent=state.get("query_intent", ""),
                complexity=classification.get("complexity_score", 0.0),
            )
            if engine is not None:
                return engine

        return self.base_route(state)

    def select_deep_engine(self, *, intent: str, complexity: float) -> str | None:
        """유형(intent) → deep 엔진 단일 디스패치. 해당 없으면 None.

        스펙 §4.3-3: complexity 임계값은 "deep 엔진을 쓸지 말지"의 게이트로만
        남고, "어느 엔진인지"는 유형이 결정한다. 전용 유형 intent는 사용자가
        형태를 명시한 것이므로 게이트를 적용하지 않는다.
        """
        for engine in _DEEP_ENGINES:
            if engine.intent == intent:
                return engine.name if self._engine_enabled(engine) else None

        if intent not in _GENERIC_DEEP_INTENTS:
            return None

        # 유형이 없는 레거시 intent만 임계값 게이트를 탄다.
        for engine in _DEEP_ENGINES:
            if self._engine_enabled(engine) and complexity >= getattr(settings, engine.threshold_attr):
                return engine.name

        return None

    @staticmethod
    def _engine_enabled(engine: DeepEngine) -> bool:
        return bool(getattr(settings, engine.enabled_flag, False))

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
