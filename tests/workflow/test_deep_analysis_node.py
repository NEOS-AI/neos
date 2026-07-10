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
