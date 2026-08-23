"""설계 경로의 배선 -- 승인되면 그 그래프가 돌고, 아니면 정적으로 내려간다.

**요청은 절대 죽지 않는다.** 설계 실패 네 갈래(타임아웃·예외·위반·게이트
거부)가 전부 정적 폴백으로 끝난다. 조용히 끝나지도 않는다 --
`graph_design_ledger` 의 존재 이유가 "이벤트를 하나도 남기지 않는 폴백은
성공과 구별되지 않는다" 이기 때문이다.
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
_MINIMAL = GraphTopology(
    nodes=_CHAIN,
    edges=(
        ("__start__", _CHAIN[0]),
        *((_CHAIN[i], _CHAIN[i + 1]) for i in range(len(_CHAIN) - 1)),
        (_CHAIN[-1], "__end__"),
    ),
    initial_writes=GRAPH_ENTRY_WRITES,
)


async def _resolve_with(monkeypatch, designer, *, use_checkpointer=False):
    workflow = MultiAgentWorkflow()
    settings_module.settings.config.workflow.graph_design_enabled = True
    monkeypatch.setattr(workflow, "_build_graph_designer", lambda: designer)
    await workflow._ensure_graph_initialized(use_checkpointer=use_checkpointer)
    return await workflow._resolve_execution_graph(
        user_input={"query": "테스트 질의", "session_id": "s1"},
        use_checkpointer=use_checkpointer,
        span=None,
    )


@pytest.mark.asyncio
async def test_an_approved_design_is_what_actually_runs(monkeypatch) -> None:
    resolved = await _resolve_with(monkeypatch, _FakeDesigner(_MINIMAL))

    assert resolved.source == "designed"
    assert resolved.nodes == _CHAIN


@pytest.mark.asyncio
async def test_a_designer_exception_falls_back_to_static(monkeypatch) -> None:
    resolved = await _resolve_with(
        monkeypatch, _FakeDesigner(RuntimeError("model exploded"))
    )

    assert resolved.source == "static"


@pytest.mark.asyncio
async def test_a_timeout_falls_back_to_static(monkeypatch) -> None:
    resolved = await _resolve_with(monkeypatch, _FakeDesigner(TimeoutError()))

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
    resolved = await _resolve_with(monkeypatch, _FakeDesigner(no_response))

    assert resolved.source == "static"


@pytest.mark.asyncio
async def test_an_approval_gate_without_a_checkpointer_falls_back_instead_of_raising(
    monkeypatch,
) -> None:
    """`use_checkpointer=False`(챗 경로)인데 설계가 승인 게이트 노드를
    포함하면 `build_ephemeral_workflow` 가
    `EphemeralApprovalGateUnsupported` 를 던진다. 그것을 밖으로 흘리면
    설계 실패가 **사용자 요청을 죽인다** -- 기본 꺼짐인 기능이 할 일이
    아니다."""

    # 🔴 이 토폴로지는 **검증을 통과해야** 한다. 검증에서 거부되면 컴파일
    # 단계에 도달하지 못하고, 테스트는 `source == "static"` 으로 통과하지만
    # **다른 이유로** 통과한다 -- 게이트 처리를 지우고 돌려도 초록인 가짜
    # 테스트가 된다. 실측: 아래 체인의 위반 0건이며
    # `execution_approval.requires` 는 비어 있다.
    gated_chain = ("query_classifier", "execution_approval") + _CHAIN[1:]
    gated = GraphTopology(
        nodes=gated_chain,
        edges=(
            ("__start__", gated_chain[0]),
            *(
                (gated_chain[i], gated_chain[i + 1])
                for i in range(len(gated_chain) - 1)
            ),
            (gated_chain[-1], "__end__"),
        ),
        initial_writes=GRAPH_ENTRY_WRITES,
    )
    resolved = await _resolve_with(monkeypatch, _FakeDesigner(gated))

    assert resolved.source == "static"


@pytest.mark.asyncio
async def test_the_flag_being_off_skips_the_designer_entirely(monkeypatch) -> None:
    called = False

    class _Tripwire:
        async def design(self, request):
            nonlocal called
            called = True
            return _MINIMAL

    workflow = MultiAgentWorkflow()
    settings_module.settings.config.workflow.graph_design_enabled = False
    monkeypatch.setattr(workflow, "_build_graph_designer", lambda: _Tripwire())
    await workflow._ensure_graph_initialized(use_checkpointer=False)

    resolved = await workflow._resolve_execution_graph(
        user_input={"query": "q", "session_id": "s1"},
        use_checkpointer=False,
        span=None,
    )

    assert resolved.source == "static"
    assert called is False
