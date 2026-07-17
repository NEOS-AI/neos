"""스펙 §4.3-1 — 분류기가 세 deep 엔진 유형 intent를 방출한다 (AC3, 키워드 경로).

기존 intent 방출 불변(K3) 회귀도 함께 고정한다.
"""

import pytest

from neos.workflow.enums import IntentType
from neos.workflow.state import WorkflowConfig
from neos.workflow.utils.query_classifier import (
    QueryClassifier,
    _classify_engine_intent,
)

pytestmark = pytest.mark.no_db


@pytest.fixture
def classifier():
    return QueryClassifier(WorkflowConfig())


# ── AC3: 세 유형이 각각 방출된다 ────────────────────────────────────────


@pytest.mark.parametrize(
    "query",
    [
        "이 주장이 사실인가 팩트체크해줘",
        "이 기사 진위를 교차 검증해줘",
        "please verify this claim against the sources",
    ],
)
async def test_keyword_path_emits_deep_analysis_intent(classifier, query):
    assert await classifier._classify_intent(query) == IntentType.DEEP_ANALYSIS.value


@pytest.mark.parametrize(
    "query",
    [
        "AI 반도체 시장에 대한 긴 보고서를 써줘",
        "이 주제로 백서를 작성해줘",
        "write a long-form report on the topic",
    ],
)
async def test_keyword_path_emits_hyper_deep_research_intent(classifier, query):
    assert await classifier._classify_intent(query) == IntentType.HYPER_DEEP_RESEARCH.value


@pytest.mark.parametrize(
    "query",
    [
        "이 작업을 단계별로 수행해줘",
        "하위 작업으로 나눠서 실행해줘",
        "break this down step by step and execute",
    ],
)
async def test_keyword_path_emits_recursive_research_intent(classifier, query):
    assert await classifier._classify_intent(query) == IntentType.RECURSIVE_RESEARCH.value


def test_engine_intent_helper_returns_none_for_plain_query():
    assert _classify_engine_intent("파이썬 관련 영상 추천해줘") is None


# ── K3: 기존 intent 방출 불변 ──────────────────────────────────────────


@pytest.mark.parametrize(
    "query,expected",
    [
        ("youtube에서 파이썬 강좌 검색해줘", IntentType.YOUTUBE_SEARCH.value),
        ("파이썬 관련 영상 추천해줘", IntentType.YOUTUBE_SEARCH.value),
        ("안녕", IntentType.SIMPLE.value),
        ("A와 B를 비교해줘", IntentType.COMPARISON.value),
        ("삼성전자 주가 전망 알려줘", IntentType.FINANCIAL_ANALYSIS.value),
        ("이 주제로 리포트를 써줘", IntentType.DEEP_RESEARCH.value),
        ("매일 아침 뉴스 알림 등록해줘", IntentType.TASK_SCHEDULING.value),
    ],
)
async def test_existing_intent_emission_is_unchanged(classifier, query, expected):
    assert await classifier._classify_intent(query) == expected


async def test_scheduling_wins_over_engine_intent(classifier):
    """TASK_SCHEDULING은 라우터 _PRIORITY_ROUTING_MAP에서 최우선이므로 양보받는다.

    주의: 질의에 "리포트"/"보고서" 같은 기존 키워드를 섞으면 안 된다. TASK_SCHEDULING은
    intent_keywords dict의 마지막 항목이라 max() 동점에서 항상 지는 기존 quirk가 있어
    (예: "매일 ... 리포트 등록해줘" → deep_research), 이 테스트가 검증하려는
    "engine intent가 스케줄에 양보하는가"와 무관한 이유로 실패한다. 이 quirk는
    HEAD에서도 동일하며 이 계획의 범위 밖이다.
    """
    intent = await classifier._classify_intent("매일 아침 팩트체크 알림 등록해줘")
    assert intent == IntentType.TASK_SCHEDULING.value


# ── AC3: LLM 경로 ──────────────────────────────────────────────────────


def test_llm_prompt_rules_describe_three_engine_types():
    """LLM 프롬프트 Rules가 세 유형을 설명한다 (스펙 §4.3-1).

    R2: _VALID_INTENTS는 전부 허용했지만 Rules에 설명이 없어 사실상 방출되지
    않던 것이 결함이었다. 열거만으로는 부족하고 Rules 설명이 있어야 한다.
    """
    from neos.workflow.utils.query_classifier import _LLM_CLASSIFICATION_PROMPT

    rules = _LLM_CLASSIFICATION_PROMPT.split("Rules:")[1].split("User query:")[0]
    for intent in (
        IntentType.DEEP_ANALYSIS.value,
        IntentType.HYPER_DEEP_RESEARCH.value,
        IntentType.RECURSIVE_RESEARCH.value,
    ):
        assert f'"{intent}"' in rules, f"Rules에 {intent} 설명이 없다"


def test_llm_valid_intents_include_three_engine_types():
    from neos.workflow.utils.query_classifier import _VALID_INTENTS

    assert IntentType.DEEP_ANALYSIS.value in _VALID_INTENTS
    assert IntentType.HYPER_DEEP_RESEARCH.value in _VALID_INTENTS
    assert IntentType.RECURSIVE_RESEARCH.value in _VALID_INTENTS


class _FakeResponse:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeLLM:
    def __init__(self, payload: str) -> None:
        self._payload = payload
        self.prompts: list[str] = []

    async def ainvoke(self, prompt):
        self.prompts.append(prompt)
        return _FakeResponse(self._payload)


@pytest.mark.parametrize(
    "intent_value",
    [
        IntentType.DEEP_ANALYSIS.value,
        IntentType.HYPER_DEEP_RESEARCH.value,
        IntentType.RECURSIVE_RESEARCH.value,
    ],
)
async def test_llm_path_emits_each_engine_type(classifier, monkeypatch, intent_value):
    import json

    payload = json.dumps(
        {
            "intent": intent_value,
            "complexity": 0.9,
            "sub_topics": ["a"],
            "required_capabilities": ["web_search"],
            "confidence": 0.9,
            "needs_ui": False,
        }
    )
    fake = _FakeLLM(payload)
    monkeypatch.setattr("neos.utils.llm_factory.create_llm", lambda **kwargs: fake)

    result = await classifier._classify_with_llm("이 주제를 다뤄줘")

    assert result is not None
    assert result["intent"] == intent_value
    # 프롬프트에 세 유형 Rules가 실제로 실려 나갔는지 확인
    assert intent_value in fake.prompts[0]
