"""트랙 I GS2 배선 -- 설계 경로가 플래그에 따라 템플릿을 보고, 체크포인터 없이는 거른다.

플래그가 꺼져 있으면 설계 관문에 넘기는 인자가 추가 전과 **같아야** 한다. 켜져 있으면
설계자 출력이 전개되고, 템플릿 규칙과 템플릿 계약으로 검증되며, 호스트가 조립에 들어간다.
"""

import pytest
from langgraph.checkpoint.memory import MemorySaver

import neos.workflow.graph as graph_module
from neos.config import settings as settings_module
from neos.workflow.contracts import NODE_CONTRACTS
from neos.workflow.graph import MultiAgentWorkflow, _recursion_limit_for
from neos.workflow.resume_graph import ResumeGraphUnavailable, resume_graph_for
from neos.workflow.subagent_nodes import EXPLORE_WEB, SubagentNodeHost
from neos.workflow.topology import GRAPH_ENTRY_WRITES, GraphTopology, topology_to_payload

NODE = EXPLORE_WEB.name

_CHAIN = (
    "query_classifier",
    "search_orchestrator",
    NODE,
    "fact_check",
    "analysis_orchestrator",
    "generation_orchestrator",
    "response_generator",
)
_DESIGN = GraphTopology(
    nodes=_CHAIN,
    edges=(
        ("__start__", _CHAIN[0]),
        *((_CHAIN[i], _CHAIN[i + 1]) for i in range(len(_CHAIN) - 1)),
        (_CHAIN[-1], "__end__"),
    ),
    initial_writes=GRAPH_ENTRY_WRITES,
)


class _Designer:
    def __init__(self, topology) -> None:
        self.topology = topology

    async def design(self, request):
        return self.topology


class _NullRuntime:
    async def cancel_for_parent(self, *args):
        return ()


def _fake_host() -> SubagentNodeHost:
    return SubagentNodeHost(
        runtime=_NullRuntime(),
        provider="anthropic",
        model_for_role=lambda provider, role: "claude-sonnet-5",
    )


def _enable(monkeypatch, *, subagent: bool) -> None:
    workflow_config = settings_module.settings.config.workflow
    monkeypatch.setattr(workflow_config, "graph_design_enabled", True)
    if subagent:
        # 켜는 순서가 검증기의 선행 조건 순서다(예산 -> 플래그). monkeypatch 는 역순으로 되돌린다.
        monkeypatch.setattr(workflow_config, "subagent_budget_micros", 10**9)
        monkeypatch.setattr(workflow_config, "subagent_nodes_enabled", True)
    monkeypatch.setattr(settings_module.settings, "LLM_PROVIDER", "anthropic")
    monkeypatch.setattr(
        "neos.workflow.subagent_nodes._default_model_for_role",
        lambda provider, role: "claude-sonnet-5",
    )


async def _resolve(monkeypatch, workflow, topology, *, use_checkpointer):
    saver = MemorySaver()

    async def _fake_get_checkpointer():
        return saver

    monkeypatch.setattr("neos.workflow.graph.get_checkpointer", _fake_get_checkpointer)
    monkeypatch.setattr(workflow, "_build_graph_designer", lambda: _Designer(topology))
    await workflow._ensure_graph_initialized(use_checkpointer=use_checkpointer)
    return await workflow._resolve_execution_graph(
        user_input={"query": "이 함수를 누가 부르나", "session_id": "s1"},
        use_checkpointer=use_checkpointer,
        span=None,
    )


@pytest.mark.asyncio
async def test_with_the_flag_off_the_design_gate_gets_exactly_the_old_arguments(monkeypatch) -> None:
    _enable(monkeypatch, subagent=False)
    seen = {}
    original = graph_module.design_graph_or_fallback

    async def _spy(**kwargs):
        seen.update(kwargs)
        return await original(**kwargs)

    monkeypatch.setattr(graph_module, "design_graph_or_fallback", _spy)
    workflow = MultiAgentWorkflow()
    resolved = await _resolve(monkeypatch, workflow, _DESIGN, use_checkpointer=True)

    assert seen["contracts"] is NODE_CONTRACTS
    assert seen["expand"] is None and seen["subagent"] is None
    assert len(seen["request"].catalog) == 31
    # 템플릿 이름은 정적 계약에 없다 -> 설계는 거부되고 정적으로 내려간다.
    assert resolved.source == "static" and resolved.subagent_host is None


@pytest.mark.asyncio
async def test_with_the_flag_on_a_checked_template_design_is_expanded_and_hosted(monkeypatch) -> None:
    _enable(monkeypatch, subagent=True)
    workflow = MultiAgentWorkflow()
    host = _fake_host()
    monkeypatch.setattr(workflow, "_build_subagent_host", lambda span, event_handler=None: host)

    resolved = await _resolve(monkeypatch, workflow, _DESIGN, use_checkpointer=True)

    assert resolved.source == "designed"
    assert resolved.subagent_host is host
    assert (NODE, NODE) in resolved.topology.edges
    assert resolved.topology.loop_bounds == {NODE: EXPLORE_WEB.max_advances}
    assert NODE in resolved.compiled.get_graph().nodes
    assert _recursion_limit_for(resolved) == max(
        50, len(_CHAIN) + EXPLORE_WEB.max_advances - 1 + 1
    )
    payload = workflow.execution_topology_payload(resolved)
    assert payload["loop_bounds"] == {NODE: EXPLORE_WEB.max_advances}


@pytest.mark.asyncio
async def test_with_the_flag_on_an_unchecked_template_design_is_rejected(monkeypatch) -> None:
    _enable(monkeypatch, subagent=True)
    unchecked_chain = tuple(node for node in _CHAIN if node != "fact_check")
    unchecked = GraphTopology(
        nodes=unchecked_chain,
        edges=(
            ("__start__", unchecked_chain[0]),
            *((unchecked_chain[i], unchecked_chain[i + 1]) for i in range(len(unchecked_chain) - 1)),
            (unchecked_chain[-1], "__end__"),
        ),
        initial_writes=GRAPH_ENTRY_WRITES,
    )
    events = []
    workflow = MultiAgentWorkflow()
    monkeypatch.setattr(workflow, "_build_subagent_host", lambda span, event_handler=None: _fake_host())
    monkeypatch.setattr(workflow, "_record_design_events", lambda evs, span: events.extend(evs))

    resolved = await _resolve(monkeypatch, workflow, unchecked, use_checkpointer=True)

    assert resolved.source == "static"
    rejected = [event for event in events if event.kind == "graph_design_rejected"]
    assert rejected
    assert {v["rule"] for v in rejected[0].payload["violations"]} == {"unchecked_subagent_report"}


@pytest.mark.asyncio
async def test_without_a_checkpointer_a_template_design_falls_back_with_a_reason(monkeypatch) -> None:
    _enable(monkeypatch, subagent=True)
    events = []
    workflow = MultiAgentWorkflow()
    built = []
    monkeypatch.setattr(workflow, "_build_subagent_host", lambda span, event_handler=None: built.append(1))
    monkeypatch.setattr(workflow, "_record_design_events", lambda evs, span: events.extend(evs))

    resolved = await _resolve(monkeypatch, workflow, _DESIGN, use_checkpointer=False)

    assert resolved.source == "static"
    assert built == [], "체크포인터 없는 경로에서 호스트(모델·DB 풀)를 만들었다"
    reasons = [event.payload.get("reason", "") for event in events if event.kind == "graph_design_fallback"]
    assert any(reason.startswith("ephemeral_subagent_unsupported") for reason in reasons)


@pytest.mark.asyncio
async def test_a_host_that_cannot_be_built_falls_back_instead_of_killing_the_request(monkeypatch) -> None:
    _enable(monkeypatch, subagent=True)
    events = []
    workflow = MultiAgentWorkflow()

    def _explode(span, event_handler=None):
        raise RuntimeError("no database")

    monkeypatch.setattr(workflow, "_build_subagent_host", _explode)
    monkeypatch.setattr(workflow, "_record_design_events", lambda evs, span: events.extend(evs))

    resolved = await _resolve(monkeypatch, workflow, _DESIGN, use_checkpointer=True)

    assert resolved.source == "static"
    assert any(
        event.payload.get("reason", "").startswith("subagent_host_unavailable")
        for event in events
    )


@pytest.mark.asyncio
async def test_resume_refuses_a_template_topology_when_the_flag_is_off(monkeypatch) -> None:
    _enable(monkeypatch, subagent=False)
    from neos.workflow.subagent_nodes import expand_subagent_nodes

    payload = topology_to_payload(expand_subagent_nodes(_DESIGN))
    # 플래그가 꺼지면 템플릿 계약을 합치지 않으므로, 템플릿 노드는 배포에서 사라진
    # 노드와 같은 드리프트 사유로 거부된다 -- 플래그 전용 사유가 따로 없다.
    with pytest.raises(ResumeGraphUnavailable, match="no longer valid") as caught:
        await resume_graph_for(
            {"execution_topology": payload},
            workflow=MultiAgentWorkflow(),
            checkpointer=MemorySaver(),
        )
    assert NODE in caught.value.reason


@pytest.mark.asyncio
async def test_resume_rebuilds_a_template_topology_with_a_host_when_the_flag_is_on(monkeypatch) -> None:
    _enable(monkeypatch, subagent=True)
    from neos.workflow.subagent_nodes import expand_subagent_nodes

    workflow = MultiAgentWorkflow()
    host = _fake_host()
    monkeypatch.setattr(workflow, "_build_subagent_host", lambda span, event_handler=None: host)
    payload = topology_to_payload(expand_subagent_nodes(_DESIGN))
    graph = await resume_graph_for(
        {"execution_topology": payload}, workflow=workflow, checkpointer=MemorySaver()
    )
    assert NODE in graph.get_graph().nodes
