# 엔진 재배치 (Phase 2) 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 세 deep 엔진(`deep_analysis`/`hyper_deep`/`recursive`)을 complexity 임계값이 아니라 **질의 유형**으로 라우팅해, R1(임계값 역전)과 R2(intent 미도달)를 함께 해소한다.

**Architecture:** `query_classifier`가 세 유형을 구별하는 intent를 방출하고(키워드 경로 + LLM 경로), `OrchestratorRouter.route()`의 3중 if-체인을 **엔진 기술 테이블(`_DEEP_ENGINES`) 기반 단일 디스패치**로 교체한다. complexity 임계값은 "deep 엔진을 쓸지 말지"의 게이트로만 남고, "어느 엔진인지"는 유형이 결정한다.

**Tech Stack:** Python 3.12, pytest (`.venv/bin/pytest`), dataclasses. 신규 의존성 없음.

**Spec:** `docs/superpowers/specs/2026-07-17-loop-architecture-consolidation-design.md` §1.3(R1·R2), §4, §7, §8

## Global Constraints

- **기존 intent 방출 불변 (K3):** 신규 intent만 추가한다. 기존 질의의 분류가 달라지면 회귀다. → 기존 `intent_keywords` 스코어링 맵을 **수정하지 않고**, 별도 전처리(`_classify_engine_intent`)로만 신규 유형을 방출한다.
- **범위 밖 (§7):** `graph.py` 전면 리팩터링 금지. Phase 3(분리, Celery/resume) 착수 금지. **엔진 삭제 금지** — 재배치지 제거가 아니다.
- **무회귀:** 세 엔진 모두 비활성일 때 기존 경로 그대로(AC5). `tests/workflow/routing/`, `tests/workflow/deep_analysis/`, `tests/workflow/test_deep_analysis_node.py` 전부 통과.
- **LangChain/LangGraph 신규 의존 금지:** `deep_analysis` 패키지는 프레임워크 프리. `orchestrator_router.py`는 workflow 쪽이므로 **기존 import는 유지**(신규 추가는 하지 않는다).
- **테스트 실행:** `.venv/bin/pytest` (프로젝트 venv). 신규 라우팅/분류기 테스트에는 `pytestmark = pytest.mark.no_db`.
- **커밋 트레일러:** 모든 커밋 메시지 끝에 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- **모델 ID 변경 금지.**

## 알려진 선행 조건 — `tests/workflow/` 단일 실행은 현재도 수집 실패한다

**이 계획을 시작하기 전에 반드시 읽어라.** HEAD(`118c453`)에서 이미 존재하는 문제이며 이 계획의 범위가 아니다.

```
ERROR tests/workflow/harness/test_policy.py     (tests/workflow/autonomy/test_policy.py 와 basename 충돌)
ERROR tests/workflow/mission/test_executor.py   (tests/workflow/hyper_deep/test_executor.py 와 basename 충돌)
```

원인: 테스트 디렉터리에 `__init__.py`가 없고 `pytest.ini`가 기본 `prepend` import 모드라, 같은 basename의 테스트 모듈 두 개가 같은 모듈명으로 충돌한다. `__pycache__` 삭제로 해결되지 않는다(실제 파일 두 개가 basename을 공유).

**따라서 무회귀 검증은 아래 두 명령으로 나눠 실행한다.** 이 계획은 테스트 레이아웃을 고치지 않는다(범위 밖).

```bash
.venv/bin/pytest tests/workflow/ -q -p no:cacheprovider \
  --ignore=tests/workflow/mission/test_executor.py \
  --ignore=tests/workflow/harness/test_policy.py
# HEAD 기준선: 341 passed

.venv/bin/pytest tests/workflow/mission/test_executor.py tests/workflow/harness/test_policy.py -q -p no:cacheprovider
# HEAD 기준선: 13 passed
```

---

## File Structure

| 파일 | 책임 |
|---|---|
| `neos/workflow/utils/query_classifier.py` (수정) | 세 유형 intent 방출. 키워드 전처리 `_ENGINE_INTENT_KEYWORDS` + `_classify_engine_intent`, LLM 프롬프트 Rules 3줄 추가 |
| `neos/workflow/routing/orchestrator_router.py` (수정) | 3중 if-체인 → `_DEEP_ENGINES` 테이블 기반 단일 디스패치(`select_deep_engine`) |
| `tests/workflow/utils/test_query_classifier_engine_intents.py` (신규) | AC3 — 키워드·LLM 경로 각각 세 유형 방출 + 기존 방출 불변 회귀 |
| `tests/workflow/routing/test_engine_reassignment.py` (신규) | AC1·AC2·AC4·AC5 — 도달성/무반복/무회귀 |
| `neos/workflow/deep_analysis/DECISIONS.md` (수정) | D21 기록 (R1 해소 + D18 선결 조건 #3 해소) |

**변경하지 않는 파일 (확인 완료):**
- `neos/workflow/graph.py` — `_should_use_recursive_agent`/`_route_after_skill_tool_selector`가 이미 `OrchestratorRouter.route()`에 **완전 위임**(graph.py:1119, 1123)한다. 라우팅 키(`"deep_analysis"`/`"hyper_deep"`/`"recursive"`)를 그대로 유지하므로 `_routing_map`(graph.py:413-418)도 무변경.
- `neos/workflow/enums.py` — 세 intent(`DEEP_ANALYSIS`/`HYPER_DEEP_RESEARCH`/`RECURSIVE_RESEARCH`)가 **이미 존재**한다(enums.py:83-86).
- `neos/config/schema.py` — 임계값/플래그 설정 전부 이미 존재. 신규 설정 없음.
- `neos/workflow/mission/routing.py`, `neos/workflow/harness/policy.py` — 별개 소비자. 범위 밖.

---

## 설계 노트 — 레거시 generic intent를 어떻게 다루는가

세 엔진의 전용 intent는 1:1로 엔진에 대응한다. 문제는 **유형을 지목하지 않는 레거시 intent** 두 개(`DEEP_RESEARCH`, `COMPLEX_ANALYSIS`)다. 현행 코드에서 이 둘은 세 블록 모두가 경쟁하는 대상이고, 그 경쟁이 R1(임계값 역전)의 무대다.

**결정:** 레거시 generic intent는 `_DEEP_ENGINES` **튜플 순서상 처음으로 "활성 + 임계값 통과"인 엔진**이 받는다(현행 우선순위 deep_analysis → hyper_deep → recursive와 동일).

**이 선택의 근거 — 1:1 매핑으로 좁히면 회귀다.** generic intent를 `deep_analysis` 하나에만 매핑하면, 현재 프로덕션에 가까운 구성(`DEEP_ANALYSIS_ENABLED=false`, `HYPER_DEEP_AGENT_ENABLED=true`)에서 `deep_research` + complexity 0.9 질의가 오늘은 `hyper_deep`으로 가는데 내일은 `base_route`로 떨어진다. Global Constraints의 무회귀 요구와 정면 충돌한다.

**R1이 해소되는 이유 (shadowing과 다르다):** R1의 결함은 "플래그를 켜면 **뒤 두 엔진이 100% 도달 불가능한 죽은 코드**가 된다"는 것이다. 재배치 후 `hyper_deep`/`recursive`는 각자의 **유형 intent로 항상 도달 가능**하며(Task 1·2가 그 intent를 실제로 방출시킨다), generic fallback은 임계값 역전의 사고가 아니라 테이블 순서로 **명시·문서화된 기본값**이다. 도달 불가 분기는 0개가 된다(Task 3의 AC4 테스트가 이를 강제한다).

---

### Task 1: 키워드 분류기가 세 유형 intent를 방출한다

**Files:**
- Modify: `neos/workflow/utils/query_classifier.py:27-36`(헬퍼 구역), `:482-491`(`_classify_intent` 후반)
- Test: `tests/workflow/utils/test_query_classifier_engine_intents.py` (신규)

**Interfaces:**
- Consumes: `IntentType.DEEP_ANALYSIS` / `IntentType.HYPER_DEEP_RESEARCH` / `IntentType.RECURSIVE_RESEARCH` (enums.py:83-86, 기존)
- Produces:
  - `_ENGINE_INTENT_KEYWORDS: dict[str, list[str]]` — 모듈 전역. 키 = 세 intent 문자열, 값 = 키워드 리스트. **dict 삽입 순서 = 동점 시 우선순위**
  - `_classify_engine_intent(query_lower: str) -> Optional[str]` — 모듈 전역 함수. 해당 없으면 `None`
  - `QueryClassifier._classify_intent(query, complexity_score=0.0, conversation_context="")` — 시그니처 불변, 반환값에 세 intent가 추가로 등장

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/workflow/utils/` 디렉터리를 만들고 `tests/workflow/utils/test_query_classifier_engine_intents.py`를 신규 작성:

```python
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
    """TASK_SCHEDULING은 라우터 _PRIORITY_ROUTING_MAP에서 최우선이므로 양보받는다."""
    intent = await classifier._classify_intent("매일 아침 팩트체크 리포트를 등록해줘")
    assert intent == IntentType.TASK_SCHEDULING.value
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `.venv/bin/pytest tests/workflow/utils/test_query_classifier_engine_intents.py -q -p no:cacheprovider`
Expected: FAIL — 수집 단계에서 `ImportError: cannot import name '_classify_engine_intent' from 'neos.workflow.utils.query_classifier'`

- [ ] **Step 3: 최소 구현 — 키워드 맵과 판별 함수 추가**

`neos/workflow/utils/query_classifier.py`의 `_is_scheduling_intent` 정의 **바로 아래**(현재 37행 근방, `# Phase 8: A2UI needs_ui 감지` 주석 앞)에 추가:

```python
# ── 스펙 §4.1 — deep 엔진 유형 판별 키워드 (Phase 2 엔진 재배치) ──────────
# 세 엔진은 complexity 임계값이 아니라 "작업의 형태"로 갈린다.
#   deep_analysis        : 검증형 분석 — "이 주장이 사실인가"
#   hyper_deep_research  : 장문 리포트 — "긴 보고서를 써라"
#   recursive_research   : 일반 태스크 분해 — "여러 단계 작업을 수행하라"
#
# 기존 self.intent_keywords 스코어링 맵에 넣지 않고 전용 전처리로 분리한 이유(K3):
# 저 맵은 intent별 매칭 수를 세어 max()로 뽑으므로, 신규 키워드를 섞으면 기존
# 질의의 승자가 바뀔 수 있다. 별도 전처리는 "신규 키워드가 하나도 안 맞으면
# None"이므로 기존 방출이 구조적으로 불변이다.
#
# dict 삽입 순서 = 동점 시 우선순위(스펙 §4.1 표 순서와 동일).
_ENGINE_INTENT_KEYWORDS: Dict[str, List[str]] = {
    IntentType.DEEP_ANALYSIS.value: [
        "팩트체크", "팩트 체크", "fact check", "fact-check", "factcheck",
        "사실인가", "사실인지", "사실 확인", "사실확인", "진위",
        "검증해", "검증이 필요", "교차 검증", "교차검증",
        "verify", "verification", "cross-check", "cross check", "debunk",
        "출처를 확인", "근거를 확인", "근거가 있는지",
    ],
    IntentType.HYPER_DEEP_RESEARCH.value: [
        "장문", "장편", "긴 보고서", "긴 리포트", "긴 글",
        "백서", "whitepaper", "white paper",
        "long-form", "long form", "longform",
        "섹션별", "챕터별", "목차를",
        "페이지 분량", "페이지 이상", "page report",
    ],
    IntentType.RECURSIVE_RESEARCH.value: [
        "단계별로", "단계로 나눠", "여러 단계", "step by step", "step-by-step",
        "multi-step", "하위 작업", "서브태스크", "subtask", "sub-task",
        "작업을 분해", "task decomposition", "분해해서",
        "나눠서 수행", "나눠서 실행", "순서대로 수행", "순서대로 실행",
    ],
}


def _classify_engine_intent(query_lower: str) -> Optional[str]:
    """deep 엔진 유형(검증형/장문/분해형) intent를 판별한다 (스펙 §4.1).

    어느 유형에도 해당하지 않으면 None을 반환하고, 호출자는 기존 키워드
    스코어링을 그대로 수행한다 — 즉 기존 intent 방출은 불변이다(K3).
    """
    scores = {
        intent: sum(1 for keyword in keywords if keyword in query_lower)
        for intent, keywords in _ENGINE_INTENT_KEYWORDS.items()
    }
    best = max(scores, key=scores.get)  # 동점 시 dict 삽입 순서상 앞선 유형
    return best if scores[best] > 0 else None
```

- [ ] **Step 4: 최소 구현 — `_classify_intent`에 전처리 연결**

같은 파일 `_classify_intent` 안, TASK_SCHEDULING 가지치기 블록과 "가장 높은 점수의 의도 반환" 블록 **사이**(현재 486행 근방)에 삽입한다. 즉 아래 기존 코드에서:

```python
        # CR-P6-06: TASK_SCHEDULING은 시간 표현 AND 등록 동작이 모두 있을 때만 인정
        if IntentType.TASK_SCHEDULING.value in intent_scores:
            if not _is_scheduling_intent(combined_lower):
                del intent_scores[IntentType.TASK_SCHEDULING.value]

        # 가장 높은 점수의 의도 반환
        if intent_scores:
```

가운데에 블록을 넣어 이렇게 만든다:

```python
        # CR-P6-06: TASK_SCHEDULING은 시간 표현 AND 등록 동작이 모두 있을 때만 인정
        if IntentType.TASK_SCHEDULING.value in intent_scores:
            if not _is_scheduling_intent(combined_lower):
                del intent_scores[IntentType.TASK_SCHEDULING.value]

        # 스펙 §4.1 — deep 엔진 유형 판별(Phase 2). 유형이 잡히면 그 intent가
        # 키워드 스코어링을 이긴다. 단 TASK_SCHEDULING은 라우터의
        # _PRIORITY_ROUTING_MAP에서 최우선이므로 살아있으면 양보한다.
        if IntentType.TASK_SCHEDULING.value not in intent_scores:
            engine_intent = _classify_engine_intent(combined_lower)
            if engine_intent:
                print(f"[DEBUG] Deep engine intent detected: {engine_intent}")
                return engine_intent

        # 가장 높은 점수의 의도 반환
        if intent_scores:
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `.venv/bin/pytest tests/workflow/utils/test_query_classifier_engine_intents.py -q -p no:cacheprovider`
Expected: PASS (18 passed)

- [ ] **Step 6: 기존 분류기 회귀 확인**

Run: `.venv/bin/pytest tests/test_youtube_workflow_integration.py -q -p no:cacheprovider`
Expected: PASS — 기존 분류가 전부 그대로여야 한다

- [ ] **Step 7: 커밋**

```bash
git add neos/workflow/utils/query_classifier.py tests/workflow/utils/test_query_classifier_engine_intents.py
git commit -m "$(cat <<'EOF'
feat(routing): emit deep engine type intents from keyword classifier

세 deep 엔진을 임계값이 아니라 질의 유형으로 가르기 위한 전제(스펙 §4.3-1).
기존 intent_keywords 스코어링 맵은 손대지 않고 전용 전처리로 분리해
기존 intent 방출을 구조적으로 불변으로 유지한다(K3).

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: LLM 분류기가 세 유형을 설명하고 방출한다

**Files:**
- Modify: `neos/workflow/utils/query_classifier.py:77-90` (`_LLM_CLASSIFICATION_PROMPT`의 Rules 절)
- Test: `tests/workflow/utils/test_query_classifier_engine_intents.py` (Task 1에서 만든 파일에 추가)

**Interfaces:**
- Consumes: `_VALID_INTENTS = [it.value for it in IntentType]` (기존, 이미 세 intent를 전부 포함한다 — 프롬프트 Rules만 비어 있었다)
- Produces: `_LLM_CLASSIFICATION_PROMPT` Rules에 세 유형 설명 3줄. `QueryClassifier._classify_with_llm(query, conversation_context="") -> Optional[Dict]` 시그니처 불변

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/workflow/utils/test_query_classifier_engine_intents.py` 끝에 추가:

```python
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
    monkeypatch.setattr(
        "neos.utils.llm_factory.create_llm", lambda **kwargs: fake
    )

    result = await classifier._classify_with_llm("이 주제를 다뤄줘")

    assert result is not None
    assert result["intent"] == intent_value
    # 프롬프트에 세 유형 Rules가 실제로 실려 나갔는지 확인
    assert intent_value in fake.prompts[0]
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `.venv/bin/pytest tests/workflow/utils/test_query_classifier_engine_intents.py::test_llm_prompt_rules_describe_three_engine_types -q -p no:cacheprovider`
Expected: FAIL — `AssertionError: Rules에 deep_analysis 설명이 없다`

- [ ] **Step 3: 최소 구현 — Rules에 세 유형 추가**

`neos/workflow/utils/query_classifier.py`의 `_LLM_CLASSIFICATION_PROMPT`에서 아래 기존 두 줄:

```python
- "generation" for creating content, images, files
- "task_execution" for planning, executing tasks
```

를 다음으로 교체(세 줄 추가):

```python
- "generation" for creating content, images, files
- "task_execution" for planning, executing tasks
- "deep_analysis" for verification-style queries where the goal is to establish whether a claim is true: fact-checking, verifying sources, cross-checking conflicting evidence
- "hyper_deep_research" for long-form report writing where length and section structure are the goal: whitepapers, multi-section or multi-page reports
- "recursive_research" for multi-step executable task decomposition: carry out a sequence of dependent steps or sub-tasks (not a research report)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv/bin/pytest tests/workflow/utils/test_query_classifier_engine_intents.py -q -p no:cacheprovider`
Expected: PASS (23 passed)

- [ ] **Step 5: 커밋**

```bash
git add neos/workflow/utils/query_classifier.py tests/workflow/utils/test_query_classifier_engine_intents.py
git commit -m "$(cat <<'EOF'
feat(routing): describe deep engine types in LLM classifier rules

R2: _VALID_INTENTS는 세 intent를 전부 허용했지만 프롬프트 Rules에 설명이
없어 사실상 방출되지 않았다. Rules에 세 유형을 명시해 LLM 경로를 살린다.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: 라우터를 유형 기반 단일 디스패치로 재작성한다

**Files:**
- Modify: `neos/workflow/routing/orchestrator_router.py:1-15`(import), `:65-74`(`_ALWAYS_SEARCH_INTENTS`), `:80-131`(`route`)
- Test: `tests/workflow/routing/test_engine_reassignment.py` (신규)

**Interfaces:**
- Consumes: Task 1·2가 방출하는 세 유형 intent
- Produces:
  - `DeepEngine` — frozen dataclass. 필드: `name: str`, `intent: str`, `enabled_flag: str`, `threshold_attr: str`
  - `_DEEP_ENGINES: tuple[DeepEngine, ...]` — 모듈 전역. **튜플 순서 = 레거시 generic intent의 fallback 우선순위**
  - `_GENERIC_DEEP_INTENTS: frozenset[str]` — `{deep_research, complex_analysis}`
  - `OrchestratorRouter.select_deep_engine(*, intent: str, complexity: float) -> str | None` — 유형 → 엔진명. 해당 없으면 `None`
  - `OrchestratorRouter.route(state) -> str` — 시그니처·반환 키(`"deep_analysis"`/`"hyper_deep"`/`"recursive"`/`"needs_approval"`/`"task_scheduling"`/`"ui_frame"`/`WorkflowPathway.*`) 전부 불변

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/workflow/routing/test_engine_reassignment.py` 신규 작성:

```python
"""스펙 §4 — 엔진 재배치. 유형 기반 단일 디스패치 (AC1·AC2·AC4·AC5).

R1(임계값 역전): 세 블록이 같은 intent를 두고 경쟁해 뒤 두 엔진의 complexity
경로가 100% 도달 불가였다. 재배치 후 각 엔진은 자기 유형 intent로 항상 도달
가능해야 한다.
"""

import inspect
from contextlib import contextmanager
from unittest.mock import patch

import pytest

from neos.workflow.enums import AutonomyLevel, IntentType, WorkflowPathway
from neos.workflow.routing import OrchestratorRouter
from neos.workflow.routing.orchestrator_router import _DEEP_ENGINES

pytestmark = pytest.mark.no_db

# 실제 스키마 기본값(neos/config/schema.py) — 임계값 역전을 그대로 재현한다.
_REAL_THRESHOLDS = {
    "DEEP_ANALYSIS_COMPLEXITY_THRESHOLD": 0.5,
    "HYPER_DEEP_COMPLEXITY_THRESHOLD": 0.85,
    "RECURSIVE_COMPLEXITY_THRESHOLD": 0.8,
}


def _state(intent, complexity=0.9):
    return {
        "autonomy_level": AutonomyLevel.ASSISTED.value,
        "query_intent": intent,
        "query_classification": {"complexity_score": complexity},
        "required_agents": [],
        "selected_tools": [],
        "original_query": "테스트 질의",
    }


@contextmanager
def _engines(*, deep_analysis=True, hyper_deep=True, recursive=True):
    with patch("neos.workflow.routing.orchestrator_router.settings") as mock_settings:
        mock_settings.A2UI_ENABLED = False
        mock_settings.EXECUTION_APPROVAL_ENABLED = False
        mock_settings.DEEP_ANALYSIS_ENABLED = deep_analysis
        mock_settings.HYPER_DEEP_AGENT_ENABLED = hyper_deep
        mock_settings.RECURSIVE_AGENT_ENABLED = recursive
        for attr, value in _REAL_THRESHOLDS.items():
            setattr(mock_settings, attr, value)
        yield mock_settings


# ── AC1 + AC4: 세 엔진 모두 활성일 때 각 엔진에 도달하는 질의가 존재한다 ──


def test_every_engine_is_reachable_when_all_three_are_enabled():
    """AC1·AC4. 임계값 역전(0.5 < 0.8 < 0.85)이 그대로여도 셋 다 도달 가능해야 한다."""
    reached = {}
    for engine in _DEEP_ENGINES:
        with _engines():
            reached[engine.name] = OrchestratorRouter().route(_state(engine.intent))

    assert reached == {engine.name: engine.name for engine in _DEEP_ENGINES}
    assert set(reached) == {"deep_analysis", "hyper_deep", "recursive"}


def test_no_engine_branch_is_unreachable_via_generic_fallback():
    """AC4. 레거시 generic intent의 fallback 경로도 엔진마다 도달 가능해야 한다."""
    with _engines(deep_analysis=True, hyper_deep=True, recursive=True):
        assert OrchestratorRouter().route(_state(IntentType.DEEP_RESEARCH.value)) == "deep_analysis"
    with _engines(deep_analysis=False, hyper_deep=True, recursive=True):
        assert OrchestratorRouter().route(_state(IntentType.DEEP_RESEARCH.value)) == "hyper_deep"
    with _engines(deep_analysis=False, hyper_deep=False, recursive=True):
        assert OrchestratorRouter().route(_state(IntentType.DEEP_RESEARCH.value)) == "recursive"


def test_explicit_type_intent_beats_generic_priority():
    """R1 해소의 핵심: deep_analysis가 1순위여도 유형 intent는 자기 엔진에 간다."""
    with _engines():
        assert OrchestratorRouter().route(_state(IntentType.HYPER_DEEP_RESEARCH.value)) == "hyper_deep"
        assert OrchestratorRouter().route(_state(IntentType.RECURSIVE_RESEARCH.value)) == "recursive"


def test_type_intent_ignores_complexity_gate():
    """스펙 §4.3-3: complexity는 '엔진을 쓸지'의 게이트일 뿐, 유형이 엔진을 정한다.
    유형을 명시한 질의는 낮은 complexity에서도 자기 엔진에 도달한다."""
    with _engines():
        assert OrchestratorRouter().route(_state(IntentType.HYPER_DEEP_RESEARCH.value, 0.0)) == "hyper_deep"


def test_disabled_engine_with_its_type_intent_falls_back_to_base_route():
    with _engines(hyper_deep=False):
        result = OrchestratorRouter().route(_state(IntentType.HYPER_DEEP_RESEARCH.value))
    assert result == WorkflowPathway.USE_ORCHESTRATORS.value


def test_generic_intent_below_gate_does_not_take_any_engine():
    with _engines():
        result = OrchestratorRouter().route(_state(IntentType.DEEP_RESEARCH.value, 0.1))
    assert result == WorkflowPathway.USE_ORCHESTRATORS.value


# ── AC2: 동일 구조 반복 블록이 남지 않는다 ────────────────────────────


def test_route_has_no_per_engine_repeated_blocks():
    """AC2. 엔진별 지식은 _DEEP_ENGINES 테이블에만 있어야 한다 — 분기 코드가
    엔진 수만큼 늘어나면 R1(임계값 역전)이 재발한다."""
    source = inspect.getsource(OrchestratorRouter.route)
    source += inspect.getsource(OrchestratorRouter.select_deep_engine)

    for flag in ("DEEP_ANALYSIS_ENABLED", "HYPER_DEEP_AGENT_ENABLED", "RECURSIVE_AGENT_ENABLED"):
        assert flag not in source, f"{flag}가 분기 코드에 하드코딩됐다"
    for threshold in (
        "DEEP_ANALYSIS_COMPLEXITY_THRESHOLD",
        "HYPER_DEEP_COMPLEXITY_THRESHOLD",
        "RECURSIVE_COMPLEXITY_THRESHOLD",
    ):
        assert threshold not in source, f"{threshold}가 분기 코드에 하드코딩됐다"
    for name in ('"deep_analysis"', '"hyper_deep"', '"recursive"'):
        assert name not in source, f"{name}가 분기 코드에 하드코딩됐다"


def test_engine_table_covers_three_engines_and_is_consistent():
    assert [e.name for e in _DEEP_ENGINES] == ["deep_analysis", "hyper_deep", "recursive"]
    assert [e.intent for e in _DEEP_ENGINES] == [
        IntentType.DEEP_ANALYSIS.value,
        IntentType.HYPER_DEEP_RESEARCH.value,
        IntentType.RECURSIVE_RESEARCH.value,
    ]


# ── AC5: 세 엔진 모두 비활성일 때 무회귀 ──────────────────────────────


@pytest.mark.parametrize(
    "intent",
    [
        IntentType.DEEP_ANALYSIS.value,
        IntentType.HYPER_DEEP_RESEARCH.value,
        IntentType.RECURSIVE_RESEARCH.value,
        IntentType.DEEP_RESEARCH.value,
        IntentType.COMPLEX_ANALYSIS.value,
    ],
)
def test_no_regression_when_all_engines_disabled(intent):
    with _engines(deep_analysis=False, hyper_deep=False, recursive=False):
        result = OrchestratorRouter().route(_state(intent))

    assert result not in {"deep_analysis", "hyper_deep", "recursive"}
    assert result == WorkflowPathway.USE_ORCHESTRATORS.value


def test_manual_autonomy_blocks_all_engines():
    state = _state(IntentType.DEEP_ANALYSIS.value)
    state["autonomy_level"] = AutonomyLevel.MANUAL.value

    with _engines():
        result = OrchestratorRouter().route(state)

    assert result not in {"deep_analysis", "hyper_deep", "recursive"}
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `.venv/bin/pytest tests/workflow/routing/test_engine_reassignment.py -q -p no:cacheprovider`
Expected: FAIL — 수집 단계에서 `ImportError: cannot import name '_DEEP_ENGINES' from 'neos.workflow.routing.orchestrator_router'`

- [ ] **Step 3: 최소 구현 — 엔진 테이블 추가**

`neos/workflow/routing/orchestrator_router.py` 상단 import에 `dataclass`를 추가:

```python
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from neos.config.settings import settings
from neos.workflow.autonomy.middleware import get_policy_from_state
from neos.workflow.enums import IntentType, WorkflowPathway
```

`_ALWAYS_SEARCH_INTENTS` 정의(현재 65-74행) **바로 아래**에 추가:

```python


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
```

- [ ] **Step 4: 최소 구현 — route()를 단일 디스패치로 교체**

같은 파일에서 `route` 메서드 전체(현재 80-131행, `def base_route` 직전까지)를 아래로 교체:

```python
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
```

- [ ] **Step 5: 최소 구현 — `_ALWAYS_SEARCH_INTENTS`에 DEEP_ANALYSIS 추가**

`_ALWAYS_SEARCH_INTENTS`(65-74행)에서 누락된 `DEEP_ANALYSIS`를 추가한다. 나머지 두 유형 intent는 이미 있다 — 이제 분류기가 세 유형을 **실제로 방출**하므로, 엔진이 꺼져 있을 때 검증형 질의가 검색 없이 `skip_orchestrators`로 새는 구멍을 막는다:

```python
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
```

- [ ] **Step 6: 테스트 통과 확인**

Run: `.venv/bin/pytest tests/workflow/routing/test_engine_reassignment.py -q -p no:cacheprovider`
Expected: PASS (16 passed)

- [ ] **Step 7: 기존 라우팅 회귀 확인**

Run: `.venv/bin/pytest tests/workflow/routing/ tests/workflow/test_deep_analysis_node.py -q -p no:cacheprovider`
Expected: PASS — 기존 `test_deep_analysis_routing.py`(7개)·`test_autonomy_routing.py`(4개)가 전부 그대로 통과해야 한다

- [ ] **Step 8: 커밋**

```bash
git add neos/workflow/routing/orchestrator_router.py tests/workflow/routing/test_engine_reassignment.py
git commit -m "$(cat <<'EOF'
refactor(routing): dispatch deep engines by query type, not threshold

R1 해소: 세 개의 거의 동일한 if-블록이 같은 intent를 두고 경쟁하면서
우선순위(deep_analysis→hyper_deep→recursive)와 임계값(0.5→0.85→0.8)이
역전돼 뒤 두 엔진의 complexity 경로가 도달 불가능한 죽은 코드였다.

_DEEP_ENGINES 테이블 기반 단일 디스패치로 교체한다. 유형 intent가 엔진을
결정하고, complexity는 유형 없는 레거시 intent의 게이트로만 남는다.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: D21로 결정을 기록한다

**Files:**
- Modify: `neos/workflow/deep_analysis/DECISIONS.md` (D20 뒤에 추가, 현재 409-423행 이후)

**Interfaces:**
- Consumes: Task 1~3의 구현 결과
- Produces: 문서만. 코드 영향 없음

- [ ] **Step 1: D21 항목 추가**

`neos/workflow/deep_analysis/DECISIONS.md` 맨 끝(D20의 "**영향:**" 문단 다음)에 추가. 기존 D 항목의 형식(**결정 / 근거 / 이탈 / 영향**)을 그대로 따른다:

```markdown

---

## D21. deep 엔진 라우팅은 complexity 임계값이 아니라 질의 유형으로 가른다 (R1 해소, D18 선결 조건 #3 해소)

**결정:** `OrchestratorRouter.route()`의 엔진별 3중 if-체인을 `_DEEP_ENGINES` 테이블 기반
**단일 디스패치**로 교체한다. 각 엔진은 자기 유형 intent를 갖고(스펙 §4.1) — `deep_analysis`
= 검증형 분석, `hyper_deep` = 장문 리포트, `recursive` = 일반 태스크 분해 — 유형 intent가
엔진을 **결정**한다. complexity 임계값은 "deep 엔진을 쓸지 말지"의 게이트로만 남고 "어느
엔진인지"는 결정하지 않는다. 유형을 지목하지 않는 레거시 intent(`DEEP_RESEARCH`,
`COMPLEX_ANALYSIS`)만 임계값 게이트를 타며, 테이블 순서(deep_analysis → hyper_deep →
recursive)상 처음으로 "활성 + 게이트 통과"인 엔진이 받는다. 분류기(`query_classifier`)는
키워드 경로와 LLM 경로 **양쪽에서** 세 유형 intent를 방출한다.

**근거 — R1(임계값 역전, 기존 문서 미기록):** 종전 `orchestrator_router.py:98-129`의 세 블록은
플래그명·상수·임계값만 다른 거의 동일한 코드였고 **셋 다 같은 intent를 두고 경쟁**했다.
라우팅 순서는 deep_analysis(1순위) → hyper_deep(2순위) → recursive(3순위)인데 임계값은
0.5 → 0.85 → 0.8로 **역전**돼 있었다. 0.85를 넘는 질의는 0.5도 이미 넘으므로 deep_analysis가
먼저 가져간다 — 즉 `DEEP_ANALYSIS_ENABLED=true`인 순간 뒤 두 엔진의 complexity 경로는
**100% 도달 불가능한 죽은 코드**가 됐다. 에러도 경고도 없다. 유일한 탈출구인 명시적
intent는 R2(아래)로 막혀 있었으므로, 플래그를 켜는 것만으로 ROMA·Ray·HyperDeep이 통째로
조용히 사라졌다. 임계값은 "얼마나 어려운가"라는 **1차원 척도**여서 세 엔진의 역할 차이를
표현할 수 없다 — 세 엔진은 난이도가 아니라 **산출물의 형태**가 다르다. 척도를 유형으로
바꾸면 경쟁 자체가 성립하지 않는다.

**근거 — R2 해소(= D18 "프로덕션 활성화 전 선결 조건" #3):** D18은 "`IntentType.DEEP_ANALYSIS`를
방출하는 쿼리 분류기가 아직 없어 intent 기반 라우팅 분기는 도달 불가능한 죽은 코드"라
기록하고 활성화 전 처리를 요구했다. 키워드 경로는 해당 intent를 아예 생성하지 않았고, LLM
경로는 `_VALID_INTENTS`에 전부 넣으면서 프롬프트 Rules에는 9개만 설명해 사실상 방출되지
않았으며, `use_llm` 기본값이 꺼짐이라 키워드 경로가 기본이었다. 이 결정으로 **세 유형 모두
양쪽 경로에서 방출**되므로 선결 조건 #3은 해소된다. (선결 조건 #1 wall-clock 바운드는
**미해소로 남는다** — 이 결정의 범위 밖이며 활성화 전 여전히 필요하다.)

**이탈:** 없음(원 설계는 챗 라우팅 방식을 규정하지 않는다). 승인 스펙
`docs/superpowers/specs/2026-07-17-loop-architecture-consolidation-design.md` §4를 그대로 구현한다.
**엔진은 삭제하지 않는다 — 재배치지 제거가 아니다**(스펙 §7).

**영향 — 레거시 generic intent는 여전히 우선순위로 갈린다(의도된 잔여):** 스펙 §4.2는
"세 엔진이 같은 intent를 두고 경쟁하지 않게 되므로 shadowing이 사라진다"고 하지만, 이는
**유형 intent에 대해** 성립한다. `DEEP_RESEARCH`/`COMPLEX_ANALYSIS`는 유형을 지목하지
않으므로 어느 엔진이 받을지 정의되지 않으며, 여기에 여전히 우선순위가 필요하다. 이를
`deep_analysis` 1:1로 좁히는 대안은 **회귀**다 — 현재 프로덕션에 가까운 구성
(`DEEP_ANALYSIS_ENABLED=false` + `HYPER_DEEP_AGENT_ENABLED=true`)에서 오늘 `hyper_deep`으로
가는 고복잡도 `deep_research` 질의가 `base_route`로 떨어진다. 따라서 테이블 순서로 남기되,
**R1과는 성질이 다르다**: (a) 순서가 임계값 상수의 사고가 아니라 테이블에 명시·문서화돼
있고, (b) 어떤 엔진도 100% 도달 불가가 아니다 — `hyper_deep`/`recursive`는 자기 유형
intent로 항상 도달한다. 후자를
`tests/workflow/routing/test_engine_reassignment.py::test_every_engine_is_reachable_when_all_three_are_enabled`
가 강제한다.

**영향 — 기존 intent 방출 불변(K3):** 신규 유형 키워드는 기존 `intent_keywords` 스코어링
맵에 넣지 않고 전용 전처리(`_classify_engine_intent`)로 분리했다. 저 맵은 매칭 수를 세어
`max()`로 뽑으므로 키워드를 섞으면 기존 질의의 승자가 바뀔 수 있다. 전처리는 "신규 키워드가
하나도 안 맞으면 `None`"이라 기존 방출이 **구조적으로** 불변이다. `TASK_SCHEDULING`은
라우터 `_PRIORITY_ROUTING_MAP`에서 최우선이므로 전처리가 양보한다. 회귀 고정:
`tests/workflow/utils/test_query_classifier_engine_intents.py::test_existing_intent_emission_is_unchanged`.

**영향 — 엔진 추가는 이제 테이블 한 줄이다:** `DeepEngine(name, intent, enabled_flag,
threshold_attr)`을 `_DEEP_ENGINES`에 추가하면 된다. 분기 코드는 늘지 않는다 — R1의 재발
경로가 구조적으로 닫힌다. `test_route_has_no_per_engine_repeated_blocks`가 엔진명·플래그명·
임계값명이 분기 코드에 하드코딩되는 것을 금지해 이를 강제한다.

**영향 — `_ALWAYS_SEARCH_INTENTS`에 `DEEP_ANALYSIS` 추가:** 세 유형이 실제로 방출되기
시작하므로, 엔진이 꺼진 상태에서 검증형 질의가 검색 없이 `skip_orchestrators`로 새지
않도록 `deep_analysis`를 always-search 목록에 넣는다(나머지 두 유형은 이미 있었다).
```

- [ ] **Step 2: 커밋**

```bash
git add neos/workflow/deep_analysis/DECISIONS.md
git commit -m "$(cat <<'EOF'
docs(deep-analysis): record D21 engine reassignment decision

R1(임계값 역전)은 기존 문서 어디에도 기록이 없었다. 결정과 함께
D18 선결 조건 #3(분류기 intent 미도달) 해소를 명시한다.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: 전체 무회귀 검증

**Files:** 없음(검증 전용)

**Interfaces:**
- Consumes: Task 1~4
- Produces: 없음

- [ ] **Step 1: workflow 전체 스위트 (basename 충돌 2개 제외)**

Run:
```bash
.venv/bin/pytest tests/workflow/ -q -p no:cacheprovider \
  --ignore=tests/workflow/mission/test_executor.py \
  --ignore=tests/workflow/harness/test_policy.py
```
Expected: PASS — HEAD 기준선 341 + 신규 39(Task 1의 18 + Task 2의 5 + Task 3의 16) = **380 passed**

- [ ] **Step 2: basename 충돌 파일 2개 별도 실행**

Run: `.venv/bin/pytest tests/workflow/mission/test_executor.py tests/workflow/harness/test_policy.py -q -p no:cacheprovider`
Expected: PASS — **13 passed** (기준선과 동일)

- [ ] **Step 3: 분류기를 쓰는 통합 테스트 회귀**

Run: `.venv/bin/pytest tests/test_youtube_workflow_integration.py tests/test_workflow_graph.py -q -p no:cacheprovider`
Expected: PASS — 분류기 변경이 기존 워크플로우 통합에 영향을 주지 않아야 한다

- [ ] **Step 4: AC1 근거 — 세 엔진 도달 질의를 end-to-end로 확인**

분류기 → 라우터 왕복이 실제로 세 엔진에 닿는지 수동 확인한다(테스트가 아니라 보고용 근거):

```bash
.venv/bin/python - <<'PY'
import asyncio
from unittest.mock import patch

from neos.workflow.routing import OrchestratorRouter
from neos.workflow.state import WorkflowConfig
from neos.workflow.utils.query_classifier import QueryClassifier

QUERIES = [
    "이 주장이 사실인가 팩트체크해줘",
    "AI 반도체 시장에 대한 긴 보고서를 써줘",
    "이 작업을 단계별로 수행해줘",
]


async def main():
    classifier = QueryClassifier(WorkflowConfig())
    for query in QUERIES:
        intent = await classifier._classify_intent(query)
        state = {
            "autonomy_level": 1,
            "query_intent": intent,
            "query_classification": {"complexity_score": 0.9},
            "required_agents": [],
            "selected_tools": [],
            "original_query": query,
        }
        with patch("neos.workflow.routing.orchestrator_router.settings") as s:
            s.A2UI_ENABLED = False
            s.EXECUTION_APPROVAL_ENABLED = False
            s.DEEP_ANALYSIS_ENABLED = True
            s.HYPER_DEEP_AGENT_ENABLED = True
            s.RECURSIVE_AGENT_ENABLED = True
            s.DEEP_ANALYSIS_COMPLEXITY_THRESHOLD = 0.5
            s.HYPER_DEEP_COMPLEXITY_THRESHOLD = 0.85
            s.RECURSIVE_COMPLEXITY_THRESHOLD = 0.8
            route = OrchestratorRouter().route(state)
        print(f"{query!r}\n  intent={intent}  route={route}\n")


asyncio.run(main())
PY
```

Expected:
```
'이 주장이 사실인가 팩트체크해줘'
  intent=deep_analysis  route=deep_analysis

'AI 반도체 시장에 대한 긴 보고서를 써줘'
  intent=hyper_deep_research  route=hyper_deep

'이 작업을 단계별로 수행해줘'
  intent=recursive_research  route=recursive
```

---

## Self-Review

**1. 스펙 커버리지 (§4.3 필요 작업 3가지):**

| 스펙 요구 | 담당 |
|---|---|
| §4.3-1 분류기가 세 유형 intent 방출 — 키워드 경로 | Task 1 |
| §4.3-1 분류기가 세 유형 intent 방출 — LLM 경로 + 프롬프트 Rules | Task 2 |
| §4.3-2 3중 if-체인 → 유형 기반 단일 디스패치 | Task 3 |
| §4.3-3 complexity는 게이트로만, 유형이 엔진 결정 | Task 3 (`select_deep_engine`) |
| R1 기록 (DECISIONS.md D21) | Task 4 |

**AC 커버리지:**

| AC | 담당 테스트 |
|---|---|
| AC1 각 엔진 도달 질의 존재 | `test_every_engine_is_reachable_when_all_three_are_enabled`, Task 5 Step 4 |
| AC2 동일 구조 반복 블록 없음 | `test_route_has_no_per_engine_repeated_blocks` |
| AC3 세 유형 방출 (키워드·LLM 각각) | Task 1의 3개 파라미터 테스트 + Task 2의 `test_llm_path_emits_each_engine_type`·`test_llm_prompt_rules_describe_three_engine_types` |
| AC4 도달 불가 분기 0개 | `test_every_engine_is_reachable_when_all_three_are_enabled`, `test_no_engine_branch_is_unreachable_via_generic_fallback` |
| AC5 세 엔진 비활성 시 무회귀 | `test_no_regression_when_all_engines_disabled`(5 파라미터) + 기존 `test_no_regression_deep_analysis_off_by_default` |

**2. 플레이스홀더 스캔:** "TBD"/"적절히"/"Similar to Task N" 없음. 모든 코드 스텝에 실제 코드 수록.

**3. 타입 정합성:**
- `DeepEngine(name, intent, enabled_flag, threshold_attr)` — Task 3 Step 3 정의 ↔ Step 4 사용(`engine.name`/`engine.intent`/`engine.enabled_flag`/`engine.threshold_attr`) ↔ 테스트(`e.name`/`e.intent`) 일치
- `_classify_engine_intent(query_lower: str) -> Optional[str]` — Task 1 Step 3 정의 ↔ Step 4 호출(`_classify_engine_intent(combined_lower)`) ↔ 테스트 import 일치
- `select_deep_engine(*, intent, complexity)` — Task 3 Step 4 정의 ↔ `route()` 호출부 키워드 인자 일치 ↔ AC2 테스트의 `inspect.getsource(OrchestratorRouter.select_deep_engine)` 일치
- 라우팅 반환 키(`"deep_analysis"`/`"hyper_deep"`/`"recursive"`)가 `graph.py:413-418` `_routing_map` 키와 일치 — graph.py 무변경 조건 충족
- `Dict`/`List`/`Optional` — `query_classifier.py`가 이미 `typing`에서 import 중(9-11행). 신규 import 불필요
