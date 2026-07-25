import pytest

from neos.config.settings import settings
from neos.workflow.deep_analysis.service import (
    build_orchestrator,
    web_search,
)


pytestmark = pytest.mark.no_db


class FakeSearchResult:
    success = True
    data = [
        {
            "url": "https://example.com",
            "title": "Title",
            "content": "Snippet",
        }
    ]


class FakeSearchTool:
    def __init__(self):
        self.cleaned = False

    async def initialize(self):
        return True

    async def execute(self, params):
        assert params == {"query": "query", "max_results": 2}
        return FakeSearchResult()

    async def cleanup(self):
        self.cleaned = True


@pytest.mark.asyncio
async def test_web_search_adapts_mcp_result_and_cleans_up():
    tools = []

    def factory():
        tool = FakeSearchTool()
        tools.append(tool)
        return tool

    results = await web_search("query", 2, tool_factory=factory)

    assert results == [
        {
            "url": "https://example.com",
            "title": "Title",
            "snippet": "Snippet",
        }
    ]
    assert tools[0].cleaned


@pytest.mark.asyncio
async def test_build_orchestrator_uses_dev_cap_and_pure_worker(monkeypatch):
    async def search_fn(query, k):
        return []

    from neos.config.settings import settings

    custom_caps = {1: 0.51, 2: 0.72, 3: 0.93}
    monkeypatch.setattr(
        settings.config.deep_analysis, "confidence_cap", custom_caps
    )
    orchestrator = await build_orchestrator(
        object(),
        "run00001",
        profile="dev",
        search_fn=search_fn,
    )
    worker = orchestrator.worker_factory()

    assert orchestrator.global_token_cap == 20000
    assert not hasattr(worker, "db")
    assert not hasattr(worker, "run_id")
    assert worker._confidence_cap == custom_caps
    assert worker._confidence_cap is not custom_caps


@pytest.mark.parametrize(
    ("feature_model", "expected_model"),
    [
        (None, "claude-sonnet-5"),
        ("claude-judge-manual", "claude-judge-manual"),
    ],
)
@pytest.mark.asyncio
async def test_build_orchestrator_resolves_judge_at_construction_boundary(
    monkeypatch, feature_model, expected_model
) -> None:
    monkeypatch.setattr(
        settings.config.deep_analysis.models,
        "judge",
        feature_model,
    )

    orchestrator = await build_orchestrator(
        object(),
        "run00001",
        search_fn=lambda query, k: [],
    )

    assert orchestrator.agentic_grader.judge_model == expected_model
    assert orchestrator.report_grader.judge_model == expected_model
