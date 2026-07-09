import pytest

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
async def test_build_orchestrator_uses_dev_cap_and_pure_worker():
    async def search_fn(query, k):
        return []

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
