# NEOS 재귀적 에이전트(ROMA) 구현 상세 문서

> **구현 기준:** NEOS v0.22.0
> **작성일:** 2026-03-07
> **참고 계획 문서:** [docs/RECURSIVE_AGENT_PLAN.md](./RECURSIVE_AGENT_PLAN.md)

---

## 1. 개요

ROMA(Recursive Open Meta-Agent) 패턴을 NEOS에 구현하였습니다. 복잡한 멀티-호프 질문을 계층적으로 분해·실행·통합하는 재귀 워크플로우를 `RECURSIVE_AGENT_ENABLED` 피처 플래그로 기존 워크플로우와 완전히 격리하여 추가했습니다.

### 구현 전략

**Python 재귀 방식 (접근 A):** 단일 `RecursiveOrchestrator` LangGraph 노드 내부에서 Python 재귀 호출로 ROMA 로직 구현. LangGraph의 동적 서브그래프 재귀 제약(순환 임포트, 그래프 컴파일 제한)을 우회합니다.

---

## 2. 파일 구조

```
neos/workflow/recursive/          ← 신규 디렉터리
├── __init__.py                   ← 패키지 공개 API
├── models.py                     ← RecursiveTaskNode, TaskAtomicity, TaskStatus
├── atomizer.py                   ← RecursiveAtomizer (원자성 판별)
├── planner.py                    ← RecursivePlanner (하위 태스크 분해)
├── executor.py                   ← RecursiveExecutor (atomic 태스크 실행)
├── aggregator.py                 ← RecursiveAggregator (결과 통합)
├── verifier.py                   ← RecursiveVerifier (충족도 검증)
├── orchestrator.py               ← RecursiveOrchestrator (메인 실행 엔진)
└── graph.py                      ← LangGraph 서브그래프 마이그레이션 플레이스홀더

neos/workflow/
├── graph.py                      ← 수정: RecursiveOrchestrator 통합
├── enums.py                      ← 수정: RECURSIVE_ORCHESTRATOR, RECURSIVE_RESEARCH 추가
└── state.py                      ← 수정: recursive_* 필드 7개 추가

neos/config/
└── settings.py                   ← 수정: RECURSIVE_* 설정 7개 추가

.env.template                     ← 수정: RECURSIVE_* 환경변수 예시 추가
```

---

## 3. 데이터 모델 (`models.py`)

### RecursiveTaskNode

재귀 태스크 트리의 단일 노드. PostgreSQL 체크포인터 호환을 위해 JSON 직렬화 가능하게 설계됩니다.

```python
@dataclass
class RecursiveTaskNode:
    description: str              # 태스크 설명
    task_id: str                  # UUID (자동 생성)
    parent_id: Optional[str]      # 부모 태스크 ID (루트=None)
    depth: int                    # 재귀 깊이 (루트=0)
    atomicity: TaskAtomicity      # ATOMIC / DECOMPOSABLE / UNKNOWN
    status: TaskStatus            # PENDING / IN_PROGRESS / COMPLETED / FAILED
    result: Optional[str]         # 실행 결과
    children: List[RecursiveTaskNode]
    metadata: Dict[str, Any]
    cost: float                   # 실행 비용 (USD)
    execution_time_ms: int
```

**주요 메서드:**

| 메서드 | 설명 |
|--------|------|
| `description_hash()` | 순환 참조 감지용 MD5 해시 |
| `to_dict()` | JSON 직렬화 (상태 저장용) |
| `from_dict()` | JSON 역직렬화 |
| `total_cost()` | 이 노드와 모든 자식의 누적 비용 |

### Enum 정의

```python
class TaskAtomicity(Enum):
    ATOMIC = "atomic"           # 직접 실행 가능
    DECOMPOSABLE = "decomposable"  # 분해 필요
    UNKNOWN = "unknown"         # 미판별

class TaskStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
```

---

## 4. 컴포넌트 상세

### 4.1 RecursiveAtomizer (`atomizer.py`)

**역할:** 태스크가 직접 실행 가능한지(ATOMIC), 분해가 필요한지(DECOMPOSABLE) 판별합니다.

**LLM 모델:** `RECURSIVE_ATOMIZER_MODEL` (기본값: `claude-haiku-4-5-20251001`, 비용 최소화)

**판별 로직:**

```
depth >= RECURSIVE_MAX_DEPTH  →  항상 ATOMIC (graceful degradation)
LLM 호출 실패                →  보수적으로 DECOMPOSABLE
confidence < 0.5             →  보수적으로 DECOMPOSABLE
atomic=true + confidence OK  →  ATOMIC
atomic=false                 →  DECOMPOSABLE
```

**LLM 출력 형식:**
```json
{
  "atomic": true,
  "reasoning": "단일 웹 검색으로 해결 가능한 사실 질문",
  "confidence": 0.9,
  "estimated_tools": ["web_search"]
}
```

---

### 4.2 RecursivePlanner (`planner.py`)

**역할:** non-atomic 태스크를 2-N개의 하위 RecursiveTaskNode로 분해합니다.

**모델 선택 전략:**

| 깊이 | 모델 | 이유 |
|------|------|------|
| depth=0 | `RECURSIVE_PLANNER_MODEL` (Opus) | 최상위 분해는 높은 품질 필요 |
| depth>0 | `RECURSIVE_ATOMIZER_MODEL` (Haiku) | 비용 절감 |

**하위 태스크 수 계산:**
```python
max_subtasks = max(2, RECURSIVE_MAX_TASKS_PER_LEVEL - task.depth)
# 깊이가 깊어질수록 더 적은 수의 하위 태스크 생성
```

**주요 메서드:**

| 메서드 | 설명 |
|--------|------|
| `decompose(task, context)` | 태스크 → 하위 태스크 목록 |
| `replan(task, previous_result, gaps, context)` | 검증 실패 후 갭 기반 재계획 |
| `_fallback_split(description)` | LLM 실패 시 2개로 단순 분할 |

**의존성 정보:** 하위 태스크 `metadata["depends_on"]`에 0-based index 목록 저장.

---

### 4.3 RecursiveExecutor (`executor.py`)

**역할:** ATOMIC으로 판별된 태스크를 LLM으로 직접 실행합니다.

**모델:** `RECURSIVE_ATOMIZER_MODEL` (Haiku)

**컨텍스트 활용:**
- `original_query`: 원래 사용자 질문
- `prior_results`: 이전에 완료된 형제 태스크 결과 (최대 3개)
- `search_synthesis`: 기존 검색 결과 (있을 경우 활용)

**실패 처리:** 예외 발생 시 `[실행 실패: ...]` 형태의 명시적 실패 메시지 반환.

---

### 4.4 RecursiveAggregator (`aggregator.py`)

**역할:** 자식 태스크 결과를 부모 태스크 맥락에서 bottom-up으로 통합합니다.

**모델:** `RECURSIVE_ATOMIZER_MODEL` (Haiku)

**처리 흐름:**

```
자식 결과 1개 → 그대로 반환 (aggregation 불필요)
자식 결과 2개 → LLM 통합 프롬프트만 실행
자식 결과 3개+ → 모순 감지 후 LLM 통합
```

**모순 감지 (`_detect_contradictions`):**
- 결과가 3개 이상일 때만 실행 (비용 절감)
- 모순 발견 시 통합 결과에 명시적으로 표시

**LLM 실패 Fallback:** 자식 결과를 단순 연결한 텍스트 반환.

---

### 4.5 RecursiveVerifier (`verifier.py`)

**역할:** 통합 결과가 원래 태스크 요구사항을 충족하는지 검증합니다.

**모델:** `RECURSIVE_ATOMIZER_MODEL` (Haiku)

**충족도 임계값:**
```python
threshold = max(settings.WORKFLOW_MIN_QUALITY_SCORE, 0.65)
# ROMA는 기존 quality_validator보다 더 높은 기준 적용
```

**빠른 실패 조건:** 결과 길이 < 50자이면 즉시 score=0.0 반환.

**반환 형식:**
```json
{
  "satisfied": false,
  "score": 0.52,
  "gaps": ["최신 데이터 부재", "경쟁사 비교 누락"],
  "suggestion": "2024년 이후 데이터 및 경쟁사 정보 추가 필요"
}
```

**Heuristic Fallback:** LLM 실패 시 결과 길이 기반으로 score 계산 (최대 0.7점).

---

### 4.6 RecursiveOrchestrator (`orchestrator.py`)

**역할:** ROMA 메인 실행 엔진. LangGraph 노드로 사용되며 Python 재귀로 5단계를 반복합니다.

**핵심 재귀 로직 (`_recursive_solve`):**

```
1. 비용 한도 체크  →  초과 시 graceful_degrade()
2. 순환 참조 감지  →  description_hash() 중복 체크
3. Atomizer 실행   →  ATOMIC / DECOMPOSABLE 판별
4. ATOMIC          →  Executor로 직접 실행 후 반환
5. DECOMPOSABLE    →  Planner로 하위 태스크 분해
6. 하위 태스크 순차 실행  →  각 subtask에 대해 재귀 호출
7. Aggregator 실행  →  자식 결과 통합
8. Verifier 실행    →  충족도 검증
9. 미충족 + 재계획 가능  →  _replan_and_solve() (최대 1회)
10. 최종 결과 반환
```

**안전 장치 목록:**

| 안전 장치 | 구현 방식 |
|-----------|-----------|
| 최대 깊이 | Atomizer에서 depth >= max_depth 시 ATOMIC 강제 |
| 비용 한도 | `RECURSIVE_BUDGET_CAP` 초과 시 graceful_degrade() |
| 순환 참조 | 설명 MD5 해시를 seen_hashes Set에 저장, 재귀 호출마다 불변 복사 |
| 재계획 횟수 | replan_count 파라미터로 최대 1회 제한 |
| 분해 실패 | subtasks 빈 리스트 시 Executor로 직접 실행 fallback |

**순차 실행 준수 (CLAUDE.md):**
```python
# asyncio.gather() 사용 금지 - 순차 실행
for subtask in subtasks:
    result = await self._recursive_solve(subtask, ...)
    prior_results[subtask.task_id] = result
```

**LangGraph 노드 반환 형식:**
```python
{
    "final_response": str,           # 최종 답변
    "recursive_task_tree": dict,     # 직렬화된 태스크 트리
    "recursive_mode": True,
    "recursive_current_depth": 0,
    "recursive_budget_remaining": float,
    "cumulative_cost": float,        # 기존 비용 + 재귀 비용 누적
    "execution_steps": [...],        # 실행 로그 추가
}
```

---

## 5. 워크플로우 통합 (`workflow/graph.py`)

### 5.1 초기화

```python
# __init__ 메서드
self.recursive_orchestrator = None
if settings.RECURSIVE_AGENT_ENABLED:
    from neos.workflow.recursive.orchestrator import RecursiveOrchestrator
    self.recursive_orchestrator = RecursiveOrchestrator(agents=self.agents)
```

### 5.2 노드 등록

```python
# _create_workflow_graph 메서드
if settings.RECURSIVE_AGENT_ENABLED:
    workflow.add_node(
        WorkflowNode.RECURSIVE_ORCHESTRATOR.value,
        self._recursive_orchestrator_node
    )
```

### 5.3 워크플로우 분기

```
SKILL_TOOL_SELECTOR
    │
    ├─ (RECURSIVE_AGENT_ENABLED=True)
    │       ↓  _should_use_recursive_agent()
    │   "recursive"         →  RECURSIVE_ORCHESTRATOR  →  RESULT_INTEGRATOR
    │   "use_orchestrators" →  HYPOTHESIS_GENERATION (기존 경로)
    │   "skip"              →  RESP_GENERATOR (기존 경로)
    │
    └─ (RECURSIVE_AGENT_ENABLED=False)
            ↓  _should_skip_orchestrators() (기존 로직 그대로)
        "use_orchestrators" →  HYPOTHESIS_GENERATION
        "skip"              →  RESP_GENERATOR
```

### 5.4 라우팅 함수 (`_should_use_recursive_agent`)

```python
def _should_use_recursive_agent(self, state: AgentState) -> str:
    intent = state.get("query_intent", "")
    complexity = state.get("query_classification", {}).get("complexity_score", 0.0)

    # 1순위: RECURSIVE_RESEARCH intent → 항상 재귀
    if intent == IntentType.RECURSIVE_RESEARCH.value:
        return "recursive"

    # 2순위: 높은 복잡도 + 심층/복합 분석 의도 → 재귀
    if complexity >= settings.RECURSIVE_COMPLEXITY_THRESHOLD:
        if intent in (IntentType.DEEP_RESEARCH.value, IntentType.COMPLEX_ANALYSIS.value):
            return "recursive"

    # 그 외: 기존 로직 위임
    return self._should_skip_orchestrators(state)
```

---

## 6. AgentState 확장 (`state.py`)

```python
class AgentState(TypedDict):
    # ... 기존 필드들 ...

    # ROMA: Recursive Open Meta-Agent
    recursive_task_tree: Optional[Dict[str, Any]]       # 직렬화된 태스크 트리
    recursive_current_depth: Optional[int]              # 현재 재귀 깊이
    recursive_max_depth: Optional[int]                  # 최대 재귀 깊이
    recursive_task_stack: Optional[List[Dict]]          # 실행 중인 태스크 스택
    recursive_completed_tasks: Optional[List[Dict]]     # 완료된 태스크 목록
    recursive_mode: Optional[bool]                      # 재귀 모드 활성화 여부
    recursive_budget_remaining: Optional[float]         # 가용 비용 (USD)
```

---

## 7. 설정 (`settings.py` / `.env.template`)

| 설정 변수 | 기본값 | 설명 |
|-----------|--------|------|
| `RECURSIVE_AGENT_ENABLED` | `False` | 재귀 에이전트 활성화 여부 |
| `RECURSIVE_MAX_DEPTH` | `3` | 최대 재귀 깊이 |
| `RECURSIVE_MAX_TASKS_PER_LEVEL` | `4` | 레벨당 최대 하위 태스크 수 |
| `RECURSIVE_COMPLEXITY_THRESHOLD` | `0.8` | 재귀 활성화 복잡도 임계값 |
| `RECURSIVE_ATOMIZER_MODEL` | `claude-haiku-4-5-20251001` | Atomizer/Executor/Aggregator/Verifier LLM |
| `RECURSIVE_PLANNER_MODEL` | `claude-opus-4-6` | Planner(depth=0) LLM |
| `RECURSIVE_BUDGET_CAP` | `0.5` | 재귀 실행 비용 한도 (USD) |

---

## 8. Enum 추가 (`enums.py`)

```python
class WorkflowNode(Enum):
    # ... 기존 값들 ...
    RECURSIVE_ORCHESTRATOR = "recursive_orchestrator"  # ROMA 재귀 오케스트레이터

class IntentType(Enum):
    # ... 기존 값들 ...
    RECURSIVE_RESEARCH = "recursive_research"  # ROMA 재귀 연구 (명시적 지정)
```

---

## 9. 활성화 및 검증 방법

### 9.1 활성화

`.env` 파일에 다음 설정을 추가합니다:

```bash
RECURSIVE_AGENT_ENABLED=true
RECURSIVE_MAX_DEPTH=3
RECURSIVE_COMPLEXITY_THRESHOLD=0.8
RECURSIVE_BUDGET_CAP=0.5
```

### 9.2 검증 시나리오

**시나리오 1: 피처 플래그 비활성화 (기존 워크플로우 무결성)**
```bash
RECURSIVE_AGENT_ENABLED=false  # 기본값
# 기존 모든 워크플로우 경로가 그대로 동작해야 함
```

**시나리오 2: 재귀 에이전트 활성화 + 복잡 쿼리**
```bash
RECURSIVE_AGENT_ENABLED=true
# 테스트 쿼리: "2024년 글로벌 AI 반도체 시장에서 엔비디아, AMD, 인텔의 점유율 변화와
#               각 사의 전략적 대응 방식, 그리고 향후 2년간의 전망을 비교 분석해줘"
# 예상: complexity >= 0.8 + COMPLEX_ANALYSIS intent → 재귀 경로 활성화
```

**시나리오 3: 비용 한도 테스트**
```bash
RECURSIVE_BUDGET_CAP=0.01   # 극히 낮은 한도
# 예상: 1-2번 실행 후 graceful_degrade() 호출, 에러 없이 부분 결과 반환
```

**시나리오 4: 최대 깊이 테스트**
```bash
RECURSIVE_MAX_DEPTH=2       # 낮은 깊이 제한
# 예상: depth=2 도달 시 Atomizer가 ATOMIC 강제, 더 이상 분해하지 않음
```

**시나리오 5: 명시적 재귀 intent**
```python
# query_classification에서 intent="recursive_research"로 분류되면
# complexity 임계값과 무관하게 재귀 경로 활성화
```

---

## 10. 비용 모델

| 컴포넌트 | 모델 | 호출 시점 |
|----------|------|-----------|
| Atomizer | Haiku | 모든 태스크 노드마다 1회 |
| Planner (depth=0) | Opus | 루트 분해 시 1회 |
| Planner (depth>0) | Haiku | 하위 레벨 분해마다 1회 |
| Executor | Haiku | atomic 태스크마다 1회 |
| Aggregator | Haiku | 자식 2개 이상인 부모마다 1회 |
| Aggregator (모순 감지) | Haiku | 자식 3개 이상인 부모마다 추가 1회 |
| Verifier | Haiku | 각 레벨 통합 후 1회 |

**depth=3, tasks_per_level=3 최악 시나리오 예상 호출 수:**
- Atomizer: 1 + 3 + 9 = 13회
- Planner: 1 + 3 = 4회
- Executor: 9회 (leaf 노드)
- Aggregator: 1 + 3 = 4회
- Verifier: 1 + 3 = 4회
- **총 약 34회 LLM 호출** (대부분 Haiku)

---

## 11. 향후 마이그레이션 계획

### 11.1 LangGraph 서브그래프 방식 (Phase 2)

`neos/workflow/recursive/graph.py`가 마이그레이션 대상 파일입니다. 조건:
- `langgraph >= 0.2.x` 서브그래프 API 안정화 이후
- 각 재귀 레벨을 독립 `StateGraph`로 분리 (정적 깊이 언롤링)

```
depth_0_graph → [ATOMIZE] → [PLAN] → depth_1_graph (서브그래프)
depth_1_graph → [ATOMIZE] → [PLAN] → depth_2_graph (서브그래프)
depth_2_graph → [ATOMIZE] → [EXECUTE] → [AGGREGATE] → [VERIFY]
```

### 11.2 병렬 실행 (Phase 3)

의존성이 없는 형제 태스크를 `asyncio.gather()`로 병렬 실행. 현재는 CLAUDE.md 순차 원칙 준수.

### 11.3 관찰가능성 (Phase 4)

- Prometheus: `recursive_depth_histogram`, `task_decomposition_count`
- OpenTelemetry: 재귀 트리 시각화 (각 노드를 span으로 표현)
- 프론트엔드 스트리밍: 재귀 진행 상황 실시간 표시

---

## 12. 관련 파일 참고 목록

| 파일 | 역할 |
|------|------|
| [neos/workflow/recursive/orchestrator.py](../neos/workflow/recursive/orchestrator.py) | ROMA 메인 실행 엔진 |
| [neos/workflow/graph.py](../neos/workflow/graph.py) | 워크플로우 통합 지점 |
| [neos/workflow/state.py](../neos/workflow/state.py) | AgentState 확장 위치 |
| [neos/workflow/enums.py](../neos/workflow/enums.py) | RECURSIVE_ORCHESTRATOR, RECURSIVE_RESEARCH |
| [neos/config/settings.py](../neos/config/settings.py) | RECURSIVE_* 설정 (줄 617 근방) |
| [.env.template](../.env.template) | 환경변수 예시 |
| [docs/RECURSIVE_AGENT_PLAN.md](./RECURSIVE_AGENT_PLAN.md) | 원본 구현 계획 문서 |
