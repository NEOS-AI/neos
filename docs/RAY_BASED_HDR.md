# Ray 기반 HyperDeepResearch 분산 처리 아키텍처 설계

> 분산 마이크로서비스 패턴을 활용한 HDR 병렬화 및 격리 실행 방안 분석

---

## 목차

1. [현황 분석: 왜 Ray가 필요한가?](#1-현황-분석-왜-ray가-필요한가)
2. [Ray 기반 분산 아키텍처 개요](#2-ray-기반-분산-아키텍처-개요)
3. [컴포넌트별 Ray Actor 설계](#3-컴포넌트별-ray-actor-설계)
4. [DAG 기반 의존성 처리 및 병렬 실행](#4-dag-기반-의존성-처리-및-병렬-실행)
5. [ExecutorPool: HyperDeepResearchAgent 병렬화](#5-executorpool-hyperdeepresearchagent-병렬화)
6. [Sandbox 기반 격리된 코드 실행 API](#6-sandbox-기반-격리된-코드-실행-api)
7. [NEOS 기존 시스템 통합 전략](#7-neos-기존-시스템-통합-전략)
8. [성능 트레이드오프 분석](#8-성능-트레이드오프-분석)
9. [구현 로드맵](#9-구현-로드맵)
10. [참고: 핵심 파일 경로](#10-참고-핵심-파일-경로)

---

## 1. 현황 분석: 왜 Ray가 필요한가?

### 1-A. 현재 HDR 실행 흐름 (순차)

```
사용자 쿼리: "2025년 AI 헬스케어 산업 현황 분석"
                    │
                    ▼
         RecursiveOrchestrator
         (max_depth=1, max_tasks=3)
                    │
         ┌──────────▼──────────┐
         │  Planner (Opus)     │  ← 쿼리를 3개 subtask로 분해
         │  depth=0            │
         └──────────┬──────────┘
                    │
         ┌──────────┴─────────────────────────────┐
         │  subtasks (metadata.depends_on 존재)   │
         │  [0] "Clinical AI 논문 수집"            │  (독립)
         │  [1] "규제·허가 현황 조사"              │  (독립)
         │  [2] "시장 규모 및 투자 트렌드 분석"    │  depends_on=[0,1]
         └──────────┬─────────────────────────────┘
                    │
         ┌──────────▼──────────────────────────────────────┐
         │  순차 실행 (for loop, CLAUDE.md 정책)            │
         │                                                  │
         │  1️⃣  HyperDeepResearchAgent.execute(task[0])    │ ← ~2분
         │      (Tavily API x5 + LLM synthesis)            │
         │                          ↓                       │
         │  2️⃣  HyperDeepResearchAgent.execute(task[1])    │ ← ~2분
         │      (같은 싱글톤 agent, 상태 초기화 후 재사용)  │
         │                          ↓                       │
         │  3️⃣  HyperDeepResearchAgent.execute(task[2])    │ ← ~2분
         │      (task[0], task[1] 결과를 prior_results로)  │
         └──────────────────────────────────────────────────┘
                    │
                    ▼  총 실행 시간: ~6분
         Aggregator → Verifier → 최종 응답
```

### 1-B. 병목 지점 파악

| 문제 | 현황 | 영향 |
|------|------|------|
| **Sibling 직렬 실행** | `task[0]`, `task[1]`은 의존성 없으나 순차 실행 | 실행 시간 = Σ(T_leaf) |
| **싱글톤 Executor** | `HyperDeepExecutor._agent`가 1개 인스턴스 | 동시 leaf 실행 불가 |
| **단일 프로세스** | GIL로 인해 Python CPU 연산 병렬화 불가 | CPU bound 작업 병목 |
| **장애 전파** | 하나의 leaf 실패 → 전체 중단 가능 | 복원력 부재 |
| **코드 실행 격리 없음** | 향후 HDR에 코드 실행 기능 추가 시 격리 환경 없음 | 확장 시 보안 리스크 |

### 1-C. `depends_on` 필드 실제 구조

```python
# neos/workflow/recursive/planner.py:240
node = RecursiveTaskNode(
    metadata={"depends_on": item.get("depends_on", [])},  # 0-based 인덱스 리스트
)

# 예시: subtasks[2]가 subtasks[0], subtasks[1]에 의존
subtasks[0].metadata["depends_on"] = []      # 독립
subtasks[1].metadata["depends_on"] = []      # 독립
subtasks[2].metadata["depends_on"] = [0, 1]  # 0번, 1번 완료 후 실행
```

**현재 Orchestrator는 이 의존성 정보를 전혀 파싱하지 않는다.** Planner가 반환하는 subtask 순서 자체가 의존성 순서를 보장하도록 프롬프트에 명시되어 있으며 (`"Order sub-tasks by dependency (list prerequisites first)"`), orchestrator는 단순히 그 순서대로 순차 실행할 뿐이다. 즉 `depends_on` 필드는 현재 완전히 미활용 상태이며, Ray DAG 설계에서 처음으로 이를 파싱해 병렬화에 활용하게 된다.

---

## 2. Ray 기반 분산 아키텍처 개요

### 2-A. 핵심 설계 철학

```
현재: 단일 Python 프로세스 내 순차 실행
         ┌────────────────────────────────┐
         │  neos-worker (단일 프로세스)   │
         │  Atomizer → Planner →          │
         │  Executor[0] → Executor[1] →   │
         │  Executor[2] → Aggregator      │
         └────────────────────────────────┘

제안: Ray 클러스터 기반 분산/병렬 실행
         ┌─────────────────────────────────────────────────┐
         │  Ray Head Node (NEOS API 서버)                  │
         │  ┌─────────────┐  ┌─────────────────────────┐   │
         │  │ Planner     │  │  ExecutorPool           │   │
         │  │ Actor       │  │  ┌───────┐ ┌───────┐   │   │
         │  │ (stateless) │  │  │Worker0│ │Worker1│   │   │
         │  └─────────────┘  │  └───────┘ └───────┘   │   │
         │  ┌─────────────┐  │  ┌───────┐             │   │
         │  │ Aggregator  │  │  │Worker2│  (ActorPool) │   │
         │  │ Actor       │  │  └───────┘             │   │
         │  └─────────────┘  └─────────────────────────┘   │
         └─────────────────────────────────────────────────┘

         Ray Worker Node (선택적 스케일아웃)
         ┌──────────────────────────────┐
         │  Sandbox Executor Actors     │
         │  (코드 실행 격리 환경)        │
         └──────────────────────────────┘
```

### 2-B. Ray 선택 이유

| 대안 | Ray 대비 단점 |
|------|-------------|
| `asyncio.gather` | 단일 Python 프로세스 → GIL 병목, 장애 격리 없음 |
| `concurrent.futures` | 스레드풀은 GIL 제약, ProcessPool은 직렬화 오버헤드 |
| Celery | 태스크 레벨 스케줄링만, Actor 상태관리 없음, DAG 기능 제한 |
| **Ray** | ✅ Actor 모델, ✅ Object Store 공유 메모리, ✅ DAG 지원, ✅ Fault tolerance |

---

## 3. 컴포넌트별 Ray Actor 설계

### 3-A. Stateless Actor (공유 가능)

Atomizer, Planner, Aggregator, Verifier는 상태가 없으므로 단일 Actor로 공유 가능.

```python
# neos/workflow/ray_actors/stateless_actors.py

import ray
from neos.workflow.recursive.atomizer import RecursiveAtomizer
from neos.workflow.recursive.planner import RecursivePlanner
from neos.workflow.recursive.aggregator import RecursiveAggregator
from neos.workflow.recursive.verifier import RecursiveVerifier
from neos.workflow.recursive.models import RecursiveTaskNode, TaskAtomicity

@ray.remote(num_cpus=0.25, max_concurrency=10)  # 10개 동시 요청 처리
class RayAtomizerActor:
    """Atomizer의 Ray 래퍼. 상태 없음, 높은 동시성 허용."""
    def __init__(self):
        self._atomizer = RecursiveAtomizer()

    async def assess(self, task_dict: dict, context: dict) -> str:
        """task_dict: RecursiveTaskNode.to_dict() 형태"""
        task = RecursiveTaskNode.from_dict(task_dict)
        result = await self._atomizer.assess(task, context)
        return result.value  # Enum → str for serialization


@ray.remote(num_cpus=0.5, max_concurrency=5)
class RayPlannerActor:
    """Planner의 Ray 래퍼. depth=0은 Opus, depth>0은 Haiku 사용."""
    def __init__(self, max_tasks_per_level: int = None):
        self._planner = RecursivePlanner(max_tasks_per_level)

    async def decompose(self, task_dict: dict, context: dict) -> list[dict]:
        task = RecursiveTaskNode.from_dict(task_dict)
        subtasks = await self._planner.decompose(task, context)
        return [s.to_dict() for s in subtasks]  # JSON 직렬화

    async def replan(
        self, task_dict: dict, previous_result: str, gaps: list, context: dict
    ) -> list[dict]:
        task = RecursiveTaskNode.from_dict(task_dict)
        subtasks = await self._planner.replan(task, previous_result, gaps, context)
        return [s.to_dict() for s in subtasks]


@ray.remote(num_cpus=0.25, max_concurrency=10)
class RayAggregatorActor:
    def __init__(self):
        self._aggregator = RecursiveAggregator()

    async def aggregate(
        self, parent_dict: dict, child_dicts: list[dict], context: dict
    ) -> tuple[str, dict]:
        """Returns (aggregated_text, updated_parent_dict)"""
        parent = RecursiveTaskNode.from_dict(parent_dict)
        children = [RecursiveTaskNode.from_dict(c) for c in child_dicts]
        result = await self._aggregator.aggregate(parent, children, context)
        return result, parent.to_dict()


@ray.remote(num_cpus=0.25, max_concurrency=10)
class RayVerifierActor:
    def __init__(self):
        self._verifier = RecursiveVerifier()

    async def verify(
        self, task_dict: dict, aggregated_result: str, context: dict
    ) -> dict:
        task = RecursiveTaskNode.from_dict(task_dict)
        return await self._verifier.verify(task, aggregated_result, context)
```

**직렬화 패턴:** `RecursiveTaskNode.to_dict()` / `from_dict()`을 활용해 Ray Object Store를 통한 inter-actor 전달. 이미 `models.py`에 구현되어 있어 추가 작업 불필요.

### 3-B. 비용 추적 공유 (Ray Shared Memory)

현재의 `_cost_accumulator` (mutable list trick) 패턴은 Ray 프로세스 경계를 넘을 수 없다.

```python
# 방안 1: Ray Named Actor로 비용 누적기 구현
@ray.remote
class CostAccumulatorActor:
    """세션별 비용 누적기 (Named Actor)."""
    def __init__(self):
        self._costs: dict[str, float] = {}  # session_id → total cost

    def add(self, session_id: str, cost: float):
        self._costs[session_id] = self._costs.get(session_id, 0.0) + cost

    def get(self, session_id: str) -> float:
        return self._costs.get(session_id, 0.0)

    def check_budget(self, session_id: str, budget_cap: float) -> bool:
        return self._costs.get(session_id, 0.0) < budget_cap

# 사용: ray.get_actor("cost_accumulator") 로 싱글톤 접근
# 각 Actor에서: cost_actor.add.remote(session_id, cost)

# 방안 2: Ray Object Store (immutable, 더 빠름)
# 실행 완료 후 비용 합산 → 최종 업데이트 (실시간 예산 체크 불가)
```

**권장:** 방안 1 (Named Actor) - 실시간 예산 초과 감지(graceful degradation)가 현재 orchestrator의 핵심 기능이므로.

---

## 4. DAG 기반 의존성 처리 및 병렬 실행

### 4-A. depends_on 의존성 → 실행 레벨 분류

```python
# neos/workflow/ray_actors/dag_utils.py

from typing import List, Dict, Set, Tuple
from neos.workflow.recursive.models import RecursiveTaskNode


def build_execution_levels(subtasks: List[RecursiveTaskNode]) -> List[List[int]]:
    """
    subtasks를 의존성에 따라 실행 레벨로 분류.
    같은 레벨의 task는 병렬 실행 가능.

    예시:
        subtasks[0]: depends_on=[]    → Level 0 (독립)
        subtasks[1]: depends_on=[]    → Level 0 (독립)
        subtasks[2]: depends_on=[0,1] → Level 1 (0,1 완료 후)

    Returns:
        [[0, 1], [2]]  ← 각 레벨의 task 인덱스 목록
    """
    n = len(subtasks)
    levels: List[int] = [-1] * n

    def get_level(idx: int, visited: Set[int] = None) -> int:
        if visited is None:
            visited = set()
        if idx in visited:
            raise ValueError(f"Circular dependency detected at subtask index {idx}")
        if levels[idx] >= 0:
            return levels[idx]

        deps = subtasks[idx].metadata.get("depends_on", [])
        if not deps:
            levels[idx] = 0
            return 0

        visited.add(idx)
        max_dep_level = max(get_level(d, visited.copy()) for d in deps)
        levels[idx] = max_dep_level + 1
        return levels[idx]

    for i in range(n):
        get_level(i)

    # 레벨별 그룹화
    max_level = max(levels) if levels else 0
    return [[i for i, lv in enumerate(levels) if lv == l] for l in range(max_level + 1)]


def build_ray_dag(
    subtasks: List[RecursiveTaskNode],
    executor_pool,  # RayExecutorPool instance
    context: dict,
) -> Dict[int, "ray.ObjectRef"]:
    """
    subtasks의 depends_on 관계를 Ray ObjectRef 의존성 그래프로 변환.

    Returns:
        {task_index: ray.ObjectRef (미완료 future)}
    """
    futures: Dict[int, "ray.ObjectRef"] = {}

    execution_levels = build_execution_levels(subtasks)

    for level_indices in execution_levels:
        for idx in level_indices:
            task = subtasks[idx]
            deps = task.metadata.get("depends_on", [])

            # 의존 task의 결과를 prior_results에 주입
            # ⚠️ ray.get()은 asyncio event loop를 블로킹하므로 사용 금지.
            # build_ray_dag()는 동기 컨텍스트 전용이거나,
            # async 버전에서는 build_execution_levels() + asyncio.gather() 패턴을 사용해야 함.
            # 아래는 동기 컨텍스트(Ray Task 내부 등) 기준 예시:
            dep_results = {}
            for dep_idx in deps:
                dep_result = ray.get(futures[dep_idx])  # 동기 컨텍스트 전용
                dep_results[subtasks[dep_idx].task_id] = dep_result

            # 현재 레벨의 task 비동기 실행 (같은 레벨 = 병렬)
            enriched_context = {
                **context,
                "prior_results": {**context.get("prior_results", {}), **dep_results},
            }
            futures[idx] = executor_pool.execute.remote(task.to_dict(), enriched_context)

    return futures
```

### 4-B. 실행 흐름 다이어그램

```
쿼리: "AI 헬스케어 분석"
              │
              ▼
      RayPlannerActor.decompose()
              │
              ▼
    subtasks = [
      T0: "임상 AI 논문" (depends_on=[]),
      T1: "규제 현황"   (depends_on=[]),
      T2: "시장 분석"   (depends_on=[0,1])
    ]
              │
              ▼
    build_execution_levels(subtasks)
    → [[0, 1], [2]]
              │
    ┌─────────┴─────────────────────────┐
    │        Level 0 (병렬 실행)        │
    │                                   │
    │  T0.execute.remote() ──→ future_0 │
    │  T1.execute.remote() ──→ future_1 │  ← 동시 실행
    └─────────────────────────────────┬─┘
                                      │
              ┌───────────────────────┘
              │ ray.get([future_0, future_1])  ← 완료 대기
              │ results = [r0, r1]
              │
    ┌─────────▼─────────────────────────┐
    │        Level 1 (순차 실행)        │
    │                                   │
    │  context에 prior_results 주입:    │
    │  {T0.id: r0, T1.id: r1}          │
    │                                   │
    │  T2.execute.remote(ctx) ──→ f_2  │
    └─────────┬─────────────────────────┘
              │
              ▼
    ray.get(future_2) → 최종 결과
              │
              ▼
    RayAggregatorActor.aggregate([r0, r1, r2])
```

### 4-C. 기존 순차 코드와의 비교

```python
# 현재 (neos/workflow/recursive/orchestrator.py:_recursive_solve)
prior_results = {}
for subtask in subtasks:  # ← 모든 subtask 직렬 실행
    subtask_result = await self._recursive_solve(subtask, child_context, ...)
    prior_results[subtask.task_id] = subtask_result

# Ray DAG 적용 후
execution_levels = build_execution_levels(subtasks)
prior_results = {}

for level_indices in execution_levels:
    level_tasks = [subtasks[i] for i in level_indices]

    # 같은 레벨: 병렬 실행
    futures = [
        executor_pool.execute.remote(task.to_dict(), build_context(prior_results))
        for task in level_tasks
    ]

    level_results = await asyncio.gather(*[
        asyncio.wrap_future(fut.future()) for fut in futures
    ])

    for task, result in zip(level_tasks, level_results):
        prior_results[task.task_id] = result
```

---

## 5. ExecutorPool: HyperDeepResearchAgent 병렬화

### 5-A. 현재 싱글톤 구조의 문제

```python
# 현재: neos/workflow/hyper_deep/executor.py
class HyperDeepExecutor:
    def __init__(self):
        self._agent = None  # 싱글톤

    def _get_agent(self):
        if self._agent is None:
            self._agent = HyperDeepResearchAgent()  # 최초 1회만 생성
        return self._agent

    # 현재 코드는 순차 실행이므로 실제 충돌은 발생하지 않음
    # Ray로 병렬화하면 동시에 2개 subtask가 execute()를 호출하게 되어
    # 같은 _agent 인스턴스에 접근 → 내부 상태(report_id, sections_data) 충돌 발생
```

### 5-B. Ray ActorPool 기반 병렬 Executor

```python
# neos/workflow/ray_actors/executor_pool.py

import ray
from ray.util import ActorPool
from typing import Optional
from neos.agents.search_agents.hyper_deep_research.agent import HyperDeepResearchAgent
from neos.workflow.recursive.models import RecursiveTaskNode, TaskStatus


@ray.remote(num_cpus=0.5, num_gpus=0, max_concurrency=1)  # 인스턴스당 1개 요청
class HyperDeepWorkerActor:
    """
    HyperDeepResearchAgent를 래핑하는 Ray Actor.

    max_concurrency=1: 인스턴스당 하나의 요청만 처리 → 상태 충돌 방지
    각 Actor는 독립된 프로세스 → GIL 없음, 완전한 병렬성
    """
    def __init__(self):
        # 각 Actor 프로세스에서 독립적으로 에이전트 초기화
        self._agent = HyperDeepResearchAgent()

    async def execute(self, task_dict: dict, context: dict) -> dict:
        """
        Args:
            task_dict: RecursiveTaskNode.to_dict()
            context: 실행 컨텍스트

        Returns:
            {"result": str, "cost": float, "task_id": str}
        """
        task = RecursiveTaskNode.from_dict(task_dict)
        task.status = TaskStatus.IN_PROGRESS

        # 상태 초기화 (HyperDeepExecutor._reset_agent_state와 동일하게 모두 리셋)
        self._agent.current_report_id = None
        self._agent.sections_data = []
        self._agent.all_collected_sources = []
        self._agent.research_metadata = {
            "total_queries_executed": 0,
            "total_sources_collected": 0,
            "unique_domains": set(),
            "analysis_iterations_completed": 0,
            "critical_reviews_completed": 0,
            "multi_query_searches": 0,
            "criticism_feedbacks_generated": 0,
            "additional_research_triggered": 0,
            "api_rate_limit_hits": 0,
            "llm_calls": 0,
            "estimated_total_tokens": 0,
            "llm_calls_by_phase": {},
            "selected_skills": [],
            "selected_tools": [],
            "selection_reasoning": "",
        }

        try:
            agent_context = {
                "session_id": context.get("session_id", ""),
                "user_id": context.get("user_id", ""),
                # ⚠️ _stream_callback은 coroutine/closure이므로 Ray pickle 직렬화 불가.
                # context에서 제외하고 Worker 내부에서 스트리밍을 직접 처리하거나,
                # Ray Named Actor(StreamBridgeActor)를 별도로 두어 SSE를 우회 전달해야 함.
                # "_stream_callback": context.get("_stream_callback"),  # 제거
                "prior_results_summary": self._build_prior_summary(context),
            }

            output = await self._agent.execute(
                query=task.description,
                context=agent_context,
            )

            content = self._extract_content(output)
            task.result = content
            task.status = TaskStatus.COMPLETED

            return {
                "result": content,
                "cost": task.cost,
                "task_id": task.task_id,
                "status": "completed",
            }
        except Exception as e:
            task.status = TaskStatus.FAILED
            return {
                "result": f"[HDR Worker Error] {task.description[:50]}: {str(e)}",
                "cost": 0.0,
                "task_id": task.task_id,
                "status": "failed",
            }

    def _build_prior_summary(self, context: dict) -> str:
        prior = context.get("prior_results", {})
        if not prior:
            return ""
        parts = []
        for task_id, result in list(prior.items())[:2]:  # 최대 2개 요약
            parts.append(f"Prior research: {result[:200]}...")
        return "\n\n".join(parts)

    def _extract_content(self, output: dict) -> str:
        if not output.get("success"):
            return f"Research failed: {output.get('error', 'Unknown error')}"
        results = output.get("results", [])
        if not results:
            return "No results returned"
        first = results[0]
        if isinstance(first, dict):
            return first.get("content", "")
        elif hasattr(first, "content"):
            return first.content
        return str(first)


class RayExecutorPool:
    """
    HyperDeepWorkerActor 풀 관리자.

    pool_size는 HYPER_DEEP_MAX_TASKS_PER_LEVEL과 일치시키는 것을 권장.
    (3 workers → 3 leaf 노드 완전 병렬화)

    ⚠️ ActorPool.submit()은 None을 반환하므로 ObjectRef 방식으로 직접 관리.
    submit() + get_next() 패턴 또는 actors에 직접 remote() 호출.
    """
    def __init__(self, pool_size: int = 3):
        self._actors = [
            HyperDeepWorkerActor.remote()
            for _ in range(pool_size)
        ]
        self._pool = ActorPool(self._actors)
        self._pool_size = pool_size
        self._next_actor_idx = 0  # 라운드로빈 인덱스

    def submit(self, task_dict: dict, context: dict) -> "ray.ObjectRef":
        """
        비동기 실행 ObjectRef 반환.

        ActorPool.submit()은 None을 반환하므로 라운드로빈으로 Actor를 직접 선택.
        반환된 ObjectRef는 ray.get() 또는 asyncio.wrap_future().future()로 대기.
        """
        actor = self._actors[self._next_actor_idx % self._pool_size]
        self._next_actor_idx += 1
        return actor.execute.remote(task_dict, context)

    async def execute_all_parallel(
        self, tasks: list[dict], context: dict
    ) -> list[dict]:
        """의존성 없는 task 목록을 기존 풀의 Worker에 병렬 실행."""
        import asyncio
        # ✅ 새 Actor 생성 대신 풀의 기존 Actor 사용
        futures = [
            self._actors[i % self._pool_size].execute.remote(t, context)
            for i, t in enumerate(tasks)
        ]
        return await asyncio.gather(*[
            asyncio.wrap_future(f.future()) for f in futures
        ])

    def __del__(self):
        # Actor 정리
        for actor in self._actors:
            ray.kill(actor, no_restart=True)
```

### 5-C. 풀 크기 최적화 가이드

```
현재 설정: HYPER_DEEP_MAX_TASKS_PER_LEVEL=3, HYPER_DEEP_MAX_DEPTH=1
           → 최대 leaf 노드 수 = 3

권장 pool_size = max_tasks_per_level  (완전 병렬화)

리소스 추정 (HDR Worker 1개 기준):
  - CPU: ~0.5 core (I/O bound: Tavily API 대기 시간 많음)
  - 메모리: ~512MB (HyperDeepResearchAgent 초기화)
  - 네트워크: Tavily API x5 calls/request

pool_size=3 서버 요구사항:
  - CPU: 1.5 cores (추가)
  - 메모리: 1.5 GB (추가)
  - 네트워크 대역폭: Tavily API 동시 호출 허용 확인 필요
```

---

## 6. Sandbox 기반 격리된 코드 실행 API

### 6-A. 코드 실행 격리의 필요성

> **현재 HDR은 임의 코드를 실행하지 않는다.** `HyperDeepResearchAgent`는 Tavily API 검색 + LLM 합성 파이프라인만 수행한다. 이 섹션은 HDR 기능을 확장할 때(LLM이 제안하는 분석 코드를 실제로 실행하는 기능 등)를 대비한 선제적 설계다.

HDR 기능 확장 시 다음과 같은 코드 실행이 추가될 수 있다:
- 수집된 데이터의 통계 분석 (pandas, numpy)
- API 응답 데이터 파싱 (json, csv)
- 계산 검증 (수식, 알고리즘 실행)
- 데이터 시각화 코드 생성 후 실행

**위험:** LLM이 생성한 코드에는 악의적 페이로드, 무한 루프, 파일시스템 접근, 네트워크 탈취 등이 포함될 수 있다.

### 6-B. 샌드박싱 방안 비교

#### 방안 1: Ray + RestrictedPython (경량)

```python
# neos/workflow/ray_actors/sandbox_executor.py

import ray
from RestrictedPython import compile_restricted, safe_globals
from RestrictedPython.Guards import safe_builtins, guarded_iter_unpack_sequence

@ray.remote(
    num_cpus=0.5,          # RestrictedPython은 Python 코드 실행 → CPU bound
    max_concurrency=4,     # CPU bound이므로 동시성을 낮게 유지 (코어 수에 비례)
    runtime_env={
        "pip": ["RestrictedPython==7.4"],
    }
)
class RestrictedPythonExecutor:
    """
    RestrictedPython 기반 AST 레벨 코드 실행 제한.

    허용: 수학 연산, 문자열 처리, 기본 자료구조
    차단: import (화이트리스트 외), open(), exec(), eval(), __import__
    """

    ALLOWED_IMPORTS = frozenset([
        "math", "statistics", "json", "re", "datetime",
        "collections", "itertools", "functools",
    ])

    async def execute_code(  # DockerSandboxExecutor와 인터페이스 일치
        self,
        code: str,
        input_data: dict = None,
        timeout_sec: int = 10,
    ) -> dict:
        """
        Returns:
            {"success": bool, "output": str, "error": str | None}
        """
        import signal

        def timeout_handler(signum, frame):
            raise TimeoutError(f"Code execution exceeded {timeout_sec}s")

        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(timeout_sec)

        try:
            # 화이트리스트 import 제한
            restricted_globals = {
                **safe_globals,
                "__builtins__": {
                    **safe_builtins,
                    "__import__": self._restricted_import,
                },
                "_getiter_": iter,
                "_getattr_": getattr,
                "_unpack_sequence_": guarded_iter_unpack_sequence,
            }

            # 입력 데이터를 globals에 주입
            if input_data:
                restricted_globals.update(input_data)

            local_vars = {}
            exec(compile_restricted(code), restricted_globals, local_vars)

            output = local_vars.get("result", local_vars.get("output", ""))
            return {"success": True, "output": str(output), "error": None}

        except SyntaxError as e:
            return {"success": False, "output": "", "error": f"SyntaxError: {e}"}
        except TimeoutError as e:
            return {"success": False, "output": "", "error": str(e)}
        except Exception as e:
            return {"success": False, "output": "", "error": f"RuntimeError: {e}"}
        finally:
            signal.alarm(0)

    def _restricted_import(self, name, *args, **kwargs):
        if name not in self.ALLOWED_IMPORTS:
            raise ImportError(f"Import '{name}' is not allowed in sandbox")
        return __import__(name, *args, **kwargs)
```

#### 방안 2: Ray Actor + Docker 컨테이너 (고격리)

```python
@ray.remote(
    runtime_env={
        "container": {
            "image": "python:3.12-slim",
            "worker_path": "/usr/local/lib/python3.12/site-packages/ray/workers/default_worker.py",
        }
    }
)
class DockerSandboxExecutor:
    """
    Ray의 container runtime_env로 Docker 내 격리 실행.

    ⚠️ Ray container runtime_env는 기본적으로 네트워크 격리를 제공하지 않음.
    완전한 네트워크 격리는 Docker 레벨에서 별도 설정 필요 (--network none 등).
    파일시스템: 컨테이너 종료 시 상태 소멸 (영속성 없음)

    요구사항:
    - Ray 2.8+
    - Docker 설치 및 Ray 워커가 Docker 소켓 접근 가능
    """

    async def execute_code(
        self,
        code: str,
        timeout_sec: int = 30,
    ) -> dict:
        # Docker 컨테이너 자체가 격리 환경
        # 추가 제한 없이도 컨테이너 종료 시 모든 상태 소멸
        import subprocess
        try:
            result = subprocess.run(
                ["python", "-c", code],
                capture_output=True,
                text=True,
                timeout=timeout_sec,
            )
            return {
                "success": result.returncode == 0,
                "output": result.stdout,
                "error": result.stderr if result.returncode != 0 else None,
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "output": "", "error": f"Execution timed out after {timeout_sec}s"}
```

#### 방안 3: Pyodide (WASM) - 추천 (장기)

```python
# 개념 설계 (현재 Ray + Pyodide 네이티브 지원 없음, 별도 HTTP 서비스로 구성)

# SandboxService (FastAPI + Pyodide)
# /execute endpoint → Pyodide WebAssembly Python 실행
# 시스템 콜 불가 → 강력한 격리
# Ray에서 HTTP 호출로 결과 수신

@ray.remote
class PyodideSandboxExecutor:
    """Pyodide WASM 기반 격리 실행 프록시."""

    def __init__(self, sandbox_service_url: str):
        self._url = sandbox_service_url  # http://sandbox-svc:8080

    async def execute_code(self, code: str, timeout_sec: int = 30) -> dict:
        import httpx
        async with httpx.AsyncClient(timeout=timeout_sec) as client:
            resp = await client.post(
                f"{self._url}/execute",
                json={"code": code, "timeout": timeout_sec},
            )
            return resp.json()
```

### 6-C. 권장 샌드박싱 전략

```
개발/스테이징 환경:
  RestrictedPython (방안 1)
  - 빠른 초기화, 의존성 최소
  - 단순 계산·파싱에 충분

프로덕션 환경:
  Docker container runtime_env (방안 2)
  - Ray 2.8+에서 공식 지원
  - 네트워크 격리 + 파일시스템 격리
  - 오버헤드: 컨테이너 시작 ~1-3초 (콜드 스타트)
  - 워커 재사용으로 웜 스타트 후 오버헤드 최소화

장기 계획:
  Pyodide WASM (방안 3)
  - 완전한 격리 (시스템 콜 불가)
  - 빠른 실행 (~100ms)
  - 별도 서비스 운영 필요
```

### 6-D. SandboxedCodeExecutor 통합 API

```python
# neos/workflow/ray_actors/sandboxed_executor.py

from dataclasses import dataclass
from typing import List, Optional
import ray


@dataclass
class CodeExecutionResult:
    success: bool
    output: str
    error: Optional[str] = None
    execution_time_ms: int = 0
    sandbox_type: str = "restricted_python"


class SandboxedCodeExecutor:
    """
    HDR 파이프라인에서 코드 실행이 필요할 때 사용하는 통합 인터페이스.

    사용 예:
        executor = SandboxedCodeExecutor(sandbox_type="restricted")
        result = await executor.execute(
            code="result = sum([1, 2, 3])",
            input_data={"values": [1, 2, 3]},
        )
    """

    def __init__(self, sandbox_type: str = "restricted"):
        if sandbox_type == "restricted":
            self._actor = RestrictedPythonExecutor.remote()
        elif sandbox_type == "docker":
            self._actor = DockerSandboxExecutor.remote()
        else:
            raise ValueError(f"Unknown sandbox type: {sandbox_type}")
        self._sandbox_type = sandbox_type

    async def execute(
        self,
        code: str,
        input_data: dict = None,
        timeout_sec: int = 30,
        allowed_imports: List[str] = None,  # 현재 미구현: RestrictedPythonExecutor에 전달 필요
    ) -> CodeExecutionResult:
        import time
        start = time.monotonic()

        # TODO: allowed_imports를 actor에 전달하는 인터페이스 추가 필요
        result = await self._actor.execute_code.remote(
            code, input_data or {}, timeout_sec
        )

        elapsed_ms = int((time.monotonic() - start) * 1000)

        return CodeExecutionResult(
            success=result["success"],
            output=result["output"],
            error=result.get("error"),
            execution_time_ms=elapsed_ms,
            sandbox_type=self._sandbox_type,
        )
```

---

## 7. NEOS 기존 시스템 통합 전략

### 7-A. DistributedRecursiveOrchestrator

기존 `RecursiveOrchestrator`를 상속하여 Ray 적용 여부를 설정값으로 제어.

```python
# neos/workflow/recursive/distributed_orchestrator.py

import ray
from typing import Dict, Any, List, Set, Optional
from neos.workflow.recursive.orchestrator import RecursiveOrchestrator
from neos.workflow.recursive.models import RecursiveTaskNode, TaskAtomicity, TaskStatus
from neos.workflow.ray_actors.dag_utils import build_execution_levels
from neos.workflow.ray_actors.executor_pool import RayExecutorPool
from neos.config.settings import settings

import logging
logger = logging.getLogger(__name__)


class DistributedRecursiveOrchestrator(RecursiveOrchestrator):
    """
    Ray 기반 분산 실행을 지원하는 RecursiveOrchestrator 확장.

    RAY_ENABLED=False 시 부모 클래스(순차 실행) 동작 유지.
    RAY_ENABLED=True 시 sibling subtask를 DAG 의존성에 따라 병렬 실행.
    """

    def __init__(
        self,
        agents=None,
        executor=None,
        max_depth=None,
        budget_cap=None,
        max_tasks_per_level=None,
        ray_enabled: bool = None,
        ray_pool_size: int = None,
    ):
        super().__init__(
            agents=agents,
            executor=executor,
            max_depth=max_depth,
            budget_cap=budget_cap,
            max_tasks_per_level=max_tasks_per_level,
        )

        self._ray_enabled = (
            ray_enabled
            if ray_enabled is not None
            else getattr(settings, "RAY_ENABLED", False)
        )

        self._ray_pool: Optional[RayExecutorPool] = None

        if self._ray_enabled:
            if not ray.is_initialized():
                ray.init(ignore_reinit_error=True)
            pool_size = ray_pool_size or max_tasks_per_level or 3
            self._ray_pool = RayExecutorPool(pool_size=pool_size)
            logger.info(f"[DistributedOrchestrator] Ray initialized, pool_size={pool_size}")

    async def _recursive_solve(
        self,
        task: RecursiveTaskNode,
        context: Dict,
        seen_hashes: Set[str],
        replan_count: int = 0,
    ) -> str:
        """RAY_ENABLED 시 sibling subtask를 DAG 병렬 실행으로 교체."""

        if not self._ray_enabled:
            # 기존 순차 실행 (부모 클래스 동작)
            return await super()._recursive_solve(task, context, seen_hashes, replan_count)

        # ── Atomicity 판별 ──
        atomicity = await self._atomizer.assess(task, context)
        task.atomicity = atomicity

        if atomicity == TaskAtomicity.ATOMIC:
            # Leaf 실행: Ray Pool 사용
            return await self._execute_via_ray(task, context)

        # ── Planner 분해 ──
        subtasks = await self._planner.decompose(task, context)
        task.children = subtasks

        # ── DAG 기반 병렬 실행 ──
        execution_levels = build_execution_levels(subtasks)
        prior_results: Dict[str, str] = {}

        for level_indices in execution_levels:
            level_tasks = [subtasks[i] for i in level_indices]

            level_context = {
                **context,
                "prior_results": {**context.get("prior_results", {}), **prior_results},
                "prior_task_descriptions": {
                    t.task_id: t.description for t in subtasks
                    if t.task_id in prior_results
                },
            }

            if len(level_tasks) == 1:
                # 단일 task: 순차 실행 (Ray 오버헤드 불필요)
                result = await self._recursive_solve(
                    level_tasks[0], level_context, seen_hashes
                )
                prior_results[level_tasks[0].task_id] = result
            else:
                # 복수 독립 task: Ray 병렬 실행
                level_results = await self._execute_level_parallel(
                    level_tasks, level_context, seen_hashes
                )
                prior_results.update(level_results)

        # ── Aggregation & Verification ──
        aggregated = await self._aggregator.aggregate(task, subtasks, context)
        task.result = aggregated

        verification = await self._verifier.verify(task, aggregated, context)

        # orchestrator.py:236 조건 그대로 유지: depth 제한 포함
        if not verification["satisfied"] and replan_count < 1 and task.depth < self._max_depth - 1:
            replan_result = await self._replan_and_solve(
                task, aggregated, verification["gaps"], context, seen_hashes
            )
            if replan_result:
                return replan_result

        task.status = TaskStatus.COMPLETED
        return aggregated

    async def _execute_via_ray(self, task: RecursiveTaskNode, context: dict) -> str:
        """단일 leaf task를 Ray Worker로 실행."""
        import asyncio
        future = self._ray_pool.submit(task.to_dict(), context)
        result_dict = await asyncio.wrap_future(future.future())

        task.cost += result_dict.get("cost", 0.0)
        cost_acc = context.get("_cost_accumulator")
        if cost_acc:
            cost_acc[0] += task.cost

        content = result_dict.get("result", "")
        task.result = content
        task.status = TaskStatus.COMPLETED
        return content

    async def _execute_level_parallel(
        self,
        tasks: List[RecursiveTaskNode],
        context: dict,
        seen_hashes: Set[str],
    ) -> Dict[str, str]:
        """같은 레벨의 독립 task들을 Ray로 병렬 실행."""
        import asyncio

        futures = [
            self._ray_pool.submit(task.to_dict(), context)
            for task in tasks
        ]

        # 모든 future 동시 대기
        result_dicts = await asyncio.gather(*[
            asyncio.wrap_future(f.future()) for f in futures
        ])

        results = {}
        for task, result_dict in zip(tasks, result_dicts):
            content = result_dict.get("result", "")
            task.result = content
            task.status = TaskStatus(result_dict.get("status", "completed"))
            results[task.task_id] = content

        return results
```

### 7-B. graph.py 통합 (최소 변경)

```python
# neos/workflow/graph.py 수정 포인트 (75-99 근방)

# 기존:
if settings.HYPER_DEEP_AGENT_ENABLED:
    from neos.workflow.recursive.orchestrator import RecursiveOrchestrator
    from neos.workflow.hyper_deep.executor import HyperDeepExecutor
    _hd_executor = HyperDeepExecutor()
    self.hyper_deep_orchestrator = RecursiveOrchestrator(
        agents=self.agents,
        executor=_hd_executor,
        max_depth=settings.HYPER_DEEP_MAX_DEPTH,
        budget_cap=settings.HYPER_DEEP_BUDGET_CAP,
        max_tasks_per_level=settings.HYPER_DEEP_MAX_TASKS_PER_LEVEL,
    )

# 변경 후:
if settings.HYPER_DEEP_AGENT_ENABLED:
    if getattr(settings, "RAY_ENABLED", False):
        from neos.workflow.recursive.distributed_orchestrator import (
            DistributedRecursiveOrchestrator
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
        from neos.workflow.recursive.orchestrator import RecursiveOrchestrator
        from neos.workflow.hyper_deep.executor import HyperDeepExecutor
        _hd_executor = HyperDeepExecutor()
        self.hyper_deep_orchestrator = RecursiveOrchestrator(
            agents=self.agents,
            executor=_hd_executor,
            max_depth=settings.HYPER_DEEP_MAX_DEPTH,
            budget_cap=settings.HYPER_DEEP_BUDGET_CAP,
            max_tasks_per_level=settings.HYPER_DEEP_MAX_TASKS_PER_LEVEL,
        )
```

### 7-C. 신규 설정 (settings.py 추가)

```python
# neos/config/settings.py에 추가 예정

# ── Ray 분산 처리 ──
RAY_ENABLED: bool = False                  # env: RAY_ENABLED
RAY_ADDRESS: str = "auto"                  # env: RAY_ADDRESS (클러스터 주소)
RAY_NUM_CPUS: Optional[float] = None       # env: RAY_NUM_CPUS (None=자동)
RAY_NUM_GPUS: Optional[float] = None       # env: RAY_NUM_GPUS
RAY_OBJECT_STORE_MEMORY: int = 2_000_000_000  # 2GB env: RAY_OBJECT_STORE_MEMORY

# ── Sandbox 코드 실행 ──
SANDBOX_ENABLED: bool = False              # env: SANDBOX_ENABLED
SANDBOX_TYPE: str = "restricted"           # env: SANDBOX_TYPE (restricted|docker|pyodide)
SANDBOX_TIMEOUT_SEC: int = 30              # env: SANDBOX_TIMEOUT_SEC
```

---

## 8. 성능 트레이드오프 분석

### 8-A. 실행 시간 비교

```
시나리오: HYPER_DEEP_MAX_TASKS_PER_LEVEL=3, 각 leaf 실행 시간 T_leaf=120s

현재 (순차):
  총 시간 = T_planner + T_leaf×3 + T_aggregator
          = 5s + 360s + 10s
          ≈ 375s (~6.25분)

Ray 병렬 (완전 독립 3개 subtask):
  총 시간 = T_planner + max(T_leaf×3 동시) + T_aggregator
          = 5s + 120s + 10s + Ray 오버헤드 (~5s)
          ≈ 140s (~2.3분)

  속도 향상: 375s / 140s ≈ 2.7배

Ray 병렬 (의존성 있는 경우: 2개 독립 + 1개 의존):
  총 시간 = T_planner + max(T_leaf×2 동시) + T_leaf(순차) + T_aggregator
          = 5s + 120s + 120s + 10s + 5s
          ≈ 260s (~4.3분)

  속도 향상: 375s / 260s ≈ 1.4배
```

### 8-B. 리소스 비용 비교

| 항목 | 순차 실행 | Ray 병렬 (pool_size=3) |
|------|----------|----------------------|
| **실행 시간** | T_leaf × N | max(T_leaf_i) |
| **메모리** | ~512MB | ~1.5GB (3 workers) |
| **CPU** | ~0.5 core | ~1.5 cores |
| **LLM API 비용** | 동일 | 동일 (호출 수 동일) |
| **Ray 오버헤드** | 없음 | ~5s 초기화 + 직렬화 |
| **장애 격리** | 없음 | Actor 재시작 자동 |
| **예산 초과 감지** | 실시간 | Actor 간 통신 필요 |

### 8-C. 적합한 사용 케이스

```
Ray 병렬화가 효과적인 경우:
  ✅ subtask 실행 시간이 길 때 (>30s) → 오버헤드 무시 가능
  ✅ subtask들이 서로 독립적일 때 (depends_on=[])
  ✅ 다수의 쿼리를 동시에 처리할 때 (multi-user 환경)
  ✅ 서버에 충분한 메모리가 있을 때 (≥4GB 여유)

Ray 병렬화가 불리한 경우:
  ❌ subtask 실행 시간이 짧을 때 (<5s) → 오버헤드 > 이득
  ❌ 모든 subtask가 순차 의존성일 때
  ❌ 메모리 제약이 심할 때
  ❌ 단일 쿼리 처리 전용 서버 (Ray 클러스터 불필요)
```

---

## 9. 구현 로드맵

### Phase 1: Ray 기반 Executor Pool (핵심 병렬화)

**목표:** HyperDeepResearchAgent의 병렬 실행 가능화

**신규 파일:**
```
neos/workflow/ray_actors/__init__.py
neos/workflow/ray_actors/executor_pool.py    ← HyperDeepWorkerActor, RayExecutorPool
neos/workflow/ray_actors/dag_utils.py        ← build_execution_levels
```

**수정 파일:**
```
neos/config/settings.py           ← RAY_* 설정 추가
neos/workflow/recursive/
  distributed_orchestrator.py    ← 신규 (RecursiveOrchestrator 확장)
neos/workflow/graph.py            ← RAY_ENABLED 분기 추가
.env.template                     ← RAY_* 환경변수 예시
```

**검증:**
```python
# 단위 테스트: DAG 의존성 레벨 계산
subtasks = [
    make_task(depends_on=[]),    # 0
    make_task(depends_on=[]),    # 1
    make_task(depends_on=[0,1]), # 2
]
assert build_execution_levels(subtasks) == [[0, 1], [2]]

# 통합 테스트: 3개 leaf 병렬 실행 시간 측정
# 기대: 순차(360s) → 병렬(~130s)
```

---

### Phase 2: Stateless Actor 공유 (오버헤드 최소화)

**목표:** Atomizer, Planner, Aggregator, Verifier를 Named Actor로 공유

**신규 파일:**
```
neos/workflow/ray_actors/stateless_actors.py  ← 4개 Actor 클래스
neos/workflow/ray_actors/cost_accumulator.py  ← CostAccumulatorActor
```

**수정 파일:**
```
neos/workflow/recursive/distributed_orchestrator.py  ← Named Actor 사용으로 전환
```

**검증:**
```python
# Named Actor 싱글톤 확인
atomizer = ray.get_actor("neos_atomizer")
assert atomizer is ray.get_actor("neos_atomizer")  # 동일 인스턴스
```

---

### Phase 3: Sandbox 코드 실행 API

**목표:** 격리된 코드 실행 인터페이스 제공

**신규 파일:**
```
neos/workflow/ray_actors/sandbox_executor.py   ← RestrictedPythonExecutor
neos/workflow/ray_actors/sandboxed_executor.py ← SandboxedCodeExecutor (통합 API)
```

**수정 파일:**
```
neos/config/settings.py  ← SANDBOX_* 설정 추가
requirements.txt         ← RestrictedPython 추가
```

**검증:**
```python
executor = SandboxedCodeExecutor(sandbox_type="restricted")

# 허용된 코드
result = await executor.execute("result = sum([1,2,3])")
assert result.success and result.output == "6"

# 차단된 코드
result = await executor.execute("import os; os.system('rm -rf /')")
assert not result.success  # ImportError
```

---

### Phase 4: 관찰가능성 통합

**목표:** Ray 메트릭을 기존 NEOS 모니터링에 연동

**수정 파일:**
```
neos/observability/metrics.py  ← Ray 메트릭 익스포터 추가
config/prometheus.yml           ← Ray Dashboard metrics 수집 설정
```

**Ray 메트릭 항목:**
```
ray_executor_pool_utilization   ← 풀 사용률
ray_task_execution_duration_ms  ← task 실행 시간
ray_parallel_speedup_ratio      ← 병렬화 속도 향상 비율
ray_actor_restarts_total        ← Actor 재시작 횟수 (장애 지표)
```

---

## 10. 참고: 핵심 파일 경로

| 파일 | 역할 |
|------|------|
| [neos/workflow/recursive/orchestrator.py](../neos/workflow/recursive/orchestrator.py) | 순차 실행 로직 (`_recursive_solve`) |
| [neos/workflow/recursive/models.py](../neos/workflow/recursive/models.py) | `RecursiveTaskNode`, `metadata["depends_on"]` |
| [neos/workflow/recursive/planner.py](../neos/workflow/recursive/planner.py) | `depends_on` 필드 생성 (line 240) |
| [neos/workflow/hyper_deep/executor.py](../neos/workflow/hyper_deep/executor.py) | 싱글톤 HyperDeepExecutor |
| [neos/workflow/graph.py](../neos/workflow/graph.py) | `hyper_deep_orchestrator` 초기화 (line 75-99) |
| [neos/config/settings.py](../neos/config/settings.py) | `HYPER_DEEP_*` 설정 (line 632-636) |
| [neos/agents/search_agents/hyper_deep_research/agent.py](../neos/agents/search_agents/hyper_deep_research/agent.py) | HDR 핵심 에이전트 |

---

*작성일: 2026-03-17*
*관련 문서: [RECURSIVE_AGENT_PLAN.md](RECURSIVE_AGENT_PLAN.md), [RECURSIVE_AGENT_FOR_HDR.md](RECURSIVE_AGENT_FOR_HDR.md)*
