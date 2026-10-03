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
from .model_roles import (
    resolve_all,
    resolve_all_effort,
    resolve_harness_effort,
    resolve_harness_model,
)
from .orchestrator import Orchestrator
from .reexecutor import SandboxReexecutor
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
        result = await tool.execute({"query": query, "max_results": k})
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


def _claim_judge_manifest(jev_config, jev_judge) -> dict:
    """매니페스트의 판정자 항목. Jev 가 꺼져 있으면 LLM 판정자 하나다."""
    if jev_judge is None:
        return {"backend": "llm"}
    from neos.jev.rubric import load_rubric

    return {
        "backend": "jev",
        "model": jev_config.model,
        "rubric": jev_config.judge_rubric,
        "rubric_digest": load_rubric(jev_config.judge_rubric).digest,
        "min_confidence": jev_config.judge_min_confidence,
        # 계산 클레임과 Jev 실패는 LLM 판정자가 맡는다 -- 같은 런에 판정자가 둘이다.
        "fallback": "llm",
    }


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
    judge_effort = resolve_harness_effort("judge").effort
    ledger = Ledger(session, run_id)

    # 트랙 J. 플래그가 켜졌을 때만 만든다 -- 꺼져 있으면 이 블록은 통째로
    # 건너뛰고 채점기·오케스트레이터는 `None` 을 받는다 (I1).
    #
    # 채점기보다 **앞에** 있는 이유는 재실행기가 provider 를 요구하기
    # 때문이다. provider 생성은 자원을 잡지 않는다("Construct the configured
    # provider without starting sandbox resources") 이므로 앞당겨도 비용이
    # 늘지 않는다.
    sandbox_provider = None
    if config.code_research_enabled or config.compose_child_enabled:
        try:
            from neos.coding.sandbox.factory import create_sandbox_provider

            sandbox_provider = create_sandbox_provider(settings.config.sandbox)
        except Exception:
            # 여기서 터뜨리지 않는 이유: 조사와 무관한 단계까지 같이 죽는다.
            # 빠진 조각은 `_run_worker` 가 질문마다 `sandbox_provider_missing`
            # 으로 시끄럽게 보고한다. 다만 **원인은 남긴다** -- 조용히 삼키면
            # "왜 조사 모드가 안 도는가" 에 답할 근거가 사라진다.
            import logging

            logging.getLogger(__name__).warning(
                "code research is enabled but its sandbox could not be built; "
                "questions will fail with sandbox_provider_missing",
                exc_info=True,
            )
            sandbox_provider = None

    reexecution = config.code_research.reexecution
    grader = DeterministicGrader(
        ledger,
        quote_threshold=config.quote_match_threshold,
        confidence_cap=config.confidence_cap,
        # provider 가 없으면 재실행기도 없다. 부술 것이 없는 재실행기를 쥐면
        # 계산 클레임이 채점 도중에 터진다 -- `grade_computed` 가 `None` 을
        # 배선 실수로 다루는 것과 같은 편에 선다.
        reexecutor=(
            None
            if sandbox_provider is None
            else SandboxReexecutor(
                ledger,
                sandbox_provider,
                cpu_sec=reexecution.cpu_sec,
                memory_mb=reexecution.memory_mb,
                stdout_bytes=reexecution.stdout_bytes,
                profile=config.code_research.sandbox_profile,
            )
        ),
    )
    # L6 (DECISIONS D99). 켜졌는지는 `build_claim_judge` 한 곳이 정한다. **재생** 카세트
    # 런만 Jev 를 부르지 않는다 -- 카세트에는 Jev 답이 없다. 녹화 카세트(라이브 표본
    # 스크립트가 쓴다)는 실제 런이므로 Jev 가 판정한다.
    jev_config = settings.config.jev
    jev_judge = None
    if getattr(cassette, "mode", "off") != "replay":
        from neos.jev.assembly import build_claim_judge

        jev_judge = build_claim_judge(jev_config)
    agentic_grader = AgenticGrader(
        judge_model=judge_model,
        threshold=config.agentic_threshold,
        sample_rate=config.agentic_sample_rate,
        max_output_tokens=config.judge_max_output_tokens,
        llm_client=llm_client,
        cassette=cassette,
        judge_effort=judge_effort,
        jev_judge=jev_judge,
        jev_min_confidence=(
            jev_config.judge_min_confidence if jev_judge is not None else None
        ),
    )
    report_grader = ReportGrader(
        ledger,
        judge_model=judge_model,
        llm_client=llm_client,
        cassette=cassette,
        judge_effort=judge_effort,
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
    max_depth = config.dev_profile.max_depth if profile == "dev" else config.max_depth
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
    finalization_floor_tokens = config.finalization_floor_tokens(synthesis_max_tokens)
    report_floor_tokens = config.report_floor_tokens(synthesis_max_tokens)
    grading_floor_tokens = config.grading_floor_tokens(synthesis_max_tokens)

    # 매니페스트는 여기서 낸다. `build_orchestrator` 는 프로파일과 유도값을
    # 아는 유일한 곳이고, Orchestrator 는 floor 를 주입받을 뿐 프로파일을
    # 모른다(위 주석 참조 -- 골든 테스트가 캡 1000 으로 그것을 짓는다).
    # Orchestrator 안에서 내면 §2.1 이 막으려는 재계산이 되살아난다.
    manifest = build_manifest(
        profile=profile,
        models=resolve_all(),
        efforts=resolve_all_effort(),
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
            # D-14: #23 은 이것을 끄고 돈다 -- 표본이 어느 코드를 쟀는지 원장이 말한다.
            "budget_aware_reduction": config.budget_aware_reduction,
            # J4 (D105): 초안을 누가 쓰나. 표본 경계가 이 값으로 갈린다.
            "compose_child_enabled": config.compose_child_enabled,
            # L6 (D99): 인용 클레임을 누가 판정했나. 경계 17 이 이 값으로 갈린다.
            "claim_judge": _claim_judge_manifest(jev_config, jev_judge),
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

    subagent_runtime = None
    if config.subagent_enabled:
        try:
            from neos.database.connection import db_manager

            from .subagent_adapter import build_da_subagent_runtime

            subagent_runtime = build_da_subagent_runtime(
                search_fn=search_fn,
                fetch_fn=fetch_fn,
                session_factory=db_manager.get_session,
            )
        except Exception:
            subagent_runtime = None

    # 런타임 팩토리는 provider 가 실제로 지어졌을 때만 만든다. 하나만 있으면
    # `_run_worker` 가 질문마다 어느 쪽이 빠졌는지 이름을 달아 보고한다.
    research_runtime_factory = None
    if sandbox_provider is not None:
        try:
            from neos.database.connection import db_manager

            from .subagent_adapter import build_research_runtime

            def research_runtime_factory(port):
                # 질문마다 불린다. 포트가 질문마다 다르기 때문이다.
                return build_research_runtime(
                    port, session_factory=db_manager.get_session
                )

        except Exception:
            import logging

            logging.getLogger(__name__).warning(
                "code research is enabled but its subagent runtime could not "
                "be built; questions will fail with "
                "research_runtime_factory_missing",
                exc_info=True,
            )
            research_runtime_factory = None

    # 트랙 J4 (D105). compose 자식은 synth 모델로 돈다. 플래그가 꺼져 있으면 짓지 않는다.
    compose_runtime_factory = None
    if config.compose_child_enabled and sandbox_provider is not None:
        from neos.database.connection import db_manager

        from .subagent_adapter import build_compose_runtime

        def compose_runtime_factory(port):
            return build_compose_runtime(port, session_factory=db_manager.get_session)

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
        subagent_runtime=subagent_runtime,
        sandbox_provider=sandbox_provider,
        research_runtime_factory=research_runtime_factory,
        compose_runtime_factory=compose_runtime_factory,
    )
