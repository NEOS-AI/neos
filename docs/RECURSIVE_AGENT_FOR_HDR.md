# NEOS HyperDeep Recursive Agent 구현 문서

> **구현 기준:** NEOS v0.22.0
> **작성일:** 2026-03-08
> **참고 문서:**
> - [docs/RECURSIVE_AGENT_PLAN.md](./RECURSIVE_AGENT_PLAN.md) — ROMA 설계 계획
> - [docs/RECURSIVE_AGENT_IMPLE.md](./RECURSIVE_AGENT_IMPLE.md) — ROMA 구현 상세

---

## 1. 개요

**HyperDeep Recursive Agent**는 ROMA(Recursive Open Meta-Agent) 컴포넌트를 재사용하되, leaf 노드 실행을 `HyperDeepResearchAgent`로 교체한 통합 에이전트입니다.

### 기존 두 시스템의 한계

| 시스템 | 강점 | 약점 |
|--------|------|------|
| **ROMA** (`RecursiveOrchestrator`) | 복잡한 쿼리를 구조적으로 분해 | leaf 실행이 얕음 (LLM 직접 호출, Haiku) |
| **HyperDeepResearchAgent** | 100+ 소스, 다단계 분석, 비판적 검토 | 단일 쿼리를 선형 파이프라인으로만 처리 |

### 해결 전략

```
HyperDeep Recursive = ROMA 분해 구조 + HyperDeepResearchAgent 실행
```

복잡한 쿼리를 ROMA가 세부 주제로 분해하고, 각 세부 주제에 대해 완전한 HyperDeepResearch 파이프라인을 실행합니다.

### 핵심 설계 원칙: Strategy Injection

`RecursiveOrchestrator`는 실행자(executor)를 생성자 주입으로 받도록 확장했습니다. 덕분에 Atomizer, Planner, Aggregator, Verifier 4개 컴포넌트를 한 줄도 수정하지 않고 재사용합니다.

```python
# executor만 교체하면 나머지 ROMA 컴포넌트 전부 재사용
orchestrator = RecursiveOrchestrator(
    executor=HyperDeepExecutor(),   # ← 교체
    max_depth=1,                    # ← leaf가 무거우므로 얕은 분해
    budget_cap=5.0,                 # ← ROMA(0.5)보다 10× 높음
)
```

---

## 2. 실행 흐름

```
사용자 쿼리 (intent=hyper_deep_research 또는 complexity >= 0.85)
    │
    ▼
SKILL_TOOL_SELECTOR
    │  _should_use_recursive_agent() → "hyper_deep"
    ▼
HYPER_DEEP_ORCHESTRATOR (LangGraph 노드)
    │
    ├─ RecursiveAtomizer  → 분해 필요? (기존 ROMA 컴포넌트 그대로)
    │
    ├─ RecursivePlanner   → 세부 주제 목록 생성 (max_tasks=3, depth=1)
    │       ↓
    │   [sub-topic 1]  [sub-topic 2]  [sub-topic 3]
    │       │               │               │
    │       ▼               ▼               ▼
    │   HyperDeepExecutor.execute()  (각 세부 주제마다)
    │       │
    │       └─ HyperDeepResearchAgent.execute()
    │               - 100+ 소스 수집
    │               - 다단계 분석 (Topic → Planning → Collection → Analysis → Report)
    │               - 비판적 검토 & 반복적 정제
    │
    ├─ RecursiveAggregator → 세부 결과 통합 (bottom-up)
    │
    └─ RecursiveVerifier  → 충족도 검증 → 재계획 (미충족 시 최대 1회)
    │
    ▼
RESULT_INTEGRATOR → 기존 파이프라인 합류
```

---

## 3. 파일 구조

```
neos/workflow/hyper_deep/               ← 신규 디렉터리
├── __init__.py                         ← 패키지 공개 API (HyperDeepExecutor 노출)
└── executor.py                         ← HyperDeepExecutor (HyperDeepResearchAgent 래퍼)

neos/workflow/recursive/                ← 기존 ROMA (최소 수정)
├── orchestrator.py                     ← 수정: executor/max_depth/budget_cap/max_tasks_per_level 주입 지원
└── planner.py                          ← 수정: max_tasks_per_level 주입 지원

neos/workflow/
├── enums.py                            ← 수정: HYPER_DEEP_ORCHESTRATOR, HYPER_DEEP_RESEARCH 추가
└── graph.py                            ← 수정: 노드 등록, 라우팅, _hyper_deep_orchestrator_node 핸들러

neos/config/
└── settings.py                         ← 수정: HYPER_DEEP_* 설정 5개 추가

.env.template                           ← 수정: HYPER_DEEP_* 환경변수 예시 추가
```

---

## 4. 컴포넌트 상세

### 4.1 HyperDeepExecutor (`executor.py`)

ROMA의 `RecursiveExecutor`를 대체하는 실행자입니다. ATOMIC으로 판별된 태스크를 `HyperDeepResearchAgent.execute()`로 처리합니다.

**싱글톤 패턴:**
```python
def _get_agent(self) -> HyperDeepResearchAgent:
    if self._agent is None:
        self._agent = HyperDeepResearchAgent()  # 최초 1회만 생성
    return self._agent
```
`HyperDeepResearchAgent.__init__`이 무거운 초기화(TavilyClient, 다수의 서브에이전트 등)를 포함하므로 첫 실행 시점에만 생성합니다.

**상태 격리:**
```python
def _reset_agent_state(self, agent) -> None:
    """각 subtask 실행 전 agent 내부 상태 초기화."""
    agent.current_report_id = None
    agent.sections_data = []
    agent.all_collected_sources = []
    agent.research_metadata = { ... }
```
싱글톤 재사용 시 이전 실행의 상태가 남아있지 않도록 매 실행 전 리셋합니다.

**결과 추출:**
```python
def _extract_content(output: Dict[str, Any]) -> str:
    """format_output() 반환값에서 마크다운 리포트 텍스트 추출."""
    results = output.get("results", [])
    first = results[0]
    return first.content if hasattr(first, "content") else first.get("content", "")
```
`HyperDeepResearchAgent.execute()`는 `format_output()`을 통해 `{"results": [SearchResult], ...}` 형식으로 반환합니다.

**Graceful degradation:**
- Tavily API 불가 → `[HyperDeep 실패: API 불가]` 명시적 메시지 반환
- 예외 발생 → `[HyperDeep 실행 오류: ...]` 메시지 반환 (워크플로우 중단 없음)

---

### 4.2 RecursiveOrchestrator 확장 (`orchestrator.py`)

기존 코드를 최소한으로 수정하여 파라미터 주입을 지원합니다.

**변경 전:**
```python
def __init__(self, agents=None):
    self._executor = RecursiveExecutor(agents=agents)
    self._max_depth = settings.RECURSIVE_MAX_DEPTH
    self._budget_cap = settings.RECURSIVE_BUDGET_CAP
```

**변경 후:**
```python
def __init__(
    self,
    agents=None,
    executor=None,            # None이면 기존 RecursiveExecutor 사용
    max_depth=None,           # None이면 settings.RECURSIVE_MAX_DEPTH
    budget_cap=None,          # None이면 settings.RECURSIVE_BUDGET_CAP
    max_tasks_per_level=None, # None이면 settings.RECURSIVE_MAX_TASKS_PER_LEVEL
):
    self._executor = executor or RecursiveExecutor(agents=agents)
    self._max_depth = max_depth if max_depth is not None else settings.RECURSIVE_MAX_DEPTH
    self._budget_cap = budget_cap if budget_cap is not None else settings.RECURSIVE_BUDGET_CAP
```

기본값이 모두 `None → settings 값`이므로 **기존 ROMA 동작이 100% 보존**됩니다.

---

### 4.3 라우팅 (`graph.py`)

`_should_use_recursive_agent()` 함수가 4-way 라우팅으로 확장됩니다.

```
"hyper_deep"        → HYPER_DEEP_ORCHESTRATOR  (1순위: 더 강력한 에이전트)
"recursive"         → RECURSIVE_ORCHESTRATOR    (2순위: 기존 ROMA)
"use_orchestrators" → HYPOTHESIS_GENERATION     (기존 경로)
"skip"              → RESP_GENERATOR            (기존 경로)
```

**HyperDeep 라우팅 조건:**
1. `intent == "hyper_deep_research"` → 항상 hyper_deep (명시적 지정)
2. `complexity >= 0.85 AND intent in (deep_research, complex_analysis)` → hyper_deep

**ROMA 라우팅 조건** (HyperDeep 미충족 시):
1. `intent == "recursive_research"` → recursive
2. `complexity >= 0.80 AND intent in (deep_research, complex_analysis)` → recursive

---

## 5. 설정

| 설정 변수 | 기본값 | ROMA 대비 | 설명 |
|-----------|--------|-----------|------|
| `HYPER_DEEP_AGENT_ENABLED` | `false` | — | 피처 플래그 |
| `HYPER_DEEP_MAX_DEPTH` | `1` | ROMA: 3 | leaf가 무겁기 때문에 얕은 분해 권장 |
| `HYPER_DEEP_MAX_TASKS_PER_LEVEL` | `3` | ROMA: 4 | 세부 주제 수 (3 = 3× HyperDeepResearch 실행) |
| `HYPER_DEEP_COMPLEXITY_THRESHOLD` | `0.85` | ROMA: 0.80 | 더 높은 복잡도 기준 |
| `HYPER_DEEP_BUDGET_CAP` | `5.0` | ROMA: 0.5 | USD 한도 (HyperDeep은 소스 수집 비용이 큼) |

---

## 6. Enum 추가 (`enums.py`)

```python
class WorkflowNode(Enum):
    HYPER_DEEP_ORCHESTRATOR = "hyper_deep_orchestrator"

class IntentType(Enum):
    HYPER_DEEP_RESEARCH = "hyper_deep_research"
```

`"hyper_deep_research"` 문자열은 이미 `refinement_service.py`, `settings.py`(timeout), `cost_router.py`에서 문자열로 사용 중이었으므로 이번에 enum으로 공식화했습니다.

---

## 7. 비용 모델

HyperDeep Recursive의 비용은 ROMA와 다릅니다.

**ROMA (기존):**
- Atomizer: Haiku × 노드 수
- Executor: Haiku × leaf 수
- 예상: $0.05~0.20 (depth=3, tasks=4)

**HyperDeep Recursive:**
- ROMA 컴포넌트 (Atomizer/Planner/Aggregator/Verifier): Haiku × 소수
- HyperDeepExecutor (각 leaf): Tavily API + 다수의 LLM 호출 (내부적으로 수십 회)
- 예상: $1.0~5.0 (depth=1, tasks=3)

> `HYPER_DEEP_BUDGET_CAP=5.0`이 하드 한도로 작동합니다. 초과 시 `graceful_degrade()`가 호출되어 지금까지 완료된 subtask 결과를 통합해 부분 결과를 반환합니다.

---

## 8. ROMA와의 컴포넌트 재사용 비교

| 컴포넌트 | ROMA | HyperDeep Recursive | 변경 여부 |
|----------|------|---------------------|-----------|
| `RecursiveAtomizer` | ✅ 사용 | ✅ 그대로 재사용 | 없음 |
| `RecursivePlanner` | ✅ 사용 | ✅ 그대로 재사용 (max_tasks 주입만 추가) | 최소 |
| `RecursiveExecutor` | ✅ 사용 | ❌ → `HyperDeepExecutor`로 교체 | 교체 |
| `RecursiveAggregator` | ✅ 사용 | ✅ 그대로 재사용 | 없음 |
| `RecursiveVerifier` | ✅ 사용 | ✅ 그대로 재사용 | 없음 |
| `RecursiveOrchestrator` | ✅ 사용 | ✅ 동일 클래스, 다른 파라미터 | 파라미터만 |

---

## 9. 활성화 방법

`.env` 파일에 다음을 추가합니다:

```bash
HYPER_DEEP_AGENT_ENABLED=true
HYPER_DEEP_MAX_DEPTH=1
HYPER_DEEP_MAX_TASKS_PER_LEVEL=3
HYPER_DEEP_COMPLEXITY_THRESHOLD=0.85
HYPER_DEEP_BUDGET_CAP=5.0
```

ROMA와 독립적으로 활성화 가능합니다. 두 에이전트를 동시에 켜면 HyperDeep이 더 높은 우선순위로 동작합니다.

---

## 10. 검증 시나리오

**시나리오 1: 피처 플래그 비활성화**
```bash
HYPER_DEEP_AGENT_ENABLED=false  # 기본값
# 기존 워크플로우 완전 동일 동작 확인
```

**시나리오 2: 명시적 intent로 활성화**
```python
# query_classification에서 intent="hyper_deep_research"로 분류 시
# complexity 임계값과 무관하게 HYPER_DEEP_ORCHESTRATOR 진입
```

**시나리오 3: 복잡도 기반 자동 활성화**
```bash
HYPER_DEEP_AGENT_ENABLED=true
# 테스트 쿼리: "2025년 글로벌 반도체 공급망 재편이 한국, 대만, 미국, 일본 각국의
#               첨단 산업 경쟁력에 미친 영향과 향후 5년 전망을 비교 분석해줘"
# 예상: complexity >= 0.85 + COMPLEX_ANALYSIS intent → HYPER_DEEP_ORCHESTRATOR 진입
```

**시나리오 4: 비용 한도 테스트**
```bash
HYPER_DEEP_BUDGET_CAP=0.01  # 극히 낮은 한도
# 예상: 첫 번째 leaf 실행 후 graceful_degrade() 호출, 부분 결과 반환
```

**시나리오 5: ROMA와 동시 활성화**
```bash
RECURSIVE_AGENT_ENABLED=true
HYPER_DEEP_AGENT_ENABLED=true
# 예상: HYPER_DEEP 우선 (복잡도 0.85+ 또는 hyper_deep_research intent)
#        ROMA는 0.80 <= complexity < 0.85 범위 또는 recursive_research intent에서만 동작
```

---

## 11. 관련 파일 참고 목록

| 파일 | 역할 |
|------|------|
| [neos/workflow/hyper_deep/executor.py](../neos/workflow/hyper_deep/executor.py) | HyperDeepExecutor 구현 |
| [neos/workflow/recursive/orchestrator.py](../neos/workflow/recursive/orchestrator.py) | ROMA 엔진 (파라미터 주입 확장) |
| [neos/workflow/recursive/planner.py](../neos/workflow/recursive/planner.py) | ROMA 분해기 (max_tasks 주입 확장) |
| [neos/agents/search_agents/hyper_deep_research/agent.py](../neos/agents/search_agents/hyper_deep_research/agent.py) | HyperDeepResearchAgent |
| [neos/workflow/enums.py](../neos/workflow/enums.py) | HYPER_DEEP_ORCHESTRATOR, HYPER_DEEP_RESEARCH |
| [neos/workflow/graph.py](../neos/workflow/graph.py) | 워크플로우 통합 지점 |
| [neos/config/settings.py](../neos/config/settings.py) | HYPER_DEEP_* 설정 |
| [docs/RECURSIVE_AGENT_IMPLE.md](./RECURSIVE_AGENT_IMPLE.md) | ROMA 구현 문서 (기반 시스템) |
