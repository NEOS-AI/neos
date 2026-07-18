"""Phase 3b: 챗은 deep analysis job의 제출자다 (D23).

D18의 블로킹 완주 노드는 사라졌다. 이 파일은 디스패치 노드의 계약을 고정한다.
"""

import pytest

pytestmark = pytest.mark.no_db


def test_initial_state_carries_conversation_id():
    """챗 경로가 run에 conversation_id를 심으려면 상태에 그 필드가 있어야 한다.

    session_id를 재사용하지 않는다 -- /api/v1/query 호출자에게 session_id는
    대화가 아니라 세션이라, 겹쳐 쓰면 run이 없는 대화를 가리킨다.
    """
    from neos.workflow import graph as graph_mod

    state = graph_mod.multi_agent_workflow._create_initial_state(
        {
            "user_id": "u1",
            "session_id": "s1",
            "query": "q",
            "conversation_id": "conv-1",
        }
    )
    assert state["conversation_id"] == "conv-1"


def test_initial_state_conversation_id_defaults_to_none():
    """대화가 아닌 호출자(/api/v1/query)는 None이어야 한다."""
    from neos.workflow import graph as graph_mod

    state = graph_mod.multi_agent_workflow._create_initial_state(
        {"user_id": "u1", "session_id": "s1", "query": "q"}
    )
    assert state["conversation_id"] is None


class _FakeSessionCtx:
    def __init__(self):
        self.committed = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def commit(self):
        self.committed += 1


class _RecordingHandler:
    def __init__(self):
        self.calls = []

    async def on_deep_analysis_started(self, **kwargs):
        self.calls.append(kwargs)


def _patch_dispatch(monkeypatch, *, submit=None, create_run=None):
    """디스패치 노드의 외부 의존 3개(세션/create_run/job 제출)를 대체한다."""
    sessions = []

    async def fake_get_session():
        s = _FakeSessionCtx()
        sessions.append(s)
        return s

    async def default_create_run(session, question, profile, **kw):
        default_create_run.kwargs = kw
        return "runDISP1"

    default_create_run.kwargs = {}

    submitted = []

    def default_submit(run_id, question="", profile="dev", **kw):
        submitted.append((run_id, question, profile))
        return "inline"

    monkeypatch.setattr(
        "neos.database.connection.db_manager.get_session", fake_get_session
    )
    monkeypatch.setattr(
        "neos.workflow.deep_analysis.ledger.create_run",
        create_run or default_create_run,
    )
    monkeypatch.setattr(
        "neos.tasks.deep_analysis_job_task.submit_deep_analysis_job",
        submit or default_submit,
    )
    return sessions, submitted, default_create_run


@pytest.mark.asyncio
async def test_dispatch_node_submits_job_and_returns_immediately(monkeypatch):
    """AC2: 챗 턴이 하네스 완주를 기다리지 않는다.

    노드는 run을 만들고 job을 제출한 뒤 곧바로 상태 diff를 돌려줘야 한다.
    """
    from neos.workflow import graph as graph_mod

    _sessions, submitted, _cr = _patch_dispatch(monkeypatch)
    handler = _RecordingHandler()

    out = await graph_mod.multi_agent_workflow._deep_analysis_dispatch_node(
        {
            "original_query": "GLM-5.2 MoE 영향?",
            "user_id": "u1",
            "conversation_id": "conv-1",
            "_event_handler": handler,
        }
    )

    assert submitted == [("runDISP1", "GLM-5.2 MoE 영향?", "default")]
    assert out["deep_analysis_run_id"] == "runDISP1"
    assert out["final_response"]  # 사용자에게 보일 안내 문구가 있어야 한다


@pytest.mark.asyncio
async def test_dispatch_node_emits_started_event_with_shared_contract(monkeypatch):
    """AC4: 챗이 받는 핸들은 전용 API와 같은 events_url을 가리킨다."""
    from neos.workflow import graph as graph_mod

    _patch_dispatch(monkeypatch)
    handler = _RecordingHandler()

    await graph_mod.multi_agent_workflow._deep_analysis_dispatch_node(
        {
            "original_query": "q",
            "user_id": "u1",
            "conversation_id": "conv-1",
            "_event_handler": handler,
        }
    )

    assert len(handler.calls) == 1
    call = handler.calls[0]
    assert call["run_id"] == "runDISP1"
    assert call["events_url"] == "/api/v1/deep-analysis/runDISP1/events"
    assert call["assistant_message_id"]  # 리포트가 채워질 메시지 ID


@pytest.mark.asyncio
async def test_dispatch_node_binds_run_to_conversation(monkeypatch):
    """리포트 영속화(실행자 계층)가 동작하려면 run이 대화/메시지를 알아야 한다."""
    from neos.workflow import graph as graph_mod

    _sessions, _submitted, create_run = _patch_dispatch(monkeypatch)
    handler = _RecordingHandler()

    await graph_mod.multi_agent_workflow._deep_analysis_dispatch_node(
        {
            "original_query": "q",
            "user_id": "u1",
            "conversation_id": "conv-1",
            "_event_handler": handler,
        }
    )

    assert create_run.kwargs["user_id"] == "u1"
    assert create_run.kwargs["conversation_id"] == "conv-1"
    assert (
        create_run.kwargs["assistant_message_id"]
        == handler.calls[0]["assistant_message_id"]
    )


@pytest.mark.asyncio
async def test_dispatch_node_skips_message_binding_outside_conversation(monkeypatch):
    """대화 밖 호출자(/api/v1/query)는 어시스턴트 메시지가 없다."""
    from neos.workflow import graph as graph_mod

    _sessions, _submitted, create_run = _patch_dispatch(monkeypatch)
    handler = _RecordingHandler()

    await graph_mod.multi_agent_workflow._deep_analysis_dispatch_node(
        {"original_query": "q", "user_id": "u1", "_event_handler": handler}
    )

    assert create_run.kwargs["conversation_id"] is None
    assert create_run.kwargs["assistant_message_id"] is None
    assert handler.calls[0]["assistant_message_id"] is None


@pytest.mark.asyncio
async def test_dispatch_node_graceful_when_submission_fails(monkeypatch):
    """제출이 깨져도 챗 턴은 살아 있어야 한다 -- 사용자는 답을 받는다."""
    from neos.workflow import graph as graph_mod

    async def boom_get_session():
        raise RuntimeError("db down")

    monkeypatch.setattr(
        "neos.database.connection.db_manager.get_session", boom_get_session
    )

    out = await graph_mod.multi_agent_workflow._deep_analysis_dispatch_node(
        {"original_query": "q", "user_id": "u1"}
    )
    assert out["final_response"] == "심층 분석을 시작하지 못했습니다."
    assert out["deep_analysis_run_id"] is None


@pytest.mark.asyncio
async def test_dispatch_node_works_without_event_handler(monkeypatch):
    """/api/v1/query 등 이벤트 핸들러 없는 호출자에서도 죽지 않는다."""
    from neos.workflow import graph as graph_mod

    _sessions, submitted, _cr = _patch_dispatch(monkeypatch)

    out = await graph_mod.multi_agent_workflow._deep_analysis_dispatch_node(
        {"original_query": "q", "user_id": "u1"}
    )
    assert submitted == [("runDISP1", "q", "default")]
    assert out["deep_analysis_run_id"] == "runDISP1"


@pytest.mark.asyncio
async def test_blocking_orchestrator_node_is_gone():
    """AC3: 블로킹 완주 노드와 그 실패 영속화 헬퍼가 제거됐다.

    9763eb5의 wall-clock 캡도 함께 사라진다 -- 실행이 요청 밖으로 나가면
    노드가 붙들 자원이 없으므로 바운드할 대상 자체가 없다(스펙 §5.2).
    """
    from neos.workflow import graph as graph_mod

    wf = graph_mod.multi_agent_workflow
    assert not hasattr(wf, "_deep_analysis_orchestrator_node")
    assert not hasattr(wf, "_persist_deep_analysis_failure")


@pytest.mark.asyncio
async def test_no_regression_deep_analysis_off_by_default_node_not_registered(
    monkeypatch,
):
    """AC7 구조적 보장: 플래그가 꺼져 있으면 노드가 등록조차 되지 않는다."""
    from neos.workflow import graph as graph_mod
    from neos.workflow.enums import WorkflowNode

    class RecordingGraph:
        def __init__(self, state_type):
            self.nodes = []

        def add_node(self, name, handler):
            self.nodes.append(name)

        def add_edge(self, *a, **kw):
            pass

        def add_conditional_edges(self, *a, **kw):
            pass

        def compile(self, **kwargs):
            return self

    monkeypatch.setattr(graph_mod, "StateGraph", RecordingGraph)
    monkeypatch.setattr(graph_mod.settings, "DEEP_ANALYSIS_ENABLED", False)

    compiled = await graph_mod.multi_agent_workflow._create_workflow_graph(
        use_checkpointer=False
    )
    assert WorkflowNode.DEEP_ANALYSIS_DISPATCH.value not in compiled.nodes


@pytest.mark.asyncio
async def test_dispatch_node_registered_and_terminal_when_flag_on(monkeypatch):
    """플래그가 켜지면 노드가 등록되고 END로 단락된다 -- 챗 턴이 여기서 끝난다.

    RESULT_INTEGRATOR로 합류하면 후속 노드들이 리포트를 기다리게 되므로
    AC2가 깨진다.
    """
    from langgraph.graph import END

    from neos.workflow import graph as graph_mod
    from neos.workflow.enums import WorkflowNode

    class RecordingGraph:
        def __init__(self, state_type):
            self.nodes = []
            self.edges = []

        def add_node(self, name, handler):
            self.nodes.append(name)

        def add_edge(self, src, dst):
            self.edges.append((src, dst))

        def add_conditional_edges(self, *a, **kw):
            pass

        def compile(self, **kwargs):
            return self

    monkeypatch.setattr(graph_mod, "StateGraph", RecordingGraph)
    monkeypatch.setattr(graph_mod.settings, "DEEP_ANALYSIS_ENABLED", True)

    compiled = await graph_mod.multi_agent_workflow._create_workflow_graph(
        use_checkpointer=False
    )
    assert WorkflowNode.DEEP_ANALYSIS_DISPATCH.value in compiled.nodes
    assert (WorkflowNode.DEEP_ANALYSIS_DISPATCH.value, END) in compiled.edges
