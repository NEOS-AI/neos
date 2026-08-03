# 프로덕션 챗 경로 → 하네스 전환 (Sub-project A) 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 완성된 deep_analysis 하네스(M0–M4)를 기존 LangGraph 챗 워크플로우의 라우팅 대상 오케스트레이터 노드로 편입해, `DEEP_ANALYSIS_ENABLED` 활성 시 deep/analytical 쿼리가 하네스로 auto-route되게 한다(기존 챗 플럼빙 재사용, RESULT_INTEGRATOR로 합류).

**Architecture:** `recursive`/`hyper_deep` 오케스트레이터가 그래프에 편입된 방식을 그대로 따른다 — 설정 플래그로 게이팅, `OrchestratorRouter.route`에서 분기, 조건부 노드 등록, `RESULT_INTEGRATOR`로 엣지. 하네스는 단일 노드로 완주하며 report_markdown을 `final_response`로 state에 매핑.

**Tech Stack:** Python 3.12, LangGraph StateGraph, async SQLAlchemy, pytest + pytest-asyncio.

**Spec:** [docs/superpowers/specs/2026-07-11-deep-analysis-chatswap-and-l5-design.md](../specs/2026-07-11-deep-analysis-chatswap-and-l5-design.md). 하네스 코어: [neos/workflow/deep_analysis/](../../../neos/workflow/deep_analysis/).

## Global Constraints

- **무회귀:** `DEEP_ANALYSIS_ENABLED=false`(기본)에서 기존 챗 라우팅/동작이 **완전히 동일**해야 한다. 비활성 시 노드는 등록조차 되지 않는다.
- **우선순위:** 활성 시 deep_analysis 분기는 `route()`에서 hyper_deep/recursive **앞**에 온다(동일 intent/복잡도에서 우선).
- **매직넘버 금지:** threshold/enabled는 `settings.config.deep_analysis.*` / `settings.DEEP_ANALYSIS_*`.
- **테스트 실 LLM 금지:** 노드 계약 테스트는 하네스 오케스트레이터/워커를 fake 주입.
- **하네스 코어 불변:** M0–M4 코드는 수정하지 않는다(통합 계층만 추가). `service.build_orchestrator`/`ledger.create_run`은 그대로 사용.
- **P2/run 스코프:** 노드가 여는 DB 세션은 하네스 Ledger 전용. 세션 커밋은 노드가 관리.
- **테스트 명령:** `.venv/bin/python -m pytest` (bare pytest는 asyncio 마커 수집 실패).

---

## 파일 구조
- Modify: `neos/config/schema.py` — `DeepAnalysisConfig`에 `complexity_threshold` 추가(`enabled` 이미 존재).
- Modify: `neos/config/settings.py` — `DEEP_ANALYSIS_ENABLED`/`DEEP_ANALYSIS_COMPLEXITY_THRESHOLD` 별칭 확인(LEGACY_PREFIX로 이미 해석되면 무변경).
- Modify: `neos/workflow/enums.py` — `WorkflowNode.DEEP_ANALYSIS_ORCHESTRATOR`, `IntentType.DEEP_ANALYSIS`.
- Modify: `neos/workflow/routing/orchestrator_router.py` — `route()`에 deep_analysis 분기.
- Modify: `neos/workflow/graph.py` — 조건부 노드 등록 + 라우팅 맵 + 엣지 + `_deep_analysis_orchestrator_node`.
- Tests: `tests/workflow/routing/test_deep_analysis_routing.py`, `tests/workflow/test_deep_analysis_node.py`.

---

### Task 1: 설정 + enum (DEEP_ANALYSIS_ENABLED / threshold / WorkflowNode / IntentType)

**Files:**
- Modify: `neos/config/schema.py` (`DeepAnalysisConfig`)
- Modify: `neos/workflow/enums.py`
- Test: `tests/workflow/routing/test_deep_analysis_routing.py` (설정/enum 부분)

**Interfaces:**
- Produces: `settings.DEEP_ANALYSIS_ENABLED: bool`(기본 False), `settings.DEEP_ANALYSIS_COMPLEXITY_THRESHOLD: float`(기본 0.5), `WorkflowNode.DEEP_ANALYSIS_ORCHESTRATOR = "deep_analysis_orchestrator"`, `IntentType.DEEP_ANALYSIS = "deep_analysis"`.

- [ ] **Step 1: 실패 테스트**

```python
# tests/workflow/routing/test_deep_analysis_routing.py
import pytest
from neos.config.settings import settings
from neos.workflow.enums import WorkflowNode, IntentType

pytestmark = pytest.mark.no_db

def test_deep_analysis_settings_defaults():
    assert settings.DEEP_ANALYSIS_ENABLED is False
    assert settings.DEEP_ANALYSIS_COMPLEXITY_THRESHOLD == 0.5

def test_deep_analysis_enum_values():
    assert WorkflowNode.DEEP_ANALYSIS_ORCHESTRATOR.value == "deep_analysis_orchestrator"
    assert IntentType.DEEP_ANALYSIS.value == "deep_analysis"
```

- [ ] **Step 2: 실패 확인** — `.venv/bin/python -m pytest tests/workflow/routing/test_deep_analysis_routing.py -v` → FAIL.

- [ ] **Step 3: 구현**
  - `schema.py` `DeepAnalysisConfig`에: `enabled: bool = False`(이미 있으면 유지), `complexity_threshold: float = 0.5` 추가.
  - `settings.py`: `DEEP_ANALYSIS_` 프리픽스가 `deep_analysis` 섹션으로 매핑되는지 확인(이미 매핑됨 — `LEGACY_PREFIX_PATHS`에 `("DEEP_ANALYSIS_", "deep_analysis")` 존재). `settings.DEEP_ANALYSIS_ENABLED` → `deep_analysis.enabled`, `settings.DEEP_ANALYSIS_COMPLEXITY_THRESHOLD` → `deep_analysis.complexity_threshold`로 해석됨. 별도 코드 불필요할 수 있음 — 테스트로 확인.
  - `enums.py`: `WorkflowNode`에 `DEEP_ANALYSIS_ORCHESTRATOR = "deep_analysis_orchestrator"`; `IntentType`에 `DEEP_ANALYSIS = "deep_analysis"`.

- [ ] **Step 4: 통과 확인** → PASS.
- [ ] **Step 5: 커밋** `git commit -m "feat(deep-analysis): add DEEP_ANALYSIS_ENABLED/threshold settings and workflow enums"`

---

### Task 2: 라우터 분기 (`OrchestratorRouter.route`)

**Files:**
- Modify: `neos/workflow/routing/orchestrator_router.py`
- Test: `tests/workflow/routing/test_deep_analysis_routing.py` (라우팅 부분)

**Interfaces:**
- Consumes: Task 1 settings/enums, `policy.allows_recursive_research()`, `state.query_intent`, `state.query_classification.complexity_score`.
- Produces: `route()`가 조건 충족 시 `"deep_analysis"` 반환.

**동작:** `route()`에서 A2UI/priority/approval 체크 뒤, **hyper_deep 분기 앞에** 삽입:
```python
if settings.DEEP_ANALYSIS_ENABLED and policy.allows_recursive_research():
    if intent == IntentType.DEEP_ANALYSIS.value:
        return "deep_analysis"
    da_intents = (IntentType.DEEP_RESEARCH.value, IntentType.COMPLEX_ANALYSIS.value)
    if complexity >= settings.DEEP_ANALYSIS_COMPLEXITY_THRESHOLD and intent in da_intents:
        return "deep_analysis"
```
(intent/complexity 변수는 기존 route()에서 이미 계산됨 — 그 위치에 삽입.)

- [ ] **Step 1: 실패 테스트** (settings monkeypatch로 enabled on/off)

```python
# 추가 to test_deep_analysis_routing.py
from types import SimpleNamespace
from neos.workflow.routing.orchestrator_router import OrchestratorRouter

def _state(intent, complexity):
    return {"query_intent": intent, "query_classification": {"complexity_score": complexity}}

def test_routes_to_deep_analysis_when_enabled(monkeypatch):
    monkeypatch.setattr("neos.workflow.routing.orchestrator_router.settings.DEEP_ANALYSIS_ENABLED", True, raising=False)
    # policy.allows_recursive_research() True 경로 확보: deep_research intent + 높은 복잡도
    r = OrchestratorRouter()
    out = r.route(_state("deep_research", 0.9))
    assert out == "deep_analysis"

def test_no_deep_analysis_when_disabled(monkeypatch):
    monkeypatch.setattr("neos.workflow.routing.orchestrator_router.settings.DEEP_ANALYSIS_ENABLED", False, raising=False)
    r = OrchestratorRouter()
    out = r.route(_state("deep_research", 0.9))
    assert out != "deep_analysis"   # 기존 경로(recursive/hyper_deep/base) 유지
```

> **주의:** `settings.DEEP_ANALYSIS_ENABLED`는 프로퍼티 해석이라 monkeypatch가 까다로울 수 있다. 라우터가 `settings.DEEP_ANALYSIS_ENABLED`를 직접 읽으므로, 테스트는 `settings` 객체의 속성을 patch하거나 `reload_settings_for_tests`로 설정 오버라이드. 구현자는 실제 settings 접근 방식에 맞춰 테스트를 조정하되, **enabled=True에서 deep_analysis, False에서 비-deep_analysis**라는 계약을 검증할 것. `policy.allows_recursive_research()`가 특정 state를 요구하면 그에 맞게 state를 구성(기존 라우터 테스트 참조).

- [ ] **Step 2~5:** 실패 확인 → 분기 삽입 → 통과 → 커밋.

```bash
git commit -m "feat(deep-analysis): route deep/analytical queries to harness when enabled (priority over recursive/hyper_deep)"
```

---

### Task 3: 그래프 노드 (`_deep_analysis_orchestrator_node`) + 조건부 등록 + 엣지

**Files:**
- Modify: `neos/workflow/graph.py`
- Test: `tests/workflow/test_deep_analysis_node.py`

**Interfaces:**
- Consumes: `service.build_orchestrator(session, run_id, *, profile, event_sink, ...)`, `ledger.create_run(session, root_text, profile) -> run_id`, `db_manager.get_session()`.
- Produces: `async _deep_analysis_orchestrator_node(self, state) -> Dict[str, Any]` returning `{"final_response": report_markdown, "deep_analysis_run_id": run_id, "execution_steps": ...}`. 조건부 노드 등록 + 라우팅 맵 `["deep_analysis"]` + 엣지 → RESULT_INTEGRATOR.

**노드 본문:**
```python
async def _deep_analysis_orchestrator_node(self, state: Dict[str, Any]) -> Dict[str, Any]:
    from neos.workflow.deep_analysis.service import build_orchestrator
    from neos.workflow.deep_analysis.ledger import create_run
    from neos.database.connection import db_manager
    query = state.get("refined_query") or state.get("original_query", "")
    profile = "default"
    try:
        async with await db_manager.get_session() as session:
            run_id = await create_run(session, query, profile)
            await session.commit()
            def sink(kind, payload):  # 노드 레벨 진행(선택적으로 execution_steps에 축적)
                pass
            orch = await build_orchestrator(session, run_id, profile=profile, event_sink=sink)
            result = await orch.run(query)
            await session.commit()
        return {
            "final_response": result["report_markdown"],
            "deep_analysis_run_id": result["run_id"],
            "execution_steps": state.get("execution_steps", []) + [
                {"step": "deep_analysis_orchestrator", "result": f"run {result['run_id']}"}],
        }
    except Exception as exc:
        logger.error(f"[DeepAnalysisOrchestratorNode] failed: {exc}")
        return {"final_response": "심층 분석 하네스 실행에 실패했습니다."}
```

**조건부 등록(그래프 빌드부, recursive 등록 패턴 미러링):**
```python
if settings.DEEP_ANALYSIS_ENABLED:
    workflow.add_node(WorkflowNode.DEEP_ANALYSIS_ORCHESTRATOR.value, self._deep_analysis_orchestrator_node)
```
라우팅 맵(조건부 엣지 매핑부):
```python
if settings.DEEP_ANALYSIS_ENABLED:
    _routing_map["deep_analysis"] = WorkflowNode.DEEP_ANALYSIS_ORCHESTRATOR.value
    workflow.add_edge(WorkflowNode.DEEP_ANALYSIS_ORCHESTRATOR.value, WorkflowNode.RESULT_INTEGRATOR.value)
```

- [ ] **Step 1: 실패 테스트** (하네스 fake 주입 — build_orchestrator/create_run monkeypatch)

```python
# tests/workflow/test_deep_analysis_node.py
import pytest
pytestmark = pytest.mark.no_db

@pytest.mark.asyncio
async def test_deep_analysis_node_maps_report_to_final_response(monkeypatch):
    from neos.workflow import graph as graph_mod
    # fake create_run / build_orchestrator / db session
    class FakeOrch:
        async def run(self, q): return {"report_markdown": "# 보고서\n본문", "run_id": "run00001"}
    class FakeSessionCtx:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def commit(self): pass
    async def fake_get_session(): return FakeSessionCtx()
    async def fake_create_run(s, q, p): return "run00001"
    async def fake_build(s, run_id, **kw): return FakeOrch()
    monkeypatch.setattr("neos.database.connection.db_manager.get_session", fake_get_session)
    monkeypatch.setattr("neos.workflow.deep_analysis.ledger.create_run", fake_create_run)
    monkeypatch.setattr("neos.workflow.deep_analysis.service.build_orchestrator", fake_build)
    # 그래프 인스턴스에서 노드 메서드 직접 호출
    g = graph_mod.multi_agent_workflow
    out = await g._deep_analysis_orchestrator_node({"original_query": "GLM-5.2 MoE 영향?"})
    assert out["final_response"].startswith("# 보고서")
    assert out["deep_analysis_run_id"] == "run00001"
```

> **주의:** monkeypatch 대상 경로는 노드 본문의 import 위치와 일치해야 한다(함수 내부 import면 원 모듈 경로 patch). 구현자는 실제 import 방식에 맞춰 patch 경로 조정. `multi_agent_workflow` 싱글턴에 메서드가 있으면 그대로 호출; 노드가 인스턴스 메서드이므로 접근 가능.

- [ ] **Step 2: 실패 확인** → FAIL.
- [ ] **Step 3: 구현** — 노드 메서드 + 조건부 등록 + 엣지.
- [ ] **Step 4: 통과 + 스모크** — 노드 테스트 PASS. `DEEP_ANALYSIS_ENABLED=true` 환경에서 그래프 빌드가 예외 없이 노드/엣지를 등록하는지 확인(reload_settings_for_tests 또는 별도 그래프 인스턴스). 전체 회귀: `.venv/bin/python -m pytest tests/workflow/ -q`(관련 서브셋) green.
- [ ] **Step 5: 커밋** `git commit -m "feat(deep-analysis): add DEEP_ANALYSIS_ORCHESTRATOR workflow node behind flag"`

---

### Task 4: DECISIONS D18 + 통합 스모크 + 무회귀 확인

**Files:**
- Modify: `neos/workflow/deep_analysis/DECISIONS.md` (D18)
- Test: `tests/workflow/test_deep_analysis_node.py` (무회귀 스모크 추가)

**내용:**
- **D18:** 하네스는 단일 workflow 노드로 완주(챗 노드 레벨 진행), per-claim SSE는 전용 `/api/v1/deep-analysis` 엔드포인트. 근거: 기존 챗 스트리밍/대화 플럼빙 재사용 + 최소 침습, 점진적 workflow 대체.
- **무회귀 스모크:** `DEEP_ANALYSIS_ENABLED=false`(기본)에서 그래프 빌드가 deep_analysis 노드를 등록하지 **않고**, 라우터가 deep_research 쿼리에 `"deep_analysis"`를 반환하지 않음을 검증.
- 전체 회귀: `.venv/bin/python -m pytest tests/workflow/ -q` green(기존 워크플로우 테스트 무회귀).

- [ ] Steps: 무회귀 테스트 작성/통과 → DECISIONS → 커밋.

```bash
git commit -m "feat(deep-analysis): record D18; verify no-regression when flag disabled (chat swap complete)"
```

**완료 게이트:** Task 1–4 통과 = 플래그 활성 시 deep/analytical 쿼리가 하네스 노드로 라우팅되어 report가 챗 응답으로 나오고, 비활성 시 기존 동작 무회귀.

---

## 자체 리뷰 (스펙 대비)
- **A.1 설정/enum** → Task 1. **A.2 라우팅** → Task 2. **A.3 노드/등록/엣지** → Task 3. **A.4 D18** → Task 4. **A.5 테스트**(라우팅/노드계약/스모크/무회귀) → Task 1–4 전반.
- **플레이스홀더:** 없음. monkeypatch 경로/policy state는 구현자가 실제 코드에 맞춰 조정하라고 명시(라우터/settings 접근이 코드베이스별로 미묘).
- **타입 일관성:** `WorkflowNode.DEEP_ANALYSIS_ORCHESTRATOR`, `IntentType.DEEP_ANALYSIS`, `route()->"deep_analysis"`, `_deep_analysis_orchestrator_node(state)->{final_response,...}`, `build_orchestrator`/`create_run` 시그니처 — 일치.
- **무회귀 불변식:** Task 4가 명시 검증.
