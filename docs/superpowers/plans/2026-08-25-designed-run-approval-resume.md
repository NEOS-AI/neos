# 설계된 run 의 승인 재개 — 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 설계된 run 이 승인 게이트에서 멈춰도 **멈출 때와 같은 토폴로지로** 재개되게 한다.

**Architecture:** 토폴로지를 `AgentState.execution_topology` 에 실어 체크포인트와
같은 수명을 갖게 한다. 재개 경로는 상태에서 그것을 읽어 **재검증한 뒤**
`build_ephemeral_workflow` 로 그래프를 다시 짓고, 실패하면 정적으로 흐르지 않고
503 으로 거부한다.

**Tech Stack:** Python 3.12 · LangGraph(StateGraph·`BaseCheckpointSaver`) ·
FastAPI · pytest(+pytest-asyncio)

**Spec:** `docs/superpowers/specs/2026-08-25-designed-run-approval-resume-design.md`

## Global Constraints

- **조용한 정적 재개 금지.** 토폴로지를 복원할 수 없으면 `HTTPException(503)`.
  정적 그래프로 재개하는 것은 복구가 아니라 스펙 §2.1이 이름 붙인 원래 버그다.
- **설계된 그래프를 캐시하지 않는다.** `MultiAgentWorkflow` 는 오래 살고 요청 간
  공유된다 — 인스턴스 슬롯에 두면 경쟁한다(G2 스펙 §2.3). 상태에서 다시 짓는다.
- **`interrupt_before` 는 저장하지 않는다.** 재개 시점에
  `set(topology.nodes) & _INTERRUPT_GATED_NODES` 로 다시 계산한다.
- **새 이벤트 kind 를 만들지 않는다.** FE 라벨 부채를 만들지 않기 위해서이며
  (§5.2 FE1 이 그 대가를 치렀다), 기존 `graph_design_fallback` 에 사유를 싣는다.
- **어떤 노드도 `execution_topology` 를 읽지 않는다.** 작성자는 오케스트레이터
  하나다(설계 §1 P2 의 상태 층 적용).
- **커밋 메시지에 `Co-Authored-By` 트레일러를 넣지 않는다.**
- 검증 명령: `.venv/bin/python -m pytest <경로> -q -p no:randomly`
  (bare `pytest` 는 asyncio 마커 수집에 실패한다 — 로드맵 §10.4)

---

### Task 1: 가정을 잰다 — 정적 그래프로 설계된 run 의 상태를 읽을 수 있는가

**이 태스크의 산출물은 코드가 아니라 답이다.** 스펙 §3.4가 🔴 로 표시한 검증되지
않은 가정이며, 깨지면 Task 4 의 설계가 바뀐다. 먼저 잰다.

**Files:**
- Test: `tests/workflow/test_designed_run_state_readback.py` (Create)

**Interfaces:**
- Consumes: `MultiAgentWorkflow`, `build_ephemeral_workflow`, `GraphTopology`
  (전부 기존)
- Produces: 없음 (판정만). 결과를 **Task 4 착수 전에** 이 파일 상단 독스트링에 적는다

- [ ] **Step 1: 왕복을 실제로 돌리는 테스트를 쓴다**

`tests/workflow/test_designed_run_state_readback.py`:

```python
"""설계된 그래프로 쓴 체크포인트를 **정적** 그래프로 읽을 수 있는가.

이 저장소는 지금까지 정적 run 의 체크포인트만 읽어 왔다. 재개 경로
(`approval_handlers`)가 `multi_agent_workflow.graph` 로 `aget_state` 를 부르므로,
설계된 run 을 재개하려면 이 왕복이 성립해야 한다. LangGraph 는 상태 채널 외에
노드별 트리거 채널을 갖고, 노드 집합이 다를 때 `aget_state` 가 무엇을 하는지
확인된 바 없다 -- 그래서 잰다.
"""

import pytest
from langgraph.checkpoint.memory import MemorySaver

from neos.workflow.graph import MultiAgentWorkflow, build_ephemeral_workflow
from neos.workflow.topology import GRAPH_ENTRY_WRITES, GraphTopology

_CHAIN = (
    "query_classifier",
    "search_orchestrator",
    "analysis_orchestrator",
    "generation_orchestrator",
    "response_generator",
)


def _chain_topology(chain):
    return GraphTopology(
        nodes=chain,
        edges=(
            ("__start__", chain[0]),
            *((chain[i], chain[i + 1]) for i in range(len(chain) - 1)),
            (chain[-1], "__end__"),
        ),
        initial_writes=GRAPH_ENTRY_WRITES,
    )


@pytest.mark.asyncio
async def test_a_designed_runs_checkpoint_is_readable_through_the_static_graph():
    saver = MemorySaver()
    workflow = MultiAgentWorkflow()
    await workflow._ensure_graph_initialized(use_checkpointer=True)

    designed = build_ephemeral_workflow(
        workflow, _chain_topology(_CHAIN), checkpointer=saver
    )
    config = {"configurable": {"thread_id": "readback-probe"}}

    # 설계된 그래프로 상태를 하나 쓴다. 노드를 돌리지 않고 aupdate_state 만
    # 쓰는 이유는 이 테스트가 재는 것이 실행이 아니라 **채널 호환성**이기 때문이다.
    await designed.aupdate_state(config, {"original_query": "설계된 run 의 질의"})

    # 정적 그래프로 같은 thread 를 읽는다. 정적 그래프도 같은 saver 를 써야
    # 한다 -- 체크포인터가 다르면 이 테스트는 아무것도 재지 않는다.
    static = workflow.graph
    static.checkpointer = saver
    state = await static.aget_state(config)

    assert state.values.get("original_query") == "설계된 run 의 질의"
```

- [ ] **Step 2: 돌려서 결과를 본다 — 실패해도 정상이다**

Run: `.venv/bin/python -m pytest tests/workflow/test_designed_run_state_readback.py -q -p no:randomly`

**이 태스크는 PASS 를 요구하지 않는다.** 두 결과 모두 유효한 답이다:
- **PASS** → 가정이 성립한다. Task 4 를 스펙대로 진행한다.
- **FAIL** → 가정이 깨졌다. Task 4 는 그래프를 거치지 않고
  `PostgreSQLCheckpointer.aget_tuple(config)` 을 직접 불러 체크포인트에서
  `execution_topology` 만 꺼내는 경로로 바꾼다(`checkpointer.py:183`,
  자체 구현이라 열 수 있다).

- [ ] **Step 3: 결과를 파일 상단에 적는다**

독스트링 끝에 한 줄을 더한다. 예:

```python
**판정 (2026-08-__):** 성립한다 / 성립하지 않는다 -- <관측한 예외나 값>.
따라서 Task 4 는 <상태 경로 / 체크포인터 직접 조회> 를 쓴다.
```

근거 없이 "될 것이다" 로 넘어가지 않는다. 이 저장소가 세 번 틀린 곳이 정확히
자가 지표를 확인하지 않은 자리다(§8.1.2).

- [ ] **Step 4: 커밋**

```bash
git add tests/workflow/test_designed_run_state_readback.py
git commit -m "test(workflow): measure whether a designed run's checkpoint reads back through the static graph"
```

---

### Task 2: 토폴로지 직렬화 왕복

**Files:**
- Modify: `neos/workflow/topology.py`
- Test: `tests/workflow/test_topology_serialization.py` (Create)

**Interfaces:**
- Consumes: `GraphTopology`(`topology.py`), `topology_hash`(`graph_design_ledger.py:219`)
- Produces:
  - `topology_to_payload(topology: GraphTopology) -> dict[str, Any]`
  - `topology_from_payload(payload: Mapping[str, Any]) -> GraphTopology`
  - 역직렬화 실패 시 `TopologyPayloadError(ValueError)`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/workflow/test_topology_serialization.py`:

```python
"""토폴로지 JSON 왕복 -- 해시가 보존되면 무손실이다.

필드를 손으로 나열해 비교하지 않는 이유는 그 목록이 `GraphTopology` 에 필드가
늘어나는 순간 낡기 때문이다. `topology_hash` 는 논리적 정체성을 재므로, 해시가
같으면 그래프로서 같다.
"""

import pytest

from neos.workflow.graph_design_ledger import topology_hash
from neos.workflow.topology import (
    GRAPH_ENTRY_WRITES,
    GraphTopology,
    TopologyPayloadError,
    topology_from_payload,
    topology_to_payload,
)

_TOPOLOGY = GraphTopology(
    nodes=("query_classifier", "response_generator"),
    edges=(
        ("__start__", "query_classifier"),
        ("query_classifier", "response_generator"),
        ("response_generator", "__end__"),
    ),
    loop_bounds={"query_classifier": 3},
    initial_writes=GRAPH_ENTRY_WRITES,
)


def test_the_round_trip_preserves_the_hash():
    restored = topology_from_payload(topology_to_payload(_TOPOLOGY))

    assert topology_hash(restored) == topology_hash(_TOPOLOGY)


def test_the_payload_survives_json():
    import json

    restored = topology_from_payload(json.loads(json.dumps(topology_to_payload(_TOPOLOGY))))

    assert topology_hash(restored) == topology_hash(_TOPOLOGY)


def test_tuples_come_back_as_tuples():
    """JSON 은 list 만 안다. 되돌려 놓지 않으면 `GraphTopology` 가
    hashable 하지 않게 되고 frozen dataclass 의 의미가 깨진다."""
    restored = topology_from_payload(topology_to_payload(_TOPOLOGY))

    assert isinstance(restored.nodes, tuple)
    assert all(isinstance(edge, tuple) for edge in restored.edges)


def test_a_payload_missing_nodes_is_rejected():
    with pytest.raises(TopologyPayloadError):
        topology_from_payload({"edges": []})


def test_a_malformed_edge_is_rejected():
    """간선이 2-튜플이 아니면 그래프를 지을 수 없다. 여기서 막지 않으면
    `build_ephemeral_workflow` 안에서 알아보기 어려운 모양으로 터진다."""
    with pytest.raises(TopologyPayloadError):
        topology_from_payload({"nodes": ["a"], "edges": [["a"]]})
```

- [ ] **Step 2: 실패를 확인한다**

Run: `.venv/bin/python -m pytest tests/workflow/test_topology_serialization.py -q -p no:randomly`
Expected: FAIL — `ImportError: cannot import name 'topology_to_payload'`

- [ ] **Step 3: 구현한다**

`neos/workflow/topology.py` 끝에 추가:

```python
class TopologyPayloadError(ValueError):
    """저장된 토폴로지 페이로드를 `GraphTopology` 로 되돌릴 수 없다.

    재개 경로가 이것을 잡아 **정적으로 흐르지 않고** 거부한다 -- 복원할 수 없는
    토폴로지로 재개하는 것은 다른 그래프로 재개하는 것과 같다.
    """


def topology_to_payload(topology: GraphTopology) -> dict[str, Any]:
    """`GraphTopology` 를 JSON 에 실을 수 있는 dict 로 만든다.

    상태에 실려 체크포인트에 저장되므로 JSON 안전해야 한다. tuple 은 list 가
    되고 `topology_from_payload` 가 되돌린다.
    """
    return {
        "nodes": list(topology.nodes),
        "edges": [list(edge) for edge in topology.edges],
        "loop_bounds": dict(topology.loop_bounds),
        "initial_writes": sorted(topology.initial_writes),
    }


def topology_from_payload(payload: Mapping[str, Any]) -> GraphTopology:
    """`topology_to_payload` 의 역. 모양이 틀리면 `TopologyPayloadError`.

    관대하게 받지 않는다 -- 여기서 통과시킨 이상한 페이로드는
    `build_ephemeral_workflow` 안에서 알아보기 어려운 예외가 된다.
    """
    if not isinstance(payload, Mapping):
        raise TopologyPayloadError(f"페이로드가 매핑이 아니다: {type(payload).__name__}")

    try:
        raw_nodes = payload["nodes"]
        raw_edges = payload["edges"]
    except KeyError as error:
        raise TopologyPayloadError(f"페이로드에 {error} 가 없다") from error

    if not isinstance(raw_nodes, (list, tuple)):
        raise TopologyPayloadError("nodes 가 시퀀스가 아니다")
    if not isinstance(raw_edges, (list, tuple)):
        raise TopologyPayloadError("edges 가 시퀀스가 아니다")

    edges: list[tuple[str, str]] = []
    for edge in raw_edges:
        if not isinstance(edge, (list, tuple)) or len(edge) != 2:
            raise TopologyPayloadError(f"간선이 2-튜플이 아니다: {edge!r}")
        edges.append((str(edge[0]), str(edge[1])))

    return GraphTopology(
        nodes=tuple(str(node) for node in raw_nodes),
        edges=tuple(edges),
        loop_bounds=dict(payload.get("loop_bounds") or {}),
        initial_writes=frozenset(payload.get("initial_writes") or ()),
    )
```

`Any` 와 `Mapping` 이 이미 임포트돼 있는지 확인하고, 없으면 파일 상단에 더한다.

- [ ] **Step 4: 통과를 확인한다**

Run: `.venv/bin/python -m pytest tests/workflow/test_topology_serialization.py -q -p no:randomly`
Expected: PASS (5건)

- [ ] **Step 5: `initial_writes` 의 실제 타입을 확인한다**

`GraphTopology.initial_writes` 가 `frozenset` 인지 다른 것인지 정의를 읽고
(`neos/workflow/topology.py:71` 근처), `topology_from_payload` 의 생성이 그 타입과
맞는지 본다. 다르면 그 타입으로 고치고 Step 4 를 다시 돌린다.

- [ ] **Step 6: 커밋**

```bash
git add neos/workflow/topology.py tests/workflow/test_topology_serialization.py
git commit -m "feat(workflow): serialise a graph topology to and from a json payload"
```

---

### Task 3: 설계된 run 이 자기 토폴로지를 상태에 남긴다

**Files:**
- Modify: `neos/workflow/state.py` (`AgentState`)
- Modify: `neos/workflow/execution_graph.py` (`ExecutionGraph`, `static_execution_graph`)
- Modify: `neos/workflow/graph.py` (`_resolve_execution_graph` 의 designed 분기, `_create_initial_state` 호출부)
- Test: `tests/workflow/test_execution_topology_state.py` (Create)

**Interfaces:**
- Consumes: `topology_to_payload`(Task 2), `ExecutionGraph`(기존, `execution_graph.py:40`)
- Produces:
  - `AgentState["execution_topology"]: dict[str, Any] | None`
  - `ExecutionGraph.topology: GraphTopology | None` (정적이면 `None`)

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/workflow/test_execution_topology_state.py`:

```python
"""설계된 run 은 자기 토폴로지를 상태에 남기고, 정적 run 은 남기지 않는다.

재개 경로가 읽을 유일한 근거다. 남기지 않으면 재개는 어느 그래프로 멈췄는지
알 수 없고, 정적 run 에 남기면 재개가 없는 토폴로지를 지으려 든다.
"""

import pytest

from neos.config import settings as settings_module
from neos.workflow.graph import MultiAgentWorkflow
from neos.workflow.graph_design_ledger import topology_hash
from neos.workflow.topology import (
    GRAPH_ENTRY_WRITES,
    GraphTopology,
    topology_from_payload,
)

_CHAIN = (
    "query_classifier",
    "search_orchestrator",
    "analysis_orchestrator",
    "generation_orchestrator",
    "response_generator",
)
_DESIGNED = GraphTopology(
    nodes=_CHAIN,
    edges=(
        ("__start__", _CHAIN[0]),
        *((_CHAIN[i], _CHAIN[i + 1]) for i in range(len(_CHAIN) - 1)),
        (_CHAIN[-1], "__end__"),
    ),
    initial_writes=GRAPH_ENTRY_WRITES,
)


class _FakeDesigner:
    async def design(self, request):
        return _DESIGNED


def _enable_design(monkeypatch):
    config = settings_module.settings.config
    monkeypatch.setattr(config.workflow, "graph_design_enabled", True)


@pytest.mark.asyncio
async def test_a_designed_graph_carries_its_topology(monkeypatch):
    workflow = MultiAgentWorkflow()
    _enable_design(monkeypatch)
    monkeypatch.setattr(workflow, "_build_graph_designer", lambda: _FakeDesigner())
    await workflow._ensure_graph_initialized(use_checkpointer=False)

    resolved = await workflow._resolve_execution_graph(
        user_input={"query": "테스트 질의", "session_id": "s1"},
        use_checkpointer=False,
        span=None,
    )

    assert resolved.source == "designed"
    assert resolved.topology is not None
    assert topology_hash(resolved.topology) == resolved.topology_hash


@pytest.mark.asyncio
async def test_a_static_graph_carries_no_topology(monkeypatch):
    """정적 run 의 `topology` 는 None 이다. 여기에 정적 토폴로지를 실으면
    재개가 정적 run 마다 그래프를 새로 짓게 되고, 그것은 지금 동작을 바꾼다."""
    workflow = MultiAgentWorkflow()
    await workflow._ensure_graph_initialized(use_checkpointer=False)

    resolved = await workflow._resolve_execution_graph(
        user_input={"query": "테스트 질의", "session_id": "s1"},
        use_checkpointer=False,
        span=None,
    )

    assert resolved.source == "static"
    assert resolved.topology is None


@pytest.mark.asyncio
async def test_the_state_payload_round_trips_back_to_the_same_graph(monkeypatch):
    """상태에 실리는 것은 페이로드이고, 그것이 같은 그래프로 되돌아와야 한다."""
    workflow = MultiAgentWorkflow()
    _enable_design(monkeypatch)
    monkeypatch.setattr(workflow, "_build_graph_designer", lambda: _FakeDesigner())
    await workflow._ensure_graph_initialized(use_checkpointer=False)

    resolved = await workflow._resolve_execution_graph(
        user_input={"query": "테스트 질의", "session_id": "s1"},
        use_checkpointer=False,
        span=None,
    )
    payload = workflow.execution_topology_payload(resolved)

    assert topology_hash(topology_from_payload(payload)) == resolved.topology_hash


def test_a_static_graph_yields_no_payload():
    workflow = MultiAgentWorkflow()

    from neos.workflow.execution_graph import ExecutionGraph

    static = ExecutionGraph(
        compiled=object(), nodes=("a",), topology_hash="x", source="static", topology=None
    )

    assert workflow.execution_topology_payload(static) is None
```

- [ ] **Step 2: 실패를 확인한다**

Run: `.venv/bin/python -m pytest tests/workflow/test_execution_topology_state.py -q -p no:randomly`
Expected: FAIL — `ExecutionGraph` 에 `topology` 인자가 없고
`execution_topology_payload` 가 없다

- [ ] **Step 3: `ExecutionGraph` 에 필드를 더한다**

`neos/workflow/execution_graph.py` 의 dataclass 에 필드 하나를 추가한다
(기본값 `None` 으로 두어 기존 생성자 호출을 깨지 않는다):

```python
    compiled: Any
    nodes: tuple[str, ...]
    topology_hash: str
    source: Literal["static", "designed"]
    # 설계된 run 이 재개될 때 다시 지을 원본. 정적이면 None 이다.
    #
    # `topology_hash` 로는 복원할 수 없다 -- 해시는 정체성이지 내용이 아니다.
    # 그리고 정적 run 에 정적 토폴로지를 실지 않는 이유는, 재개가 정적 run 마다
    # 그래프를 새로 짓게 되어 지금 동작을 바꾸기 때문이다.
    topology: "GraphTopology | None" = None
```

`GraphTopology` 임포트를 파일 상단에 더한다(순환 임포트가 나면
`from __future__ import annotations` 와 `TYPE_CHECKING` 을 쓴다).

- [ ] **Step 4: 설계 분기가 토폴로지를 싣게 한다**

`neos/workflow/graph.py` 의 `_resolve_execution_graph` 마지막 `return`:

```python
        return ExecutionGraph(
            compiled=compiled,
            nodes=outcome.topology.nodes,
            topology_hash=topology_hash(outcome.topology),
            source="designed",
            topology=outcome.topology,
        )
```

- [ ] **Step 5: 페이로드 헬퍼를 더한다**

`MultiAgentWorkflow` 에 메서드 하나:

```python
    def execution_topology_payload(
        self, execution_graph: ExecutionGraph
    ) -> dict[str, Any] | None:
        """이 실행이 상태에 남길 토폴로지 페이로드. 정적이면 None.

        재개(`approval_handlers`)가 읽는 유일한 근거이며, 상태에 실리므로
        체크포인트와 **같은 수명**을 갖는다 -- 곁 테이블을 두지 않은 이유가
        그것이다(스펙 §3.1).
        """
        if execution_graph.topology is None:
            return None
        return topology_to_payload(execution_graph.topology)
```

`topology_to_payload` 임포트를 더한다.

- [ ] **Step 6: 상태 키를 선언한다**

`neos/workflow/state.py` 의 `AgentState` 에:

```python
    # 이 실행이 어떤 그래프로 돌고 있는가. 정적 실행이면 None.
    #
    # **오케스트레이터만 쓴다. 어떤 노드도 읽지 않는다.** 노드가 읽으면 자기
    # 그래프 모양에 따라 행동을 바꾸게 되고, 그것은 C1 계약(`reads`/`writes`)이
    # 표현하려는 것과 정반대 방향의 결합이다. 승인 재개가 "이 스레드가 어떤
    # 토폴로지로 멈췄는가" 를 복원하는 데만 쓴다.
    execution_topology: NotRequired[dict[str, Any] | None]
```

`NotRequired` 가 임포트돼 있는지 확인한다(`typing`).

- [ ] **Step 7: 초기 상태에 싣는다**

`neos/workflow/graph.py:2713` 근처, `initial_state` 를 만든 뒤
`execution_graph` 가 결정된 지점에서:

```python
            initial_state["execution_topology"] = self.execution_topology_payload(
                execution_graph
            )
```

`execution_graph` 가 `initial_state` 보다 **뒤에** 만들어지면 그 순서에 맞춰
넣는다. 두 값이 다 있는 첫 지점이면 어디든 된다.

- [ ] **Step 8: 통과를 확인한다**

Run: `.venv/bin/python -m pytest tests/workflow/test_execution_topology_state.py -q -p no:randomly`
Expected: PASS (4건)

- [ ] **Step 9: 회귀를 본다**

Run: `.venv/bin/python -m pytest tests/workflow -q -p no:randomly`
Expected: 전부 통과. `ExecutionGraph` 생성자를 부르는 기존 테스트가 깨지면
기본값 `None` 이 빠진 것이다.

- [ ] **Step 10: 커밋**

```bash
git add neos/workflow/state.py neos/workflow/execution_graph.py neos/workflow/graph.py tests/workflow/test_execution_topology_state.py
git commit -m "feat(workflow): record the designed topology in the run state"
```

---

### Task 4: 재개가 같은 토폴로지로 그래프를 다시 짓는다

⚠️ **Task 1 의 판정을 먼저 읽는다.** 가정이 깨졌으면 Step 3 의 상태 조회를
`PostgreSQLCheckpointer.aget_tuple(config)` 직접 호출로 바꾼다 — 나머지 단계는
그대로다.

**Files:**
- Create: `neos/workflow/resume_graph.py`
- Modify: `neos/api/handlers/approval_handlers.py:123-200`
- Test: `tests/workflow/test_resume_graph.py` (Create)

**왜 별도 모듈인가:** `approval_handlers.py` 는 HTTP 관심사(소유권·세션·스트림)를
들고 있고, 그래프 복원은 워크플로 관심사다. 섞으면 복원 로직을 테스트하려고
FastAPI 요청을 지어야 한다.

**Interfaces:**
- Consumes: `topology_from_payload`·`TopologyPayloadError`(Task 2),
  `build_ephemeral_workflow`·`_INTERRUPT_GATED_NODES`(`graph.py`),
  `validate_topology`(`topology.py:112`), `NODE_CONTRACTS`(`contracts.py`)
- Produces:
  - `class ResumeGraphUnavailable(Exception)` — `reason: str` 을 들고 있다
  - `async def resume_graph_for(state_values: Mapping[str, Any], *, workflow, checkpointer) -> Any`
    설계된 run 이면 재구성한 그래프를, 정적 run 이면 `workflow.graph` 를 돌려준다

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/workflow/test_resume_graph.py`:

```python
"""재개용 그래프 복원 -- 같은 토폴로지로 짓거나, 짓지 못하면 거부한다.

정적으로 흐르는 경로가 없다는 것이 이 모듈의 요점이다. 스펙 §2.1: 조용한 정적
재개는 복구가 아니라 원래 버그이며, 사용자에게는 승인이 처리된 것으로 보이고
실제로는 설계가 의도한 것과 다른 파이프라인이 돈다.
"""

import pytest
from langgraph.checkpoint.memory import MemorySaver

from neos.workflow.graph import MultiAgentWorkflow
from neos.workflow.resume_graph import ResumeGraphUnavailable, resume_graph_for
from neos.workflow.topology import GRAPH_ENTRY_WRITES, GraphTopology, topology_to_payload

_CHAIN = (
    "query_classifier",
    "search_orchestrator",
    "analysis_orchestrator",
    "generation_orchestrator",
    "response_generator",
)
_DESIGNED = GraphTopology(
    nodes=_CHAIN,
    edges=(
        ("__start__", _CHAIN[0]),
        *((_CHAIN[i], _CHAIN[i + 1]) for i in range(len(_CHAIN) - 1)),
        (_CHAIN[-1], "__end__"),
    ),
    initial_writes=GRAPH_ENTRY_WRITES,
)


async def _workflow():
    workflow = MultiAgentWorkflow()
    await workflow._ensure_graph_initialized(use_checkpointer=True)
    return workflow


@pytest.mark.asyncio
async def test_a_static_run_resumes_on_the_static_graph():
    workflow = await _workflow()

    graph = await resume_graph_for(
        {"execution_topology": None}, workflow=workflow, checkpointer=MemorySaver()
    )

    assert graph is workflow.graph


@pytest.mark.asyncio
async def test_a_designed_run_resumes_on_a_rebuilt_graph():
    """라벨이 아니라 **컴파일된 그래프 자체**를 본다. 정적 그래프에
    source='designed' 를 붙여 놓아도 통과하는 단언은 이 배선을 지키지 못한다
    (G2 스펙 서두의 경고)."""
    workflow = await _workflow()

    graph = await resume_graph_for(
        {"execution_topology": topology_to_payload(_DESIGNED)},
        workflow=workflow,
        checkpointer=MemorySaver(),
    )

    assert graph is not workflow.graph
    assert set(_CHAIN).issubset(set(graph.nodes))


@pytest.mark.asyncio
async def test_a_malformed_payload_is_refused_not_downgraded():
    workflow = await _workflow()

    with pytest.raises(ResumeGraphUnavailable) as caught:
        await resume_graph_for(
            {"execution_topology": {"nodes": "not-a-list"}},
            workflow=workflow,
            checkpointer=MemorySaver(),
        )

    assert "payload" in caught.value.reason


@pytest.mark.asyncio
async def test_a_topology_that_no_longer_validates_is_refused():
    """멈춘 뒤 배포가 계약을 바꾸면 저장된 토폴로지는 더 이상 유효하지 않다.
    `build_ephemeral_workflow` 는 재검증하지 않는다고 자기 독스트링에 적어
    뒀으므로(스펙 §2.2), 재검증은 이 경로가 한다."""
    workflow = await _workflow()
    unknown = GraphTopology(
        nodes=("node_that_does_not_exist",),
        edges=(("__start__", "node_that_does_not_exist"), ("node_that_does_not_exist", "__end__")),
        initial_writes=GRAPH_ENTRY_WRITES,
    )

    with pytest.raises(ResumeGraphUnavailable) as caught:
        await resume_graph_for(
            {"execution_topology": topology_to_payload(unknown)},
            workflow=workflow,
            checkpointer=MemorySaver(),
        )

    assert "valid" in caught.value.reason


@pytest.mark.asyncio
async def test_the_rebuilt_graph_gates_the_same_nodes():
    """`interrupt_before` 는 저장하지 않고 지금 정책으로 다시 계산한다
    (스펙 §3.4). 게이트 노드가 있는 토폴로지는 재개 그래프에서도 게이트된다."""
    workflow = await _workflow()
    gated_chain = (*_CHAIN[:-1], "execution_approval", _CHAIN[-1])
    gated = GraphTopology(
        nodes=gated_chain,
        edges=(
            ("__start__", gated_chain[0]),
            *((gated_chain[i], gated_chain[i + 1]) for i in range(len(gated_chain) - 1)),
            (gated_chain[-1], "__end__"),
        ),
        initial_writes=GRAPH_ENTRY_WRITES,
    )

    graph = await resume_graph_for(
        {"execution_topology": topology_to_payload(gated)},
        workflow=workflow,
        checkpointer=MemorySaver(),
    )

    assert "execution_approval" in graph.interrupt_before_nodes
```

- [ ] **Step 2: 실패를 확인한다**

Run: `.venv/bin/python -m pytest tests/workflow/test_resume_graph.py -q -p no:randomly`
Expected: FAIL — `ModuleNotFoundError: neos.workflow.resume_graph`

- [ ] **Step 3: 구현한다**

`neos/workflow/resume_graph.py`:

```python
"""승인 재개용 그래프 복원.

설계된 run 이 승인 게이트에서 멈추면, 재개는 **멈출 때와 같은 토폴로지** 위에서
일어나야 한다. 설계된 그래프는 호출 스코프의 ephemeral 객체라 캐시되지 않으므로
(G2 스펙 §2.3 -- 공유 인스턴스에 두면 요청 간 경쟁한다), 상태에 실린 토폴로지로
**다시 짓는다.**

**정적으로 흐르는 경로가 없다.** 복원할 수 없으면 예외를 올리고 호출자가 거부한다.
정적 그래프로 재개하면 LangGraph 는 체크포인트의 채널을 읽고 자기 간선을 따라
계속 가므로, 사용자에게는 승인이 처리된 것으로 보이면서 설계가 의도한 것과 다른
파이프라인이 돈다 -- §3.2가 이 저장소의 관통 주제로 적은 "모든 실패가 성공처럼
보였다" 의 재개 판이다.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from neos.workflow.contracts import NODE_CONTRACTS
from neos.workflow.topology import (
    TopologyPayloadError,
    topology_from_payload,
    validate_topology,
)

if TYPE_CHECKING:
    from neos.workflow.graph import MultiAgentWorkflow


class ResumeGraphUnavailable(Exception):
    """이 스레드를 지금 재개할 수 없다.

    `reason` 은 사람이 읽을 사유이며 로그와 응답에 그대로 실린다. 호출자는
    이것을 503 으로 바꾼다 -- "요청이 틀렸다" 가 아니라 "서버가 지금 이 스레드를
    재개할 수 없다" 이고, 계약을 되돌리는 배포가 나가면 같은 요청이 성공한다.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


async def resume_graph_for(
    state_values: Mapping[str, Any],
    *,
    workflow: "MultiAgentWorkflow",
    checkpointer: Any,
) -> Any:
    """재개에 쓸 컴파일된 그래프를 돌려준다.

    정적 run(`execution_topology` 가 없거나 None)이면 정적 그래프를 그대로
    돌려준다 -- 지금 동작이며 바꾸지 않는다.
    """
    from neos.workflow.graph import _INTERRUPT_GATED_NODES, build_ephemeral_workflow

    payload = state_values.get("execution_topology")
    if not payload:
        return workflow.graph

    try:
        topology = topology_from_payload(payload)
    except TopologyPayloadError as error:
        raise ResumeGraphUnavailable(
            f"stored topology payload could not be read: {error}"
        ) from error

    # `build_ephemeral_workflow` 는 재검증하지 않는다 -- 자기 독스트링이 "승인된
    # 토폴로지만 들어온다는 전제 위에 서 있다" 고 적는다. 그 전제는 설계 직후에는
    # 참이고 재개 시점에는 참이 아니다: 멈춘 뒤 배포가 노드를 없애거나 requires 를
    # 바꿀 수 있다. LLM 을 쓰지 않으므로 값싸다.
    violations = validate_topology(topology, NODE_CONTRACTS)
    if violations:
        raise ResumeGraphUnavailable(
            f"stored topology is no longer valid against the current contracts: {violations}"
        )

    # `interrupt_before` 는 저장하지 않고 다시 계산한다 -- 저장하면 게이트 정책이
    # 바뀌었을 때 옛 목록으로 재개한다.
    interrupt_before = sorted(set(topology.nodes) & _INTERRUPT_GATED_NODES)

    try:
        return build_ephemeral_workflow(
            workflow,
            topology,
            checkpointer=checkpointer,
            interrupt_before=interrupt_before,
        )
    except Exception as error:  # noqa: BLE001 -- 어떤 실패든 재개는 거부다
        raise ResumeGraphUnavailable(
            f"could not rebuild the designed graph: {type(error).__name__}: {error}"
        ) from error
```

- [ ] **Step 4: `validate_topology` 의 실제 시그니처에 맞춘다**

`neos/workflow/topology.py:112` 를 읽고 인자와 반환값을 확인한다. 위반 목록을
돌려주는지, 다른 모양인지에 따라 `violations` 판정을 고친다. 그리고
`test_a_topology_that_no_longer_validates_is_refused` 의 `"valid" in reason`
단언이 실제 사유 문자열과 맞는지 본다.

- [ ] **Step 5: 통과를 확인한다**

Run: `.venv/bin/python -m pytest tests/workflow/test_resume_graph.py -q -p no:randomly`
Expected: PASS (5건)

- [ ] **Step 6: 커밋**

```bash
git add neos/workflow/resume_graph.py tests/workflow/test_resume_graph.py
git commit -m "feat(workflow): rebuild the designed graph for approval resume"
```

---

### Task 5: 재개 핸들러가 복원된 그래프를 쓰고, 실패하면 503 으로 거부한다

**Files:**
- Modify: `neos/api/handlers/approval_handlers.py:123-200`
- Test: `tests/api/test_approval_resume_graph.py` (Create)

**Interfaces:**
- Consumes: `resume_graph_for`·`ResumeGraphUnavailable`(Task 4)
- Produces: 없음 (핸들러 동작 변경)

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/api/test_approval_resume_graph.py`:

```python
"""재개 핸들러가 복원된 그래프를 쓰는가, 그리고 못 쓰면 무엇을 하는가.

핸들러 전체를 HTTP 로 돌리지 않고 그래프 선택 지점만 본다 -- 이 태스크가
바꾸는 것이 그것이고, 소유권·세션·스트림은 기존 테스트가 덮는다.
"""

import pytest
from fastapi import HTTPException

from neos.workflow.resume_graph import ResumeGraphUnavailable


@pytest.mark.asyncio
async def test_an_unavailable_resume_graph_becomes_a_503(monkeypatch):
    """정적으로 흐르지 않는다. 흐르면 사용자는 승인이 처리됐다고 보고
    실제로는 다른 파이프라인이 돈다(스펙 §2.1)."""
    from neos.api.handlers import approval_handlers

    async def _refuse(*args, **kwargs):
        raise ResumeGraphUnavailable("stored topology is no longer valid")

    monkeypatch.setattr(approval_handlers, "resume_graph_for", _refuse)

    with pytest.raises(HTTPException) as caught:
        await approval_handlers._resolve_resume_graph(
            state_values={"execution_topology": {"nodes": ["a"], "edges": []}},
            workflow=object(),
            checkpointer=None,
        )

    assert caught.value.status_code == 503
    assert "topology" in caught.value.detail


@pytest.mark.asyncio
async def test_a_resolvable_graph_is_returned_as_is(monkeypatch):
    from neos.api.handlers import approval_handlers

    sentinel = object()

    async def _resolve(*args, **kwargs):
        return sentinel

    monkeypatch.setattr(approval_handlers, "resume_graph_for", _resolve)

    graph = await approval_handlers._resolve_resume_graph(
        state_values={"execution_topology": None},
        workflow=object(),
        checkpointer=None,
    )

    assert graph is sentinel
```

- [ ] **Step 2: 실패를 확인한다**

Run: `.venv/bin/python -m pytest tests/api/test_approval_resume_graph.py -q -p no:randomly`
Expected: FAIL — `_resolve_resume_graph` 가 없다

- [ ] **Step 3: 얇은 어댑터를 더한다**

`neos/api/handlers/approval_handlers.py` 에 임포트와 함수를 더한다:

```python
from neos.workflow.resume_graph import ResumeGraphUnavailable, resume_graph_for


async def _resolve_resume_graph(*, state_values, workflow, checkpointer):
    """재개에 쓸 그래프를 고르고, 고를 수 없으면 503 으로 거부한다.

    **정적으로 내려가지 않는다.** 복원 실패 시 정적 그래프로 재개하는 것이
    이 작업이 고치는 원래 버그다 -- 그 run 은 설계가 의도한 것과 다른 경로로
    계속 가면서 성공한 것처럼 보인다.

    503 인 이유: 이것은 "요청이 틀렸다" 가 아니라 "서버가 지금 이 스레드를
    재개할 수 없다" 이고, 계약을 되돌리는 배포가 나가면 같은 요청이 성공한다.
    초기화되지 않은 그래프에 대해 이 핸들러가 이미 쓰는 코드와 같다.
    """
    try:
        return await resume_graph_for(
            state_values, workflow=workflow, checkpointer=checkpointer
        )
    except ResumeGraphUnavailable as error:
        logger.error(f"[ApprovalHandler] resume graph unavailable: {error.reason}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"이 실행을 재개할 수 없습니다 (topology): {error.reason}",
        ) from error
```

- [ ] **Step 4: 재개 경로를 그 그래프로 바꾼다**

`approval_handlers.py:130` 의 `graph = multi_agent_workflow.graph` 는 **상태를
읽는 데만** 쓰고, `aget_state` 로 상태를 얻은 **뒤** 재개용 그래프를 고른다.
`current_graph_state` 를 얻는 블록(139줄) 다음에:

```python
    resume_graph = await _resolve_resume_graph(
        state_values=current_graph_state.values,
        workflow=multi_agent_workflow,
        checkpointer=multi_agent_workflow.graph.checkpointer,
    )
```

그리고 그 아래의 `graph.aupdate_state(...)`(176줄)와
`graph.astream(None, config=config)`(198줄)를 **`resume_graph`** 로 바꾼다.
`graph.aget_state`(139줄)는 **바꾸지 않는다** — 상태를 읽는 것은 그래프 선택보다
먼저 일어나야 한다.

> ⚠️ Task 1 이 "성립하지 않는다" 로 판정했으면 139줄의 `graph.aget_state` 를
> 체크포인터 직접 조회로 바꾼다. 그 경우에도 이 태스크의 나머지는 같다.

- [ ] **Step 5: 통과를 확인한다**

Run: `.venv/bin/python -m pytest tests/api/test_approval_resume_graph.py -q -p no:randomly`
Expected: PASS (2건)

- [ ] **Step 6: 재개가 무엇으로 재개했는지 원장에 남긴다 (스펙 §4)**

이 단계가 없으면 **재개가 성공했는지 아무도 알 수 없다.** 스펙 §1의 관문이
"재개에 쓰인 그래프의 토폴로지 해시가 멈출 때의 것과 같다" 인데, 해시를 남기지
않으면 그 관문은 테스트 안에서만 참이고 프로덕션에서는 검증할 수 없다.

새 이벤트 kind 를 만들지 않는다(Global Constraints). 기존 로거에 싣는다.

먼저 테스트에 한 건을 더한다 — `tests/api/test_approval_resume_graph.py`:

```python
@pytest.mark.asyncio
async def test_a_designed_resume_records_which_topology_it_used(monkeypatch, caplog):
    """해시를 남기지 않으면 스펙 §1의 관문을 프로덕션에서 확인할 수 없다.
    `graph_design_accepted` 의 topology_hash 와 조인할 수 있어야 한다."""
    import logging

    from neos.api.handlers import approval_handlers
    from neos.workflow.topology import GRAPH_ENTRY_WRITES, GraphTopology, topology_to_payload

    topology = GraphTopology(
        nodes=("query_classifier", "response_generator"),
        edges=(
            ("__start__", "query_classifier"),
            ("query_classifier", "response_generator"),
            ("response_generator", "__end__"),
        ),
        initial_writes=GRAPH_ENTRY_WRITES,
    )
    sentinel = object()

    async def _resolve(*args, **kwargs):
        return sentinel

    monkeypatch.setattr(approval_handlers, "resume_graph_for", _resolve)

    with caplog.at_level(logging.INFO):
        await approval_handlers._resolve_resume_graph(
            state_values={"execution_topology": topology_to_payload(topology)},
            workflow=object(),
            checkpointer=None,
        )

    assert any("topology_hash" in record.message for record in caplog.records)
```

그리고 `_resolve_resume_graph` 의 성공 경로에 한 줄을 더한다:

```python
        graph = await resume_graph_for(
            state_values, workflow=workflow, checkpointer=checkpointer
        )
        payload = state_values.get("execution_topology")
        if payload:
            from neos.workflow.graph_design_ledger import topology_hash
            from neos.workflow.topology import topology_from_payload

            logger.info(
                "[ApprovalHandler] resumed on the designed graph "
                f"topology_hash={topology_hash(topology_from_payload(payload))}"
            )
        return graph
```

`return await resume_graph_for(...)` 였던 것을 위 형태로 바꾼다.

Run: `.venv/bin/python -m pytest tests/api/test_approval_resume_graph.py -q -p no:randomly`
Expected: PASS (3건)

- [ ] **Step 7: 기존 승인 테스트가 여전히 도는지 본다**

Run: `.venv/bin/python -m pytest tests/api -q -p no:randomly`
Expected: 전부 통과

- [ ] **Step 8: 커밋**

```bash
git add neos/api/handlers/approval_handlers.py tests/api/test_approval_resume_graph.py
git commit -m "feat(api): resume approvals on the graph the run actually used"
```

---

### Task 6: 우회로를 걷어낸다

**Files:**
- Modify: `neos/workflow/graph.py` (`_resolve_execution_graph` 의 게이트 폴백)
- Modify: `tests/workflow/test_graph_design_wiring.py`

**Interfaces:**
- Consumes: Task 5 의 재개 경로가 있다는 사실
- Produces: 없음

- [ ] **Step 1: 기대를 뒤집는 테스트를 먼저 고친다**

`tests/workflow/test_graph_design_wiring.py` 의
`test_an_approval_gate_falls_back_even_when_a_checkpointer_exists` 를 다시
`test_an_approval_gate_with_a_checkpointer_runs_as_designed` 로 되돌리되,
**왕복한 계보를 독스트링에 남긴다**:

```python
@pytest.mark.asyncio
async def test_an_approval_gate_with_a_checkpointer_runs_as_designed(
    monkeypatch,
) -> None:
    """체크포인터가 있으면 게이트가 들어간 설계도 그대로 돈다.

    ⚠️ **이 기대는 두 번 뒤집혔다. 계보를 남긴다.**
    처음에는 이 이름이었고, 2026-08-25 에
    `test_an_approval_gate_falls_back_even_when_a_checkpointer_exists` 로
    뒤집혔다 -- 설계된 run 이 게이트에서 멈추면 재개가 **정적 그래프** 위에서
    일어나 다른 파이프라인이 돌기 때문이었고, 그때는 재개 경로가 없어서
    "멈출 수 있는 설계를 만들지 않는다" 가 유일한 안전책이었다.

    지금은 재개가 상태에 실린 토폴로지로 그래프를 다시 짓는다
    (`neos/workflow/resume_graph.py`). 우회로가 필요 없어졌으므로 되돌린다.

    **이 테스트가 지키는 돌연변이:** `interrupt_before` 계산이 죽어 항상 빈
    목록이 되면 게이트가 걸리지 않아 사람 승인이 조용히 생략된다.
    """

    from langgraph.checkpoint.memory import MemorySaver

    saver = MemorySaver()

    async def _fake_get_checkpointer():
        return saver

    monkeypatch.setattr(
        "neos.workflow.graph.get_checkpointer", _fake_get_checkpointer
    )

    _, resolved = await _resolve_with(
        monkeypatch, _FakeDesigner(_GATED), use_checkpointer=True
    )

    assert resolved.source == "designed"
    assert resolved.nodes == _GATED_CHAIN
    # 게이트가 실제로 걸렸는가 -- 노드만 있고 인터럽트가 없으면 사람 승인이
    # 조용히 생략된다.
    assert "execution_approval" in resolved.compiled.interrupt_before_nodes
```

- [ ] **Step 2: 실패를 확인한다**

Run: `.venv/bin/python -m pytest tests/workflow/test_graph_design_wiring.py -q -p no:randomly`
Expected: FAIL — 지금은 `source == "static"` 이다

- [ ] **Step 3: 폴백을 걷어낸다**

`neos/workflow/graph.py` 의 `_resolve_execution_graph` 에서 `if interrupt_before:`
블록(폴백 + `graph_design_fallback` 이벤트) 전체를 지운다. `interrupt_before`
**계산은 남긴다** — `build_ephemeral_workflow` 에 넘겨야 한다.

`EphemeralApprovalGateUnsupported` 를 잡는 `except` 는 **지우지 않는다.** 그 예외는
체크포인터 없이 게이트 노드를 컴파일할 때 나므로 챗 경로(`use_checkpointer=False`)
에서 여전히 유효한 방어다. 다만 그 블록 앞에 붙여 둔 "지금 이 분기는 도달
불가능하다" 주석은 이제 **틀렸으므로 지운다.**

- [ ] **Step 4: 통과를 확인한다**

Run: `.venv/bin/python -m pytest tests/workflow/test_graph_design_wiring.py -q -p no:randomly`
Expected: PASS. 특히
`test_an_approval_gate_without_a_checkpointer_falls_back_instead_of_raising`
가 여전히 통과해야 한다 — 체크포인터가 없을 때는 예전 기전으로 돌아간다.
그 테스트의 독스트링에 붙은 "지금은 그 지점에 도달하지 않는다" 경고도 이제
틀렸으므로 지운다.

- [ ] **Step 5: 커밋**

```bash
git add neos/workflow/graph.py tests/workflow/test_graph_design_wiring.py
git commit -m "feat(workflow): let designed graphs carry approval gates again"
```

---

### Task 7: 왕복 통합 검증과 문서 갱신

**Files:**
- Test: `tests/workflow/test_designed_resume_round_trip.py` (Create)
- Modify: `docs/DEEP_ANALYSIS_HARNESS_ROADMAP.md` (§15.3 H3 상자, §14 상태표)
- Modify: `docs/superpowers/specs/2026-08-23-graph-designer-wiring-g2-design.md` §8

**Interfaces:**
- Consumes: Task 2~6 전부
- Produces: 없음

- [ ] **Step 1: 관문을 직접 재는 테스트를 쓴다**

`tests/workflow/test_designed_resume_round_trip.py`:

```python
"""관문: 재개에 쓰인 그래프의 토폴로지가 멈출 때의 것과 같은가.

스펙 §1이 든 관문 그 자체다. 앞선 태스크들은 조각을 고정하고, 이 테스트는
조각이 이어지는지 본다 -- 상태에 실린 페이로드가 재개 경로를 통해 같은
그래프로 돌아오는가.
"""

import pytest
from langgraph.checkpoint.memory import MemorySaver

from neos.config import settings as settings_module
from neos.workflow.graph import MultiAgentWorkflow
from neos.workflow.graph_design_ledger import topology_hash
from neos.workflow.resume_graph import resume_graph_for
from neos.workflow.topology import (
    GRAPH_ENTRY_WRITES,
    GraphTopology,
    topology_from_payload,
)

_CHAIN = (
    "query_classifier",
    "search_orchestrator",
    "analysis_orchestrator",
    "generation_orchestrator",
    "execution_approval",
    "response_generator",
)
_GATED = GraphTopology(
    nodes=_CHAIN,
    edges=(
        ("__start__", _CHAIN[0]),
        *((_CHAIN[i], _CHAIN[i + 1]) for i in range(len(_CHAIN) - 1)),
        (_CHAIN[-1], "__end__"),
    ),
    initial_writes=GRAPH_ENTRY_WRITES,
)


class _FakeDesigner:
    async def design(self, request):
        return _GATED


@pytest.mark.asyncio
async def test_the_resume_graph_has_the_topology_the_run_stopped_on(monkeypatch):
    saver = MemorySaver()

    async def _fake_get_checkpointer():
        return saver

    monkeypatch.setattr("neos.workflow.graph.get_checkpointer", _fake_get_checkpointer)
    monkeypatch.setattr(
        settings_module.settings.config.workflow, "graph_design_enabled", True
    )

    workflow = MultiAgentWorkflow()
    monkeypatch.setattr(workflow, "_build_graph_designer", lambda: _FakeDesigner())
    await workflow._ensure_graph_initialized(use_checkpointer=True)

    resolved = await workflow._resolve_execution_graph(
        user_input={"query": "승인이 필요한 질의", "session_id": "s-round-trip"},
        use_checkpointer=True,
        span=None,
    )
    assert resolved.source == "designed"

    # 오케스트레이터가 상태에 실었을 값.
    payload = workflow.execution_topology_payload(resolved)

    resume_graph = await resume_graph_for(
        {"execution_topology": payload}, workflow=workflow, checkpointer=saver
    )

    # 관문: 재개 그래프의 토폴로지 정체성이 멈출 때의 것과 같다.
    assert topology_hash(topology_from_payload(payload)) == resolved.topology_hash
    assert resume_graph is not workflow.graph
    assert set(_CHAIN).issubset(set(resume_graph.nodes))
    assert "execution_approval" in resume_graph.interrupt_before_nodes
```

- [ ] **Step 2: 돌린다**

Run: `.venv/bin/python -m pytest tests/workflow/test_designed_resume_round_trip.py -q -p no:randomly`
Expected: PASS

- [ ] **Step 3: 전체 스위트를 돌린다**

Run: `.venv/bin/python -m pytest -q -p no:randomly`
Expected: 3240 이상 passed / 0 failed (기준선은 2026-08-25 의 3240)

- [ ] **Step 4: lint**

Run: `.venv/bin/python -m ruff check neos/workflow/resume_graph.py neos/workflow/topology.py neos/workflow/graph.py neos/workflow/state.py neos/workflow/execution_graph.py neos/api/handlers/approval_handlers.py tests/workflow tests/api`
Expected: 만진 파일에 새 에러 없음 (저장소 전체는 기존 343건이 있다 — CI 는 세
디렉터리만 게이트로 건다)

- [ ] **Step 5: G2 스펙 §8 을 닫는다**

`docs/superpowers/specs/2026-08-23-graph-designer-wiring-g2-design.md` §8 의
"승인 재개는 정적 그래프에 묶여 있다" 절 **머리에** 해소 상자를 붙인다(원문은
계보를 위해 남긴다):

```markdown
> ✅ **해소됨 (2026-08-__).** 토폴로지가 `AgentState.execution_topology` 에 실려
> 체크포인트와 같은 수명을 갖고, 재개는 그것을 읽어 재검증한 뒤 그래프를 다시
> 짓는다. 설계는 `2026-08-25-designed-run-approval-resume-design.md`.
> **이 절이 이 작업을 미룬 근거("SCHEMA1 위에 마이그레이션을 한 칸 더")는
> 2026-08-25 에 SCHEMA1 이 닫히면서 사라졌고, 실제로 마이그레이션은 0건이다.**
```

- [ ] **Step 6: 로드맵을 갱신한다**

`docs/DEEP_ANALYSIS_HARNESS_ROADMAP.md`:
- §15.3 H3 상자의 차단 요인 ② 를 "우회로 채택" 에서 **"제대로 닫혔다"** 로 고치고,
  우회로가 무엇이었는지와 왜 걷혔는지를 남긴다
- §1 상태표 트랙 G 행에서 "승인 게이트가 있는 질의는 설계 경로로 가지 않는다
  (의도된 축소)" 를 지운다 — 더 이상 참이 아니다

- [ ] **Step 7: 커밋**

```bash
git add tests/workflow/test_designed_resume_round_trip.py docs/
git commit -m "test(workflow): pin the resume round trip, and close the G2 spec's open item"
```

---

## 완료 기준

1. 설계된 run 이 게이트에서 멈춘 뒤 **같은 토폴로지로** 재개된다 (Task 7 Step 1)
2. 복원할 수 없으면 **503 이고 정적으로 흐르지 않는다** (Task 5)
3. 계약이 바뀐 토폴로지는 재검증에서 걸린다 (Task 4)
4. 정적 run 의 재개는 달라지지 않는다 (Task 4 Step 1 의 첫 테스트)
5. 마이그레이션 **0건**
6. 전체 스위트 0 failed

## 이 계획이 하지 않는 것

- **`graph_design_enabled` 를 켜지 않는다.** 켜는 것은 별도 결정이고 그 관문은
  로드맵 §15.3 이 든다. 그리고 설계자 통과율 75% 는 `must_write` 수정 **이전에**
  잰 수이므로 켜기 전에 새 사전 등록으로 다시 재야 한다(§13.5).
- **상태 크기를 재지 않는다.** 설계된 run 이 아직 없어 잴 대상이 없다
  (스펙 §8). 플래그를 켠 뒤 `langgraph_checkpoints` 행 크기를 정적 run 과 비교한다.
- **기존 체크포인트를 마이그레이션하지 않는다.** 이미 멈춰 있는 run 은
  `execution_topology` 가 없어 `None` 으로 읽히고 정적 재개된다 — 지금과 같은
  동작이며, 플래그가 꺼져 있어 설계된 run 자체가 아직 없다.
