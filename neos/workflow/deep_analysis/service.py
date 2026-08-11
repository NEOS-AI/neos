"""Production dependency wiring for the Deep Analysis Harness."""

from __future__ import annotations

from neos.config.model_routing import resolve_model
from neos.config.settings import settings

from .graders.agentic import AgenticGrader
from .graders.deterministic import DeterministicGrader
from .graders.report import ReportGrader
from .ledger import Ledger
from .orchestrator import Orchestrator
from .skill_selector import SkillSelector
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
    skill_registry=None,
) -> Orchestrator:
    config = settings.config.deep_analysis
    judge_model = resolve_model(
        config=settings.config.model_routing,
        provider="anthropic",
        role="everyday",
        feature_override=config.models.judge,
    ).model
    ledger = Ledger(session, run_id)
    grader = DeterministicGrader(
        ledger,
        quote_threshold=config.quote_match_threshold,
        confidence_cap=config.confidence_cap,
    )
    agentic_grader = AgenticGrader(
        judge_model=judge_model,
        threshold=config.agentic_threshold,
        sample_rate=config.agentic_sample_rate,
        max_output_tokens=config.judge_max_output_tokens,
        llm_client=llm_client,
        cassette=cassette,
    )
    report_grader = ReportGrader(
        ledger,
        judge_model=judge_model,
        llm_client=llm_client,
        cassette=cassette,
    )

    skill_selector = (
        SkillSelector(skill_registry) if skill_registry is not None else None
    )

    def worker_factory():
        options = {
            "llm_client": llm_client,
            "http_client": http_client,
            "cassette": cassette,
            "skill_selector": skill_selector,
            "confidence_cap": config.confidence_cap,
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
    synthesis_max_tokens = (
        config.dev_profile.synthesis_max_tokens
        if profile == "dev"
        else config.synthesis_max_tokens
    )
    # Two nested tiers, not one pool. The outer floor keeps investigation out
    # of the finalization chain; the inner one keeps node_reduction out of the
    # report. `reduce_tree` calls `reduce_node` once per node and nothing caps
    # that count -- 6 measured runs averaged 3.7 calls against an allowance of
    # 2 -- so without the inner tier the assembly's reservation is taken by
    # whichever reduction happens to run last. Both come from
    # `DeepAnalysisConfig` so `neos/config/loader.py`'s
    # `warn_finalization_floor_ratio` can never describe a floor that is not
    # the one enforced here.
    finalization_floor_tokens = config.finalization_floor_tokens(
        synthesis_max_tokens
    )
    report_floor_tokens = config.report_floor_tokens(synthesis_max_tokens)
    grading_floor_tokens = config.grading_floor_tokens(synthesis_max_tokens)
    return Orchestrator(
        session,
        run_id,
        worker_factory,
        grader,
        agentic_grader=agentic_grader,
        report_grader=report_grader,
        ledger=ledger,
        event_sink=event_sink,
        checkpoint=checkpoint,
        llm_client=llm_client,
        cassette=cassette,
        global_token_cap=global_token_cap,
        finalization_floor_tokens=finalization_floor_tokens,
        report_floor_tokens=report_floor_tokens,
        grading_floor_tokens=grading_floor_tokens,
        min_viable_output_tokens=config.min_viable_output_tokens,
        parallel_workers=parallel_workers,
        max_depth=max_depth,
        synthesis_max_tokens=synthesis_max_tokens,
    )
