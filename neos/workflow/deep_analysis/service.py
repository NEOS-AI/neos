"""Production dependency wiring for the Deep Analysis Harness."""

from __future__ import annotations

from neos.config.settings import settings

from .citation import CitationRenderer
from .graders.agentic import AgenticGrader
from .graders.deterministic import DeterministicGrader
from .graders.report import ReportGrader
from .ledger import Ledger
from .manifest import (
    MANIFEST_KIND,
    build_manifest,
    component_id,
    component_id_for_class,
    prompt_hashes,
)
from .model_roles import resolve_all, resolve_harness_model
from .orchestrator import Orchestrator
from .skill_selector import SkillSelector
from .synthesizer import Synthesizer
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
    judge_model = resolve_harness_model("judge").model
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

    # 매니페스트는 여기서 낸다. `build_orchestrator` 는 프로파일과 유도값을
    # 아는 유일한 곳이고, Orchestrator 는 floor 를 주입받을 뿐 프로파일을
    # 모른다(위 주석 참조 -- 골든 테스트가 캡 1000 으로 그것을 짓는다).
    # Orchestrator 안에서 내면 §2.1 이 막으려는 재계산이 되살아난다.
    manifest = build_manifest(
        profile=profile,
        models=resolve_all(),
        budget={
            "global_token_cap": global_token_cap,
            "synthesis_max_tokens": synthesis_max_tokens,
            "finalization_floor_tokens": finalization_floor_tokens,
            "report_floor_tokens": report_floor_tokens,
            "grading_floor_tokens": grading_floor_tokens,
            "min_viable_output_tokens": config.min_viable_output_tokens,
            # 파생값이지만 일부러 싣는다 -- D75 -> D77 -> D78 이 세 번
            # 틀린 것이 정확히 이 뺄셈이다.
            "available_for_investigation": max(
                0, global_token_cap - finalization_floor_tokens
            ),
            "report_floor_funded_attempts": config.report_floor_funded_attempts,
        },
        prompts=prompt_hashes(),
        skills=(
            None
            if skill_registry is None
            else sorted(
                (
                    {"name": info.name, "version": info.version}
                    for info in skill_registry.list_skills()
                ),
                key=lambda item: item["name"],
            )
        ),
        components={
            "grader": component_id(grader),
            "agentic_grader": component_id(agentic_grader),
            "report_grader": component_id(report_grader),
            # `build_orchestrator` 는 이 kwargs 를 항상 None 으로 넘기지만
            # `Orchestrator.__init__` 은 그럴 때 Synthesizer/CitationRenderer 를
            # 무조건 만든다 -- 인스턴스가 없을 뿐 부품은 항상 배선된다.
            "synthesizer": component_id_for_class(Synthesizer),
            "citation_renderer": component_id_for_class(CitationRenderer),
            "search_fn": getattr(search_fn, "__qualname__", None),
            "fetch_fn": getattr(fetch_fn, "__qualname__", None),
            "cassette": cassette is not None,
        },
        config={
            "max_depth": max_depth,
            "parallel_workers": parallel_workers,
            "quote_match_threshold": config.quote_match_threshold,
            "confidence_cap": config.confidence_cap,
            "agentic_threshold": config.agentic_threshold,
            "agentic_sample_rate": config.agentic_sample_rate,
            "claim_retry_cap": config.claim_retry_cap,
            "decompose_max_tokens": config.decompose_max_tokens,
            "judge_max_output_tokens": config.judge_max_output_tokens,
            "entailment_max_output_tokens": config.entailment_max_output_tokens,
            "subquestions": {
                "adopt_threshold": config.subq_adopt_threshold,
                "adopt_cap": config.subq_adopt_cap,
                "budget_policy": config.subq_budget_policy,
                "reviewer_enabled": config.subq_reviewer_enabled,
            },
            "effort": {
                name: {
                    "token_cap": effort.token_cap,
                    "wall_clock_cap": effort.wall_clock_cap,
                }
                for name, effort in config.effort.items()
            },
        },
    )
    await ledger.log(MANIFEST_KIND, None, manifest)

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
