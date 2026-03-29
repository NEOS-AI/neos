# Ray 기반 HDR 분산 처리 코드 리뷰

> 설계 문서: [docs/RAY_BASED_HDR.md](./RAY_BASED_HDR.md)
> 구현 문서: [docs/RAY_HDR.md](./RAY_HDR.md)
> 리뷰 일자: 2026-03-19

---

## 검토 대상 파일

| 파일 | 역할 |
|------|------|
| `neos/workflow/ray_actors/dag_utils.py` | depends_on DAG → 레벨 그룹화 |
| `neos/workflow/ray_actors/executor_pool.py` | HyperDeepWorkerActor, RayExecutorPool |
| `neos/workflow/ray_actors/cost_accumulator.py` | CostAccumulatorActor Named Actor |
| `neos/workflow/ray_actors/stateless_actors.py` | Atomizer/Planner/Aggregator/Verifier Named Actors |
| `neos/workflow/ray_actors/sandbox_executor.py` | RestrictedPythonExecutor |
| `neos/workflow/ray_actors/sandboxed_executor.py` | SandboxedCodeExecutor 통합 API |
| `neos/workflow/recursive/distributed_orchestrator.py` | Ray 병렬 실행 오케스트레이터 |
| `neos/main.py` (Ray 관련 섹션) | Ray init + Named Actor 초기화 |
| `neos/observability/metrics.py` (Ray 메트릭 섹션) | Ray Prometheus 메트릭 정의 |

---

## 🔴 Critical Issues (즉시 수정 필요)

### 1. Phase 2 Named Actors 완전 미연결 (Dead Code)

**파일:** `neos/workflow/ray_actors/stateless_actors.py`, `neos/main.py:139-148`

`main.py` lifespan에서 `create_all_named_actors()`를 통해 Atomizer/Planner/Aggregator/Verifier Named Actor를 생성하지만, `DistributedRecursiveOrchestrator`는 이들을 **전혀 사용하지 않는다.** 오케스트레이터는 부모 클래스 `RecursiveOrchestrator.__init__()`이 생성한 로컬 인스턴스(`self._atomizer`, `self._planner`, ...)를 그대로 사용한다.

```python
# distributed_orchestrator.py - _recursive_solve() 내부
atomicity = await self._atomizer.assess(task, context)   # ← 로컬 인스턴스 (Ray Actor X)
subtasks = await self._planner.decompose(task, context)  # ← 로컬 인스턴스 (Ray Actor X)
aggregated = await self._aggregator.aggregate(...)        # ← 로컬 인스턴스 (Ray Actor X)
```

**영향:**
- Phase 2 전체(Named Actor 4개 + `create_all_named_actors()`)가 메모리만 차지하는 dead code
- `RAY_HDR.md` 4장 문서 내용과 실제 동작이 불일치
- Atomizer/Planner가 메인 프로세스에서 실행되므로 Phase 2의 메모리 절약 효과 없음

**수정 방향:** `DistributedRecursiveOrchestrator.__init__()`에서 Named Actor 핸들을 가져와 `self._atomizer`, `self._planner` 등을 Named Actor 래퍼로 교체하거나, 반대로 Phase 2 Named Actors를 제거하고 현재 로컬 실행 방식을 유지하는 방향 중 하나를 선택해야 한다.

---

### 2. Ray 메트릭 — 정의만 있고 기록 코드 없음

**파일:** `neos/observability/metrics.py:276-311`

`metrics.py`에 5개 Ray 메트릭이 정의되어 있지만, `executor_pool.py`와 `distributed_orchestrator.py` 어디에도 `.set()` / `.observe()` / `.inc()` 호출이 없다. Prometheus에서 이 메트릭들은 항상 초기값(0)을 반환한다.

```python
# metrics.py에 정의된 메트릭 (정의만 존재, 기록 코드 없음)
self.ray_pool_utilization         # Gauge — 기록 없음
self.ray_task_duration_seconds    # Histogram — 기록 없음
self.ray_parallel_speedup_ratio   # Gauge — 기록 없음
self.ray_actor_restarts_total     # Counter — 기록 없음
self.ray_level_tasks_parallel     # Histogram — 기록 없음
```

**영향:** Grafana 대시보드에서 Ray 관련 지표를 모니터링할 수 없음. 병렬화 효과를 정량적으로 측정 불가.

**수정 위치:**
- `executor_pool.py`의 `execute_all_parallel()` / `submit()` 내부 → `ray_task_duration_seconds`, `ray_level_tasks_parallel` 기록
- `distributed_orchestrator.py`의 `_execute_level_parallel()` → `ray_pool_utilization`, `ray_parallel_speedup_ratio` 기록

---

### 3. `warmup()` 미호출 — 콜드 스타트 실패 가능

**파일:** `neos/main.py:125-152`

`HyperDeepResearchAgent.__init__()`이 무거우므로(TavilyClient + 6개 sub-agent 초기화 ~5-15초) 서버 시작 직후 Actor가 준비되기 전에 첫 요청이 도착하면 실행이 지연되거나 실패할 수 있다.

`RAY_HDR.md:709`에서 `warmup()` 호출을 권장하지만 실제 `main.py` lifespan에 구현되지 않았다.

```python
# RAY_HDR.md 권장 코드 (main.py에 미구현)
if settings.RAY_ENABLED and isinstance(wf.hyper_deep_orchestrator, DistributedRecursiveOrchestrator):
    await wf.hyper_deep_orchestrator.warmup()
```

**영향:** 서버 시작 후 첫 HDR 요청의 응답 시간이 예측 불가능하게 길어지거나, Actor 초기화 완료 전 타임아웃 발생 가능.

---

## 🟠 Medium Issues (개선 필요)

### 4. `_replan_and_solve()` — 재계획 subtask 순차 실행 유지

**파일:** `neos/workflow/recursive/orchestrator.py:252-286`

`DistributedRecursiveOrchestrator._recursive_solve()`에서 검증 실패 시 부모의 `_replan_and_solve()`를 그대로 상속 호출한다. 재계획 subtask들이 `_recursive_solve()`(오버라이드됨)를 통해 Ray 실행되지만, 바깥 루프 자체는 `for replan_task in replan_tasks`로 순차다.

```python
# orchestrator.py:278-280 (상속됨, 오버라이드 없음)
for replan_task in replan_tasks:
    result = await self._recursive_solve(replan_task, context, seen_hashes, replan_count=1)
```

**영향:** 독립적인 재계획 subtask들이 병렬화되지 않아 재계획 시 속도 향상 효과 없음.

---

### 5. `_graceful_degrade()` — `RecursiveExecutor` fallback으로 품질 저하

**파일:** `neos/workflow/recursive/orchestrator.py:288-294`

비용 한도 초과 시 `_graceful_degrade()`가 `self._executor.execute()`를 호출한다. `DistributedRecursiveOrchestrator` 생성 시 `executor=None`을 전달하므로(graph.py 참조) 기본 `RecursiveExecutor`가 사용된다.

```python
# graph.py:91-98 — executor 파라미터 없이 생성
self.hyper_deep_orchestrator = DistributedRecursiveOrchestrator(
    agents=self.agents,
    max_depth=settings.HYPER_DEEP_MAX_DEPTH,
    # executor 미지정 → RecursiveExecutor (기본 LLM 직접 호출)
)
```

**영향:** 비용 한도 초과 시 HyperDeep 품질 대신 기본 LLM 응답으로 대체되며, 이 동작이 명시적으로 문서화되지 않음.

---

### 6. `asyncio.get_event_loop()` deprecated 사용

**파일:** `neos/workflow/ray_actors/sandbox_executor.py:97`

```python
async def execute_code(self, ...):
    loop = asyncio.get_event_loop()  # ← deprecated (Python 3.10+)
    result = await asyncio.wait_for(
        loop.run_in_executor(None, self._run_restricted, code, input_data or {}),
        timeout=timeout_sec,
    )
```

`async def` 내부이므로 이미 실행 중인 event loop가 보장된다. `asyncio.get_running_loop()`로 교체해야 한다.

**영향:** Python 3.12에서 `DeprecationWarning` 발생. 향후 버전에서 제거될 수 있음.

---

### 7. `warmup()` 에서 `assert` 사용

**파일:** `neos/workflow/ray_actors/executor_pool.py:202`

```python
assert all(results), "일부 Worker Actor warmup 실패"
```

Python `-O` (최적화) 모드에서 `assert` 문은 비활성화된다. 프로덕션 환경에서 Worker warmup 실패가 무음으로 통과될 수 있다.

**수정:** `RuntimeError`로 교체.

```python
if not all(results):
    raise RuntimeError("일부 Worker Actor warmup 실패")
```

---

### 8. `RayExecutorPool.__del__()` — 인터프리터 종료 시 안전성 문제

**파일:** `neos/workflow/ray_actors/executor_pool.py:237-243`

```python
def __del__(self):
    for actor in self._actors:
        try:
            ray.kill(actor, no_restart=True)
        except Exception:
            pass
```

Python 인터프리터 종료 시 `__del__`이 호출될 때 Ray가 이미 `ray.shutdown()`된 상태일 수 있다. `except Exception: pass`로 억제되지만, `ray.kill()` 호출 자체가 불필요하다. Ray는 클러스터 종료 시 Actor를 자동으로 정리하므로 명시적 kill이 필요 없다.

---

### 9. `dag_utils.py` — 범위 외 인덱스 미검증

**파일:** `neos/workflow/ray_actors/dag_utils.py:56-58`

```python
deps_raw = subtasks[idx].metadata.get("depends_on", [])
deps = [int(d) for d in deps_raw]
```

순환 의존성은 `visiting` 집합으로 감지하지만, LLM이 `depends_on`에 범위를 벗어난 인덱스(예: subtasks 길이 이상)를 반환하면 `_get_level(d, visiting)`에서 `IndexError`가 발생한다.

**수정 위치:** `int(d)` 변환 후 `0 <= d < n` 검증 추가.

```python
deps = [int(d) for d in deps_raw]
# LLM이 범위 외 인덱스를 반환하는 경우 무시
deps = [d for d in deps if 0 <= d < n and d != idx]
```

---

### 10. `_reset_agent_state()` — 하드코딩으로 취약한 설계

**파일:** `neos/workflow/ray_actors/executor_pool.py:42-67`

`HyperDeepResearchAgent`의 내부 속성명과 `research_metadata` 딕셔너리 키 목록을 하드코딩으로 초기화한다.

```python
self._agent.research_metadata = {
    "total_queries_executed": 0,
    "total_sources_collected": 0,
    "unique_domains": set(),
    # ... 13개 키 하드코딩 ...
}
```

`HyperDeepResearchAgent`에 새 메타데이터 필드를 추가하면 `_reset_agent_state()`와 동기화가 깨지며, 이전 실행의 잔류 상태가 다음 실행에 혼입된다.

**수정 방향:** `HyperDeepResearchAgent`에 `reset()` 메서드를 추가하고 Actor에서 호출.

---

## 🟡 Minor Issues (코드 품질)

### 11. `execute_all_parallel()` — `_next_idx` 미갱신으로 라운드로빈 불일치

**파일:** `neos/workflow/ray_actors/executor_pool.py:229-235`

`execute_all_parallel()`은 `i % self._pool_size`로 Actor를 선택하지만 `self._next_idx`를 갱신하지 않는다. `submit()`과 혼용 시 라운드로빈 균형이 깨진다. (현재 코드에서 두 메서드를 동시에 호출하지 않으므로 실질적 버그는 아님)

### 12. `CostAccumulatorActor._costs` — TTL 없는 무한 성장

**파일:** `neos/workflow/ray_actors/cost_accumulator.py:40`

세션 종료 시 `reset(session_id)`를 명시적으로 호출해야만 정리된다. 미호출 시 장기 운영에서 `_costs` 딕셔너리가 모든 과거 세션 ID를 메모리에 계속 유지한다.

### 13. `child_context` 레벨 루프 하단 재할당 중복

**파일:** `neos/workflow/recursive/distributed_orchestrator.py:211-215`

```python
child_context = {
    **child_context,
    "prior_results": prior_results,          # 이미 동일 dict 참조
    "prior_task_descriptions": prior_task_descriptions,  # 이미 동일 dict 참조
}
```

`prior_results`와 `prior_task_descriptions`는 가변 dict이므로, `child_context`가 이미 동일 객체 참조를 보유한다. 재할당이 불필요하다.

### 14. `SandboxedCodeExecutor.execute()` — 미구현 파라미터 노출

**파일:** `neos/workflow/ray_actors/sandboxed_executor.py:85`

```python
allowed_imports: Optional[List[str]] = None,  # 미래 확장용
```

실제로 사용되지 않는 파라미터가 공개 시그니처에 노출되어 있다. 호출자가 이 파라미터를 전달해도 효과가 없음.

### 15. `CostAccumulatorActor` — `num_cpus` 미지정으로 1 CPU 소비

**파일:** `neos/workflow/ray_actors/cost_accumulator.py:31`

```python
@ray.remote  # 기본 num_cpus=1
class CostAccumulatorActor:
```

단순 key-value dict 연산에 1 CPU를 할당한다. `@ray.remote(num_cpus=0)`으로 변경하면 CPU 소비 없이 스케줄링 가능하다.

---

## ✅ 잘 된 부분

| 항목 | 파일:라인 | 설명 |
|------|-----------|------|
| asyncio+Ray 브릿지 일관성 | `executor_pool.py`, `distributed_orchestrator.py` | `ray.get()` 직접 호출 없이 `asyncio.wrap_future(ref.future())` 패턴 일관 사용 → event loop blocking 방지 |
| `_stream_callback`, `_cost_accumulator` 직렬화 제외 | `distributed_orchestrator.py:317-335` | `_build_ray_context()`가 Ray pickle 불가 항목을 일관되게 제외 |
| `visiting` 불변 복사 | `dag_utils.py:64` | `visiting \| {idx}` 로 불변 복사 → 재귀 스택 간 DAG 탐색 오염 방지 |
| `RAY_ENABLED=false` 1줄 fallback | `distributed_orchestrator.py:117-118` | 부모 클래스 완전 위임으로 기존 순차 실행과 100% 동일 |
| Ray 초기화 실패 graceful fallback | `distributed_orchestrator.py:91-96` | warning 로그 + `_ray_enabled = False`로 순차 실행 유지 |
| LLM 문자열 인덱스 방어 | `dag_utils.py:58` | `depends_on: ["0","1"]` 형태를 `int()` 변환으로 처리 |
| `max_concurrency=1` Actor 격리 | `executor_pool.py:25` | HyperDeepWorkerActor의 내부 상태 충돌 방지 |
| `num_cpus=0.5` I/O bound 최적화 | `executor_pool.py:25` | HDR의 I/O bound 특성을 반영한 적절한 리소스 설정 |
| `seen_hashes` 불변 복사 상속 | `distributed_orchestrator.py:140` | 재귀 호출 간 해시 오염 방지 패턴 일관 유지 |
| Sandbox timeout 크로스 플랫폼 | `sandbox_executor.py:99` | `signal.SIGALRM` 대신 `asyncio.wait_for` — Windows/macOS 호환 |

---

## 수정 우선순위 요약

| 우선순위 | 번호 | 이슈 | 주요 영향 |
|----------|------|------|-----------|
| **P0** | #1 | Phase 2 Named Actors 미연결 | 문서-구현 불일치, dead code |
| **P0** | #2 | Ray 메트릭 기록 코드 없음 | 모니터링 완전 불가 |
| **P0** | #3 | `warmup()` 미호출 | 콜드 스타트 실패 가능성 |
| **P1** | #6 | `asyncio.get_event_loop()` deprecated | Python 3.12 DeprecationWarning |
| **P1** | #7 | `assert` → `RuntimeError` | 프로덕션 `-O` 모드 안전성 |
| **P1** | #9 | `dag_utils` 범위 외 인덱스 미검증 | LLM 오출력 시 `IndexError` 크래시 |
| **P2** | #4 | `_replan_and_solve` 순차 유지 | 재계획 시 병렬화 미활용 |
| **P2** | #5 | `_graceful_degrade` executor 불일치 | 비용 한도 초과 시 품질 저하 |
| **P2** | #10 | `_reset_agent_state()` 하드코딩 | 에이전트 변경 시 무증상 상태 혼입 |
| **P3** | #12 | `CostAccumulatorActor` 메모리 누수 | 장기 운영 시 메모리 증가 |
| **P3** | #8 | `__del__()` 안전성 | 종료 시 불필요한 예외 발생 |
| **P3** | #11, #13, #14, #15 | Minor 코드 품질 | 유지보수성 |
