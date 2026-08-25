"""설계 경로의 배선 -- 승인되면 그 그래프가 돌고, 아니면 정적으로 내려간다.

**요청은 절대 죽지 않는다.** 설계 실패 다섯 갈래(설계자 조립 실패·타임아웃·
예외·위반·게이트 거부)가 전부 정적 폴백으로 끝난다. 조용히 끝나지도 않는다 --
`graph_design_ledger` 의 존재 이유가 "이벤트를 하나도 남기지 않는 폴백은
성공과 구별되지 않는다" 이기 때문이다.

**메타데이터만 보는 단언은 이 배선을 지키지 못한다.** `source`/`nodes` 는
`ExecutionGraph` 가 스스로 실어 나르는 라벨일 뿐이라, 정적 그래프에
`source="designed"` 를 붙여 놓아도 통과한다(실제로 `compiled=self.graph` 로
바꿔 보면 그런 단언만 있는 테스트는 전부 초록이었다). 그래서 승인 경로는
**컴파일된 그래프 자체** 를 본다: 정적 그래프와 다른 객체인가, 그리고 설계된
노드가 실제로 그 안에 배선되어 있는가.
"""

import pytest

from neos.config import settings as settings_module
from neos.workflow.graph import MultiAgentWorkflow
from neos.workflow.topology import GRAPH_ENTRY_WRITES, GraphTopology


class _FakeDesigner:
    def __init__(self, result):
        self._result = result

    async def design(self, request):
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


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


# 🔴 승인 **가능한** 최소 체인이다. `response_generator` 하나짜리 토폴로지는
# 어떤 경우에도 통과하지 못한다 -- 그 노드의 requires 는 {analysis_results,
# execution_start, generation_results, search_results} 이고
# GRAPH_ENTRY_WRITES 는 {execution_start, original_query, session_id, user_id}
# 라, 세 키를 채우는 노드가 경로에 있어야 한다. `query_classifier` 가 앞에
# 오는 이유는 세 orchestrator 가 전부 `required_agents` 를 요구하고 그것을
# 쓰는 노드가 `query_classifier` 이기 때문이다.
# 실측: 이 체인의 `validate_topology` 위반 0건.
_CHAIN = (
    "query_classifier",
    "search_orchestrator",
    "analysis_orchestrator",
    "generation_orchestrator",
    "response_generator",
)
_MINIMAL = _chain_topology(_CHAIN)

# 🔴 이 토폴로지도 **검증을 통과해야** 한다. 검증에서 거부되면 컴파일
# 단계에 도달하지 못하고, 게이트 테스트는 `source == "static"` 으로 통과하지만
# **다른 이유로** 통과한다 -- 게이트 처리를 지우고 돌려도 초록인 가짜
# 테스트가 된다. 실측: 아래 체인의 위반 0건이며
# `execution_approval.requires` 는 비어 있다.
_GATED_CHAIN = ("query_classifier", "execution_approval") + _CHAIN[1:]
_GATED = _chain_topology(_GATED_CHAIN)


def _enable_design(monkeypatch, enabled=True):
    """플래그를 `monkeypatch` 로 켠다 -- 직접 대입하면 테스트가 끝나도 전역
    설정에 남아, `-k` 필터나 `pytest-randomly` 의 무작위 순서에서 뒤에 도는
    다른 테스트가 이 플래그를 켠 채로 돈다."""

    monkeypatch.setattr(
        settings_module.settings.config.workflow, "graph_design_enabled", enabled
    )


async def _resolve_with(monkeypatch, designer, *, use_checkpointer=False):
    """`(workflow, resolved)` 를 돌려준다 -- `resolved.compiled` 가 정적
    그래프와 **다른 객체** 인지 보려면 호출한 workflow 도 필요하다."""

    workflow = MultiAgentWorkflow()
    _enable_design(monkeypatch)
    monkeypatch.setattr(workflow, "_build_graph_designer", lambda: designer)
    await workflow._ensure_graph_initialized(use_checkpointer=use_checkpointer)
    resolved = await workflow._resolve_execution_graph(
        user_input={"query": "테스트 질의", "session_id": "s1"},
        use_checkpointer=use_checkpointer,
        span=None,
    )
    return workflow, resolved


@pytest.mark.asyncio
async def test_an_approved_design_is_what_actually_runs(monkeypatch) -> None:
    workflow, resolved = await _resolve_with(monkeypatch, _FakeDesigner(_MINIMAL))

    assert resolved.source == "designed"
    assert resolved.nodes == _CHAIN
    # 🔴 여기부터가 이 테스트의 이름값이다. 위 두 줄은 `ExecutionGraph` 가
    # 실어 나르는 라벨일 뿐이라, 정적 그래프를 "designed" 라고 부르기만 해도
    # 통과한다. 실행되는 것이 **설계된 그래프** 인지는 컴파일된 객체를 봐야
    # 안다.
    assert resolved.compiled is not workflow.graph
    assert set(resolved.compiled.get_graph().nodes) >= set(_CHAIN)


@pytest.mark.asyncio
async def test_a_designer_that_cannot_be_built_falls_back_to_static(
    monkeypatch,
) -> None:
    """설계자 **조립** 은 `design_graph_or_fallback` 의 try 바깥에서 돈다 --
    인자를 만드는 코드이기 때문이다. 그래서 그 실패는 원장 함수가 잡아 주지
    않고, 막지 않으면 그대로 사용자 요청을 죽인다.

    가상의 위험이 아니다: `settings.LLM_PROVIDER` 는 자유 문자열이라
    `gemini`/`ollama` 배포에서 `resolve_model` 이 `ValueError: Unknown model
    provider` 를 던지고, API 키가 없으면 `LLMFactory.create_llm` 이 같은
    모양으로 실패한다."""

    def _explode():
        raise ValueError("Unknown model provider: gemini")

    workflow = MultiAgentWorkflow()
    _enable_design(monkeypatch)
    monkeypatch.setattr(workflow, "_build_graph_designer", _explode)
    await workflow._ensure_graph_initialized(use_checkpointer=False)

    resolved = await workflow._resolve_execution_graph(
        user_input={"query": "테스트 질의", "session_id": "s1"},
        use_checkpointer=False,
        span=None,
    )

    assert resolved.source == "static"


@pytest.mark.asyncio
async def test_a_designer_exception_falls_back_to_static(monkeypatch) -> None:
    _, resolved = await _resolve_with(
        monkeypatch, _FakeDesigner(RuntimeError("model exploded"))
    )

    assert resolved.source == "static"


@pytest.mark.asyncio
async def test_a_timeout_falls_back_to_static(monkeypatch) -> None:
    _, resolved = await _resolve_with(monkeypatch, _FakeDesigner(TimeoutError()))

    assert resolved.source == "static"


@pytest.mark.asyncio
async def test_a_topology_that_violates_the_rules_falls_back_to_static(
    monkeypatch,
) -> None:
    """`response_generator` 가 없는 설계는 mandatory 규칙에 걸린다 -- 구조적
    으로 성립해도 사용자에게 돌려줄 응답을 만들지 않는 그래프다."""

    # 실측: 위반 1건 `missing_mandatory/response_generator`.
    no_response = GraphTopology(
        nodes=("query_classifier",),
        edges=(("__start__", "query_classifier"), ("query_classifier", "__end__")),
        initial_writes=GRAPH_ENTRY_WRITES,
    )
    _, resolved = await _resolve_with(monkeypatch, _FakeDesigner(no_response))

    assert resolved.source == "static"


@pytest.mark.asyncio
async def test_an_approval_gate_without_a_checkpointer_falls_back_instead_of_raising(
    monkeypatch,
) -> None:
    """승인 게이트 노드가 들어간 설계는 **요청을 죽이지 않고** 정적으로
    내려간다.

    ⚠️ 이 테스트가 처음 쓰였을 때의 기전은 `build_ephemeral_workflow` 가
    던지는 `EphemeralApprovalGateUnsupported` 를 잡는 것이었다. 지금은 그
    지점에 **도달하지 않는다** -- 게이트 노드가 있으면 컴파일 전에 폴백한다
    (아래 테스트가 이유를 적는다). 바깥에서 본 성질은 같으므로 남긴다."""

    _, resolved = await _resolve_with(monkeypatch, _FakeDesigner(_GATED))

    assert resolved.source == "static"


@pytest.mark.asyncio
async def test_an_approval_gate_falls_back_even_when_a_checkpointer_exists(
    monkeypatch,
) -> None:
    """체크포인터가 있어도 **게이트가 들어간 설계는 쓰지 않는다.**

    ⚠️ 이 테스트는 2026-08-25 에 기대를 뒤집었다. 원래는
    `test_an_approval_gate_with_a_checkpointer_runs_as_designed` 였고
    "체크포인터가 있으면 설계된 그래프가 게이트를 걸고 돈다" 를 고정했다.
    그 행동에는 재개 경로가 없다 -- `approval_handlers.py` 는
    `multi_agent_workflow.graph`(정적 컴파일 그래프)를 상대로 재개하는데
    설계된 그래프는 호출 스코프의 ephemeral 객체라 어디에도 캐시되지 않는다.
    즉 멈춘 run 은 **다른 그래프** 위에서 재개된다.

    그래서 멈출 수 있는 설계를 애초에 만들지 않는다. 사람 승인을 포기하는
    것이 아니다 -- 승인이 필요한 질의는 정적 경로가 그대로 처리한다.

    **이 테스트가 지키는 돌연변이:** `interrupt_before` 계산이 죽어 항상 빈
    목록이 되면 게이트 설계가 그대로 실행된다. 위 테스트(체크포인터 없음)는
    그 돌연변이를 잡지 못한다 -- 거기서는 어차피 정적으로 떨어지기 때문이다.
    """

    from langgraph.checkpoint.memory import MemorySaver

    from neos.workflow import graph as graph_module

    saver = MemorySaver()

    async def _fake_get_checkpointer():
        return saver

    # `_ensure_graph_initialized(use_checkpointer=True)` 도 같은 이름을 부른다
    # -- 모듈 레벨 이름 하나를 갈아 끼우면 정적·설계 양쪽이 다 덮인다
    # (진짜 PostgreSQL 체크포인터는 이 테스트에 필요 없다).
    monkeypatch.setattr(
        "neos.workflow.graph.get_checkpointer", _fake_get_checkpointer
    )

    recorded: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        graph_module,
        "add_span_event",
        lambda span, name, attrs=None: recorded.append((name, dict(attrs or {}))),
    )

    _, resolved = await _resolve_with(
        monkeypatch, _FakeDesigner(_GATED), use_checkpointer=True
    )

    assert resolved.source == "static"

    # 폴백은 조용하지 않다 -- **어느 노드 때문인지** 원장이 말한다. 사유 없는
    # 폴백은 정적 실행과 구별되지 않는다.
    reason = next(
        attrs["reason"]
        for name, attrs in recorded
        if name == "graph_design_fallback"
    )
    assert reason == "approval_gate_in_designed_topology"
    gated = next(
        attrs["gated_nodes"]
        for name, attrs in recorded
        if name == "graph_design_fallback"
    )
    assert "execution_approval" in gated


@pytest.mark.asyncio
async def test_the_designed_graph_leaves_no_trace_on_the_shared_instance(
    monkeypatch,
) -> None:
    """G2-c 불변식을 **설계 분기 위에서** 지킨다.

    `tests/workflow/test_execution_graph.py` 의 리크 가드는
    `graph_design_enabled = False` 로 돌아 정적 분기만 걷는다 -- 그쪽에서는
    `self.graph` 에 같은 객체를 다시 대입해도 티가 안 나므로, `self.graph =
    compiled` 같은 리크를 넣어도 초록이었다. 리크가 실제로 가능한 분기는
    설계 분기 하나뿐이라(거기서만 진짜 다른 컴파일 그래프가 생긴다), 그
    분기 위에 가드를 하나 더 세운다."""

    workflow = MultiAgentWorkflow()
    _enable_design(monkeypatch)
    monkeypatch.setattr(workflow, "_build_graph_designer", lambda: _FakeDesigner(_MINIMAL))
    await workflow._ensure_graph_initialized(use_checkpointer=False)

    graph_before = workflow.graph
    checkpointer_cache_before = dict(workflow._graphs_by_checkpointer)
    instance_attrs_before = set(vars(workflow))
    class_attrs_before = set(vars(MultiAgentWorkflow))

    resolved = await workflow._resolve_execution_graph(
        user_input={"query": "q", "session_id": "s1"},
        use_checkpointer=False,
        span=None,
    )

    # 설계가 실제로 승인됐는지 먼저 확인한다 -- 폴백으로 내려갔다면 아래
    # 단언들은 공허하게 참이 된다(정적 분기는 애초에 리크할 그래프가 없다).
    assert resolved.source == "designed"
    assert resolved.compiled is not graph_before

    assert workflow.graph is graph_before
    assert dict(workflow._graphs_by_checkpointer) == checkpointer_cache_before
    assert set(vars(workflow)) == instance_attrs_before
    assert set(vars(MultiAgentWorkflow)) == class_attrs_before


@pytest.mark.asyncio
async def test_the_flag_being_off_skips_the_designer_entirely(monkeypatch) -> None:
    called = False

    class _Tripwire:
        async def design(self, request):
            nonlocal called
            called = True
            return _MINIMAL

    workflow = MultiAgentWorkflow()
    _enable_design(monkeypatch, enabled=False)
    monkeypatch.setattr(workflow, "_build_graph_designer", lambda: _Tripwire())
    await workflow._ensure_graph_initialized(use_checkpointer=False)

    resolved = await workflow._resolve_execution_graph(
        user_input={"query": "q", "session_id": "s1"},
        use_checkpointer=False,
        span=None,
    )

    assert resolved.source == "static"
    assert called is False


class _SpanSpy:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []


@pytest.mark.asyncio
async def test_a_fallback_records_its_reason(monkeypatch) -> None:
    """"이벤트를 하나도 남기지 않는 폴백은 성공과 구별되지 않는다" --
    `graph_design_ledger` 모듈의 존재 이유다. 목적지를 붙이는 것이 배선의
    절반이다."""

    from neos.workflow import graph as graph_module

    recorded: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        graph_module,
        "add_span_event",
        lambda span, name, attrs=None: recorded.append((name, dict(attrs or {}))),
    )

    await _resolve_with(monkeypatch, _FakeDesigner(RuntimeError("model exploded")))

    kinds = [name for name, _attrs in recorded]
    assert "graph_design_requested" in kinds
    assert "graph_design_fallback" in kinds
    reason = next(
        attrs["reason"] for name, attrs in recorded if name == "graph_design_fallback"
    )
    assert "RuntimeError" in reason


@pytest.mark.asyncio
async def test_the_query_is_truncated_before_it_reaches_logs_and_traces(
    monkeypatch,
) -> None:
    """`graph_design_requested.payload["query"]` 는 질의 **전문**이다
    (`graph_design_ledger.py:143`). 그대로 흘리면 사용자 질의가 로그와
    트레이스에 통째로 남는다. 이 저장소에는 이미 자르는 규율이 있다 --
    `graph.py:2444` 의 `query_preview` 가 100자다."""

    from neos.workflow import graph as graph_module

    recorded: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        graph_module,
        "add_span_event",
        lambda span, name, attrs=None: recorded.append((name, dict(attrs or {}))),
    )

    long_query = "가" * 500
    workflow = MultiAgentWorkflow()
    _enable_design(monkeypatch)
    monkeypatch.setattr(workflow, "_build_graph_designer", lambda: _FakeDesigner(_MINIMAL))
    await workflow._ensure_graph_initialized(use_checkpointer=False)
    await workflow._resolve_execution_graph(
        user_input={"query": long_query, "session_id": "s1"},
        use_checkpointer=False,
        span=None,
    )

    requested = next(
        attrs for name, attrs in recorded if name == "graph_design_requested"
    )
    assert "query" not in requested
    assert len(requested["query_preview"]) <= 100
