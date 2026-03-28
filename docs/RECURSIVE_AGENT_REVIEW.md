# NEOS 재귀 에이전트(ROMA) 코드 리뷰

> **리뷰 대상:** `neos/workflow/recursive/` 전체, 관련 수정 파일
> **리뷰 기준:** `docs/RECURSIVE_AGENT_PLAN.md` (계획) vs `docs/RECURSIVE_AGENT_IMPLE.md` (구현)
> **작성일:** 2026-03-07
> **버전:** NEOS v0.22.0

---

## 요약

| 심각도 | 건수 |
|--------|------|
| 🔴 심각 (기능 미동작) | 3 |
| 🟠 주요 버그 / 로직 오류 | 4 |
| 🟡 설계 문제 / 불일치 | 7 |
| 🔵 개선 / 누락 사항 | 4 |

---

## 🔴 심각 — 기능 미동작 수준

### R-01. 실제 비용 추적 미구현 → Budget Cap 무력화

**관련 파일:** `neos/workflow/recursive/orchestrator.py:130`, `executor.py`

비용 한도 체크 로직이 있지만 실질적으로 동작하지 않습니다.

```python
# orchestrator.py:130
if context.get("total_cost", 0.0) >= self._budget_cap:
    return await self._graceful_degrade(task, context)
```

**원인 체인:**

1. `executor.execute()`가 `task.cost`를 업데이트하지 않음
2. `atomizer`, `planner`, `aggregator`, `verifier` 어느 컴포넌트도 실제 LLM 토큰 비용을 `task.cost`에 반영하지 않음
3. `context["total_cost"]`는 `_build_context`에서 초기화된 후 재귀 중 절대 갱신되지 않음
4. 결과적으로 `root_task.total_cost()`는 항상 `0.0` 반환

**영향:**
- `graceful_degrade()`가 절대 호출되지 않음
- `recursive_budget_remaining` 반환값이 항상 `budget_cap`과 같음
- `.env`의 `RECURSIVE_BUDGET_CAP` 설정이 무의미

**수정 방향:** 각 컴포넌트가 LLM 응답의 `usage` 메타데이터를 읽어 `task.cost`에 누적, `context["total_cost"]`를 재귀 호출 후 갱신.

---

### R-02. Executor가 실시간 검색 미연동 (LLM 직접 호출만)

**관련 파일:** `neos/workflow/recursive/executor.py:29-125`

`RecursiveExecutor`는 `search_orchestrator` 파라미터를 받지만 실제로 사용하지 않습니다.

```python
class RecursiveExecutor:
    def __init__(self, search_orchestrator=None, agents=None):
        self._search_orchestrator = search_orchestrator  # 저장만 하고 미사용
        ...
    async def _execute_with_llm(self, task, context):
        # 항상 LLM 직접 호출만 수행
        response = await llm.ainvoke(prompt)
```

**영향:**
- ATOMIC 태스크가 웹 검색 없이 LLM 훈련 데이터만으로 답변
- 최신 정보(주가, 시장 점유율 등)가 필요한 복잡 질의에서 구조적 한계
- NEOS의 핵심 강점인 실시간 검색이 ROMA 경로에서 완전히 빠짐

**참고:** 구현 문서에서 "초기 구현에서는 LLM을 직접 호출"이라고 명시했으나, 이 상태에서는 ROMA의 분해-실행 이점이 크게 반감됩니다.

---

### R-03. AgentState의 recursive 필드 일부 미사용

**관련 파일:** `neos/workflow/state.py:130-131`, `neos/workflow/recursive/orchestrator.py:97-109`

`AgentState`에 추가된 두 필드가 `orchestrator.execute()` 반환 dict에 포함되지 않아 항상 `None`입니다.

```python
# state.py에 선언됨
recursive_task_stack: Optional[List[Dict]]       # 항상 None
recursive_completed_tasks: Optional[List[Dict]]  # 항상 None
```

이 필드를 읽거나 활용하는 코드도 없습니다. 불필요한 상태 필드이거나, 실제로 채워져야 하는 필드입니다.

---

## 🟠 주요 버그 / 로직 오류

### R-04. DAG 의존성이 실행에 미반영

**관련 파일:** `neos/workflow/recursive/planner.py:214`, `orchestrator.py:172-177`

Planner가 `metadata["depends_on"]`에 의존성 인덱스를 저장하지만, Orchestrator가 이를 검사하지 않습니다.

```python
# planner.py: 의존성 저장
metadata={"depends_on": item.get("depends_on", [])}

# orchestrator.py: 단순 순차 실행 (의존성 무시)
for subtask in subtasks:
    subtask_result = await self._recursive_solve(subtask, child_context, seen_hashes)
```

**영향:** B가 A에 의존한다고 계획을 세워도, A가 완료되기 전에 B를 실행하는 경우는 없지만(순차 실행이므로) 의존성이 없는 태스크들도 무조건 직렬 실행됩니다. 향후 병렬 실행(Phase 3) 전환 시 의존성 로직이 없으면 레이스 컨디션이 발생합니다.

---

### R-05. `completed_task_descriptions` 미업데이트

**관련 파일:** `neos/workflow/recursive/orchestrator.py:260`

```python
# _build_context
"completed_task_descriptions": [],  # 초기화 후 재귀 중 절대 갱신 안 됨
```

Atomizer 프롬프트의 `Already solved: ...` 컨텍스트가 항상 비어 있어, 동일하거나 유사한 하위 태스크를 중복 실행하는 것을 방지할 수 없습니다.

---

### R-06. max_subtasks 상한이 실제 적용되지 않음

**관련 파일:** `neos/workflow/recursive/planner.py:99, 196-221`

```python
max_subtasks = max(2, self._max_tasks_per_level - task.depth)
# LLM 프롬프트에 힌트만 전달
prompt = _PLANNER_PROMPT.format(max_subtasks=max_subtasks, ...)
```

LLM이 `max_subtasks`보다 많은 하위 태스크를 반환해도 `_build_subtask_nodes`에서 모두 추가합니다. 설정값 `RECURSIVE_MAX_TASKS_PER_LEVEL`이 사실상 soft limit도 아닌 권고 값에 불과합니다.

**수정 방향:** `_build_subtask_nodes`에서 `subtask_dicts[:max_subtasks]`로 잘라내기.

---

### R-07. `_replan_and_solve`에서 depth 중복 설정

**관련 파일:** `neos/workflow/recursive/orchestrator.py:233`

```python
for replan_task in replan_tasks:
    replan_task.depth = task.depth + 1  # ← 중복
```

`planner.replan()`의 `_build_subtask_nodes`에서 이미 `depth = parent.depth + 1`로 설정합니다. 결과는 동일하지만 `_build_subtask_nodes`의 내부 구현에 암묵적으로 의존하는 코드입니다.

---

## 🟡 설계 문제 / 불일치

### R-08. Verifier 임계값 문서·코드·docstring 불일치

**관련 파일:** `neos/workflow/recursive/verifier.py:54-57`

| 위치 | 값 |
|------|----|
| 계획 문서 §5.6 | `threshold = 0.75` |
| 구현 문서 §4.5 | `max(WORKFLOW_MIN_QUALITY_SCORE, 0.65)` |
| `verifier.py` 클래스 docstring | "0.75 중 더 높은 값" |
| 실제 코드 | `max(..., 0.65)` |

같은 파일 안에서 docstring과 코드가 다릅니다.

---

### R-09. `recursive_current_depth` 항상 0 반환

**관련 파일:** `neos/workflow/recursive/orchestrator.py:101`

```python
"recursive_current_depth": 0,  # 항상 0 고정
```

실제 도달한 최대 깊이를 반영하지 않습니다. 관찰가능성·디버깅 목적의 값이 의미 없습니다.

---

### R-10. bool 환경변수 파싱 취약

**관련 파일:** `neos/config/settings.py:620`

```python
RECURSIVE_AGENT_ENABLED: bool = bool(env_vars.get("RECURSIVE_AGENT_ENABLED", False))
```

환경변수는 문자열이므로 `.env`에 `RECURSIVE_AGENT_ENABLED=false`를 설정해도 `bool("false") == True`가 됩니다. 비활성화 의도가 무시되어 재귀 에이전트가 항상 활성화됩니다.

**수정 방향:**
```python
RECURSIVE_AGENT_ENABLED: bool = env_vars.get("RECURSIVE_AGENT_ENABLED", "").lower() in ("1", "true", "yes")
```

---

### R-11. Executor의 `prior_results` 컨텍스트에 태스크 설명 미포함

**관련 파일:** `neos/workflow/recursive/executor.py:118-125`

```python
def _build_prior_context(self, prior_results: Dict[str, str]) -> str:
    for task_id, result in prior_results.items():
        parts.append(f"- {result[:300]}")  # task_id나 설명 없이 결과만 전달
```

LLM에게 어떤 태스크의 결과인지 설명 없이 순수 결과 텍스트만 전달하므로 연관성을 파악하기 어렵습니다.

---

### R-12. `atomizer.py` confidence 조건 분기 중복

**관련 파일:** `neos/workflow/recursive/atomizer.py:135-141`

```python
if not atomic and confidence < 0.5:
    return TaskAtomicity.DECOMPOSABLE
if atomic and confidence < 0.5:
    return TaskAtomicity.DECOMPOSABLE  # 결국 confidence < 0.5이면 무조건 DECOMPOSABLE
return TaskAtomicity.ATOMIC if atomic else TaskAtomicity.DECOMPOSABLE
```

두 조건을 `if confidence < 0.5: return DECOMPOSABLE`로 합칠 수 있습니다.

---

### R-13. FAILED 자식 노드 결과가 통합에 포함

**관련 파일:** `neos/workflow/recursive/aggregator.py:82`

```python
completed_children = [n for n in child_nodes if n.result]
```

`TaskStatus.FAILED`인 노드도 `result`에 `"[실행 실패: ...]"` 문자열을 가지므로 통합 대상에 포함됩니다. 실패 메시지가 aggregation 품질을 저하시킬 수 있습니다.

**수정 방향:**
```python
completed_children = [n for n in child_nodes if n.result and n.status == TaskStatus.COMPLETED]
```

---

### R-14. MD5 `usedforsecurity=False` 누락

**관련 파일:** `neos/workflow/recursive/models.py:51`

```python
hashlib.md5(self.description.strip().lower().encode()).hexdigest()
```

FIPS 규정 준수 환경에서 `usedforsecurity=False` 인자 없이 MD5 호출 시 `ValueError`가 발생합니다.

**수정 방향:**
```python
hashlib.md5(self.description.strip().lower().encode(), usedforsecurity=False).hexdigest()
```

---

## 🔵 개선 / 누락 사항

### R-15. 테스트 코드 전무

계획 문서 §8에서 Sprint 1부터 단위 테스트 작성을 명시(`tests/workflow/recursive/test_atomizer.py` 등)했으나 테스트 파일이 하나도 없습니다.

최소 검증이 필요한 케이스:
- `Atomizer`: `depth >= max_depth` 시 ATOMIC 강제, LLM 실패 시 DECOMPOSABLE
- `Planner`: fallback_split, max_subtasks 상한 적용
- `Verifier`: 50자 미만 즉시 실패, heuristic_verify
- `Orchestrator`: 순환 참조 감지, budget cap graceful degradation

---

### R-16. 관찰가능성(Observability) 미구현

계획 문서 §8 Sprint 4에 명시된 항목들이 전혀 없습니다:

- Prometheus 메트릭: `recursive_depth_histogram`, `task_decomposition_count`
- OpenTelemetry 트레이싱: 재귀 트리 시각화
- 재귀 실행 중 어느 단계에서 얼마나 걸리는지 확인할 방법 없음

---

### R-17. `atomizer.py`의 `available_tools` 파라미터 삭제

계획 문서 §5.2에서 `assess(task, available_tools, context)` 3개 파라미터를 정의했으나, 실제 구현은 `assess(task, context)` 2개 파라미터입니다. LLM이 실제 사용 가능한 도구 목록 없이 `estimated_tools`를 추정하므로 도구 기반 원자성 판단 정확도가 낮아집니다.

---

### R-18. `_graceful_degrade` 내부 Executor 호출 시 비용 재진입

**관련 파일:** `neos/workflow/recursive/orchestrator.py:243-249`

```python
async def _graceful_degrade(self, task, context):
    if completed_children:
        return await self._aggregator.aggregate(...)
    return await self._executor.execute(task, context)  # 비용 추가 발생
```

비용 초과로 진입했는데 내부에서 다시 LLM 호출을 합니다. 비용 추적이 제대로 구현된다면 이 호출이 budget_cap을 초과할 수 있습니다. 현재는 비용 추적이 안 되어 잠재적으로 숨겨진 문제입니다.

---

## 전체 이슈 요약표

| 번호 | 파일 | 심각도 | 이슈 |
|------|------|--------|------|
| R-01 | `orchestrator.py`, `executor.py` | 🔴 | 비용 추적 미구현 → budget cap 무력화 |
| R-02 | `executor.py` | 🔴 | 실시간 검색 미연동 (LLM 직접 호출만) |
| R-03 | `state.py`, `orchestrator.py` | 🔴 | task_stack / completed_tasks 상태 필드 미사용 |
| R-04 | `planner.py`, `orchestrator.py` | 🟠 | DAG 의존성이 실행에 미반영 |
| R-05 | `orchestrator.py` | 🟠 | completed_task_descriptions 미업데이트 |
| R-06 | `planner.py` | 🟠 | max_subtasks 상한 미적용 |
| R-07 | `orchestrator.py` | 🟠 | replan_task.depth 중복 설정 |
| R-08 | `verifier.py` | 🟡 | threshold 값 문서·docstring·코드 불일치 |
| R-09 | `orchestrator.py` | 🟡 | recursive_current_depth 항상 0 반환 |
| R-10 | `settings.py` | 🟡 | bool 환경변수 파싱 취약 |
| R-11 | `executor.py` | 🟡 | prior_results에 태스크 설명 미포함 |
| R-12 | `atomizer.py` | 🟡 | confidence 조건 분기 중복 |
| R-13 | `aggregator.py` | 🟡 | FAILED 자식 노드 필터링 미비 |
| R-14 | `models.py` | 🟡 | MD5 usedforsecurity=False 누락 |
| R-15 | `tests/` | 🔵 | 테스트 코드 전무 |
| R-16 | 전체 | 🔵 | Observability (Prometheus / OTel) 미구현 |
| R-17 | `atomizer.py` | 🔵 | available_tools 파라미터 삭제됨 |
| R-18 | `orchestrator.py` | 🔵 | graceful_degrade 내부 비용 재진입 잠재 위험 |

---

## 수정 우선순위 권고

### 1순위 (즉시 수정)
- **R-10** (bool 파싱): 단순 수정, 의도치 않은 활성화 방지
- **R-06** (max_subtasks): 한 줄 수정으로 설정값 신뢰성 확보
- **R-13** (FAILED 필터링): 한 줄 수정, 통합 품질 개선
- **R-14** (MD5 FIPS): 한 줄 수정

### 2순위 (주요 기능 보완)
- **R-01** (비용 추적): LLM 응답 usage 파싱 + context 갱신 구현
- **R-05** (completed_task_descriptions): 재귀 루프에서 갱신 로직 추가
- **R-08** (Verifier threshold): docstring 및 계획 문서와 일치시키기

### 3순위 (중장기)
- **R-02** (검색 연동): SearchOrchestrator 실제 연동 (Phase 2)
- **R-04** (DAG 실행): 병렬 실행 전환(Phase 3) 전에 반드시 구현
- **R-15** (테스트): 컴포넌트별 단위 테스트 작성
- **R-16** (Observability): Prometheus / OTel 연동
