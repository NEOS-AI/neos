"""Production dependency wiring for the Deep Analysis Harness."""

from __future__ import annotations

from neos.config.settings import settings

from .graders.deterministic import DeterministicGrader
from .ledger import Ledger
from .orchestrator import Orchestrator
from .worker import Worker


async def web_search(query: str, k: int, *, tool_factory=None) -> list[dict]:
    if tool_factory is None:
        from neos.tools.tools.web_search import WebSearchMCPTool

        tool_factory = WebSearchMCPTool

    tool = tool_factory()
    initialized = await tool.initialize()
    if not initialized:
        return []
    try:
        result = await tool.execute(
            {"query": query, "max_results": k}
        )
        if not result.success or not isinstance(result.data, list):
            return []
        return [
            {
                "url": item.get("url", ""),
                "title": item.get("title", ""),
                "snippet": item.get("content", ""),
            }
            for item in result.data
            if item.get("url")
        ]
    finally:
        await tool.cleanup()


async def build_orchestrator(
    session,
    run_id: str,
    *,
    profile: str = "dev",
    cassette=None,
    event_sink=None,
    checkpoint=None,
    search_fn=web_search,
    fetch_fn=None,
    llm_client=None,
    http_client=None,
) -> Orchestrator:
    config = settings.config.deep_analysis
    ledger = Ledger(session, run_id)
    grader = DeterministicGrader(
        ledger,
        quote_threshold=config.quote_match_threshold,
        confidence_cap=config.confidence_cap,
    )

    def worker_factory():
        options = {
            "llm_client": llm_client,
            "http_client": http_client,
            "cassette": cassette,
        }
        if fetch_fn is not None:
            options["fetch_fn"] = fetch_fn
        return Worker(search_fn, **options)

    global_token_cap = (
        config.dev_profile.global_token_cap
        if profile == "dev"
        else config.global_token_cap
    )
    parallel_workers = (
        config.dev_profile.parallel_workers
        if profile == "dev"
        else config.parallel_workers
    )
    max_depth = (
        config.dev_profile.max_depth if profile == "dev" else config.max_depth
    )
    return Orchestrator(
        session,
        run_id,
        worker_factory,
        grader,
        ledger=ledger,
        event_sink=event_sink,
        checkpoint=checkpoint,
        llm_client=llm_client,
        cassette=cassette,
        global_token_cap=global_token_cap,
        parallel_workers=parallel_workers,
        max_depth=max_depth,
    )

