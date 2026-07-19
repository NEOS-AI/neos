from __future__ import annotations

import os
from typing import Any

from neos.config.loader import LEGACY_ENV_KEYS, SECRET_ENV_MAPPING, load_app_config
from neos.config.schema import AppConfig
from neos.prompts.artifact import SYSTEM_PROMPT_FOR_ARTIFACT

WORKFLOW_CRITICAL_NODES = [
    "query_classifier",
    "search_orchestrator",
    "analysis_orchestrator",
    "quality_validator",
    "response_generator",
]
ALLOWED_FILE_EXTENSIONS = [".pdf", ".docx", ".txt", ".md", ".csv", ".xlsx", ".pptx"]
CELERY_ACCEPT_CONTENT = ["json"]
INLINE_VIS_SYSTEM_PROMPT = """
## Inline Visualization Tools
You have access to visualization tools. Use them to enhance explanations:
- `renderDiagram`: For processes (flowchart), system structures, sequences, or causal relationships
- `renderChart`: For comparisons (bar), trends over time (line), or proportions (pie)

Rules:
- Call visualization tools BETWEEN text paragraphs, not all at the end
- Use Mermaid syntax: wrap node text with special chars in quotes (e.g., A["Node text"] --> B)
- One response can contain multiple tool calls
"""

CONSTANT_SETTINGS = {
    "ARTIFACTS_SYSTEM_PROMPT": SYSTEM_PROMPT_FOR_ARTIFACT,
    "INLINE_VIS_SYSTEM_PROMPT": INLINE_VIS_SYSTEM_PROMPT,
    "WORKFLOW_CRITICAL_NODES": WORKFLOW_CRITICAL_NODES,
    "ALLOWED_FILE_EXTENSIONS": ALLOWED_FILE_EXTENSIONS,
    "CELERY_ACCEPT_CONTENT": CELERY_ACCEPT_CONTENT,
    "CODING_FAKE_LOOP_ENABLED": os.getenv(
        "CODING_FAKE_LOOP_ENABLED", "false"
    ).lower()
    in {"1", "true", "yes", "on"},
    "CODING_DEV_RECONCILIATION_SECONDS": float(
        os.getenv("CODING_DEV_RECONCILIATION_SECONDS", "2")
    ),
    "CODING_DEV_DISCOVERY_BATCH_SIZE": int(
        os.getenv("CODING_DEV_DISCOVERY_BATCH_SIZE", "100")
    ),
    "CODING_DEV_SHUTDOWN_SECONDS": float(
        os.getenv("CODING_DEV_SHUTDOWN_SECONDS", "10")
    ),
    "CODING_CELERY_ENABLED": os.getenv(
        "CODING_CELERY_ENABLED", "false"
    ).lower()
    in {"1", "true", "yes", "on"},
    "CODING_CELERY_QUEUE": os.getenv("CODING_CELERY_QUEUE", "coding"),
    "CODING_CELERY_RECONCILIATION_SECONDS": float(
        os.getenv("CODING_CELERY_RECONCILIATION_SECONDS", "10")
    ),
    "CODING_CELERY_DISCOVERY_BATCH_SIZE": int(
        os.getenv("CODING_CELERY_DISCOVERY_BATCH_SIZE", "100")
    ),
    "CODING_CELERY_SOFT_TIME_LIMIT_SECONDS": int(
        os.getenv("CODING_CELERY_SOFT_TIME_LIMIT_SECONDS", "300")
    ),
    "CODING_CELERY_HARD_TIME_LIMIT_SECONDS": int(
        os.getenv("CODING_CELERY_HARD_TIME_LIMIT_SECONDS", "360")
    ),
    "CODING_EXECUTION_LEASE_SECONDS": int(
        os.getenv("CODING_EXECUTION_LEASE_SECONDS", "30")
    ),
    "JWT_ALGORITHM": "HS256",
    "PASSWORD_MIN_LENGTH": 8,
    "PASSWORD_MAX_LENGTH": 72,
    "PASSWORD_REQUIRE_UPPERCASE": False,
    "PASSWORD_REQUIRE_LOWERCASE": True,
    "PASSWORD_REQUIRE_DIGIT": True,
    "PASSWORD_REQUIRE_SPECIAL": True,
    "API_KEY_LENGTH": 32,
    "API_KEY_PREFIX": "neos_",
}

LEGACY_EXACT_PATHS = {
    **SECRET_ENV_MAPPING,
    **LEGACY_ENV_KEYS,
    "WORKFLOW_RESPONSE_CACHE_TTL": "cache.workflow_response_ttl",
    "USER_SPECIFIC_CACHE": "cache.user_specific",
    "SEMANTIC_CACHE_ENABLED": "cache.semantic.enabled",
    "SEMANTIC_CACHE_THRESHOLD": "cache.semantic.threshold",
    "FAST_LLM_MODEL": "llm.fast_model",
    "LLM_TIMEOUT_RESEARCH_PLANNING": "llm.research_planning_timeout",
    "GEMINI_EMBEDDING_TASK_TYPE": "embedding.gemini_task_type",
    "GEMINI_EMBEDDING_IMAGE_TASK_TYPE": "embedding.gemini_image_task_type",
    "GEMINI_EMBEDDING_VIDEO_TASK_TYPE": "embedding.gemini_video_task_type",
    "AGENT_TIMEOUTS": "agent.timeouts",
    "MAX_ITERATIONS": "agent.max_iterations",
    "AGENT_TIMEOUT": "agent.timeout",
    "MAX_CONCURRENT_WORKFLOWS": "agent.max_concurrent_workflows",
    "MAX_CONCURRENT_AGENTS_PER_WORKFLOW": "agent.max_concurrent_agents_per_workflow",
    "STREAM_EVENT_TIMEOUT": "agent.stream_event_timeout",
    "STREAM_HEARTBEAT_INTERVAL": "agent.stream_heartbeat_interval",
    "SEARCH_ORCHESTRATION_TIMEOUT": "workflow.search_orchestration_timeout",
    "API_V1_PREFIX": "api.v1_prefix",
    "DEBUG": "api.debug",
    "CORS_ALLOWED_ORIGINS": "api.cors.allowed_origins",
    "CORS_ALLOW_CREDENTIALS": "api.cors.allow_credentials",
    "API_GATEWAY_ENABLED": "api.gateway.enabled",
    "API_GATEWAY_USER_ID_HEADER": "api.gateway.user_id_header",
    "API_GATEWAY_TRUSTED_IPS": "api.gateway.trusted_ips",
    "JWT_ACCESS_TOKEN_EXPIRE_MINUTES": "auth.access_token_expire_minutes",
    "JWT_REFRESH_TOKEN_EXPIRE_DAYS": "auth.refresh_token_expire_days",
    "GOOGLE_OAUTH_CLIENT_ID": "auth.google_oauth_client_id",
    "GOOGLE_OAUTH_CLIENT_SECRET": "auth.google_oauth_client_secret",
    "SESSION_COOKIE_NAME": "session.cookie_name",
    "SESSION_EXPIRE_SECONDS": "session.expire_seconds",
    "RATE_LIMIT_LOGIN_ATTEMPTS": "rate_limit.login_attempts",
    "RATE_LIMIT_LOGIN_WINDOW_SECONDS": "rate_limit.login_window_seconds",
    "RATE_LIMIT_API_CALLS_PER_MINUTE": "rate_limit.api_calls_per_minute",
    "CIRCUIT_BREAKER_EXPECTED_EXCEPTION": "circuit_breaker.expected_exception",
    "LOG_LEVEL": "observability.log_level",
    "OBSERVABILITY_ENABLED": "observability.enabled",
    "PHOENIX_HOST": "observability.phoenix.host",
    "PHOENIX_PORT": "observability.phoenix.port",
    "PHOENIX_COLLECTOR_ENDPOINT": "observability.phoenix.collector_endpoint",
    "PHOENIX_PROJECT_NAME": "observability.phoenix.project_name",
    "METRICS_ENABLED": "observability.metrics_enabled",
    "TRACE_ENABLED": "observability.trace_enabled",
    "MAX_TRACES": "observability.max_traces",
    "TRACE_RETENTION_DAYS": "observability.trace_retention_days",
    "TRACK_LLM_CALLS": "observability.track_llm_calls",
    "TRACK_AGENT_PERFORMANCE": "observability.track_agent_performance",
    "TRACK_WORKFLOW_METRICS": "observability.track_workflow_metrics",
    "TOOL_SELECTION_STRATEGY": "mcp.tool_selection_strategy",
    "TOOL_QUALITY_THRESHOLD": "mcp.tool_quality_threshold",
    "TOOL_PERFORMANCE_PRIORITY": "mcp.tool_performance_priority",
    "WEB_SEARCH_LOG_ASYNC": "web_search_logging.async_enabled",
    "WEB_SEARCH_LOG_QUEUE_TYPE": "web_search_logging.queue_type",
    "S3_BUCKET_NAME": "storage.s3.bucket_name",
    "S3_ENDPOINT_URL": "storage.s3.endpoint_url",
    "AWS_REGION": "storage.s3.region",
    "RUSTFS_BUCKET_NAME": "storage.rustfs.bucket_name",
    "RUSTFS_ENDPOINT_URL": "storage.rustfs.endpoint_url",
    "LOCAL_STORAGE_PATH": "storage.local.path",
    "MAX_FILE_SIZE": "document_processing.max_file_size",
    "CHUNK_SIZE": "document_processing.chunk_size",
    "CHUNK_OVERLAP": "document_processing.chunk_overlap",
    "DEFAULT_CHUNKING_STRATEGY": "document_processing.default_chunking_strategy",
    "SEMANTIC_CHUNK_THRESHOLD": "document_processing.semantic_chunk_threshold",
    "EVIDENCE_GRAPH_ENABLED": "knowledge_graph.evidence_graph.enabled",
    "KG_POPULATION_ENABLED": "knowledge_graph.population.enabled",
    "KG_MAX_TRAVERSAL_DEPTH": "knowledge_graph.max_traversal_depth",
    "KG_SEARCH_WEIGHT": "knowledge_graph.search_weight",
    "KG_EXTRACTION_ENABLED": "knowledge_graph.extraction.enabled",
    "KG_EXTRACTION_MODEL": "knowledge_graph.extraction.model",
    "KG_MIN_CONFIDENCE": "knowledge_graph.min_confidence",
    "ENVIRONMENT": "environment",
    "ARTIFACTS_ENABLED": "artifacts.enabled",
    "ARTIFACT_LLM_MODEL": "artifacts.llm_model",
    "ARTIFACT_LLM_TEMPERATURE": "artifacts.llm_temperature",
    "ARTIFACT_LLM_MAX_TOKENS": "artifacts.llm_max_tokens",
    "CHAT_DEFAULT_MAX_TOKENS": "chat.default_max_tokens",
    "ENABLE_WORKFLOW_IN_CHAT": "chat.enable_workflow",
    "ENABLE_RESPONSE_REFINEMENT": "chat.enable_response_refinement",
    "CHAT_HISTORY_ENABLED": "chat.history_enabled",
    "MAX_HISTORY_MESSAGES": "chat.max_history_messages",
    "HISTORY_CONTEXT_MAX_TOKENS": "chat.history_context_max_tokens",
    "HISTORY_USAGE_LEVEL": "chat.history_usage_level",
    "THINKING_BLOCKS_ENABLED": "chat.thinking_blocks_enabled",
    "MAX_THINKING_LENGTH": "chat.max_thinking_length",
    "DISABLE_THINKING_FOR_SEARCH": "chat.disable_thinking_for_search",
    "CHAT_TOKEN_BUDGET": "chat.token_budget",
    "USE_TIKTOKEN": "context_optimization.use_tiktoken",
    "TOKEN_COUNTER_MODEL": "context_optimization.token_counter_model",
    "CONTEXT_OVERFLOW_DETECTION": "context_optimization.overflow_detection",
    "CONTEXT_WINDOW_THRESHOLD": "context_optimization.window_threshold",
    "MAX_CONTEXT_TOKENS": "context_optimization.max_context_tokens",
    "CONTEXT_RESERVE_TOKENS": "context_optimization.reserve_tokens",
    "TOOL_RESULT_SUMMARIZATION": "context_optimization.tool_result_summarization",
    "TOOL_RESULT_MAX_LENGTH": "context_optimization.tool_result_max_length",
    "TOOL_RESULT_SUMMARIZATION_MODEL": "context_optimization.tool_result_summarization_model",
    "MESSAGE_COMPRESSION_ENABLED": "context_optimization.message_compression_enabled",
    "MESSAGE_COMPRESSION_THRESHOLD": "context_optimization.message_compression_threshold",
    "MESSAGE_COMPRESSION_RATIO": "context_optimization.message_compression_ratio",
    "MESSAGE_HISTORY_MAX_TOKENS": "context_optimization.message_history_max_tokens",
    "SEMANTIC_DEDUPLICATION": "context_optimization.semantic_deduplication",
    "SEMANTIC_SIMILARITY_THRESHOLD": "context_optimization.semantic_similarity_threshold",
    "WORKFLOW_CONTEXT_BUDGET": "context_optimization.workflow_context_budget",
    "DEFAULT_WORKFLOW_TOKEN_BUDGET": "context_optimization.default_workflow_token_budget",
    "DEEP_RESEARCH_TOKEN_BUDGET": "deep_research.token_budget",
    "OTEL_ENABLED": "telemetry.otel.enabled",
    "OTEL_EXPORTER_JAEGER_ENDPOINT": "telemetry.otel.exporter_jaeger_endpoint",
    "OTEL_SERVICE_NAME": "telemetry.otel.service_name",
    "OTEL_SERVICE_VERSION": "telemetry.otel.service_version",
    "OTEL_DEPLOYMENT_ENVIRONMENT": "telemetry.otel.deployment_environment",
    "OTEL_TRACES_SAMPLER": "telemetry.otel.traces_sampler",
    "OTEL_TRACES_SAMPLER_ARG": "telemetry.otel.traces_sampler_arg",
    "OTEL_BSP_MAX_QUEUE_SIZE": "telemetry.otel.bsp_max_queue_size",
    "OTEL_BSP_SCHEDULE_DELAY": "telemetry.otel.bsp_schedule_delay",
    "OTEL_BSP_MAX_EXPORT_BATCH_SIZE": "telemetry.otel.bsp_max_export_batch_size",
    "DEFAULT_COST_BUDGET": "cost_aware_routing.default_budget",
    "CITATIONS_ENABLED": "citations.enabled",
    "CITATION_DEFAULT_STYLE": "citations.default_style",
    "DUCKDUCKGO_MAX_RESULTS": "search_fallback.duckduckgo_max_results",
    "RECURSIVE_AGENT_ENABLED": "recursive_agent.enabled",
    "HYPER_DEEP_AGENT_ENABLED": "hyper_deep_agent.enabled",
    "CONTEXTUAL_RETRIEVAL_ENABLED": "contextual_retrieval.enabled",
    "APPROVAL_REQUIRED_SKILLS": "execution_approval.required_skills",
    "DEFAULT_AUTONOMY_LEVEL": "execution_approval.default_autonomy_level",
    "CHANNEL_BOT_USER_ID": "channels.bot_user_id",
    "CONTEXT_MAX_TOKENS": "context_assembly.max_tokens",
    "CONTEXT_SHORT_TERM_RATIO": "context_assembly.short_term_ratio",
    "CONTEXT_LONG_TERM_RATIO": "context_assembly.long_term_ratio",
    "CONTEXT_EPISODIC_RATIO": "context_assembly.episodic_ratio",
    "OLLAMA_BASE_URL": "model_providers.ollama.base_url",
    "OLLAMA_DEFAULT_MODEL": "model_providers.ollama.default_model",
    "INLINE_VIS_ENABLED": "inline_visualization.enabled",
}

LEGACY_PREFIX_PATHS = [
    ("DATABASE_", "database"),
    ("REDIS_", "redis"),
    ("SMART_CACHE_TTL_", "smart_cache.ttl"),
    ("SMART_CACHE_", "smart_cache"),
    ("LLM_", "llm"),
    ("EMBEDDING_DATASET_", "embedding.dataset"),
    ("EMBEDDING_", "embedding"),
    ("VISION_", "vision"),
    ("REDDIT_USER_AGENT", "sources"),
    ("SEC_EDGAR_USER_AGENT", "sources"),
    ("OPENALEX_EMAIL", "sources"),
    ("STOCK_API_PROVIDER", "sources"),
    ("YOUTUBE_", "youtube"),
    ("LINK_FOLLOWER_", "iterative_explorer.link_follower"),
    ("ITERATIVE_EXPLORER_", "iterative_explorer"),
    ("QUALITY_EVALUATOR_", "quality_evaluator"),
    ("WORKFLOW_", "workflow"),
    ("RESEARCH_HARNESS_", "research_harness"),
    ("CIRCUIT_BREAKER_", "circuit_breaker"),
    ("MCP_", "mcp"),
    ("DATASET_", "dataset"),
    ("DEEP_RESEARCH_", "deep_research"),
    ("CELERY_", "celery"),
    ("MEMORY_", "memory"),
    ("QUERY_CLASSIFIER_", "query_classifier"),
    ("EXECUTIVE_SUMMARY_", "executive_summary"),
    ("QUERY_EXPANSION_", "query_expansion"),
    ("COST_AWARE_ROUTING_", "cost_aware_routing"),
    ("FACT_CHECK_", "fact_check"),
    ("SEARCH_FALLBACK_", "search_fallback"),
    ("TOOL_SEARCH_", "tool_search"),
    ("HYBRID_SEARCH_", "hybrid_search"),
    ("RERANKER_", "reranker"),
    ("CHECKPOINTER_S3_", "checkpointer.s3"),
    ("CHECKPOINTER_", "checkpointer"),
    ("RECURSIVE_", "recursive_agent"),
    ("HYPER_DEEP_", "hyper_deep_agent"),
    ("DEEP_ANALYSIS_", "deep_analysis"),
    ("RAY_", "ray"),
    ("SANDBOX_", "sandbox"),
    ("CONTEXTUAL_", "contextual_retrieval"),
    ("EXECUTION_APPROVAL_", "execution_approval"),
    ("APPROVAL_", "execution_approval"),
    ("CHANNEL_TELEGRAM_", "channels.telegram"),
    ("CHANNEL_DISCORD_", "channels.discord"),
    ("CHANNEL_SLACK_", "channels.slack"),
    ("CRON_", "cron"),
    ("A2UI_", "a2ui"),
]


def _legacy_setting_path(name: str) -> str | None:
    if name in LEGACY_EXACT_PATHS:
        return LEGACY_EXACT_PATHS[name]
    for prefix, base_path in LEGACY_PREFIX_PATHS:
        if name == prefix:
            return base_path
        if name.startswith(prefix):
            suffix = name[len(prefix) :].lower()
            return f"{base_path}.{suffix}" if suffix else base_path
    return None


def _get_nested(config: AppConfig, dotted_path: str) -> Any:
    value: Any = config
    for part in dotted_path.split("."):
        if isinstance(value, dict):
            value = value[part]
        else:
            value = getattr(value, part)
    return value


class Settings:
    def __init__(
        self,
        config: AppConfig | None = None,
        *,
        env: str | None = None,
        config_path: str | None = None,
        secrets_path: str | None = None,
    ) -> None:
        self._config = config or load_app_config(env=env, config_path=config_path, secrets_path=secrets_path)

    @property
    def config(self) -> AppConfig:
        return self._config

    def reload_for_tests(
        self,
        env: str | None = None,
        config_path: str | None = None,
        secrets_path: str | None = None,
    ) -> "Settings":
        return reload_settings_for_tests(env=env, config_path=config_path, secrets_path=secrets_path)

    def __getattr__(self, name: str) -> Any:
        if name in CONSTANT_SETTINGS:
            return CONSTANT_SETTINGS[name]

        if name.isupper():
            path = _legacy_setting_path(name)
            if path is not None:
                try:
                    return _get_nested(self._config, path)
                except (AttributeError, KeyError):
                    pass

        raise AttributeError(f"{type(self).__name__!s} object has no attribute {name!r}")


settings = Settings()


def get_settings() -> Settings:
    return settings


def reload_settings_for_tests(
    env: str | None = None,
    config_path: str | None = None,
    secrets_path: str | None = None,
) -> Settings:
    global settings
    settings = Settings(env=env, config_path=config_path, secrets_path=secrets_path)
    return settings
