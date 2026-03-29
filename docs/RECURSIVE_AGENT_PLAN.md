# NEOS 재귀적 에이전트 워크플로우 구현 계획

> **참고 논문/구현:** [ROMA: Recursive Open Meta-Agent](https://discuss.pytorch.kr/t/roma-recursive-open-meta-agent/8691)
> **작성일:** 2026-03-07
> **대상 버전:** NEOS v0.22.0+

---

## 1. 개요 및 목적

### 1.1 ROMA란?

ROMA(Recursive Open Meta-Agent)는 복잡한 문제를 계층적으로 분해하여 재귀적으로 해결하는 메타 에이전트 프레임워크입니다. SEAL-0 벤치마크에서 45.6%의 정확도를 기록, Kimi Researcher(36%), Gemini 2.5 Pro(19.8%)를 초과하는 성능을 달성했습니다.

**핵심 원리:** 모든 문제는 "직접 해결 가능한가(atomic), 아니면 더 작은 하위 문제로 분해해야 하는가"의 이진(binary) 결정에서 시작합니다. 이 결정은 재귀적으로 반복되며 트리 구조의 실행 계획을 형성합니다.

### 1.2 현재 NEOS 워크플로우와의 차이점

| 항목 | 현재 NEOS | ROMA 적용 후 |
|------|-----------|-------------|
| 문제 분해 | 단일 계층 (`replanner` 루프백) | 다층 계층 트리 (재귀적 서브그래프) |
| 분기 결정 | `should_replan` (단순 coverage 체크) | `Atomizer` (LLM 기반 원자성 판단) |
| 실행 단위 | 에이전트별 고정 역할 | 동적 하위 태스크 생성 및 실행 |
| 결과 통합 | `result_integrator` (단층 병합) | `Aggregator` (계층별 상향 통합) |
| 검증 | `quality_validator` (단순 점수) | `Verifier` (원래 쿼리 대비 충족도 검증) |

### 1.3 구현 목표

- 복잡한 멀티-호프 질문에서 **자율적 문제 분해**를 수행
- 각 하위 문제가 해결 불가능하다고 판단될 경우 **재귀적으로 재분해**
- 하위 문제 결과를 **계층별로 상향 통합**하여 최종 답변 구성
- 재귀 깊이 제어 및 비용 인식 라우팅으로 **무한 루프 방지**

---

## 2. ROMA 핵심 컴포넌트 분석

```
                        ┌─────────────────────────────┐
                        │   ROMA 실행 흐름 (트리 구조)   │
                        └─────────────────────────────┘

Problem P
    │
    ▼
[Atomizer] ─── atomic? ──→ [Executor] ──→ Result
    │
    │ not atomic
    ▼
[Planner] ─── sub-tasks ──→ [P1, P2, P3]
                                │
                    ┌───────────┼───────────┐
                    ▼           ▼           ▼
              [Atomizer]  [Atomizer]  [Atomizer]
                 │ ...       │ ...       │ ...
                 ▼           ▼           ▼
               R(P1)        R(P2)       R(P3)
                    └───────────┼───────────┘
                                ▼
                          [Aggregator]
                                │
                                ▼
                          [Verifier]
                                │
                     ┌──────────┴──────────┐
                     ▼                     ▼
                  Satisfied          Not Satisfied
                     │                     │
                     ▼                     ▼
               Final Answer      Recursive Re-planning
```

### 2.1 5대 핵심 컴포넌트

#### Atomizer (원자성 판별기)
- **역할:** 태스크가 즉시 실행 가능한지, 더 분해해야 하는지 판단
- **입력:** 현재 태스크 설명 + 사용 가능한 컨텍스트
- **출력:** `atomic=True` (직접 실행) / `atomic=False` (분해 필요)
- **판단 기준:**
  - 단일 검색으로 해결 가능한가?
  - 도구 하나로 처리 가능한가?
  - 외부 의존성이 없는가?

#### Planner (하위 태스크 분해기)
- **역할:** non-atomic 태스크를 2-N개의 하위 태스크로 분해
- **현재 NEOS 유사 컴포넌트:** `PlanningAgent.create_research_plan()`, `ResearchReplanner`
- **개선 방향:** 하위 태스크 간 의존성 그래프(DAG) 생성

#### Executor (원자 태스크 실행기)
- **역할:** atomic으로 판별된 태스크를 실제 도구/에이전트로 실행
- **현재 NEOS 유사 컴포넌트:** `SearchOrchestrator`, `AnalysisOrchestrator`
- **개선 방향:** 태스크 유형에 따른 동적 에이전트 선택

#### Aggregator (결과 통합기)
- **역할:** 동일 수준의 하위 태스크 결과를 상위 수준으로 통합
- **현재 NEOS 유사 컴포넌트:** `ResultProcessor.integrate_results()`
- **개선 방향:** 계층별 맥락 보존 통합, 충돌 감지

#### Verifier (검증기)
- **역할:** 최종 통합 결과가 원래 태스크를 충족하는지 검증
- **현재 NEOS 유사 컴포넌트:** `QualityValidator`, `SelfReflectionProcessor`
- **개선 방향:** 원래 태스크 요구사항 대비 충족도 점수화

---

## 3. 현재 NEOS 코드베이스 분석

### 3.1 재활용 가능한 기존 컴포넌트

| 기존 컴포넌트 | ROMA 역할 | 재활용 방식 |
|-------------|---------|-----------|
| `PlanningAgent` | Planner | 하위 태스크 분해에 직접 활용, DAG 지원 추가 |
| `ResearchReplanner` | 부분적 Planner | coverage gap 분석 로직 재활용 |
| `HypothesisManager` | 부분적 Atomizer | 가설 기반 분기 판단 로직 참고 |
| `SearchOrchestrator` | Executor | 태스크 유형별 검색 실행기로 활용 |
| `ResultProcessor` | 부분적 Aggregator | 기본 통합 로직 재활용, 계층 인식 추가 |
| `QualityValidator` | 부분적 Verifier | 품질 점수화 로직 재활용 |
| `SelfReflectionProcessor` | Verifier | 커버리지 gap 검증 로직 재활용 |

### 3.2 새로 구현해야 할 컴포넌트

1. **`RecursiveAtomizer`** - 태스크 원자성 판별 (완전 신규)
2. **`RecursiveTaskNode`** - 재귀 태스크 데이터 모델 (완전 신규)
3. **`RecursiveAggregator`** - 계층별 결과 통합 (부분 신규)
4. **`RecursiveVerifier`** - 태스크 충족도 검증 (부분 신규)
5. **`RecursiveWorkflowGraph`** - LangGraph 서브그래프 기반 재귀 실행 엔진 (완전 신규)

### 3.3 `AgentState` 확장 필요 사항

현재 `AgentState`(TypedDict)에 다음 필드를 추가해야 합니다:

```python
# 재귀 에이전트 관련 상태
recursive_task_tree: Optional[Dict[str, Any]]   # 전체 태스크 트리 구조
recursive_current_depth: Optional[int]           # 현재 재귀 깊이
recursive_max_depth: Optional[int]               # 최대 재귀 깊이 (설정값)
recursive_task_stack: Optional[List[Dict]]        # 현재 실행 중인 태스크 스택
recursive_completed_tasks: Optional[List[Dict]]   # 완료된 태스크 목록
recursive_mode: Optional[bool]                   # 재귀 모드 활성화 여부
recursive_budget_remaining: Optional[float]       # 재귀 실행 가용 비용
```

---

## 4. 구현 아키텍처 설계

### 4.1 LangGraph 서브그래프 기반 재귀 실행 전략

LangGraph는 `StateGraph`의 중첩(nested subgraph)을 지원합니다. ROMA의 재귀 구조는 두 가지 방식으로 구현 가능합니다:

#### 방식 A: 서브그래프 방식 (권장)
```
메인 그래프:
START → ... → [RECURSIVE_ORCHESTRATOR] → ... → END

재귀 서브그래프 (독립 StateGraph):
[ATOMIZER] → (atomic?) → [EXECUTOR]
                ↓ not atomic
            [PLANNER] → 하위 태스크 생성
                ↓
         재귀 서브그래프 호출 (각 하위 태스크)
                ↓
           [AGGREGATOR]
                ↓
           [VERIFIER] → (satisfied?) → 결과 반환
                ↓ not satisfied
            [PLANNER] (재계획)
```

**장점:** 명확한 경계, 깊이 제어 용이, 독립 테스트 가능
**단점:** LangGraph 서브그래프 API 학습 곡선

#### 방식 B: 단일 그래프 + 상태 스택 방식
- 단일 `StateGraph` 내에서 `recursive_task_stack`으로 재귀 시뮬레이션
- 조건부 엣지로 루프백 구현

**장점:** 기존 그래프 구조에 자연스럽게 통합
**단점:** 상태 관리 복잡도 증가, 체크포인터와의 호환성 주의 필요

> **결론: 방식 A(서브그래프)를 주 구현 방식으로 채택**
> 단, 초기 구현은 방식 B로 시작하여 점진적으로 서브그래프로 분리

### 4.2 재귀 깊이 제어 전략

```python
RECURSIVE_MAX_DEPTH = 3  # 기본값 (설정으로 오버라이드 가능)
RECURSIVE_MAX_TASKS_PER_LEVEL = 5  # 레벨당 최대 하위 태스크 수
RECURSIVE_BUDGET_PER_LEVEL_FACTOR = 0.5  # 레벨 증가 시 예산 50% 감소
```

**안전 장치:**
- 최대 깊이 초과 시 현재 정보로 최선 답변 생성 (graceful degradation)
- 비용 예산 소진 시 즉시 종료 (기존 `cost_router` 활용)
- 타임아웃 초과 시 중단 (기존 `WORKFLOW_TIMEOUT_SECONDS` 활용)
- 순환 참조 감지 (태스크 설명 해시 중복 체크)

### 4.3 IntentType 확장

`neos/workflow/enums.py`에 새로운 IntentType 추가:

```python
class IntentType(Enum):
    # ... 기존 값들 ...
    RECURSIVE_RESEARCH = "recursive_research"   # ROMA 재귀 연구
```

**라우팅 조건:** `recursive_research` intent이거나, `complexity_score >= 0.8`이고 `deep_research` intent인 경우

---

## 5. 구현 세부 계획

### Phase 1: 핵심 데이터 모델 및 Atomizer (1주)

#### 5.1 `RecursiveTaskNode` 데이터 모델

**파일:** `neos/workflow/recursive/models.py` (신규)

```python
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from enum import Enum

class TaskAtomicity(Enum):
    ATOMIC = "atomic"         # 직접 실행 가능
    DECOMPOSABLE = "decomposable"  # 분해 필요
    UNKNOWN = "unknown"       # 미판별

@dataclass
class RecursiveTaskNode:
    task_id: str              # UUID
    parent_id: Optional[str]  # 부모 태스크 ID (루트는 None)
    depth: int                # 재귀 깊이 (루트=0)
    description: str          # 태스크 설명
    atomicity: TaskAtomicity  # 원자성 판별 결과
    status: str               # pending / in_progress / completed / failed
    result: Optional[str]     # 실행 결과
    children: List['RecursiveTaskNode'] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    cost: float = 0.0         # 실행 비용
    execution_time_ms: int = 0
```

#### 5.2 `RecursiveAtomizer` 구현

**파일:** `neos/workflow/recursive/atomizer.py` (신규)

**핵심 로직:**

```python
class RecursiveAtomizer:
    """
    태스크가 원자적(직접 실행 가능)인지, 분해 가능한지 판별합니다.

    판별 기준:
    1. 단일 도구로 해결 가능한가? → atomic
    2. 단일 웹 검색으로 답 가능한가? → atomic
    3. 명확한 단일 사실 질문인가? → atomic
    4. 여러 출처, 여러 관점, 비교가 필요한가? → decomposable
    5. 시간적 단계가 필요한가(A를 알아야 B를 알 수 있는)? → decomposable
    """

    async def assess(
        self,
        task: RecursiveTaskNode,
        available_tools: List[str],
        context: Dict[str, Any]
    ) -> TaskAtomicity:
        ...
```

**LLM 프롬프트 설계:**
- Haiku 모델 사용 (비용 최소화)
- 구조화된 JSON 출력 (atomic: bool, reasoning: str, estimated_tools: List[str])
- 신뢰도 점수 포함 (0.0-1.0)

### Phase 2: Planner 및 Executor 구현 (1주)

#### 5.3 `RecursivePlanner` 구현

**파일:** `neos/workflow/recursive/planner.py` (신규)

**기존 `PlanningAgent` 활용:**
- `create_research_plan()` 로직을 베이스로
- 하위 태스크 간 **의존성 그래프(DAG)** 추가
- 현재 깊이 및 예산 인식 (깊이 증가 시 더 적은 수의 하위 태스크)

```python
class RecursivePlanner:
    async def decompose(
        self,
        task: RecursiveTaskNode,
        context: Dict[str, Any],
        max_subtasks: int = 4
    ) -> List[RecursiveTaskNode]:
        """태스크를 하위 태스크 목록으로 분해"""
        ...

    def _build_dependency_graph(
        self,
        subtasks: List[RecursiveTaskNode]
    ) -> Dict[str, List[str]]:
        """하위 태스크 간 의존성 그래프 생성"""
        ...
```

#### 5.4 `RecursiveExecutor` 구현

**파일:** `neos/workflow/recursive/executor.py` (신규)

**기존 에이전트 동적 선택:**
- `SkillBasedToolSelector`와 연동하여 태스크 유형에 맞는 에이전트 선택
- 기존 `SearchOrchestrator`, `AnalysisOrchestrator` 활용

```python
class RecursiveExecutor:
    async def execute(
        self,
        task: RecursiveTaskNode,
        agents: Dict[str, Any],
        state: AgentState
    ) -> str:
        """atomic 태스크를 실제 에이전트로 실행"""
        ...
```

### Phase 3: Aggregator 및 Verifier 구현 (1주)

#### 5.5 `RecursiveAggregator` 구현

**파일:** `neos/workflow/recursive/aggregator.py` (신규)

**설계 원칙:**
- 하위 태스크 결과를 **bottom-up**으로 통합
- 각 레벨에서 맥락 요약 생성 (토큰 효율화)
- 충돌/모순 정보 감지 및 표시

```python
class RecursiveAggregator:
    async def aggregate(
        self,
        parent_task: RecursiveTaskNode,
        child_results: List[RecursiveTaskNode],
        context: Dict[str, Any]
    ) -> str:
        """자식 태스크 결과를 부모 태스크 맥락에서 통합"""
        ...

    def _detect_contradictions(
        self,
        results: List[str]
    ) -> List[Dict[str, Any]]:
        """결과 간 모순 탐지"""
        ...
```

#### 5.6 `RecursiveVerifier` 구현

**파일:** `neos/workflow/recursive/verifier.py` (신규)

**기존 컴포넌트 활용:**
- `QualityValidator`의 품질 점수화 로직 재활용
- `SelfReflectionProcessor`의 gap 분석 로직 참고

```python
class RecursiveVerifier:
    async def verify(
        self,
        original_task: RecursiveTaskNode,
        aggregated_result: str,
        threshold: float = 0.75
    ) -> Dict[str, Any]:
        """
        Returns:
            {
                "satisfied": bool,
                "score": float,
                "gaps": List[str],
                "suggestion": str
            }
        """
        ...
```

### Phase 4: LangGraph 워크플로우 통합 (1주)

#### 5.7 `RecursiveWorkflowGraph` - 서브그래프 구현

**파일:** `neos/workflow/recursive/graph.py` (신규)

```python
from langgraph.graph import StateGraph, START, END

class RecursiveWorkflowGraph:
    """
    ROMA 패턴을 구현하는 LangGraph 서브그래프

    노드 구성:
    - atomize: RecursiveAtomizer 실행
    - plan: RecursivePlanner 실행
    - execute: RecursiveExecutor 실행
    - aggregate: RecursiveAggregator 실행
    - verify: RecursiveVerifier 실행

    엣지 구성:
    START → atomize
    atomize → execute (atomic인 경우)
    atomize → plan (decomposable인 경우)
    plan → [서브그래프 재귀 호출] (각 하위 태스크)
    [하위 태스크 완료] → aggregate
    aggregate → verify
    verify → END (satisfied)
    verify → plan (not satisfied, max_depth 미초과)
    verify → END (max_depth 초과, graceful degradation)
    """

    def build(self) -> StateGraph:
        ...
```

#### 5.8 메인 `MultiAgentWorkflow` 통합

**파일:** `neos/workflow/graph.py` (수정)

**통합 지점:**
1. `WorkflowNode` enum에 `RECURSIVE_ORCHESTRATOR` 추가
2. `_create_workflow_graph()`에서 recursive 서브그래프를 노드로 등록
3. `_should_skip_orchestrators()`에서 `recursive_research` intent 라우팅 추가
4. `AgentState`에 recursive 관련 필드 추가

```
기존 흐름:
SKILL_TOOL_SELECTOR → HYPOTHESIS_GENERATION → SEARCH_ORCHESTRATOR → ...

추가 흐름:
SKILL_TOOL_SELECTOR → RECURSIVE_ORCHESTRATOR → RESULT_INTEGRATOR → ...
                           ↑
                    (recursive_research intent 또는
                     complexity >= 0.8 && deep_research)
```

#### 5.9 `enums.py` 수정

```python
class WorkflowNode(Enum):
    # ... 기존 값들 ...
    RECURSIVE_ORCHESTRATOR = "recursive_orchestrator"  # ROMA 재귀 오케스트레이터

class IntentType(Enum):
    # ... 기존 값들 ...
    RECURSIVE_RESEARCH = "recursive_research"  # ROMA 재귀 연구
```

#### 5.10 `settings.py` 설정 추가

```python
# 재귀 에이전트 설정
RECURSIVE_AGENT_ENABLED: bool = bool(env_vars.get("RECURSIVE_AGENT_ENABLED", False))
RECURSIVE_MAX_DEPTH: int = int(env_vars.get("RECURSIVE_MAX_DEPTH", 3))
RECURSIVE_MAX_TASKS_PER_LEVEL: int = int(env_vars.get("RECURSIVE_MAX_TASKS_PER_LEVEL", 4))
RECURSIVE_COMPLEXITY_THRESHOLD: float = float(env_vars.get("RECURSIVE_COMPLEXITY_THRESHOLD", 0.8))
RECURSIVE_ATOMIZER_MODEL: str = env_vars.get("RECURSIVE_ATOMIZER_MODEL", "claude-haiku-4-5-20251001")
RECURSIVE_PLANNER_MODEL: str = env_vars.get("RECURSIVE_PLANNER_MODEL", "claude-opus-4-6")
RECURSIVE_BUDGET_CAP: float = float(env_vars.get("RECURSIVE_BUDGET_CAP", 0.5))  # USD
```

---

## 6. 파일 구조

```
neos/workflow/
├── recursive/                          ← 신규 디렉터리
│   ├── __init__.py
│   ├── models.py                       ← RecursiveTaskNode, TaskAtomicity
│   ├── atomizer.py                     ← RecursiveAtomizer
│   ├── planner.py                      ← RecursivePlanner
│   ├── executor.py                     ← RecursiveExecutor
│   ├── aggregator.py                   ← RecursiveAggregator
│   ├── verifier.py                     ← RecursiveVerifier
│   ├── graph.py                        ← RecursiveWorkflowGraph (서브그래프)
│   └── orchestrator.py                 ← RecursiveOrchestrator (메인 진입점)
├── graph.py                            ← 수정 (통합 지점)
├── enums.py                            ← 수정 (새 노드/인텐트 추가)
├── state.py                            ← 수정 (새 state 필드 추가)
└── ...
neos/config/
└── settings.py                         ← 수정 (새 설정 추가)
```

---

## 7. 구현 시 주의사항 및 위험 요소

### 7.1 LangGraph 서브그래프 재귀 제한

LangGraph는 현재 서브그래프의 **동적 재귀 호출**을 직접 지원하지 않습니다 (순환 임포트 및 그래프 컴파일 제약). 따라서 다음 두 가지 접근 중 하나를 선택해야 합니다:

**접근 A - 상태 기반 재귀 시뮬레이션 (권장 초기 구현):**
- 단일 `RecursiveOrchestrator` 노드 내에서 Python 재귀/반복으로 ROMA 로직 구현
- LangGraph 엣지가 아닌 Python 제어 흐름으로 재귀 표현
- LangGraph 노드는 진입/종료 지점 역할만 담당

**접근 B - 정적 깊이 언롤링 (Advanced):**
- 최대 깊이(예: 3)를 미리 알고, `depth_0_graph`, `depth_1_graph`, `depth_2_graph`를 정적으로 정의
- 각 깊이의 그래프가 다음 깊이 그래프를 서브그래프로 포함
- 구현 복잡도 높지만 LangGraph 철학에 부합

> **초기 구현은 접근 A로 시작, 안정화 후 접근 B로 마이그레이션 검토**

### 7.2 CLAUDE.md 순차적 도구 실행 원칙

현재 CLAUDE.md에 **순차적 도구 실행(sequential tool use)** 원칙이 명시되어 있습니다. 재귀 에이전트 내 병렬 하위 태스크 실행은 이 원칙과 충돌할 수 있으므로:

- 하위 태스크 실행은 **기본적으로 순차 실행**
- 병렬 실행이 필요한 경우 명시적으로 표시하고 사용자 확인 필요
- `asyncio.gather()`를 활용하되, 개별 에이전트 호출은 순차 유지

### 7.3 비용 제어

재귀 실행은 LLM 호출 횟수를 기하급수적으로 증가시킬 수 있습니다:
- Atomizer는 반드시 **Haiku 모델** 사용
- Planner는 상위 레벨만 **Opus 모델**, 하위 레벨은 Haiku
- `RECURSIVE_BUDGET_CAP` 설정으로 하드 제한
- 기존 `cost_router` 및 `cost_tracking` 상태 필드 활용

### 7.4 상태 직렬화

PostgreSQL 체크포인터는 `AgentState`를 직렬화합니다. `RecursiveTaskNode`는 `dataclass`이므로:
- JSON 직렬화 가능한 형태로 설계 (복잡한 타입 지양)
- `List[Dict[str, Any]]` 형태로 상태에 저장
- 실제 `RecursiveTaskNode` 객체는 실행 중에만 메모리에 유지

### 7.5 기존 워크플로우 하위 호환성

- `RECURSIVE_AGENT_ENABLED = False`가 기본값 → **피처 플래그로 격리**
- 기존 `deep_research`, `replanner` 등 기존 경로 완전 유지
- A/B 테스트 가능한 구조로 설계

---

## 8. 구현 순서 (Task 목록)

### Sprint 1 (1주차): 기반 구조
- [ ] `neos/workflow/recursive/` 디렉터리 생성
- [ ] `models.py`: `RecursiveTaskNode`, `TaskAtomicity` 구현
- [ ] `atomizer.py`: `RecursiveAtomizer` 구현 (LLM 기반 판별)
- [ ] `settings.py`: 재귀 관련 설정 추가
- [ ] `state.py`: `AgentState`에 recursive 필드 추가
- [ ] `enums.py`: `RECURSIVE_ORCHESTRATOR`, `RECURSIVE_RESEARCH` 추가
- [ ] 단위 테스트: `tests/workflow/recursive/test_atomizer.py`

### Sprint 2 (2주차): 핵심 실행 로직
- [ ] `planner.py`: `RecursivePlanner` 구현
- [ ] `executor.py`: `RecursiveExecutor` 구현
- [ ] `aggregator.py`: `RecursiveAggregator` 구현
- [ ] `verifier.py`: `RecursiveVerifier` 구현
- [ ] 단위 테스트: 각 컴포넌트별 테스트

### Sprint 3 (3주차): 통합 및 연결
- [ ] `orchestrator.py`: `RecursiveOrchestrator` 구현 (Phase 1: Python 재귀 방식)
- [ ] `graph.py`: `MultiAgentWorkflow`에 `recursive_orchestrator` 노드 추가
- [ ] 라우팅 로직: `_should_use_recursive_agent()` 조건 함수 추가
- [ ] 통합 테스트: E2E 재귀 실행 테스트

### Sprint 4 (4주차): 고도화 및 관찰가능성
- [ ] Prometheus 메트릭 추가 (`recursive_depth_histogram`, `task_decomposition_count`)
- [ ] OpenTelemetry 트레이싱: 재귀 트리 시각화 지원
- [ ] `graph.py`: Phase 2 - LangGraph 서브그래프 방식으로 마이그레이션 검토
- [ ] 문서 업데이트 및 사용 예시 작성

---

## 9. 성능 기대치

| 쿼리 유형 | 현재 NEOS | ROMA 적용 후 (예상) |
|---------|----------|------------------|
| 단순 질문 | 동일 (우회) | 동일 (재귀 미활성화) |
| 복잡한 멀티-호프 연구 | 평균 3-5 검색 | 계층적 6-12 검색 (더 깊이) |
| 비교 분석 | 단층 비교 | 각 대상별 하위 연구 → 통합 |
| 종합 보고서 | 단일 패스 | 섹션별 재귀 연구 → 통합 |
| **응답 품질** | 기준선 | +15~30% 예상 (SEAL-0 벤치마크 참고) |
| **실행 비용** | 기준선 | +30~50% 예상 (복잡한 쿼리에서) |
| **실행 시간** | 기준선 | +20~40% 예상 |

---

## 10. 미래 확장 계획

### 10.1 병렬 재귀 실행
- 독립적인 하위 태스크를 병렬로 실행하여 속도 개선
- `asyncio.gather()` + Celery 태스크큐 활용
- 의존성이 없는 태스크는 병렬, 의존성이 있는 태스크는 순차 실행

### 10.2 재귀 실행 캐싱
- `RecursiveTaskNode` 해시 기반으로 동일 태스크 중복 실행 방지
- 기존 시맨틱 캐시(`smart_cache_manager`) 연동

### 10.3 사용자 가시성 개선
- 재귀 트리 구조를 스트리밍으로 프론트엔드에 전달
- "현재 분석 중: 하위 태스크 2/4 - X에 대한 세부 조사" 형태의 진행 상황 표시

### 10.4 LangGraph 서브그래프 마이그레이션
- `langgraph>=0.2.x`의 서브그래프 API 안정화 이후 마이그레이션
- 각 재귀 레벨을 독립 서브그래프로 분리하여 더 명확한 경계 형성

---

## 11. 관련 파일 참고 목록

| 파일 | 참고 이유 |
|------|---------|
| [neos/workflow/graph.py](../neos/workflow/graph.py) | 메인 워크플로우 통합 지점 |
| [neos/workflow/state.py](../neos/workflow/state.py) | AgentState 확장 위치 |
| [neos/workflow/enums.py](../neos/workflow/enums.py) | 새 노드/인텐트 추가 위치 |
| [neos/agents/planning_agent.py](../neos/agents/planning_agent.py) | Planner 기반 코드 |
| [neos/workflow/processors/replanner.py](../neos/workflow/processors/replanner.py) | coverage gap 분석 참고 |
| [neos/workflow/processors/self_reflection.py](../neos/workflow/processors/self_reflection.py) | Verifier 기반 코드 |
| [neos/workflow/utils/cost_router.py](../neos/workflow/utils/cost_router.py) | 비용 제어 연동 |
| [neos/config/settings.py](../neos/config/settings.py) | 새 설정 추가 위치 |
| [neos/workflow/orchestrators/search_orchestrator.py](../neos/workflow/orchestrators/search_orchestrator.py) | Executor 기반 코드 |
