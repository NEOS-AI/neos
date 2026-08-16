from __future__ import annotations

import logging
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

logger = logging.getLogger(__name__)


def _split_csv(value: Any) -> Any:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return value


class StrictConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class CorsConfig(StrictConfigModel):
    allowed_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    allow_credentials: bool = True

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def parse_allowed_origins(cls, value: Any) -> Any:
        return _split_csv(value)


class GatewayModeConfig(StrictConfigModel):
    enabled: bool = False
    user_id_header: str = "X-User-ID"
    trusted_ips: list[str] = Field(default_factory=lambda: ["127.0.0.1", "::1"])

    @field_validator("trusted_ips", mode="before")
    @classmethod
    def parse_trusted_ips(cls, value: Any) -> Any:
        return _split_csv(value)


class ApiConfig(StrictConfigModel):
    v1_prefix: str = "/api/v1"
    debug: bool = False
    cors: CorsConfig = Field(default_factory=CorsConfig)
    gateway: GatewayModeConfig = Field(default_factory=GatewayModeConfig)

    @field_validator("debug", mode="before")
    @classmethod
    def parse_debug_aliases(cls, value: Any) -> Any:
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"release", "prod", "production"}:
                return False
            if normalized in {"debug", "dev", "development"}:
                return True
        return value


class DatabaseConfig(StrictConfigModel):
    url: str = Field(default="postgresql+asyncpg://postgres:password@localhost/neos", repr=False)
    pool_size: int = 20
    max_overflow: int = 30
    pool_timeout: int = 30
    pool_recycle: int = 1800


class RedisConfig(StrictConfigModel):
    url: str = Field(default="redis://localhost:6379", repr=False)
    ttl: int = 3600
    pool_size: int = 50
    min_idle_connections: int = 10


class CacheSemanticConfig(StrictConfigModel):
    enabled: bool = True
    threshold: float = 0.90


class CacheConfig(StrictConfigModel):
    workflow_response_ttl: int = 7200
    user_specific: bool = False
    semantic: CacheSemanticConfig = Field(default_factory=CacheSemanticConfig)


class SmartCacheTtlConfig(StrictConfigModel):
    realtime: int = 900
    financial: int = 600
    analysis: int = 604800
    research: int = 2592000
    generation: int = 7776000


class SmartCacheConfig(StrictConfigModel):
    enabled: bool = True
    similarity_threshold: float = 0.85
    max_entries: int = 100000
    statistics_enabled: bool = True
    ttl: SmartCacheTtlConfig = Field(default_factory=SmartCacheTtlConfig)


class LLMConfig(StrictConfigModel):
    provider: str = "anthropic"
    # None이면 provider × everyday 역할 기본값으로 해석된다 (neos/config/model_routing.py)
    model: str | None = None
    temperature: float = 0.1
    timeout: int = 120
    research_planning_timeout: int = 180
    fast_model: str = "claude-haiku-4-5-20251001"


class ProviderModelRolesConfig(StrictConfigModel):
    everyday: str
    powerful: str


class ModelRoutingConfig(StrictConfigModel):
    anthropic: ProviderModelRolesConfig = Field(
        default_factory=lambda: ProviderModelRolesConfig(
            everyday="claude-sonnet-5",
            powerful="claude-opus-5",
        )
    )
    openai: ProviderModelRolesConfig = Field(
        default_factory=lambda: ProviderModelRolesConfig(
            everyday="gpt-5.6-terra",
            powerful="gpt-5.6-sol",
        )
    )


class EmbeddingDatasetConfig(StrictConfigModel):
    enabled: bool = False
    sample_rate: float = 0.1
    dir: str = "datasets/embeddings"


class EmbeddingConfig(StrictConfigModel):
    provider: str = "gemini"
    model: str = "gemini-embedding-2-flash"
    dimension: int = 3072
    gemini_task_type: str = "retrieval_document"
    gemini_image_task_type: str = "retrieval_document"
    gemini_video_task_type: str = "retrieval_document"
    dataset: EmbeddingDatasetConfig = Field(default_factory=EmbeddingDatasetConfig)


class VisionConfig(StrictConfigModel):
    provider: str = "auto"
    enabled: bool = True
    max_tokens: int = 1000
    image_detail: str = "auto"


class AgentConfig(StrictConfigModel):
    max_iterations: int = 10
    timeout: int = 300
    timeouts: dict[str, int] = Field(
        default_factory=lambda: {
            "knowledge_search": 20,
            "realtime_info_search": 30,
            "realtime_data_search": 30,
            "multi_query_search": 35,
            "web_lookup": 15,
            "data_analysis": 60,
            "comparative_analysis": 60,
            "web_content_analysis": 45,
            "image_generation": 120,
            "api_call": 30,
            "file_processing": 90,
            "task_creation": 30,
            "deep_research": 300,
            "hyper_deep_research": 600,
            "iterative_web_explorer": 180,
            "youtube_search": 45,
        }
    )
    max_concurrent_workflows: int = 100
    max_concurrent_agents_per_workflow: int = 10
    stream_event_timeout: float = 2.0
    stream_heartbeat_interval: int = 30


class LinkFollowerConfig(StrictConfigModel):
    max_links: int = 10
    min_relevance: float = 0.5


class IterativeExplorerConfig(StrictConfigModel):
    max_depth: int = 5
    max_pages: int = 20
    max_iterations: int = 10
    min_quality: float = 0.75
    concurrent_fetches: int = 3
    timeout: int = 180
    tavily_timeout: int = 30
    cache_ttl: int = 3600
    completeness_cache_ttl: int = 1800
    initial_search_results: int = 10
    recent_results_window: int = 5
    page_limit_threshold: float = 0.9
    link_follower: LinkFollowerConfig = Field(default_factory=LinkFollowerConfig)


class QualityEvaluatorConfig(StrictConfigModel):
    completeness_weight: float = 0.4
    credibility_weight: float = 0.3
    diversity_weight: float = 0.3
    early_termination_threshold: float = 0.3
    high_credibility_threshold: float = 0.7
    dominance_threshold: float = 0.5

    @model_validator(mode="after")
    def warn_when_weights_do_not_sum_to_one(self) -> "QualityEvaluatorConfig":
        weight_sum = self.completeness_weight + self.credibility_weight + self.diversity_weight
        if abs(weight_sum - 1.0) > 0.01:
            logger.warning(
                "Quality evaluator weights sum to %.3f, not 1.0. "
                "This may affect quality scoring accuracy.",
                weight_sum,
            )
        return self


class WorkflowConfig(StrictConfigModel):
    search_orchestration_timeout: int = 40
    min_quality_score: float = 0.4
    max_retries: int = 2
    max_iterations: int = 10
    timeout_seconds: int = 300
    cache_enabled: bool = True
    cache_ttl: int = 3600
    # 설계 서브에이전트로 질의별 그래프를 짤지 여부. 기본은 꺼짐이다 -- 정적
    # 그래프가 기본 경로다. 질의마다 LLM 으로 토폴로지를 새로 짜는 비용(지연,
    # 비용, 비결정성)은 라우팅에서 "매 요청마다 LLM 으로 난이도를 분류"하는
    # 안을 기각한 이유와 같다.
    graph_design_enabled: bool = Field(
        default=False,
        description="설계 서브에이전트로 질의별 그래프를 짤지 여부. 기본은 정적 그래프다.",
    )
    graph_design_timeout_sec: float = Field(
        default=20.0,
        gt=0,
        le=120,
        description="설계 서브에이전트 호출 타임아웃. 넘으면 정적 그래프로 폴백한다.",
    )


class ResearchHarnessModelChecksConfig(StrictConfigModel):
    enabled: bool = True
    timeout_seconds: float = 20
    max_claims: int = 8
    provider: str = ""
    model: str = ""


class ResearchHarnessPersistenceConfig(StrictConfigModel):
    persist_runs: bool = False
    store_full_check_details: bool = False
    evidence_storage_policy: Literal["summary_only", "redacted", "full"] = "summary_only"
    cache_policy: Literal["passed_only", "allow_advisory_fail"] = "passed_only"


class ResearchHarnessDirectRepairConfig(StrictConfigModel):
    enabled: bool = False
    search_timeout_seconds: float = 25
    search_retries: int = 1


class ResearchHarnessConfig(StrictConfigModel):
    enabled: bool = True
    allow_off: bool = False
    default_mode: Literal["auto", "advisory", "gate", "off"] = "auto"
    gate_threshold: float = 0.82
    advisory_threshold: float = 0.70
    high_risk_threshold: float = 0.90
    max_repair_attempts: int = 1
    hyper_deep_repair_attempts: int = 2
    model_checks: ResearchHarnessModelChecksConfig = Field(default_factory=ResearchHarnessModelChecksConfig)
    persistence: ResearchHarnessPersistenceConfig = Field(default_factory=ResearchHarnessPersistenceConfig)
    direct_repair: ResearchHarnessDirectRepairConfig = Field(default_factory=ResearchHarnessDirectRepairConfig)


class ThinkingEngineConfig(StrictConfigModel):
    enabled: bool = True
    persist_traces: bool = False
    persist_task_dag: bool = False
    task_level_harness: bool = True
    max_trace_text_length: int = 240


class SecretsConfig(StrictConfigModel):
    openai_api_key: str | None = Field(default=None, repr=False)
    anthropic_api_key: str | None = Field(default=None, repr=False)
    google_api_key: str | None = Field(default=None, repr=False)
    tavily_api_key: str | None = Field(default=None, repr=False)
    youtube_api_key: str | None = Field(default=None, repr=False)
    github_api_token: str | None = Field(default=None, repr=False)
    reddit_client_id: str | None = Field(default=None, repr=False)
    reddit_client_secret: str | None = Field(default=None, repr=False)
    serpapi_api_key: str | None = Field(default=None, repr=False)
    semantic_scholar_api_key: str | None = Field(default=None, repr=False)
    news_api_key: str | None = Field(default=None, repr=False)
    openweather_api_key: str | None = Field(default=None, repr=False)
    exchangerate_api_key: str | None = Field(default=None, repr=False)
    financialdatasets_api_key: str | None = Field(default=None, repr=False)
    alpha_vantage_api_key: str | None = Field(default=None, repr=False)
    cohere_api_key: str | None = Field(default=None, repr=False)
    aws_access_key_id: str | None = Field(default=None, repr=False)
    aws_secret_access_key: str | None = Field(default=None, repr=False)
    rustfs_access_key: str | None = Field(default=None, repr=False)
    rustfs_secret_key: str | None = Field(default=None, repr=False)
    checkpointer_s3_access_key: str | None = Field(default=None, repr=False)
    checkpointer_s3_secret_key: str | None = Field(default=None, repr=False)
    channel_telegram_bot_token: str | None = Field(default=None, repr=False)
    channel_discord_bot_token: str | None = Field(default=None, repr=False)
    channel_slack_bot_token: str | None = Field(default=None, repr=False)
    channel_slack_app_token: str | None = Field(default=None, repr=False)


class SourceIntegrationsConfig(StrictConfigModel):
    reddit_user_agent: str = "NEOS-Research-Engine/1.0"
    sec_edgar_user_agent: str = "NEOS-Research contact@neos.ai"
    openalex_email: str = ""
    stock_api_provider: str = "yahoo"


class YouTubeConfig(StrictConfigModel):
    max_results: int = 10
    transcript_languages: list[str] = Field(default_factory=lambda: ["en", "ko"])
    min_relevance_score: float = 0.5
    enable_auto_captions: bool = True
    max_transcript_length: int = 50000

    @field_validator("transcript_languages", mode="before")
    @classmethod
    def parse_transcript_languages(cls, value: Any) -> Any:
        return _split_csv(value)


class AuthConfig(StrictConfigModel):
    jwt_secret_key: str | None = Field(default=None, repr=False)
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7
    google_oauth_client_id: str | None = Field(default=None, repr=False)
    google_oauth_client_secret: str | None = Field(default=None, repr=False)


class SessionConfig(StrictConfigModel):
    cookie_name: str = "neos_session"
    expire_seconds: int = 604800


class RateLimitConfig(StrictConfigModel):
    login_attempts: int = 5
    login_window_seconds: int = 600
    api_calls_per_minute: int = 100


class CircuitBreakerConfig(StrictConfigModel):
    enabled: bool = True
    fail_threshold: int = 5
    recovery_timeout: int = 60
    expected_exception: bool = True


class PhoenixConfig(StrictConfigModel):
    host: str = "localhost"
    port: int = 6006
    collector_endpoint: str | None = None
    project_name: str = "neos-multi-agent"


class ObservabilityConfig(StrictConfigModel):
    enabled: bool = True
    log_level: str = "INFO"
    phoenix: PhoenixConfig = Field(default_factory=PhoenixConfig)
    metrics_enabled: bool = True
    trace_enabled: bool = True
    max_traces: int = 1000
    trace_retention_days: int = 30
    track_llm_calls: bool = True
    track_agent_performance: bool = True
    track_workflow_metrics: bool = True


class MCPConfig(StrictConfigModel):
    enabled: bool = True
    server_host: str = "localhost"
    server_port: int = 8000
    timeout: int = 30
    retry_count: int = 3
    fallback_enabled: bool = True
    tool_selection_strategy: str = "mcp_fallback"
    tool_quality_threshold: float = 0.7
    tool_performance_priority: bool = False


class DatasetConfig(StrictConfigModel):
    auto_save: bool = True
    save_format: str = "jsonl"
    base_path: str = "datasets"


class WebSearchLoggingConfig(StrictConfigModel):
    async_enabled: bool = True
    queue_type: str = "memory"


class S3StorageConfig(StrictConfigModel):
    bucket_name: str = "neos-documents"
    endpoint_url: str | None = None
    region: str = "us-east-1"


class RustFSStorageConfig(StrictConfigModel):
    bucket_name: str = "neos-documents"
    endpoint_url: str | None = None


class LocalStorageConfig(StrictConfigModel):
    path: str = "storage/documents"


class StorageConfig(StrictConfigModel):
    provider: str = "local"
    s3: S3StorageConfig = Field(default_factory=S3StorageConfig)
    rustfs: RustFSStorageConfig = Field(default_factory=RustFSStorageConfig)
    local: LocalStorageConfig = Field(default_factory=LocalStorageConfig)


class CheckpointerS3Config(StrictConfigModel):
    backend: str = "s3"
    bucket: str = "neos-checkpoints"
    region: str = "us-east-1"
    endpoint_url: str | None = None


class CheckpointerConfig(StrictConfigModel):
    type: str = "postgres"
    blob_threshold: int = 1048576
    s3: CheckpointerS3Config = Field(default_factory=CheckpointerS3Config)


class DocumentProcessingConfig(StrictConfigModel):
    max_file_size: int = 52428800
    chunk_size: int = 1000
    chunk_overlap: int = 200
    default_chunking_strategy: str = "sentence"
    semantic_chunk_threshold: float = 0.75


class KnowledgeGraphFeatureConfig(StrictConfigModel):
    enabled: bool = False


class KnowledgeGraphExtractionConfig(StrictConfigModel):
    enabled: bool = True
    # None이면 everyday 역할 기본값으로 해석된다
    model: str | None = None


class KnowledgeGraphConfig(StrictConfigModel):
    evidence_graph: KnowledgeGraphFeatureConfig = Field(default_factory=KnowledgeGraphFeatureConfig)
    population: KnowledgeGraphFeatureConfig = Field(default_factory=KnowledgeGraphFeatureConfig)
    max_traversal_depth: int = 2
    search_weight: float = 0.3
    extraction: KnowledgeGraphExtractionConfig = Field(default_factory=KnowledgeGraphExtractionConfig)
    min_confidence: float = 0.7


class DeepResearchConfig(StrictConfigModel):
    max_polling_duration: int = 4800
    poll_interval: int = 10
    default_quality_score: float = 0.85
    chunk_size: int = 200
    max_sources_in_memory: int = 50
    max_concurrent_requests: int = 3
    min_request_interval: float = 0.5
    token_budget: int = 150000


class ArtifactsConfig(StrictConfigModel):
    enabled: bool = True
    llm_model: str = "claude-haiku-4-5-20251001"
    llm_temperature: float = 0.7
    llm_max_tokens: int = 4096


class ChatConfig(StrictConfigModel):
    default_max_tokens: int = 200000
    enable_workflow: bool = True
    enable_response_refinement: bool = True
    history_enabled: bool = True
    max_history_messages: int = 20
    history_context_max_tokens: int = 2000
    history_usage_level: str = "full"
    thinking_blocks_enabled: bool = True
    max_thinking_length: int = 0
    disable_thinking_for_search: bool = True
    token_budget: int = 80000


class ContextOptimizationConfig(StrictConfigModel):
    use_tiktoken: bool = True
    token_counter_model: str = "gpt-4"
    overflow_detection: bool = True
    window_threshold: float = 0.85
    max_context_tokens: int = 800000
    reserve_tokens: int = 4096
    tool_result_summarization: bool = True
    tool_result_max_length: int = 4000
    # None이면 everyday 역할 기본값으로 해석된다
    tool_result_summarization_model: str | None = None
    message_compression_enabled: bool = True
    message_compression_threshold: int = 30
    message_compression_ratio: float = 0.5
    message_history_max_tokens: int = 50000
    semantic_deduplication: bool = True
    semantic_similarity_threshold: float = 0.92
    workflow_context_budget: bool = True
    default_workflow_token_budget: int = 100000


class OTelConfig(StrictConfigModel):
    enabled: bool = False
    exporter_jaeger_endpoint: str = "http://localhost:4318/v1/traces"
    service_name: str = "neos-workflow"
    service_version: str = "0.19.0"
    deployment_environment: str = "development"
    traces_sampler: str = "always_on"
    traces_sampler_arg: float = 1.0
    bsp_max_queue_size: int = 2048
    bsp_schedule_delay: int = 5000
    bsp_max_export_batch_size: int = 512


class TelemetryConfig(StrictConfigModel):
    otel: OTelConfig = Field(default_factory=OTelConfig)


class CeleryConfig(StrictConfigModel):
    enabled: bool = False
    broker_url: str = Field(default="redis://localhost:6379/1", repr=False)
    result_backend: str = Field(default="redis://localhost:6379/2", repr=False)
    task_serializer: str = "json"
    result_serializer: str = "json"
    timezone: str = "UTC"
    worker_prefetch_multiplier: int = 4
    task_acks_late: bool = True


class MemoryConfig(StrictConfigModel):
    short_term_ttl: int = 3600
    long_term_enabled: bool = True
    episodic_enabled: bool = True
    max_context_items: int = 10


class QueryClassifierConfig(StrictConfigModel):
    use_llm: bool = False
    llm_model: str = "claude-haiku-4-5-20251001"
    llm_timeout: int = 10


class ExecutiveSummaryConfig(StrictConfigModel):
    enabled: bool = True
    min_words: int = 500
    max_sentences: int = 3


class QueryExpansionConfig(StrictConfigModel):
    enabled: bool = False
    variations: int = 3


class CostAwareRoutingConfig(StrictConfigModel):
    enabled: bool = False
    default_budget: float = 5.0


class CitationConfig(StrictConfigModel):
    enabled: bool = True
    default_style: str = "numbered"


class FactCheckConfig(StrictConfigModel):
    enabled: bool = True
    complexity_threshold: float = 0.4


class SearchFallbackConfig(StrictConfigModel):
    enabled: bool = True
    duckduckgo_max_results: int = 10


class ToolSearchConfig(StrictConfigModel):
    enabled: bool = False
    top_k: int = 5
    max_rounds: int = 3
    rrf_k: int = 60


class HybridSearchConfig(StrictConfigModel):
    alpha: float = 0.5
    candidate_count: int = 50


class RerankerConfig(StrictConfigModel):
    enabled: bool = True
    top_n: int = 10
    model: str = "rerank-english-v3.0"


class RecursiveAgentConfig(StrictConfigModel):
    enabled: bool = False
    max_depth: int = 3
    max_tasks_per_level: int = 4
    complexity_threshold: float = 0.8
    atomizer_model: str = "claude-haiku-4-5-20251001"
    planner_model: str | None = None
    budget_cap: float = 0.5


class HyperDeepAgentConfig(StrictConfigModel):
    enabled: bool = False
    max_depth: int = 1
    max_tasks_per_level: int = 3
    complexity_threshold: float = 0.85
    budget_cap: float = 5.0
    task_level_harness_enabled: bool = True


class DeepAnalysisEffortConfig(StrictConfigModel):
    token_cap: int
    wall_clock_cap: int


class DeepAnalysisModelsConfig(StrictConfigModel):
    scout: str | None = None
    dig: str | None = None
    synth: str | None = None
    judge: str | None = None


class DeepAnalysisDevProfileConfig(StrictConfigModel):
    # 20000 could not hold ONE worker_analysis call: measured input_bound for
    # that stage ran 5,542 / 10,893 / 17,723 (min/median/max), and that is
    # before the finalization floor is subtracted. The profile was sized
    # before `reserve` charged for input at all, which is why dev runs were
    # pathological rather than merely small. 100,000 left 58,960 for
    # investigation against a 41,040 floor (41%), matching the default
    # profile's 43.7%.
    #
    # 140,000 (2026-08-10, D56). `report_floor_tokens` now counts the
    # truncation expansion it always paid for, which moves dev's finalization
    # floor 48,000 -> 68,000. At the old cap that is 68% -- past
    # `finalization_floor_warn_ratio`, so the shipped defaults would warn --
    # and it would cut investigation from 52,000 to 32,000, below what dev
    # runs already use (sample #12's `f9bba141` consumed 50,318 before
    # stopping at the floor). 140,000 puts the floor at 49% and gives
    # investigation 72,000.
    #
    # The default profile needs no change: the same correction takes it from
    # 31% to 45% of its 300,000 cap.
    #
    # This costs real tokens, and only on the runs that reach the floor --
    # one of five dev runs in each of samples #11 and #12. The other four
    # spent 23,000-39,000, nowhere near either cap.
    global_token_cap: int = 140000
    parallel_workers: int = 2
    max_depth: int = 2
    # dev shrinks the budget 3x (300000 -> 100000) but inherited a synthesis
    # ceiling sized for the full profile, which is why the finalization floor
    # did not fit before this file's input allowances were added: three
    # 4000-token calls against what was then a 20000 cap.
    #
    # 1200 was measured against node_reduction -- its actual consumption ran a
    # median of 1109 tokens INCLUDING input, at granted ceilings whose median
    # was 748. That sized the *reduction* stage correctly and the *assembly*
    # stage far too small, because the same knob caps both.
    #
    # 2000 (2026-08-09) is measured against assembly. Sample #9: `llm_truncated`
    # fired 13 times for `report_assembly` out of 17 truncations run-wide, and
    # the delivered report bodies cluster at 1,309-1,932 characters -- right at
    # what a 1200-token ceiling can emit. The judge rejected 3 of its 4 refusals
    # partly for "본문이 중간에 끊겼다". With `truncation_retry_multiplier` the
    # expansion retry reaches 4000, which covers the 1,932-character median body
    # with margin.
    #
    # Paid for by `report_retry_cap` 2 -> 1: the floor is
    # `(cap + 1) * (assembly + grading)`, so one fewer attempt funds a larger
    # ceiling. dev's finalization floor goes 41,040 -> 48,000 (41% -> 48% of
    # the cap), still under `finalization_floor_warn_ratio`.
    #
    # ge=1: at s <= 0, the floor formulas can push report_floor_tokens above
    # floor_tokens (which stays non-negative) and `TokenBudget.__init__`
    # raises an opaque ValueError on every run instead of failing at config
    # validation with a clear message.
    synthesis_max_tokens: int = Field(default=2000, ge=1)


class DeepAnalysisDiscardRecallConfig(StrictConfigModel):
    """Thresholds for the entailment discard-recall measurement.

    ``safe_upper_bound`` and ``over_discard_lower_bound`` are the
    pre-registered stopping rule. They are fixed before data is collected and
    must not be tuned after seeing a result.

    **Sample-size consequence of these defaults.** With zero verified
    discards, the Wilson upper bound is ``z^2 / (n + z^2)``. At ``z=1.96``
    that falls below ``safe_upper_bound=0.10`` only from **n = 35** distinct
    discards upward (n=34 gives 0.1015, n=35 gives 0.0989). The planned
    ``mixed-v1`` 5+1 run is expected to yield roughly 16 distinct discards,
    where the best attainable upper bound is ~0.194. A ``safe`` verdict is
    therefore unreachable at the planned sample size — only
    ``over_discarding`` or ``inconclusive`` can be returned, and clearing
    entailment requires the staged expansion to pool at least 35 distinct
    discards with zero verified. This is a documented property of the
    pre-registered rule, not a defect to be tuned away.
    """

    wilson_z: float = 1.96
    safe_upper_bound: float = 0.10
    over_discard_lower_bound: float = 0.40


class DeepAnalysisConfig(StrictConfigModel):
    enabled: bool = False
    complexity_threshold: float = 0.5
    models: DeepAnalysisModelsConfig = Field(default_factory=DeepAnalysisModelsConfig)
    effort: dict[str, DeepAnalysisEffortConfig] = Field(
        default_factory=lambda: {
            "scout": DeepAnalysisEffortConfig(
                token_cap=2000,
                wall_clock_cap=120,
            ),
            "dig": DeepAnalysisEffortConfig(
                token_cap=12000,
                wall_clock_cap=600,
            ),
            "synth": DeepAnalysisEffortConfig(
                token_cap=8000,
                wall_clock_cap=300,
            ),
        }
    )
    global_token_cap: int = 300000
    breadth_pass_ratio: float = 0.30
    score_floor: float = 0.05
    aging_per_round: float = 0.05
    value_decay: float = 0.8
    max_depth: int = 4
    # discovery 소스로 쓸 스킬 allowlist. URL을 반환해 fetch/원문대조가 가능한
    # 것만 넣는다 — URL 없는 스킬 결과는 E_SOURCE_DEAD로 거절된다.
    discovery_skills: list[str] = Field(
        default_factory=lambda: [
            "arxiv",
            "pubmed",
            "openalex",
            "semantic-scholar",
            "google-scholar",
            "sec-edgar",
            "news-api",
            "wikipedia",
        ]
    )
    # dig의 token_cap(12000)을 도구 스키마가 잠식하지 않도록 하는 상한.
    max_discovery_skills: int = 3
    # 챗 워크플로우 노드가 orch.run()을 기다리는 상한(초). D18 선결조건(1).
    # 이 값은 run 전체를 덮는다 — effort별 wall_clock_cap(dig 600s)보다 크게 잡으면
    # 바운드 의미가 없다. 챗 경로의 실질 예산은 프론트 maxDuration(60s)이 더 작으므로,
    # 이 캡은 "게이트웨이가 포기한 뒤에도 백엔드가 자원을 붙들고 있는 것"을 막는 용도다.
    node_wall_clock_cap: float = 300.0
    parallel_workers: int = 4
    quote_match_threshold: float = 0.92
    confidence_cap: dict[int, float] = Field(
        default_factory=lambda: {1: 0.6, 2: 0.8, 3: 0.95}
    )
    agentic_threshold: float = 0.35
    agentic_sample_rate: float = 0.3
    # The judge returns {"label", "rationale"}. The budget is consumed mainly
    # by ADAPTIVE THINKING, not the rationale: the judge model declares
    # `thinking: adaptive` and llm.py:137 hardcodes thinking_enabled=True.
    # Thinking tokens count against max_tokens but are stripped from content,
    # so they are invisible in a cassette while fully charged — one truncated
    # response spent 300 output tokens on 83 characters of text. Tune this
    # against the thinking budget, not against rationale length.
    # At the previous hardcoded 300, four
    # responses in sample 20260802T052306Z were cut mid-rationale — and a
    # truncated response raises JSONParseError, which _judge_failed turns
    # into a D14 fail-open pass for non-mandatory claims. One of those had
    # already emitted "label": "CONTRADICTS", so a rejection became an
    # acceptance. Completed responses measured 60-282 tokens (median 104),
    # a maximum censored by the old ceiling.
    judge_max_output_tokens: int = 800
    # One batched entailment call decides keep/narrow/discard for every claim a
    # worker produced. On truncation, parse_json raises and worker.py returns
    # the original batch — the whole batch bypasses the discard filter, and
    # nothing records it. At 1200, one of eighteen calls in sample
    # 20260802T052306Z was cut; completed responses ran 97-923 tokens.
    # As with the judge ceiling, adaptive thinking (llm.py:137) consumes most
    # of the budget invisibly — the truncated call spent ~1155 tokens on
    # thinking for 183 characters of text.
    #
    # Do NOT recalibrate this from batch size. Measured across all 18 calls in
    # that sample, tokens do not scale with claim count: 1 claim->97,
    # 3 claims->{237,434,923,1200(cut)}, 4->{302-598}, 5->{181,225},
    # 6->{512-655}. The cut hit a 3-claim batch while every 6-claim batch
    # finished. The driver is thinking-token variance, not batch size.
    entailment_max_output_tokens: int = 3000

    # A truncated response is a *different failure* from a malformed one: the
    # judgement is unfinished, not wrong. When a call is cut at its configured
    # ceiling (not by the budget clamp), call_json retries once at this
    # multiple of the ceiling.
    #
    # 2.0 is a compromise, not a measured sufficiency. The judge was cut at
    # both 300 and 800, so doubling is not guaranteed to be enough — when it
    # is not, the call site fails closed. The alternative, requesting all
    # remaining headroom, lets one worker monopolise the dev profile's
    # global_token_cap of 100000 across parallel_workers=2 and starve its peer.
    #
    # gt=1.0 because a multiplier at or below 1.0 would not expand the
    # retry's ceiling at all -- it terminates safely but is meaningless.
    truncation_retry_multiplier: float = Field(default=2.0, gt=1.0)
    # The report judge returns {"answers_question", "strength_ok", "rationale"}
    # -- a shape as small as the claim judge's, and it runs on the same model
    # (service.py resolves both from role="everyday").
    #
    # This was hardcoded at 400 in report.py. No truncation has ever been
    # observed at stage="report_grading", but that is not evidence the ceiling
    # is adequate: the deterministic gate rejects before the judge is called in
    # 52 of 61 recorded runs, so the call itself is rare. The relevant evidence
    # comes from the sibling stage -- claim_grading truncated four times at a
    # cap of 300 on the same model, because adaptive thinking (llm.py) spends
    # the ceiling invisibly. 400 sits between that observed failure and the 800
    # the claim judge now uses.
    #
    # Aligned with judge_max_output_tokens rather than raised independently:
    # two judges with the same output shape on the same model should not drift
    # apart for no measured reason.
    report_judge_max_output_tokens: int = 800
    # Share of "factual assertion" sentences allowed to carry no footnote
    # before the report is rejected. Was a module literal in report.py.
    #
    # This is the single most consequential gate in the harness by measured
    # effect: it accounts for all 156 recorded report rejections, and 52 of
    # 61 runs never got past it. Whether 0.20 is right is genuinely open --
    # the reports may be badly cited, or the threshold may be too tight --
    # and that cannot be settled until the ratios themselves are recorded
    # (see report_graded diagnostics). The value is unchanged pending that
    # evidence; it is a setting so the answer can be acted on.
    report_uncited_ratio_max: float = Field(default=0.20, gt=0.0, le=1.0)

    # How many node_reduction calls the finalization floor budgets for.
    #
    # Measured: node_reduction runs a median of 2 times per run (max 9). Runs
    # with deeper trees will see their last reductions degrade to joining
    # child answers, but assembly and the judge survive -- which is the point
    # of the reserve, and why the report tier is isolated from this one.
    # Budgeting for the observed maximum of 9 would put the reduction tier at
    # 93,600 on the default profile -- 93.6% of the dev profile's entire
    # 100,000-token cap on its own, before the report tier or any
    # investigation budget is even counted.
    finalization_reduction_allowance: int = Field(default=2, ge=1)

    # Fraction of a profile's global_token_cap above which the finalization
    # floor is judged to be crowding out investigation. Not expected to fire
    # on the shipped defaults -- the floor is 43.7% of the default profile's
    # cap (131,200 / 300,000) and 41.0% of dev's (41,040 / 100,000) -- so this
    # is a backstop for a profile tuned into a corner, not a signal for normal
    # operation. That margin is thinner than it looks: before the input
    # currency was added the floor was 4.3%/22% of the same caps, nowhere
    # near this 0.5 threshold; 41-44% sits close enough that a moderate
    # further increase to the floor (or cut to a cap) would trip it.
    finalization_floor_warn_ratio: float = Field(default=0.5, gt=0.0, le=1.0)

    # Smallest output grant `TokenBudget.reserve` will issue rather than refuse.
    #
    # A reservation used to succeed on >= 1 token. Measured 2026-08-04: all 5
    # dev runs of the funnel sample died because grants of 25, 38, 851, and
    # 1,123 tokens were issued for prompts needing far more, truncated, and
    # (truncation now being a hard error) failed the whole run.
    #
    # Derived from the same sample's SUCCESSFUL split_decompose calls, which
    # consumed 1,229 / 1,460 / 1,903 / 2,044 output tokens. 2048 covers that
    # observed range, so a grant below it is one the stage has never been
    # seen to complete within. It is not a truncation guarantee -- nothing at
    # this layer can be -- it removes the catastrophic tail.
    #
    # `reserve` clamps this by the caller's own `max_output_tokens`, so stages
    # that deliberately ask for less (the report judge asks 800) are unaffected.
    min_viable_output_tokens: int = Field(default=2048, ge=1)

    # Input allowances for the finalization stages, expressed as multiples of
    # `synthesis_max_tokens` so a profile that shrinks its synthesis ceiling
    # shrinks its floor with it instead of needing three more per-profile
    # knobs.
    #
    # These exist because the floor and `TokenBudget.reserve` used different
    # currencies: the floor counted output tokens only, while `reserve`
    # charges `conservative_input_bound(request) + output`. Measured
    # 2026-08-04: one node_reduction took 6,480 on input alone -- larger than
    # the entire 4,400-token dev floor of the time.
    #
    # Measured: node_reduction input_bound ran 1,225 / 1,369 / 6,480
    # (min/median/max) against synthesis_max_tokens=4000 -> 6480/4000 = 1.62.
    reduction_input_ratio: float = Field(default=1.6, gt=0.0)
    # Never measured -- report_assembly has never received a reservation in
    # 574 runs. This is not an estimate but a CLAMP: `prompt_clamp` shrinks
    # the assembly's child blocks and caveats until `prompt_input_bound`
    # reports a value under this allowance. That bounds those two pieces,
    # not the whole prompt: `root_answer` is deliberately never clamped
    # (design D-6, prompt_clamp.py) so body coverage is preserved, and on
    # the degraded-reduction path it comes from
    # `Synthesizer._degraded_summary`, which joins EVERY child's answer with
    # no bound on child count. A wide degraded tree can therefore make
    # `root_answer` plus the template alone exceed this allowance after the
    # clampable material has already been dropped to nothing. When that
    # happens `clamp_prompt` reports `exhausted=True` and lets `reserve()`
    # decide, same as any other oversized call -- the clamp narrows the
    # failure mode, it does not eliminate it.
    assembly_input_ratio: float = Field(default=3.0, gt=0.0)
    # Derived, not clamped. The judge is handed the whole report and giving it
    # a truncated one changes what is being judged, so there is nothing to
    # clamp. This ratio is NOT a strict bound on the judge's input -- three
    # things add to the assembly's own output ceiling (synthesis_max_tokens)
    # before `ReportGrader.grade_agentic` sees the prompt:
    #   1. `CitationRenderer.render` (citation.py) appends a `## 출처` block
    #      with ONE LINE PER CITED CLAIM, each carrying that claim's full
    #      source URL(s). The count of cited claims is unbounded here.
    #   2. `root_text` (the root question) is passed alongside the report and
    #      is not part of the assembly's output at all.
    #   3. The `report_judge.md` prompt template's own literal instruction
    #      text is a fixed but non-trivial number of bytes.
    # 5.0x carries headroom for all three rather than deriving a strict
    # bound: the token -> UTF-8 byte conversion alone (Korean runs ~3 bytes
    # per syllable at roughly one token per syllable; 4.5 bytes/token covers
    # rarer 4-byte characters and JSON escaping) would already consume most
    # of the margin over 4.0x, so the round-up to 5.0x is what actually
    # absorbs 1-3 above.
    grading_input_ratio: float = Field(default=5.0, gt=0.0)

    max_stall_rounds: int = 3
    claim_retry_cap: int = 2
    # 2 -> 1 (2026-08-09). The extra attempt was buying nothing: sample #9's
    # `report_assembly` reservations were `[1200, 2400]` per run -- the initial
    # call plus its expansion retry, both on attempt 0. Attempts 1 and 2 never
    # got an LLM call at all; they emitted the deterministic template, which is
    # why their `uncited_ratio` and assertion counts were byte-identical to each
    # other in every run. Meanwhile the cap multiplies the report floor
    # (`(cap + 1) * (assembly + grading)`), so the dead attempt was taxing the
    # ceiling that made attempt 0 truncate.
    report_retry_cap: int = 1
    resolve_threshold: float = 0.7
    conflict_reinvestigation_cap: int = 1
    conflict_value_threshold: float = 0.6
    subq_adopt_threshold: float = 0.3
    # 채택 상한. D65 는 `_do_split` 과 같은 4 를 하드코딩했다. 표본 #17 이
    # 그것을 재는 이유를 줬다 -- dev 5건에서 질문이 74 -> 155 로 늘었는데
    # `claim_verified` 는 129 -> 116 으로 **줄었다.** 넓이를 산 대가로 자식
    # 하나하나의 조사가 얕아졌다는 가설이고, 이 노브가 그 가설의 손잡이다.
    subq_adopt_cap: int = 4
    # 채택된 자식들에게 부모의 잔여를 어떻게 나누는가.
    #
    #   "uniform"       -- 잔여 / (n + 1). D65 의 정책이고 표본 #17 이 이것으로
    #                      측정됐다. 부모가 계속 조사하므로 자기 몫을 남긴다.
    #   "value_weighted" -- 부모 몫 하나를 떼고, 나머지를 `value_est` 비율로
    #                      나눈다. 워커가 매긴 값이 실제로 조사 가치를 반영한다면
    #                      값이 높은 가지가 더 깊이 판다.
    #
    # 표본 #18 이 `value_weighted` 를 쟀고 **반증됐다** (D70). 사전 등록대로
    # 되돌린다. 배선은 확실히 작동했다 -- 형제 예산이 흩어진 그룹이 0/23 에서
    # 21/22 로 갔다(H-2). 그런데 `claim_verified` 는 dev 5건에서 82 -> 65 로
    # 내려갔고 `abandoned` 는 15 -> 30 으로 **두 배**가 됐다.
    #
    # 즉 워커의 `value_est` 는 **어느 가지가 증거를 낼지 예측하지 못한다.**
    # 값이 낮다고 예산을 덜 준 가지들이 굶어 죽었고, 그 대가로 산 깊이는
    # 검증된 클레임으로 돌아오지 않았다.
    subq_budget_policy: Literal["uniform", "value_weighted"] = "uniform"
    # §6.3.2 의 독립 심사자. D11 -> D13 -> D65 가 세 번 미뤘다.
    #
    # 워커가 자기 제안에 스스로 값을 매기는 것(D65)은 공짜지만 공정하지 않다.
    # 표본 #17 에서 채택 88건 중 `resolved` 는 2건이고 `abandoned` 가 15건
    # 새로 생겼다 -- 자기 채점이 넓이를 과대평가한다는 신호일 수 있다.
    # 심사자는 제안 전체를 한 번에 보고 **상대 가치**를 다시 매기고 의미
    # 중복을 병합한다(결정론적 정규화가 못 잡는 것).
    #
    # 호출 하나가 더 늘어나므로 기본은 꺼짐이다.
    subq_reviewer_enabled: bool = False
    subq_reviewer_max_output_tokens: int = 700
    # Tier 1 은 **1차 기관 출처**다 -- 규칙을 만든 기관, 데이터를 낸 기관,
    # 심사를 거친 학술 저장소. 편입 기준은 "이 도메인의 문서가 그 사실의
    # 원본인가" 이지 "신뢰할 만한가" 가 아니다. 언론과 기업 블로그는 신뢰할
    # 만해도 2차이므로 들어오지 않는다.
    #
    # 2026-08-09 확장. 원래 목록은 `.gov`/`.edu` 로 **미국 중심**이라
    # `eur-lex.europa.eu`, `who.int`, `birmingham.ac.uk` 이 전부 tier2 --
    # `dev.to` 와 같은 등급이었다. 표본 #7 에서 판정자가 반려한 사유가 정확히
    # 이것이다: "질문이 요구한 '공식 EU 출처' 를 전혀 사용하지 못하고 모두
    # 2차 블로그성 출처에 의존". 증거 119건 중 tier1 은 19건(16%)뿐이었고,
    # 그중에도 `.ac.uk`/`.gov.uk` 는 세지 않은 채였다.
    source_tiers: dict[str, list[str]] = Field(
        default_factory=lambda: {
            "tier1": [
                # 학술 저장소·코드 원본
                "arxiv.org",
                "github.com",
                # 미국
                ".gov",
                ".edu",
                # 초국가 기관 (EU, UN/WHO 계열)
                "europa.eu",
                ".int",
                # 영국
                ".gov.uk",
                ".ac.uk",
                # 한국
                ".go.kr",
                ".re.kr",
                ".ac.kr",
                # 일본
                ".go.jp",
                ".ac.jp",
                # 호주·캐나다·뉴질랜드
                ".gov.au",
                ".edu.au",
                ".gc.ca",
                ".govt.nz",
            ],
            "tier2": ["*"],
        }
    )
    # 검색에서 가져올 후보 배수. `search_result_limit` 개를 fetch 하되 그
    # 몇 배를 후보로 받아 tier 순으로 고른다. fetch 수는 그대로이므로
    # 늘어나는 비용은 검색 결과 몇 줄뿐이다.
    source_candidate_multiplier: int = 3
    # 1차 기관 출처를 겨냥해 한 번 더 검색할 때 원 질문 뒤에 붙일 키워드.
    #
    # `source_candidate_multiplier` 와 `_rank_by_source_tier`(D45)는 **엔진이
    # 이미 돌려준 것 안에서만** 고른다. 엔진이 tier1 URL 을 0건 반환하면 정렬은
    # 항등 함수이고 후보를 3배로 넓혀도 같은 질의의 3배일 뿐이다. 표본 #10 의
    # 판정자가 남긴 두 불만 중 하나가 여기다 -- "질문이 요구한 공식 EU 출처
    # 대신 2차 비공식 출처".
    #
    # `site:` 문법이 아니라 평문 키워드인 이유: `web_search` 는 질의 문자열
    # 하나만 받고(`service.py:17`) 백엔드 엔진이 무엇인지 모른다. `site:` 를
    # 지원하지 않는 엔진에서는 0건이 돌아오는데, 그러면 fetch 할 URL 이 없어
    # 모든 클레임이 E_NO_EVIDENCE 로 거절된다 -- 검색어에 brief 전문을 넣었을
    # 때와 같은 고장이다. 키워드는 최악의 경우에도 결과를 흐릴 뿐 없애지 않고,
    # 워커는 두 질의를 **병합**하므로 결과 집합은 기저 질의의 상위집합이다.
    # `site:` 를 지원하는 배포는 이 값을 그 문법으로 덮어쓰면 된다.
    #
    # 빈 문자열이면 2차 질의를 건너뛴다 -- 별도 on/off 플래그를 두지 않는다.
    search_primary_augment: str = "공식 기관 원문 official primary source"
    dev_profile: DeepAnalysisDevProfileConfig = Field(
        default_factory=DeepAnalysisDevProfileConfig
    )
    discard_recall: DeepAnalysisDiscardRecallConfig = Field(
        default_factory=DeepAnalysisDiscardRecallConfig
    )
    search_result_limit: int = 3
    fetch_timeout_seconds: float = 15.0
    # Identifies this client to the sites it fetches. Deliberately a
    # descriptive bot string, not a browser string: sites that block bots are
    # expressing a preference, and impersonating a browser circumvents it.
    # Wikipedia requires an identifiable UA and returns 403 for browser-like
    # strings; it returns 200 for this one. Deployments should point the
    # contact URL at something they actually monitor.
    fetch_user_agent: str = (
        "NEOS-DeepAnalysis/0.23 (+https://github.com/NEOS-AI/neos)"
    )
    evidence_context_chars: int = 2000
    excerpt_max_chars: int = 500
    # 1500이었을 때 실측 캐소트(20260728T104241Z)에서 decompose 응답 3건이
    # 정확히 1500 output_tokens에서 stop_reason=max_tokens로 잘렸다(1235/1995/1869자,
    # ≈1.13자/토큰 — 에러 로그의 "~1680자" 관측과 일치). 그중 최대 개별
    # subquestion 객체는 399자였다. 완전한 응답(최대 7개) 추정치:
    # 7 * 399자 + JSON 오버헤드(~40자) ≈ 2833자 / 1.13자당토큰 ≈ 2501토큰.
    # 여기에 여유를 두어 3200으로 설정(추정치 대비 +28% 여유, 기존 1500의 ~2.1배).
    decompose_max_tokens: int = 3200
    worker_max_output_tokens: int = 4000
    # ge=1: at s <= 0, the floor formulas can push report_floor_tokens above
    # floor_tokens (which stays non-negative) and `TokenBudget.__init__`
    # raises an opaque ValueError on every run instead of failing at config
    # validation with a clear message.
    synthesis_max_tokens: int = Field(default=4000, ge=1)
    sse_keepalive_seconds: float = 0.5
    # ── Phase 3a (D22): durable job 서비스 ──────────────────────────────
    # 실행 큐. celery_app.py의 task_queues에 이미 정의된 4종 중 하나여야 한다
    # ('default'/'search'/'analysis'/'generation').
    job_queue: str = "analysis"
    # celery_app.py의 전역 기본값(soft 300s / hard 360s)은 심층분석 run에
    # 턱없이 짧다 -- dig effort 하나의 wall_clock_cap만 600s다. 태스크
    # 데코레이터에서 이 값으로 덮어쓴다.
    job_soft_time_limit: int = 3600
    job_time_limit: int = 3900
    # Celery 재시도는 resume=True로 재큐잉된다(스펙 §9 "resume 트리거 = Celery 재시도").
    job_max_retries: int = 2
    # 이벤트 커서 폴링 간격(초). 이벤트가 있으면 즉시 다음 배치를 읽으므로
    # 이 간격은 "새 이벤트가 없을 때"만 적용된다.
    events_poll_interval: float = 1.0
    # 새 이벤트 없이 이만큼 지나면 스트림을 닫는다. 무한 유휴 SSE 커넥션이
    # 워커/게이트웨이 슬롯을 잡아먹지 않게 하는 상한이다. 클라이언트는
    # 마지막 seq를 ?after=로 넘겨 재접속하면 이어서 받는다.
    events_stream_idle_timeout: float = 300.0

    def grading_floor_tokens(self, synthesis_max_tokens: int) -> int:
        """The INNERMOST floor: one judge call that `report_assembly` cannot
        touch (token_budget.GRADING_STAGES).

        Sized for **one** call, not the whole retry loop. The loop's earlier
        gradings are welcome to run on the tier above; what this guarantees
        is that the *last* draft -- the one that actually ships -- can still
        be judged. That was the failure: all three gate passes in the
        ledger's history came from the judge starving on the final attempt,
        which `ReportGrader.grade` degrades to a pass.

        `truncation_retry_multiplier` is in the formula because a judge call
        is really up to two: `call_json` retries a truncated response with a
        doubled ceiling, visible in the ledger as `report_grading`
        reservations of 800 then 1600. The floor that ignored the retry
        could fund the first call and not the second.

        Sample #6 measured judge prompts of 5,900-17,084 tokens against
        3,555-9,443 remaining, so this is checked against reality rather
        than derived and hoped for: dev (1200) gives 13,600 and prod (4000)
        gives 41,600, covering both.
        """
        return int(
            self.truncation_retry_multiplier
            * (
                self.grading_input_ratio * synthesis_max_tokens
                + self.report_judge_max_output_tokens
            )
        )

    def report_floor_tokens(self, synthesis_max_tokens: int) -> int:
        """The INNER floor tier: `report_retry_cap + 1` rounds of one
        assembly plus one judge, counted in the input+output currency
        `TokenBudget.reserve` actually charges.

        `node_reduction` cannot draw on this (token_budget.REPORT_STAGES).
        Sizing it for the whole retry loop is deliberate: `_finalize`
        re-assembles up to `report_retry_cap` times and grades every draft,
        so a tier covering one round leaves the later rounds to fail open --
        the failure this split exists to end.

        The `assembly` term counts the truncation expansion, for the same
        reason `grading_floor_tokens` does (D56, 2026-08-10). `call_text`
        answers a truncated assembly with **the same prompt at
        `truncation_retry_multiplier` times the output ceiling**
        (llm.py:464-474), so a truncated attempt charges its input twice and
        its output `1 + m` times -- not the `input + output` this term used
        to assume.

        Measured, not derived and hoped for. Sample #12 logged the pair
        directly:

            reserved  input_bound=5926 max_out=2000 total=7926   <- attempt
            reserved  input_bound=5926 max_out=4000 total=9926   <- expansion
            DEGRADED  reason=input_bound                          <- retry

        17,852 against a term of 8,000. Five of six runs reserved twice for
        `report_assembly`; one reserved three times. The old term funded two
        attempts, a truncated attempt costs three, and so `_finalize`'s retry
        was refused its reservation in four of six runs -- which is why the
        retry loop had never run (D53, D55). The corrected term is 18,000.

        Note `grading` is left as `m * (input + output)` rather than the
        exact `m * input + (1 + m) * output`. The two differ by exactly one
        `report_judge_max_output_tokens` (800 dev / 800 prod) against a term
        of 10,800 -- under 8%, and no measurement points at it. The assembly
        term is corrected because a sample measured it binding.
        """
        assembly = int(
            self.truncation_retry_multiplier
            * self.assembly_input_ratio
            * synthesis_max_tokens
            + (1 + self.truncation_retry_multiplier) * synthesis_max_tokens
        )
        grading = int(
            self.grading_input_ratio * synthesis_max_tokens
            + self.report_judge_max_output_tokens
        )
        return (self.report_retry_cap + 1) * (assembly + grading)

    def finalization_floor_tokens(self, synthesis_max_tokens: int) -> int:
        """The TOTAL floor: the report tier plus
        `finalization_reduction_allowance` node_reduction calls.

        Shared by `neos/config/loader.py`'s `warn_finalization_floor_ratio`
        (checks this against `global_token_cap` at config-load time) and
        `neos/workflow/deep_analysis/service.py`'s `build_orchestrator` (the
        floor actually enforced by `TokenBudget`). Kept as one method, not two
        independent expressions, so a future change to the formula cannot
        silently leave the warning describing a floor that is no longer in
        force.
        """
        reduction = int(
            (self.reduction_input_ratio + 1) * synthesis_max_tokens
        )
        return (
            self.report_floor_tokens(synthesis_max_tokens)
            + self.finalization_reduction_allowance * reduction
        )


class RayConfig(StrictConfigModel):
    enabled: bool = False
    address: str = "auto"
    num_cpus: float | None = None
    object_store_memory: int = 2_000_000_000


class SandboxLifecycleConfig(StrictConfigModel):
    create_timeout_sec: float = Field(default=30.0, gt=0, le=300)
    idle_timeout_sec: float = Field(default=900.0, gt=0)
    max_lifetime_sec: float = Field(default=14_400.0, gt=0)


class SandboxResourceConfig(StrictConfigModel):
    cpu_count: float = Field(default=1.0, gt=0, le=64)
    memory_bytes: int = Field(default=512 * 1024 * 1024, gt=0)
    pids: int = Field(default=128, gt=0)
    workspace_bytes: int = Field(default=1024 * 1024 * 1024, gt=0)
    tmpfs_bytes: int = Field(default=64 * 1024 * 1024, gt=0)


class SandboxExecutionConfig(StrictConfigModel):
    command_timeout_sec: float = Field(default=30.0, gt=0)
    max_output_bytes: int = Field(default=1024 * 1024, gt=0)
    max_stdin_bytes: int = Field(default=1024 * 1024, gt=0)
    allowed_env_names: list[str] = Field(
        default_factory=lambda: [
            "HOME",
            "LANG",
            "LC_ALL",
            "PATH",
            "TERM",
            "TMPDIR",
        ]
    )


class SandboxStreamConfig(StrictConfigModel):
    pty_max_sessions: int = Field(default=4, gt=0, le=32)
    replay_events: int = Field(default=1024, gt=0)
    replay_bytes: int = Field(default=1024 * 1024, gt=0)
    watcher_debounce_sec: float = Field(default=0.05, gt=0, le=5)


class SandboxWorkspaceConfig(StrictConfigModel):
    tree_max_entries: int = Field(default=5_000, gt=0, le=20_000)
    file_max_bytes: int = Field(default=1024 * 1024, gt=0)
    diff_max_bytes: int = Field(default=2 * 1024 * 1024, gt=0)
    edit_batch_size: int = Field(default=20, gt=0, le=100)
    ticket_ttl_seconds: int = Field(default=30, gt=0, le=300)
    pty_idle_ttl_seconds: int = Field(default=1_800, gt=0)
    pty_max_sessions: int = Field(default=3, gt=0, le=10)


class SandboxDockerConfig(StrictConfigModel):
    image: str = ""
    network_mode: str = "none"
    user: str = "10001:10001"
    allow_unpinned_image: bool = False


class SandboxMemoryConfig(StrictConfigModel):
    root: str = ".neos/sandboxes"


class SandboxConfig(StrictConfigModel):
    enabled: bool = False
    provider: Literal["memory", "docker"] = "memory"
    lifecycle: SandboxLifecycleConfig = Field(
        default_factory=SandboxLifecycleConfig
    )
    resources: SandboxResourceConfig = Field(
        default_factory=SandboxResourceConfig
    )
    execution: SandboxExecutionConfig = Field(
        default_factory=SandboxExecutionConfig
    )
    streams: SandboxStreamConfig = Field(default_factory=SandboxStreamConfig)
    workspace: SandboxWorkspaceConfig = Field(
        default_factory=SandboxWorkspaceConfig
    )
    memory: SandboxMemoryConfig = Field(default_factory=SandboxMemoryConfig)
    docker: SandboxDockerConfig = Field(default_factory=SandboxDockerConfig)


class CodingModelConfig(StrictConfigModel):
    enabled: bool = False
    provider: Literal["anthropic"] = "anthropic"
    model: str | None = None
    model_timeout_sec: float = Field(default=120, gt=0, le=600)
    tool_timeout_sec: float = Field(default=30, gt=0, le=300)
    max_turns: int = Field(default=20, gt=0, le=100)
    max_tool_calls: int = Field(default=50, gt=0, le=500)
    max_consecutive_tool_errors: int = Field(default=3, gt=0, le=20)
    max_output_tokens: int = Field(default=8192, gt=0)
    max_transcript_bytes: int = Field(default=1_048_576, gt=0)
    max_text_delta_bytes: int = Field(default=16_384, gt=0)
    max_public_text_bytes: int = Field(default=1_048_576, gt=0)
    max_cost_usd: float = Field(default=5.0, gt=0)
    input_cost_micros_per_million: int = Field(default=0, ge=0)
    output_cost_micros_per_million: int = Field(default=0, ge=0)
    command_enabled: bool = True
    command_allowlist: list[str] = Field(
        default_factory=lambda: ["pytest", "ruff", "mypy", "pnpm", "git"]
    )
    mutation_snapshot_interval: int = Field(default=5, gt=0)
    approval_ttl_seconds: int = Field(default=900, gt=0)
    approval_reconciliation_batch_size: int = Field(default=100, gt=0, le=1000)

    @model_validator(mode="after")
    def validate_command_policy(self) -> "CodingModelConfig":
        if not (
            self.max_text_delta_bytes
            <= self.max_public_text_bytes
            <= self.max_transcript_bytes
        ):
            raise ValueError("coding public text byte limits are invalid")
        malformed = any(
            not command or re.fullmatch(r"[A-Za-z0-9._+-]+", command) is None
            for command in self.command_allowlist
        )
        if malformed or (self.command_enabled and not self.command_allowlist):
            raise ValueError("coding command allowlist is invalid")
        if not self.command_enabled and self.command_allowlist:
            raise ValueError("command-disabled mode requires an empty command allowlist")
        return self


class ContextualRetrievalConfig(StrictConfigModel):
    enabled: bool = False
    model: str = "claude-haiku-4-5-20251001"
    max_tokens: int = 200
    max_concurrent: int = 3
    max_chunks_per_doc: int = 200
    budget_cap_usd: float = 0.10
    embed_source: str = "contextual"


class ExecutionApprovalConfig(StrictConfigModel):
    enabled: bool = False
    required_skills: list[str] = Field(
        default_factory=lambda: ["api_call", "file_processing", "task_creation", "code_execution"]
    )
    timeout_seconds: int = 60
    default_autonomy_level: Literal[0, 1, 2] = 1

    @field_validator("required_skills", mode="before")
    @classmethod
    def parse_required_skills(cls, value: Any) -> Any:
        return _split_csv(value)


class TelegramChannelConfig(StrictConfigModel):
    enabled: bool = False


class DiscordChannelConfig(StrictConfigModel):
    enabled: bool = False


class SlackChannelConfig(StrictConfigModel):
    enabled: bool = False


class ChannelConfig(StrictConfigModel):
    telegram: TelegramChannelConfig = Field(default_factory=TelegramChannelConfig)
    discord: DiscordChannelConfig = Field(default_factory=DiscordChannelConfig)
    slack: SlackChannelConfig = Field(default_factory=SlackChannelConfig)
    bot_user_id: str = ""


class ContextAssemblyConfig(StrictConfigModel):
    max_tokens: int = 8000
    short_term_ratio: float = 0.50
    long_term_ratio: float = 0.30
    episodic_ratio: float = 0.20

    @property
    def ratio_sum(self) -> float:
        return self.short_term_ratio + self.long_term_ratio + self.episodic_ratio


class CronConfig(StrictConfigModel):
    enabled: bool = True
    default_timezone: str = "UTC"
    max_tasks_per_user: int = 20
    llm_fallback_enabled: bool = True
    llm_model: str = "claude-haiku-4-5-20251001"


class OllamaConfig(StrictConfigModel):
    base_url: str = "http://localhost:11434"
    default_model: str = "llama3.1:8b"


class ModelProviderConfig(StrictConfigModel):
    ollama: OllamaConfig = Field(default_factory=OllamaConfig)


class A2UIConfig(StrictConfigModel):
    enabled: bool = False
    llm_model: str = "claude-haiku-4-5-20251001"
    llm_provider: str = "anthropic"
    max_components: int = 10
    frame_timeout: int = 300


class InlineVisualizationConfig(StrictConfigModel):
    enabled: bool = True


class AppConfig(StrictConfigModel):
    environment: Literal["development", "staging", "production"] = "development"
    api: ApiConfig = Field(default_factory=ApiConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    redis: RedisConfig = Field(default_factory=RedisConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)
    smart_cache: SmartCacheConfig = Field(default_factory=SmartCacheConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    model_routing: ModelRoutingConfig = Field(default_factory=ModelRoutingConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    vision: VisionConfig = Field(default_factory=VisionConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    iterative_explorer: IterativeExplorerConfig = Field(default_factory=IterativeExplorerConfig)
    quality_evaluator: QualityEvaluatorConfig = Field(default_factory=QualityEvaluatorConfig)
    workflow: WorkflowConfig = Field(default_factory=WorkflowConfig)
    research_harness: ResearchHarnessConfig = Field(default_factory=ResearchHarnessConfig)
    thinking_engine: ThinkingEngineConfig = Field(default_factory=ThinkingEngineConfig)
    secrets: SecretsConfig = Field(default_factory=SecretsConfig)
    sources: SourceIntegrationsConfig = Field(default_factory=SourceIntegrationsConfig)
    youtube: YouTubeConfig = Field(default_factory=YouTubeConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    session: SessionConfig = Field(default_factory=SessionConfig)
    rate_limit: RateLimitConfig = Field(default_factory=RateLimitConfig)
    circuit_breaker: CircuitBreakerConfig = Field(default_factory=CircuitBreakerConfig)
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)
    mcp: MCPConfig = Field(default_factory=MCPConfig)
    dataset: DatasetConfig = Field(default_factory=DatasetConfig)
    web_search_logging: WebSearchLoggingConfig = Field(default_factory=WebSearchLoggingConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    checkpointer: CheckpointerConfig = Field(default_factory=CheckpointerConfig)
    document_processing: DocumentProcessingConfig = Field(default_factory=DocumentProcessingConfig)
    knowledge_graph: KnowledgeGraphConfig = Field(default_factory=KnowledgeGraphConfig)
    deep_research: DeepResearchConfig = Field(default_factory=DeepResearchConfig)
    artifacts: ArtifactsConfig = Field(default_factory=ArtifactsConfig)
    chat: ChatConfig = Field(default_factory=ChatConfig)
    context_optimization: ContextOptimizationConfig = Field(default_factory=ContextOptimizationConfig)
    telemetry: TelemetryConfig = Field(default_factory=TelemetryConfig)
    celery: CeleryConfig = Field(default_factory=CeleryConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    query_classifier: QueryClassifierConfig = Field(default_factory=QueryClassifierConfig)
    executive_summary: ExecutiveSummaryConfig = Field(default_factory=ExecutiveSummaryConfig)
    query_expansion: QueryExpansionConfig = Field(default_factory=QueryExpansionConfig)
    cost_aware_routing: CostAwareRoutingConfig = Field(default_factory=CostAwareRoutingConfig)
    citations: CitationConfig = Field(default_factory=CitationConfig)
    fact_check: FactCheckConfig = Field(default_factory=FactCheckConfig)
    search_fallback: SearchFallbackConfig = Field(default_factory=SearchFallbackConfig)
    tool_search: ToolSearchConfig = Field(default_factory=ToolSearchConfig)
    hybrid_search: HybridSearchConfig = Field(default_factory=HybridSearchConfig)
    reranker: RerankerConfig = Field(default_factory=RerankerConfig)
    recursive_agent: RecursiveAgentConfig = Field(default_factory=RecursiveAgentConfig)
    hyper_deep_agent: HyperDeepAgentConfig = Field(default_factory=HyperDeepAgentConfig)
    deep_analysis: DeepAnalysisConfig = Field(default_factory=DeepAnalysisConfig)
    ray: RayConfig = Field(default_factory=RayConfig)
    sandbox: SandboxConfig = Field(default_factory=SandboxConfig)
    coding_model: CodingModelConfig = Field(default_factory=CodingModelConfig)
    contextual_retrieval: ContextualRetrievalConfig = Field(default_factory=ContextualRetrievalConfig)
    execution_approval: ExecutionApprovalConfig = Field(default_factory=ExecutionApprovalConfig)
    channels: ChannelConfig = Field(default_factory=ChannelConfig)
    context_assembly: ContextAssemblyConfig = Field(default_factory=ContextAssemblyConfig)
    cron: CronConfig = Field(default_factory=CronConfig)
    model_providers: ModelProviderConfig = Field(default_factory=ModelProviderConfig)
    a2ui: A2UIConfig = Field(default_factory=A2UIConfig)
    inline_visualization: InlineVisualizationConfig = Field(default_factory=InlineVisualizationConfig)

    @model_validator(mode="after")
    def validate_sandbox_policy(self) -> "AppConfig":
        sandbox = self.sandbox
        if (
            sandbox.lifecycle.idle_timeout_sec
            > sandbox.lifecycle.max_lifetime_sec
        ):
            raise ValueError("Sandbox idle timeout exceeds maximum lifetime.")
        if (
            sandbox.execution.command_timeout_sec
            > sandbox.lifecycle.max_lifetime_sec
        ):
            raise ValueError("Sandbox command timeout exceeds maximum lifetime.")
        if self.environment == "production" and sandbox.provider == "docker":
            docker = sandbox.docker
            digest_image = re.fullmatch(
                r"[^\s]+@sha256:[0-9a-f]{64}",
                docker.image,
            )
            non_root = docker.user.split(":", 1)[0] != "0"
            if (
                digest_image is None
                or docker.network_mode != "none"
                or not non_root
                or docker.allow_unpinned_image
            ):
                raise ValueError("Unsafe production Docker sandbox configuration.")
        return self

    @model_validator(mode="after")
    def validate_coding_model_policy(self) -> "AppConfig":
        if not self.coding_model.enabled:
            return self
        if not self.sandbox.enabled or not self.secrets.anthropic_api_key:
            raise ValueError(
                "coding real loop requires an enabled sandbox and Anthropic credential"
            )
        if (
            self.coding_model.input_cost_micros_per_million <= 0
            or self.coding_model.output_cost_micros_per_million <= 0
        ):
            raise ValueError(
                "coding real loop requires positive input and output prices"
            )
        if (
            self.environment in {"staging", "production"}
            and self.sandbox.provider != "docker"
        ):
            raise ValueError(
                "coding real loop requires a Docker sandbox in staging and production"
            )
        return self

    @model_validator(mode="after")
    def validate_context_assembly_ratios(self) -> "AppConfig":
        ratio_sum = self.context_assembly.ratio_sum
        if abs(ratio_sum - 1.0) <= 0.01:
            return self

        message = f"Context assembly ratios sum to {ratio_sum:.3f}, not 1.0."
        if self.environment in {"staging", "production"}:
            raise ValueError(message)
        logger.warning(message)
        return self
