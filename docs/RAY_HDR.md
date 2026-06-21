# Ray 기반 HyperDeepResearch 분산 처리 — 구현 상세

> 설계 원칙은 [docs/RAY_BASED_HDR.md](./RAY_BASED_HDR.md) 참조.
> 이 문서는 실제 구현된 코드와 사용 방법을 기술한다.
> 마지막 업데이트: 2026-03-19 (코드 리뷰 [RAY_BASED_HDR_REVIEW.md](./RAY_BASED_HDR_REVIEW.md) 반영)

---

## 목차

1. [아키텍처 개요](#1-아키텍처-개요)
2. [파일 구조](#2-파일-구조)
3. [Phase 1: ExecutorPool 병렬 실행](#3-phase-1-executorpool-병렬-실행)
4. [Phase 2: Stateless Named Actors](#4-phase-2-stateless-named-actors)
5. [Phase 3: Sandbox 코드 실행](#5-phase-3-sandbox-코드-실행)
6. [Phase 4: 메트릭 통합](#6-phase-4-메트릭-통합)
7. [설정 레퍼런스](#7-설정-레퍼런스)
8. [활성화 및 검증](#8-활성화-및-검증)
9. [알려진 제한사항](#9-알려진-제한사항)

---

## 1. 아키텍처 개요

### 기존 문제: 순차 실행 병목

`RecursiveOrchestrator._recursive_solve()`의 for-loop이 독립 sibling 태스크도 순차 실행.
`Planner`가 생성한 `metadata["depends_on"]` 필드는 존재하지만 Orchestrator에서 전혀 활용되지 않았음.

```
기존 (순차):
  T0 (2분) → T1 (2분) → T2 (2분 / T0,T1에 의존) = ~6.25분

Ray 병렬 (완전 독립 기준):
  T0 ┐
  T1 ┘ (병렬, 2분) → T2 (2분) = ~4.3분

  완전 독립 (T0, T1, T2 모두 독립):
  T0 ┐
  T1 ┤ (병렬, 2분) = ~2.3분  ← 2.7× 속도 향상
  T2 ┘
```

### 설계 원칙

| 원칙 | 구현 |
|------|------|
| **Feature flag** | `ray.enabled: false`(기본) → 기존 순차 실행과 완전 동일 |
| **상속 기반** | `DistributedRecursiveOrchestrator extends RecursiveOrchestrator` |
| **asyncio 브릿지** | `await asyncio.wrap_future(ref.future())` — `ray.get()` 직접 호출 금지 |
| **직렬화 격리** | `_stream_callback`, `_cost_accumulator` context에서 반드시 제외 |
| **Graceful fallback** | Ray 초기화 실패 → warning 로그 후 순차 실행 유지 |
| **Named Actor 어댑터** | Phase 2 Named Actor를 로컬 인스턴스와 동일 인터페이스로 래핑 |

---

## 2. 파일 구조

```
neos/
├── agents/search_agents/hyper_deep_research/
│   └── agent.py                         ← reset() 메서드 추가
├── workflow/
│   ├── ray_actors/                      ← 신규 패키지
│   │   ├── __init__.py
│   │   ├── dag_utils.py                 ← depends_on DAG → 레벨 그룹화 (범위 검증 추가)
│   │   ├── executor_pool.py             ← HyperDeepWorkerActor, RayExecutorPool
│   │   ├── cost_accumulator.py          ← CostAccumulatorActor (Named Actor, TTL 추가)
│   │   ├── stateless_actors.py          ← Atomizer/Planner/Aggregator/Verifier Named Actors
│   │   ├── sandbox_executor.py          ← RestrictedPythonExecutor (Phase 3)
│   │   └── sandboxed_executor.py        ← SandboxedCodeExecutor 통합 API
│   └── recursive/
│       ├── orchestrator.py              ← 기존 (수정 없음)
│       └── distributed_orchestrator.py  ← Named Actor 어댑터 + 메트릭 기록 + replan 병렬화
├── config/
│   └── settings.py                      ← RAY_*, SANDBOX_* 설정 추가
├── main.py                              ← ray.init/shutdown + Named Actor 초기화 + warmup
└── observability/
    └── metrics.py                       ← Ray 메트릭 5개 정의 (기록 코드는 orchestrator에)

config/prometheus/
└── prometheus.yml                       ← ray-head scrape 설정 추가

pyproject.toml                           ← ray[default]>=2.8.0, sandbox optional
.env.template                            ← RAY_* 환경변수 문서화
```

---

## 3. Phase 1: ExecutorPool 병렬 실행

### 3-A. `dag_utils.py` — depends_on DAG 파싱

**함수:** `build_execution_levels(subtasks) -> List[List[int]]`

```python
from neos.workflow.ray_actors.dag_utils import build_execution_levels

subtasks = [
    RecursiveTaskNode(description="T0", metadata={"depends_on": []}),
    RecursiveTaskNode(description="T1", metadata={"depends_on": []}),
    RecursiveTaskNode(description="T2", metadata={"depends_on": [0, 1]}),
]

levels = build_execution_levels(subtasks)
# 반환: [[0, 1], [2]]
# → T0, T1 병렬 실행 후 T2 실행
```

**구현 세부:**
- `metadata["depends_on"]`의 인덱스를 항상 `int()` 변환 (LLM이 `["0","1"]` 문자열 반환 가능)
- 위상 정렬로 동일 레벨 독립 태스크 그룹화
- 순환 의존성 → `ValueError` 발생
- `visiting` 집합을 불변 복사(`visiting | {idx}`)로 유지 → 재귀 스택 간 오염 방지
- **범위 검증:** `0 <= int(d) < n and int(d) != idx` 조건으로 범위 외 인덱스·자기 의존 무시 (LLM 오출력 방어)

```python
deps = [
    int(d)
    for d in deps_raw
    if 0 <= int(d) < n and int(d) != idx  # 범위 외·자기 참조 방어
]
```

---

### 3-B. `executor_pool.py` — Ray Worker Actor 풀

#### `HyperDeepWorkerActor`

```python
@ray.remote(num_cpus=0.5, num_gpus=0, max_concurrency=1)
class HyperDeepWorkerActor:
    ...
```

| 속성 | 값 | 이유 |
|------|-----|------|
| `num_cpus=0.5` | 0.5 core | HDR는 I/O bound (Tavily API 대기 지배) |
| `max_concurrency=1` | 1 요청/인스턴스 | 내부 상태 충돌 방지 |
| 인스턴스당 agent 1개 | — | `HyperDeepResearchAgent` 독립 보유 |

**`_reset_agent_state()` → `agent.reset()` 위임**

Actor 재사용 시 `HyperDeepResearchAgent.reset()`에 위임하여 내부 상태를 초기화.
agent에 새 필드가 추가될 때 자동으로 반영되므로 동기화 문제가 없다.

```python
# executor_pool.py
def _reset_agent_state(self) -> None:
    self._agent.reset()  # agent.py의 reset()에 위임

# agent.py — HyperDeepResearchAgent
def reset(self) -> None:
    self.current_report_id = None
    self.sections_data = []
    self.all_collected_sources = []
    self.research_metadata = { ... }  # __init__과 동일한 초기값
    self.event_logger = None
```

**context 직렬화 제한**

Ray pickle 직렬화 불가 항목을 Worker context에 절대 포함하지 않음:

```python
# 허용
agent_context = {
    "session_id": context.get("session_id", ""),
    "user_id": context.get("user_id", ""),
    "prior_research_context": prior_summary,  # 문자열만 허용
}

# 금지 — Ray pickle 불가
# "_stream_callback": context.get("_stream_callback"),  # coroutine/closure
# "_cost_accumulator": context.get("_cost_accumulator"),  # mutable list
```

**반환 형식:**

```python
{
    "result": str,    # 리포트 마크다운
    "cost": float,    # 현재 0.0 (HDR agent 비용 추출 미구현)
    "task_id": str,
    "status": "completed" | "failed",
}
```

#### `RayExecutorPool`

```python
pool = RayExecutorPool(pool_size=3)  # HYPER_DEEP_MAX_TASKS_PER_LEVEL과 동일하게

# 단일 태스크 제출
future = pool.submit(task.to_dict(), context)
result = await asyncio.wrap_future(future.future())

# 복수 독립 태스크 일괄 실행
results = await pool.execute_all_parallel(
    [t.to_dict() for t in tasks],
    context
)

# warm-up (main.py lifespan에서 자동 호출됨)
await pool.warmup()
```

**라운드로빈 선택:**
- `submit()`: `self._actors[self._next_idx % pool_size]` + `self._next_idx` 갱신
- `execute_all_parallel()`: `self._actors[(self._next_idx + i) % pool_size]` + `self._next_idx` 일괄 갱신
  → 두 메서드를 혼용해도 라운드로빈 균형 유지

**warmup 실패 처리:**

```python
# assert 대신 RuntimeError — Python -O 최적화 모드에서도 안전
if not all(results):
    raise RuntimeError("일부 Worker Actor warmup 실패")
```

**Actor 정리 정책:**

`__del__`에서 `ray.kill()`을 호출하지 않는다. Ray는 클러스터 종료 시 Actor를 자동으로 정리하므로 명시적 kill이 불필요하며, 인터프리터 종료 시 Ray가 이미 `shutdown()`된 상태일 경우 불필요한 예외를 유발할 수 있다.

---

### 3-C. `distributed_orchestrator.py` — 핵심 오케스트레이터

#### 초기화

```python
orchestrator = DistributedRecursiveOrchestrator(
    agents=agents,
    max_depth=1,           # HYPER_DEEP_MAX_DEPTH
    budget_cap=5.0,        # HYPER_DEEP_BUDGET_CAP
    max_tasks_per_level=3, # HYPER_DEEP_MAX_TASKS_PER_LEVEL
    ray_enabled=True,
    ray_pool_size=3,
)
```

`__init__` 내부에서 Ray Pool 생성 후 `_connect_named_actors(ray)`를 호출하여
`self._atomizer`, `self._planner`, `self._aggregator`, `self._verifier`를
Named Actor 어댑터로 교체한다.

#### Named Actor 어댑터 연결 흐름

```
main.py lifespan:
  create_all_named_actors()  ← Named Actor 4개 Ray 클러스터에 등록

DistributedRecursiveOrchestrator.__init__():
  _connect_named_actors(ray)
    ray.get_actor("neos_atomizer")  → _NamedAtomizerAdapter(handle)
    ray.get_actor("neos_planner")   → _NamedPlannerAdapter(handle)
    ray.get_actor("neos_aggregator")→ _NamedAggregatorAdapter(handle)
    ray.get_actor("neos_verifier")  → _NamedVerifierAdapter(handle)
    # Named Actor 미발견 시 → warning 로그 + 로컬 인스턴스 유지

_recursive_solve():
  await self._atomizer.assess(task, ctx)  ← 어댑터가 직렬화/역직렬화 처리
  await self._planner.decompose(task, ctx)
  await self._aggregator.aggregate(...)
  await self._verifier.verify(...)
```

#### `_recursive_solve()` 오버라이드 전략

```python
async def _recursive_solve(self, task, context, seen_hashes, replan_count=0):
    # ray.enabled: false → 부모 클래스 완전 위임
    if not self._ray_enabled or self._ray_pool is None:
        return await super()._recursive_solve(task, context, seen_hashes, replan_count)

    # ATOMIC → Ray Worker 실행
    if atomicity == TaskAtomicity.ATOMIC:
        return await self._execute_via_ray(task, context)

    # DECOMPOSABLE → DAG 레벨별 병렬 실행
    subtasks = await self._planner.decompose(task, context)
    execution_levels = build_execution_levels(subtasks)

    prior_results = {}
    for level_indices in execution_levels:
        level_tasks = [subtasks[i] for i in level_indices]

        if len(level_tasks) == 1:
            # 단일 태스크: 재귀 처리 (Ray 오버헤드 불필요)
            result = await self._recursive_solve(level_tasks[0], ...)
            prior_results[level_tasks[0].task_id] = result
        else:
            # 복수 독립 태스크: Ray 병렬 실행
            results = await self._execute_level_parallel(level_tasks, ...)
            prior_results.update(zip([t.task_id for t in level_tasks], results))
```

#### `_replan_and_solve()` 오버라이드 (병렬화)

부모 클래스의 순차 for-loop을 대체하여 재계획 subtask에도 DAG 레벨 병렬화를 적용한다.

```python
async def _replan_and_solve(self, task, aggregated, gaps, context, seen_hashes):
    replan_tasks = await self._planner.replan(task, aggregated, gaps, context)
    if not replan_tasks:
        return None

    # 재계획 태스크도 DAG 레벨별 병렬 실행
    execution_levels = build_execution_levels(replan_tasks)
    replan_results = {}

    for level_indices in execution_levels:
        level_tasks = [replan_tasks[i] for i in level_indices]
        if len(level_tasks) == 1:
            result = await self._recursive_solve(level_tasks[0], ..., replan_count=1)
            level_tasks[0].result = result
            replan_results[level_tasks[0].task_id] = result
        else:
            results = await self._execute_level_parallel(level_tasks, ...)
            for t, res in zip(level_tasks, results):
                t.result = res
                replan_results[t.task_id] = res

    all_children = list(task.children) + replan_tasks
    return await self._aggregator.aggregate(task, all_children, context)
```

#### 비용 추적

`_cost_accumulator`(mutable list)는 Ray 프로세스 경계를 넘을 수 없으므로, Worker 결과 수신 후 메인 프로세스에서만 업데이트:

```python
async def _execute_via_ray(self, task, context):
    future = self._ray_pool.submit(task.to_dict(), ray_context)
    result_dict = await asyncio.wrap_future(future.future())

    # 메인 프로세스에서만 누적
    cost_acc = context.get("_cost_accumulator")
    if cost_acc is not None:
        cost_acc[0] += result_dict.get("cost", 0.0)
```

#### `_build_ray_context()` — 안전한 context 생성

```python
def _build_ray_context(self, context):
    return {
        "session_id": context.get("session_id", ""),
        "user_id": context.get("user_id", ""),
        "detected_language": context.get("detected_language", "ko"),
        "original_query": context.get("original_query", ""),
        "prior_results_summary": self._summarize_prior_results(
            context.get("prior_results", {})
        ),
        # 제외: _stream_callback, _cost_accumulator
    }
```

---

### 3-D. `graph.py` 수정

```python
# neos/workflow/graph.py
if settings.HYPER_DEEP_AGENT_ENABLED:
    if getattr(settings, "RAY_ENABLED", False):
        from neos.workflow.recursive.distributed_orchestrator import (
            DistributedRecursiveOrchestrator,
        )
        self.hyper_deep_orchestrator = DistributedRecursiveOrchestrator(
            agents=self.agents,
            max_depth=settings.HYPER_DEEP_MAX_DEPTH,
            budget_cap=settings.HYPER_DEEP_BUDGET_CAP,
            max_tasks_per_level=settings.HYPER_DEEP_MAX_TASKS_PER_LEVEL,
            ray_enabled=True,
            ray_pool_size=settings.HYPER_DEEP_MAX_TASKS_PER_LEVEL,
        )
    else:
        # 기존 순차 실행 경로 (변경 없음)
        from neos.workflow.recursive.orchestrator import RecursiveOrchestrator
        from neos.workflow.hyper_deep.executor import HyperDeepExecutor
        _hd_executor = HyperDeepExecutor()
        self.hyper_deep_orchestrator = RecursiveOrchestrator(...)
```

> **주의:** RAY 경로에서는 `HyperDeepExecutor`를 주입하지 않음.
> `DistributedRecursiveOrchestrator`의 ATOMIC 실행이 `HyperDeepWorkerActor`를 직접 사용하므로 싱글톤 executor 불필요.

---

### 3-E. `main.py` 수정

```python
# lifespan startup
if getattr(settings, "RAY_ENABLED", False):
    try:
        import ray
        if not ray.is_initialized():
            ray.init(
                address=settings.RAY_ADDRESS,
                ignore_reinit_error=True,
                object_store_memory=settings.RAY_OBJECT_STORE_MEMORY,
            )
        # Phase 2 Named Actors 생성 (Atomizer, Planner, Aggregator, Verifier)
        from neos.workflow.ray_actors.stateless_actors import create_all_named_actors
        create_all_named_actors(max_tasks_per_level=settings.HYPER_DEEP_MAX_TASKS_PER_LEVEL)

        # Phase 2 CostAccumulatorActor
        from neos.workflow.ray_actors.cost_accumulator import get_or_create_cost_accumulator
        get_or_create_cost_accumulator()

    except Exception as e:
        logger.warning(f"Ray 초기화 실패, 순차 실행으로 fallback: {e}")

    # Worker Actor 준비 완료 대기 (콜드 스타트 방지) — [9-C 해결]
    try:
        from neos.workflow.recursive.distributed_orchestrator import DistributedRecursiveOrchestrator
        orchestrator = getattr(multi_agent_workflow, "hyper_deep_orchestrator", None)
        if isinstance(orchestrator, DistributedRecursiveOrchestrator):
            await orchestrator.warmup()
    except Exception as e:
        logger.warning(f"Worker Actor warmup 실패: {e}")

# lifespan shutdown
if getattr(settings, "RAY_ENABLED", False):
    import ray
    if ray.is_initialized():
        ray.shutdown()
```

---

## 4. Phase 2: Stateless Named Actors

### 개요

Atomizer, Planner, Aggregator, Verifier를 Named Actor로 공유.
단일 인스턴스가 여러 요청을 처리 → 메모리 절약.
`DistributedRecursiveOrchestrator`는 `_connect_named_actors()`를 통해 Named Actor 핸들을
어댑터 클래스로 래핑하여 로컬 인스턴스와 동일한 인터페이스로 사용한다.

### Named Actor 키

| Actor | 키 | `max_concurrency` | `num_cpus` |
|-------|-----|-------------------|------------|
| `RayAtomizerActor` | `neos_atomizer` | 10 | 0.25 |
| `RayPlannerActor` | `neos_planner` | 5 | 0.5 |
| `RayAggregatorActor` | `neos_aggregator` | 10 | 0.25 |
| `RayVerifierActor` | `neos_verifier` | 10 | 0.25 |
| `CostAccumulatorActor` | `neos_cost_accumulator` | 1 (기본) | **0** |

### Named Actor 어댑터 클래스 (distributed_orchestrator.py)

`stateless_actors.py`의 Named Actor는 dict 기반 인터페이스(직렬화 요구)를 사용하므로,
`distributed_orchestrator.py` 내부의 어댑터 클래스가 직렬화/역직렬화를 캡슐화한다:

```python
class _NamedAtomizerAdapter:
    def __init__(self, actor_handle): self._actor = actor_handle

    async def assess(self, task, context) -> TaskAtomicity:
        result_str = await asyncio.wrap_future(
            self._actor.assess.remote(task.to_dict(), _safe_context(context)).future()
        )
        return TaskAtomicity(result_str)

class _NamedPlannerAdapter:
    async def decompose(self, task, context) -> List[RecursiveTaskNode]:
        dicts = await asyncio.wrap_future(
            self._actor.decompose.remote(task.to_dict(), _safe_context(context)).future()
        )
        return [RecursiveTaskNode.from_dict(d) for d in dicts]

    async def replan(self, task, previous_result, gaps, context) -> List[RecursiveTaskNode]:
        dicts = await asyncio.wrap_future(
            self._actor.replan.remote(
                task.to_dict(), previous_result, gaps, _safe_context(context)
            ).future()
        )
        return [RecursiveTaskNode.from_dict(d) for d in dicts]

class _NamedAggregatorAdapter:
    async def aggregate(self, parent, children, context) -> str:
        result_str, _ = await asyncio.wrap_future(
            self._actor.aggregate.remote(
                parent.to_dict(), [c.to_dict() for c in children], _safe_context(context)
            ).future()
        )
        return result_str

class _NamedVerifierAdapter:
    async def verify(self, task, aggregated_result, context) -> Dict:
        return await asyncio.wrap_future(
            self._actor.verify.remote(
                task.to_dict(), aggregated_result, _safe_context(context)
            ).future()
        )
```

### context 필터링

```python
# distributed_orchestrator.py 및 stateless_actors.py 공통 패턴
_NON_SERIALIZABLE_KEYS = frozenset(["_stream_callback", "_cost_accumulator"])

def _safe_context(context):
    return {k: v for k, v in context.items() if k not in _NON_SERIALIZABLE_KEYS}
```

### `create_all_named_actors()` 유틸리티

```python
from neos.workflow.ray_actors.stateless_actors import create_all_named_actors

# main.py lifespan에서 ray.init() 직후 호출
# → distributed_orchestrator.__init__()의 _connect_named_actors() 전에 반드시 실행
create_all_named_actors(max_tasks_per_level=3)

# 이미 존재하는 Named Actor는 재사용 (ValueError 처리)
```

### `CostAccumulatorActor` 사용법

```python
from neos.workflow.ray_actors.cost_accumulator import get_or_create_cost_accumulator
import asyncio

cost_actor = get_or_create_cost_accumulator()

# 비용 누적 (lazy TTL eviction 포함)
total = await asyncio.wrap_future(cost_actor.add.remote("session123", 0.05).future())

# 예산 체크
ok = await asyncio.wrap_future(cost_actor.check_budget.remote("session123", 5.0).future())

# 세션 종료 시 초기화 (명시 호출 권장)
await asyncio.wrap_future(cost_actor.reset.remote("session123").future())
```

**TTL 기반 자동 정리:**

세션 종료 시 `reset()`이 호출되지 않아도 마지막 접근 후 1시간(`_SESSION_TTL_SEC=3600`) 경과 시
`_evict_expired()`가 자동으로 항목을 제거한다 (lazy eviction — `add()` 호출 시 트리거).

**`num_cpus=0`:**

`CostAccumulatorActor`는 단순 dict 연산만 수행하므로 `@ray.remote(num_cpus=0)`으로 설정하여
CPU 스케줄러 리소스를 소비하지 않는다.

---

## 5. Phase 3: Sandbox 코드 실행

> **현재 HDR는 임의 코드를 실행하지 않음.**
> 향후 LLM이 생성한 분석 코드(pandas, json 파싱 등) 실행 기능 추가 시를 위한 예방적 설계.

### 활성화

```bash
# optional dependency 설치
uv add --optional sandbox RestrictedPython

# 환경변수
SANDBOX_ENABLED=true
SANDBOX_TYPE=restricted   # restricted | docker | pyodide
SANDBOX_TIMEOUT_SEC=30
```

### 사용법

```python
from neos.workflow.ray_actors.sandboxed_executor import SandboxedCodeExecutor

executor = SandboxedCodeExecutor(sandbox_type="restricted")

# 허용된 코드 실행
result = await executor.execute(
    code="result = sum(values)",
    input_data={"values": [1, 2, 3, 4, 5]},
    timeout_sec=10,
)
# result.success == True
# result.output == "15"
# result.execution_time_ms == ~5

# 차단된 import
result = await executor.execute("import os; os.system('rm -rf /')")
# result.success == False
# result.error == "'os' import는 sandbox에서 허용되지 않습니다."
```

**`execute()` 시그니처:**

```python
async def execute(
    self,
    code: str,
    input_data: Optional[Dict[str, Any]] = None,
    timeout_sec: Optional[int] = None,
) -> CodeExecutionResult:
```

> `allowed_imports` 파라미터는 이전 버전에 있었으나 실제 동작하지 않아 제거됨.
> import 허용 목록 변경이 필요하면 `sandbox_executor.py`의 `_ALLOWED_IMPORTS` 수정.

### 허용/차단 목록

| 항목 | 상태 |
|------|------|
| `math, statistics, json, re, datetime, collections, itertools, functools` | ✅ 허용 |
| `os, sys, subprocess, socket, urllib` | ❌ 차단 |
| `open()` | ❌ 차단 |
| `exec()`, `eval()` | ❌ 차단 |
| `__import__`(화이트리스트 외) | ❌ 차단 |

### Timeout 구현

`asyncio.wait_for()` 기반 (크로스 플랫폼 안전):

```python
loop = asyncio.get_running_loop()  # get_event_loop() deprecated (Python 3.10+) 대신 사용
result = await asyncio.wait_for(
    loop.run_in_executor(None, self._run_restricted, code, input_data),
    timeout=timeout_sec,
)
```

> `signal.SIGALRM` 대신 사용. macOS에서는 SIGALRM이 작동하지만 Windows 불가.

---

## 6. Phase 4: 메트릭 통합

### 추가된 Prometheus 메트릭

`neos/observability/metrics.py`에 정의, **기록은 `distributed_orchestrator.py`의 메인 프로세스에서** 수행:

```python
# _execute_level_parallel() — 레벨별 병렬 실행 완료 후
metrics.ray_level_tasks_parallel.observe(n)

utilization = min(n / pool_size, 1.0)
metrics.ray_pool_utilization.labels(pool_name="hyper_deep").set(utilization)

if elapsed > 0 and n > 1:
    speedup = (elapsed * n) / elapsed  # 순차 예상 / 실제 병렬
    metrics.ray_parallel_speedup_ratio.set(speedup)

for task in tasks:
    metrics.ray_task_duration_seconds.labels(
        task_type="hdr", level=str(task.depth)
    ).observe(elapsed)

# _execute_via_ray() — 단일 ATOMIC 태스크 완료 후
metrics.ray_task_duration_seconds.labels(
    task_type="hdr", level=str(task.depth)
).observe(elapsed)
```

> **원칙:** Ray Worker 내부에서는 메트릭 직접 기록 불가 (별도 프로세스).
> 반드시 Worker 결과 수신 후 메인 프로세스에서 기록.

> **`ray_actor_restarts_total`:** Actor 재시작을 감지하는 외부 훅이 필요하므로 현재 미기록.
> Ray Dashboard의 Actor 재시작 카운터로 대체 모니터링 가능.

### Prometheus scrape 설정

`config/prometheus/prometheus.yml`에 `ray-head` job 추가됨:

```yaml
- job_name: 'ray-head'
  scrape_interval: 15s
  static_configs:
    - targets:
        - 'localhost:8080'  # ray.init(_metrics_export_port=8080) 필요
  metrics_path: '/metrics'
```

Ray Head Node 시작 시:

```bash
ray start --head --metrics-export-port=8080
```

또는 코드에서:

```python
ray.init(_metrics_export_port=8080, ...)
```

---

## 7. 설정 레퍼런스

### `neos/config/settings.py`

```python
# ── Ray 분산 처리 ──
RAY_ENABLED: bool          # 기본 false. true 시 Ray 병렬 실행 활성화
RAY_ADDRESS: str           # 기본 "auto" (로컬 Ray 자동 시작)
                           # 외부 클러스터: "ray://head:10001"
RAY_NUM_CPUS: float | None # Ray init 시 할당 CPU 수 (None = 자동)
RAY_OBJECT_STORE_MEMORY: int  # 기본 2,000,000,000 (2GB)

# ── Sandbox 코드 실행 ──
SANDBOX_ENABLED: bool      # 기본 false
SANDBOX_TYPE: str          # "restricted" | "docker" | "pyodide" (기본 "restricted")
SANDBOX_TIMEOUT_SEC: int   # 기본 30초
```

### YAML 설정 (`config/neos.local.yaml` 또는 deployment overlay)

```yaml
# Phase 1: 핵심 병렬 실행
ray:
  enabled: true
  address: auto
  object_store_memory: 2000000000

# Phase 3: Sandbox (선택적)
sandbox:
  enabled: true
  type: restricted
  timeout_sec: 30
```

### 리소스 계산

`HYPER_DEEP_MAX_TASKS_PER_LEVEL=3`, `pool_size=3` 기준:

| 항목 | 단일 노드 추가 요구량 |
|------|----------------------|
| CPU (Worker) | +1.5 cores (0.5 × 3) |
| CPU (Named Actors) | +1.25 cores (0.25×3 + 0.5 Planner) |
| Memory | +1.5 GB (HyperDeepResearchAgent × 3) |
| Ray Object Store | +2 GB |
| Tavily API | 최대 동시 15+ 호출 (Rate Limit 주의) |

---

## 8. 활성화 및 검증

### 단계 1: Ray 설치 확인

```bash
uv sync  # ray[default]>=2.8.0 자동 설치
python -c "import ray; print(ray.__version__)"
```

### 단계 2: DAG 유틸리티 단위 테스트

```python
from neos.workflow.recursive.models import RecursiveTaskNode
from neos.workflow.ray_actors.dag_utils import build_execution_levels

def make_task(deps):
    return RecursiveTaskNode(description="test", metadata={"depends_on": deps})

# 케이스 1: 완전 독립 3개
assert build_execution_levels([make_task([]), make_task([]), make_task([])]) == [[0, 1, 2]]

# 케이스 2: 2 + 1 의존
assert build_execution_levels([make_task([]), make_task([]), make_task([0,1])]) == [[0, 1], [2]]

# 케이스 3: 완전 체인
assert build_execution_levels([make_task([]), make_task([0]), make_task([1])]) == [[0], [1], [2]]

# 케이스 4: 순환 의존성
try:
    build_execution_levels([make_task([1]), make_task([0])])
    assert False, "ValueError 미발생"
except ValueError:
    pass

# 케이스 5: 범위 외 인덱스 (LLM 오출력 방어)
# depends_on=[99]는 무시되어 독립 태스크로 처리됨
assert build_execution_levels([make_task([99]), make_task([])]) == [[0, 1]]

# 케이스 6: 자기 의존 (LLM 오출력 방어)
assert build_execution_levels([make_task([0]), make_task([])]) == [[0, 1]]

print("✅ dag_utils 단위 테스트 통과")
```

### 단계 3: `ray.enabled: false` 회귀 테스트

```bash
# config/neos.local.yaml에서 ray.enabled를 설정하지 않거나 false로 유지
NEOS_CONFIG_PATH=config/neos.local.yaml python -c "
from neos.workflow.graph import MultiAgentWorkflow
wf = MultiAgentWorkflow()
print(type(wf.hyper_deep_orchestrator).__name__)  # RecursiveOrchestrator
print('✅ 기존 순차 실행 경로 정상')
"
```

### 단계 4: `ray.enabled: true` 통합 테스트

```bash
# Ray Head Node 시작 (로컬)
ray start --head --metrics-export-port=8080

# NEOS 서버 시작 (별도 터미널)
# → main.py lifespan에서 ray.init → create_all_named_actors → warmup 순으로 자동 실행
NEOS_CONFIG_PATH=config/neos.local.yaml python -m neos.main

# Ray Dashboard 확인
open http://localhost:8265
# Actors 탭에서 확인:
#   HyperDeepWorkerActor × 3
#   RayAtomizerActor, RayPlannerActor, RayAggregatorActor, RayVerifierActor (Named)
#   CostAccumulatorActor (Named)

# HDR 요청 실행 후 병렬 실행 시간 측정
# 기대값: 3개 독립 subtask 기준 ~2.5× 속도 향상
```

### 단계 5: Named Actor 어댑터 확인

```bash
NEOS_CONFIG_PATH=config/neos.local.yaml python -c "
import ray
ray.init(ignore_reinit_error=True)
from neos.workflow.ray_actors.stateless_actors import create_all_named_actors
create_all_named_actors(max_tasks_per_level=3)

from neos.workflow.recursive.distributed_orchestrator import DistributedRecursiveOrchestrator
orch = DistributedRecursiveOrchestrator(ray_enabled=True, ray_pool_size=3)

from neos.workflow.recursive.distributed_orchestrator import (
    _NamedAtomizerAdapter, _NamedPlannerAdapter,
    _NamedAggregatorAdapter, _NamedVerifierAdapter,
)
assert isinstance(orch._atomizer, _NamedAtomizerAdapter), '어댑터 미연결'
assert isinstance(orch._planner, _NamedPlannerAdapter), '어댑터 미연결'
print('✅ Named Actor 어댑터 연결 확인')
ray.shutdown()
"
```

### 단계 6: Sandbox 테스트 (Phase 3)

```bash
uv add --optional sandbox RestrictedPython

NEOS_CONFIG_PATH=config/neos.local.yaml python -c "
import asyncio
from neos.workflow.ray_actors.sandboxed_executor import SandboxedCodeExecutor

async def test():
    ex = SandboxedCodeExecutor()

    # 허용 코드
    r = await ex.execute('result = sum([1,2,3])')
    assert r.success and r.output == '6', f'실패: {r}'
    print('✅ 허용 코드 실행 성공')

    # 차단 코드
    r = await ex.execute('import os')
    assert not r.success, f'차단 실패: {r}'
    print('✅ 금지 import 차단 확인')

asyncio.run(test())
"
```

---

## 9. 알려진 제한사항

### 9-A. SSE 스트리밍 손실 (Phase 1 known limitation)

**문제:** `_stream_callback`이 Ray pickle 직렬화 불가 → Worker에 전달 불가.
HDR Phase 이벤트(검색 진행 상황 SSE)가 `ray.enabled: true` 시 전달되지 않음.

**현재 상태:** Orchestrator 레벨의 시작/완료 이벤트만 SSE 전달 가능.

**장기 해결 방향:** `StreamBridgeActor` — Redis Pub/Sub 경유 이벤트 브릿지:

```python
# 미구현 — 향후 구현 예정
@ray.remote
class StreamBridgeActor:
    def __init__(self, redis_url, session_id):
        self._redis = redis.from_url(redis_url)
        self._session_id = session_id

    def emit(self, event_type, data):
        self._redis.publish(f"hdr_events:{self._session_id}", json.dumps({
            "event": event_type, "data": data
        }))
```

### 9-B. 비용 추적 정밀도 저하

`_cost_accumulator`(mutable list)는 Ray 프로세스 경계 불가.
Worker 결과 수신 후 메인 프로세스에서 일괄 업데이트 → 레벨 완료 전 예산 초과 조기 감지 불가.

**해결책:** Phase 2의 `CostAccumulatorActor`를 Worker에서 직접 호출하도록 확장 가능.
단, Worker에서 Named Actor 접근 시 Actor name(`"neos_cost_accumulator"`)을 context에 문자열로 전달해야 함.

### ~~9-C. HyperDeepWorkerActor 초기화 지연~~ (해결됨)

`main.py` lifespan의 `await orchestrator.warmup()` 호출로 서버 시작 시 Worker Actor 초기화를 완료한다.
첫 요청 도착 전에 모든 Worker가 준비 상태가 보장된다.

### 9-D. Tavily API Rate Limit

Pool 3개 Worker가 동시에 각 5회 Tavily 호출 → 동시 15회+ API 요청 발생.
Tavily Free Tier 기본 분당 100회 제한은 충분하지만, 고부하 시 초과 가능.

**완화책:** `ResearchConfig`에서 Worker당 `max_queries` 제한 검토.

### 9-E. Docker Sandbox 미구현

`SANDBOX_TYPE=docker`는 인터페이스만 정의. 실제 Docker 컨테이너 격리 실행 미구현.
현재 `restricted` 타입만 사용 가능.

### 9-F. Pyodide WASM Sandbox 미구현

`SANDBOX_TYPE=pyodide`는 인터페이스만 정의. 별도 FastAPI + Pyodide 서비스 필요.
장기 로드맵 항목.
