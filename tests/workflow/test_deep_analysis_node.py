import pytest

pytestmark = pytest.mark.no_db


@pytest.mark.asyncio
async def test_deep_analysis_node_maps_report_to_final_response(monkeypatch):
    from neos.workflow import graph as graph_mod

    class FakeOrch:
        async def run(self, q):
            return {"report_markdown": "# 보고서\n본문", "run_id": "run00001"}

    class FakeSessionCtx:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def commit(self):
            pass

    async def fake_get_session():
        return FakeSessionCtx()

    async def fake_create_run(s, q, p):
        return "run00001"

    async def fake_build(s, run_id, **kw):
        return FakeOrch()

    monkeypatch.setattr(
        "neos.database.connection.db_manager.get_session", fake_get_session
    )
    monkeypatch.setattr(
        "neos.workflow.deep_analysis.ledger.create_run", fake_create_run
    )
    monkeypatch.setattr(
        "neos.workflow.deep_analysis.service.build_orchestrator", fake_build
    )

    g = graph_mod.multi_agent_workflow
    out = await g._deep_analysis_orchestrator_node(
        {"original_query": "GLM-5.2 MoE 영향?"}
    )
    assert out["final_response"].startswith("# 보고서")
    assert out["deep_analysis_run_id"] == "run00001"


@pytest.mark.asyncio
async def test_deep_analysis_node_graceful_on_failure(monkeypatch):
    from neos.workflow import graph as graph_mod

    async def boom_get_session():
        raise RuntimeError("db down")

    monkeypatch.setattr(
        "neos.database.connection.db_manager.get_session", boom_get_session
    )

    g = graph_mod.multi_agent_workflow
    out = await g._deep_analysis_orchestrator_node({"original_query": "x"})
    assert out["final_response"] == "심층 분석 하네스 실행에 실패했습니다."


@pytest.mark.asyncio
async def test_deep_analysis_node_persists_failed_status_on_run_error(monkeypatch):
    """D18 선결조건(2) 회귀: orch.run()이 실패하면 run 상태를 새 세션에서
    'failed'로 내구성 있게 확정해야 한다(원 세션은 롤백 상태일 수 있음).
    예전엔 노드 except가 커밋 없이 종료해 status='running' 고아 run이 남았다."""
    from neos.workflow import graph as graph_mod

    sessions = []

    class FakeSessionCtx:
        def __init__(self):
            self.committed = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def commit(self):
            self.committed += 1

    async def fake_get_session():
        s = FakeSessionCtx()
        sessions.append(s)
        return s

    async def fake_create_run(s, q, p):
        return "runFAIL1"

    class BoomOrch:
        async def run(self, q):
            raise RuntimeError("harness exploded")

    async def fake_build(s, run_id, **kw):
        return BoomOrch()

    failed = []

    class FakeLedger:
        def __init__(self, session, run_id):
            self.run_id = run_id

        async def fail_run(self):
            failed.append(self.run_id)

    monkeypatch.setattr(
        "neos.database.connection.db_manager.get_session", fake_get_session
    )
    monkeypatch.setattr(
        "neos.workflow.deep_analysis.ledger.create_run", fake_create_run
    )
    monkeypatch.setattr(
        "neos.workflow.deep_analysis.service.build_orchestrator", fake_build
    )
    monkeypatch.setattr(
        "neos.workflow.deep_analysis.ledger.Ledger", FakeLedger
    )

    g = graph_mod.multi_agent_workflow
    out = await g._deep_analysis_orchestrator_node({"original_query": "x"})

    assert out["final_response"] == "심층 분석 하네스 실행에 실패했습니다."
    assert failed == ["runFAIL1"]  # 실패 상태가 확정됨
    assert len(sessions) == 2  # 원 세션 + 실패 확정용 새 세션
    assert sessions[1].committed == 1


@pytest.mark.asyncio
async def test_no_regression_deep_analysis_off_by_default_node_not_registered(monkeypatch):
    """D18 무회귀 계약: DEEP_ANALYSIS_ENABLED가 기본값(False)일 때 그래프 빌드가
    deep_analysis_orchestrator 노드를 아예 등록하지 않는다(recursive/hyper_deep과 동일한
    조건부 등록 패턴을 그대로 따름 — neos/workflow/graph.py의 `if settings.DEEP_ANALYSIS_ENABLED:` 가드)."""
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

    workflow = graph_mod.multi_agent_workflow
    compiled = await workflow._create_workflow_graph(use_checkpointer=False)

    assert WorkflowNode.DEEP_ANALYSIS_ORCHESTRATOR.value not in compiled.nodes
