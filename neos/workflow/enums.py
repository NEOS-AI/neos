from enum import Enum


class WorkflowNode(Enum):
    REFINEMENT_CHECKER = "refinement_checker"
    QUERY_REFINEMENT = "query_refinement_agent"
    CONVERSATION_CTX_PROC = "conversation_context_processor"

    QUERY_CLS = "query_classifier"

    # Agent Skills
    SKILL_TOOL_SELECTOR = "skill_tool_selector"

    # Workflow Orchestrators
    SEARCH_ORCHESTRATOR = "search_orchestrator"
    ANALYSIS_ORCHESTRATOR = "analysis_orchestrator"
    GENERATION_ORCHESTRATOR = "generation_orchestrator"

    # Phase 2 nodes
    RESEARCH_CONTINUATION = "research_continuation"  # 2.2
    HYPOTHESIS_GENERATION = "hypothesis_generation"  # 2.5 - before search
    HYPOTHESIS_EVALUATION = "hypothesis_evaluation"  # 2.5 - after search
    REPLANNER = "replanner"  # 2.4 - adaptive replanning
    SELF_REFLECTION = "self_reflection"  # 2.6

    # result processors
    RESULT_INTEGRATOR = "result_integrator"
    FACT_CHECK = "fact_check"
    QUALITY_VALIDATOR = "quality_validator"
    RESP_GENERATOR = "response_generator"


class WorkflowPathway(Enum):
    USE_ORCHESTRATORS = "use_orchestrators"
    SKIP_ORCHESTRATORS = "skip_orchestrators"

    PROCEED = "proceed"
    REGENERATE = "regenerate"


class IntentType(Enum):
    SIMPLE = "simple_conversation"
    COMPARISON = "comparison"
    DATA_ANALYSIS = "data_analysis"
    GENERATION = "generation"
    REALTIME_INFO = "realtime_info"
    TASK_EXECUTION = "task_execution"

    FINANCIAL_ANALYSIS = "financial_analysis"
    TECHNICAL_ANALYSIS = "technical_analysis"
    COMPLEX_ANALYSIS = "complex_analysis"

    DEEP_RESEARCH = "deep_research"
    YOUTUBE_SEARCH = "youtube_search"


class ComplexityIndicator(Enum):
    MULTI_SUBJ = "multiple_subjects"
    DEPTH_REQ = "depth_required"
    COMPARISON_MULTI = "comparison_multiple"
    MULTI_ASPECT = "multi_aspect"
