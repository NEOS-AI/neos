# NEOS Config Inventory

Generated from `neos/config/settings.py`, `.env.template`, and the config refactor policy in `docs/CONFIG_REFACTOR_PLAN.md`.

## Extraction

- Settings fields command: `rg "^[[:space:]]+[A-Z][A-Z0-9_]+[[:space:]]*:" neos/config/settings.py -n`
- Env template keys command: `rg "^[A-Z][A-Z0-9_]+=" .env.template -n`
- Public uppercase settings fields: `355`
- Assignment-like `.env.template` keys: `227`
  - ⚠️ **This figure is stale.** Re-running the command above yields `46`; the
    template was cut to secrets-only by I1 (`59d98aa6`) and this line was not
    re-measured. Left as-is rather than guessed at, and flagged so it is not
    read as current.
- Combined unique inventory keys, including target bootstrap controls: `367`

## Classification Summary

- `secret_env`: `34`
- `control_env`: `8`
- `yaml`: `309`
- `constant`: `14`
- `removed`: `2`

## Inventory Table

| Setting name | Current source | Target source | Target YAML path | Rationale |
| --- | --- | --- | --- | --- |
| `DATABASE_URL` | settings.py + .env.template | `secret_env` | `database.url` | Secret, credential ID, token, or credential-bearing URL remains env-sourced. |
| `DATABASE_POOL_SIZE` | settings.py + .env.template | `yaml` | `database.pool_size` | Non-secret runtime behavior belongs in validated YAML. |
| `DATABASE_MAX_OVERFLOW` | settings.py + .env.template | `yaml` | `database.max_overflow` | Non-secret runtime behavior belongs in validated YAML. |
| `DATABASE_POOL_TIMEOUT` | settings.py + .env.template | `yaml` | `database.pool_timeout` | Non-secret runtime behavior belongs in validated YAML. |
| `DATABASE_POOL_RECYCLE` | settings.py + .env.template | `yaml` | `database.pool_recycle` | Non-secret runtime behavior belongs in validated YAML. |
| `REDIS_URL` | settings.py + .env.template | `secret_env` | `redis.url` | Secret, credential ID, token, or credential-bearing URL remains env-sourced. |
| `REDIS_TTL` | settings.py + .env.template | `yaml` | `redis.ttl` | Non-secret runtime behavior belongs in validated YAML. |
| `REDIS_POOL_SIZE` | settings.py + .env.template | `yaml` | `redis.pool_size` | Non-secret runtime behavior belongs in validated YAML. |
| `REDIS_MIN_IDLE_CONNECTIONS` | settings.py + .env.template | `yaml` | `redis.min_idle_connections` | Non-secret runtime behavior belongs in validated YAML. |
| `WORKFLOW_RESPONSE_CACHE_TTL` | settings.py + .env.template | `yaml` | `cache.workflow_response.ttl` | Non-secret runtime behavior belongs in validated YAML. |
| `USER_SPECIFIC_CACHE` | settings.py + .env.template | `yaml` | `cache.user_specific` | Non-secret runtime behavior belongs in validated YAML. |
| `SEMANTIC_CACHE_ENABLED` | settings.py + .env.template | `yaml` | `cache.semantic.enabled` | Non-secret runtime behavior belongs in validated YAML. |
| `SEMANTIC_CACHE_THRESHOLD` | settings.py + .env.template | `yaml` | `cache.semantic.threshold` | Non-secret runtime behavior belongs in validated YAML. |
| `SMART_CACHE_ENABLED` | settings.py | `yaml` | `smart_cache.enabled` | Non-secret runtime behavior belongs in validated YAML. |
| `SMART_CACHE_SIMILARITY_THRESHOLD` | settings.py | `yaml` | `smart_cache.similarity_threshold` | Non-secret runtime behavior belongs in validated YAML. |
| `SMART_CACHE_MAX_ENTRIES` | settings.py | `yaml` | `smart_cache.max_entries` | Non-secret runtime behavior belongs in validated YAML. |
| `SMART_CACHE_STATISTICS_ENABLED` | settings.py | `yaml` | `smart_cache.statistics_enabled` | Non-secret runtime behavior belongs in validated YAML. |
| `SMART_CACHE_TTL_REALTIME` | settings.py | `yaml` | `smart_cache.ttl.realtime` | Non-secret runtime behavior belongs in validated YAML. |
| `SMART_CACHE_TTL_FINANCIAL` | settings.py | `yaml` | `smart_cache.ttl.financial` | Non-secret runtime behavior belongs in validated YAML. |
| `SMART_CACHE_TTL_ANALYSIS` | settings.py | `yaml` | `smart_cache.ttl.analysis` | Non-secret runtime behavior belongs in validated YAML. |
| `SMART_CACHE_TTL_RESEARCH` | settings.py | `yaml` | `smart_cache.ttl.research` | Non-secret runtime behavior belongs in validated YAML. |
| `SMART_CACHE_TTL_GENERATION` | settings.py | `yaml` | `smart_cache.ttl.generation` | Non-secret runtime behavior belongs in validated YAML. |
| `OPENAI_API_KEY` | settings.py + .env.template | `secret_env` | `secrets.openai_api_key` | Secret, credential ID, token, or credential-bearing URL remains env-sourced. |
| `ANTHROPIC_API_KEY` | settings.py + .env.template | `secret_env` | `secrets.anthropic_api_key` | Secret, credential ID, token, or credential-bearing URL remains env-sourced. |
| `ANTHROPIC_WORKSPACE_ID` | .env.template | `secret_env` | `secrets.anthropic_workspace_id` | Not itself secret, but paired with the key: an identity-linked key rejects every request without it, and rotating the key can change the workspace. Kept beside the key rather than in YAML. |
| `GOOGLE_API_KEY` | settings.py | `secret_env` | `secrets.google_api_key` | Secret, credential ID, token, or credential-bearing URL remains env-sourced. |
| `TAVILY_API_KEY` | settings.py + .env.template | `secret_env` | `secrets.tavily_api_key` | Secret, credential ID, token, or credential-bearing URL remains env-sourced. |
| `YOUTUBE_API_KEY` | settings.py + .env.template | `secret_env` | `secrets.youtube_api_key` | Secret, credential ID, token, or credential-bearing URL remains env-sourced. |
| `FAST_LLM_MODEL` | settings.py + .env.template | `yaml` | `llm.fast_model` | Non-secret runtime behavior belongs in validated YAML. |
| `EVIDENCE_GRAPH_ENABLED` | settings.py + .env.template | `yaml` | `knowledge_graph.evidence_graph.enabled` | Non-secret runtime behavior belongs in validated YAML. |
| `KG_POPULATION_ENABLED` | settings.py | `yaml` | `knowledge_graph.population.enabled` | Non-secret runtime behavior belongs in validated YAML. |
| `KG_MAX_TRAVERSAL_DEPTH` | settings.py | `yaml` | `knowledge_graph.max_traversal_depth` | Non-secret runtime behavior belongs in validated YAML. |
| `KG_SEARCH_WEIGHT` | settings.py | `yaml` | `knowledge_graph.search_weight` | Non-secret runtime behavior belongs in validated YAML. |
| `GITHUB_API_TOKEN` | settings.py + .env.template | `secret_env` | `secrets.github_api_token` | Secret, credential ID, token, or credential-bearing URL remains env-sourced. |
| `REDDIT_CLIENT_ID` | settings.py + .env.template | `secret_env` | `secrets.reddit_client_id` | Secret, credential ID, token, or credential-bearing URL remains env-sourced. |
| `REDDIT_CLIENT_SECRET` | settings.py + .env.template | `secret_env` | `secrets.reddit_client_secret` | Secret, credential ID, token, or credential-bearing URL remains env-sourced. |
| `REDDIT_USER_AGENT` | settings.py + .env.template | `yaml` | `sources.reddit_user_agent` | Non-secret runtime behavior belongs in validated YAML. |
| `SERPAPI_API_KEY` | settings.py + .env.template | `secret_env` | `secrets.serpapi_api_key` | Secret, credential ID, token, or credential-bearing URL remains env-sourced. |
| `SEC_EDGAR_USER_AGENT` | settings.py + .env.template | `yaml` | `sources.sec_edgar_user_agent` | Non-secret runtime behavior belongs in validated YAML. |
| `OPENALEX_EMAIL` | settings.py + .env.template | `yaml` | `sources.openalex_email` | Non-secret runtime behavior belongs in validated YAML. |
| `OPENWEATHER_API_KEY` | settings.py + .env.template | `secret_env` | `secrets.openweather_api_key` | Secret, credential ID, token, or credential-bearing URL remains env-sourced. |
| `EXCHANGERATE_API_KEY` | settings.py + .env.template | `secret_env` | `secrets.exchangerate_api_key` | Secret, credential ID, token, or credential-bearing URL remains env-sourced. |
| `STOCK_API_PROVIDER` | settings.py + .env.template | `yaml` | `sources.stock_api_provider` | Non-secret runtime behavior belongs in validated YAML. |
| `FINANCIALDATASETS_API_KEY` | settings.py + .env.template | `secret_env` | `secrets.financialdatasets_api_key` | Secret, credential ID, token, or credential-bearing URL remains env-sourced. |
| `ALPHA_VANTAGE_API_KEY` | settings.py + .env.template | `secret_env` | `secrets.alpha_vantage_api_key` | Secret, credential ID, token, or credential-bearing URL remains env-sourced. |
| `YOUTUBE_MAX_RESULTS` | settings.py + .env.template | `yaml` | `youtube.max_results` | Non-secret runtime behavior belongs in validated YAML. |
| `YOUTUBE_TRANSCRIPT_LANGUAGES` | settings.py + .env.template | `yaml` | `youtube.transcript_languages` | Non-secret runtime behavior belongs in validated YAML. |
| `YOUTUBE_MIN_RELEVANCE_SCORE` | settings.py + .env.template | `yaml` | `youtube.min_relevance_score` | Non-secret runtime behavior belongs in validated YAML. |
| `YOUTUBE_ENABLE_AUTO_CAPTIONS` | settings.py + .env.template | `yaml` | `youtube.enable_auto_captions` | Non-secret runtime behavior belongs in validated YAML. |
| `YOUTUBE_MAX_TRANSCRIPT_LENGTH` | settings.py + .env.template | `yaml` | `youtube.max_transcript_length` | Non-secret runtime behavior belongs in validated YAML. |
| `LLM_PROVIDER` | settings.py + .env.template | `yaml` | `llm.provider` | Non-secret runtime behavior belongs in validated YAML. |
| `LLM_MODEL` | settings.py + .env.template | `yaml` | `llm.model` | Non-secret runtime behavior belongs in validated YAML. |
| `LLM_TEMPERATURE` | settings.py + .env.template | `yaml` | `llm.temperature` | Non-secret runtime behavior belongs in validated YAML. |
| `LLM_TIMEOUT` | settings.py + .env.template | `yaml` | `llm.timeout` | Non-secret runtime behavior belongs in validated YAML. |
| `LLM_TIMEOUT_RESEARCH_PLANNING` | settings.py + .env.template | `yaml` | `llm.research_planning_timeout` | Non-secret runtime behavior belongs in validated YAML. |
| `EMBEDDING_PROVIDER` | settings.py + .env.template | `yaml` | `embedding.provider` | Non-secret runtime behavior belongs in validated YAML. |
| `EMBEDDING_MODEL` | settings.py + .env.template | `yaml` | `embedding.model` | Non-secret runtime behavior belongs in validated YAML. |
| `EMBEDDING_DIMENSION` | settings.py + .env.template | `yaml` | `embedding.dimension` | Non-secret runtime behavior belongs in validated YAML. |
| `GEMINI_EMBEDDING_TASK_TYPE` | settings.py + .env.template | `yaml` | `embedding.gemini_task_type` | Non-secret runtime behavior belongs in validated YAML. |
| `GEMINI_EMBEDDING_IMAGE_TASK_TYPE` | settings.py + .env.template | `yaml` | `embedding.gemini_image_task_type` | Non-secret runtime behavior belongs in validated YAML. |
| `GEMINI_EMBEDDING_VIDEO_TASK_TYPE` | settings.py + .env.template | `yaml` | `embedding.gemini_video_task_type` | Non-secret runtime behavior belongs in validated YAML. |
| `EMBEDDING_DATASET_ENABLED` | settings.py + .env.template | `yaml` | `embedding.dataset.enabled` | Non-secret runtime behavior belongs in validated YAML. |
| `EMBEDDING_DATASET_SAMPLE_RATE` | settings.py + .env.template | `yaml` | `embedding.dataset.sample_rate` | Non-secret runtime behavior belongs in validated YAML. |
| `EMBEDDING_DATASET_DIR` | settings.py | `yaml` | `embedding.dataset.dir` | Non-secret runtime behavior belongs in validated YAML. |
| `VISION_PROVIDER` | settings.py + .env.template | `yaml` | `vision.provider` | Non-secret runtime behavior belongs in validated YAML. |
| `VISION_ENABLED` | settings.py + .env.template | `yaml` | `vision.enabled` | Non-secret runtime behavior belongs in validated YAML. |
| `VISION_MAX_TOKENS` | settings.py + .env.template | `yaml` | `vision.max_tokens` | Non-secret runtime behavior belongs in validated YAML. |
| `VISION_IMAGE_DETAIL` | settings.py + .env.template | `yaml` | `vision.image_detail` | Non-secret runtime behavior belongs in validated YAML. |
| `MAX_ITERATIONS` | settings.py + .env.template | `yaml` | `agent` | Non-secret runtime behavior belongs in validated YAML. |
| `AGENT_TIMEOUT` | settings.py + .env.template | `yaml` | `agent` | Non-secret runtime behavior belongs in validated YAML. |
| `AGENT_TIMEOUTS` | settings.py | `yaml` | `agent.timeouts` | Non-secret runtime behavior belongs in validated YAML. |
| `ITERATIVE_EXPLORER_MAX_DEPTH` | settings.py | `yaml` | `iterative_explorer.max_depth` | Non-secret runtime behavior belongs in validated YAML. |
| `ITERATIVE_EXPLORER_MAX_PAGES` | settings.py | `yaml` | `iterative_explorer.max_pages` | Non-secret runtime behavior belongs in validated YAML. |
| `ITERATIVE_EXPLORER_MAX_ITERATIONS` | settings.py | `yaml` | `iterative_explorer.max_iterations` | Non-secret runtime behavior belongs in validated YAML. |
| `ITERATIVE_EXPLORER_MIN_QUALITY` | settings.py | `yaml` | `iterative_explorer.min_quality` | Non-secret runtime behavior belongs in validated YAML. |
| `ITERATIVE_EXPLORER_CONCURRENT_FETCHES` | settings.py | `yaml` | `iterative_explorer.concurrent_fetches` | Non-secret runtime behavior belongs in validated YAML. |
| `ITERATIVE_EXPLORER_TIMEOUT` | settings.py | `yaml` | `iterative_explorer.timeout` | Non-secret runtime behavior belongs in validated YAML. |
| `ITERATIVE_EXPLORER_TAVILY_TIMEOUT` | settings.py | `yaml` | `iterative_explorer.tavily_timeout` | Non-secret runtime behavior belongs in validated YAML. |
| `ITERATIVE_EXPLORER_CACHE_TTL` | settings.py | `yaml` | `iterative_explorer.cache_ttl` | Non-secret runtime behavior belongs in validated YAML. |
| `ITERATIVE_EXPLORER_COMPLETENESS_CACHE_TTL` | settings.py | `yaml` | `iterative_explorer.completeness_cache_ttl` | Non-secret runtime behavior belongs in validated YAML. |
| `ITERATIVE_EXPLORER_INITIAL_SEARCH_RESULTS` | settings.py | `yaml` | `iterative_explorer.initial_search_results` | Non-secret runtime behavior belongs in validated YAML. |
| `ITERATIVE_EXPLORER_RECENT_RESULTS_WINDOW` | settings.py | `yaml` | `iterative_explorer.recent_results_window` | Non-secret runtime behavior belongs in validated YAML. |
| `ITERATIVE_EXPLORER_PAGE_LIMIT_THRESHOLD` | settings.py | `yaml` | `iterative_explorer.page_limit_threshold` | Non-secret runtime behavior belongs in validated YAML. |
| `LINK_FOLLOWER_MAX_LINKS` | settings.py | `yaml` | `iterative_explorer.link_follower.max_links` | Non-secret runtime behavior belongs in validated YAML. |
| `LINK_FOLLOWER_MIN_RELEVANCE` | settings.py | `yaml` | `iterative_explorer.link_follower.min_relevance` | Non-secret runtime behavior belongs in validated YAML. |
| `QUALITY_EVALUATOR_COMPLETENESS_WEIGHT` | settings.py | `yaml` | `quality_evaluator.completeness_weight` | Non-secret runtime behavior belongs in validated YAML. |
| `QUALITY_EVALUATOR_CREDIBILITY_WEIGHT` | settings.py | `yaml` | `quality_evaluator.credibility_weight` | Non-secret runtime behavior belongs in validated YAML. |
| `QUALITY_EVALUATOR_DIVERSITY_WEIGHT` | settings.py | `yaml` | `quality_evaluator.diversity_weight` | Non-secret runtime behavior belongs in validated YAML. |
| `QUALITY_EVALUATOR_EARLY_TERMINATION_THRESHOLD` | settings.py | `yaml` | `quality_evaluator.early_termination_threshold` | Non-secret runtime behavior belongs in validated YAML. |
| `QUALITY_EVALUATOR_HIGH_CREDIBILITY_THRESHOLD` | settings.py | `yaml` | `quality_evaluator.high_credibility_threshold` | Non-secret runtime behavior belongs in validated YAML. |
| `QUALITY_EVALUATOR_DOMINANCE_THRESHOLD` | settings.py | `yaml` | `quality_evaluator.dominance_threshold` | Non-secret runtime behavior belongs in validated YAML. |
| `SEARCH_ORCHESTRATION_TIMEOUT` | settings.py | `yaml` | `workflow.search_orchestration_timeout` | Non-secret runtime behavior belongs in validated YAML. |
| `WORKFLOW_MIN_QUALITY_SCORE` | settings.py | `yaml` | `workflow.min_quality_score` | Non-secret runtime behavior belongs in validated YAML. |
| `WORKFLOW_MAX_RETRIES` | settings.py | `yaml` | `workflow.max_retries` | Non-secret runtime behavior belongs in validated YAML. |
| `WORKFLOW_MAX_ITERATIONS` | settings.py | `yaml` | `workflow.max_iterations` | Non-secret runtime behavior belongs in validated YAML. |
| `WORKFLOW_TIMEOUT_SECONDS` | settings.py | `yaml` | `workflow.timeout_seconds` | Non-secret runtime behavior belongs in validated YAML. |
| `WORKFLOW_CRITICAL_NODES` | settings.py | `constant` | `-` | Code invariant, prompt body, password policy, or wire-format constant. |
| `WORKFLOW_CACHE_ENABLED` | settings.py | `yaml` | `workflow.cache_enabled` | Non-secret runtime behavior belongs in validated YAML. |
| `WORKFLOW_CACHE_TTL` | settings.py | `yaml` | `workflow.cache_ttl` | Non-secret runtime behavior belongs in validated YAML. |
| `RESEARCH_HARNESS_ENABLED` | settings.py compatibility | `yaml` | `research_harness.enabled` | Non-secret runtime behavior belongs in validated YAML; legacy uppercase access remains for compatibility. |
| `RESEARCH_HARNESS_ALLOW_OFF` | settings.py compatibility | `yaml` | `research_harness.allow_off` | Non-secret runtime behavior belongs in validated YAML; legacy uppercase access remains for compatibility. |
| `RESEARCH_HARNESS_DEFAULT_MODE` | settings.py compatibility | `yaml` | `research_harness.default_mode` | Non-secret runtime behavior belongs in validated YAML; legacy uppercase access remains for compatibility. |
| `RESEARCH_HARNESS_GATE_THRESHOLD` | settings.py compatibility | `yaml` | `research_harness.gate_threshold` | Non-secret runtime behavior belongs in validated YAML; legacy uppercase access remains for compatibility. |
| `RESEARCH_HARNESS_ADVISORY_THRESHOLD` | settings.py compatibility | `yaml` | `research_harness.advisory_threshold` | Non-secret runtime behavior belongs in validated YAML; legacy uppercase access remains for compatibility. |
| `RESEARCH_HARNESS_HIGH_RISK_THRESHOLD` | settings.py compatibility | `yaml` | `research_harness.high_risk_threshold` | Non-secret runtime behavior belongs in validated YAML; legacy uppercase access remains for compatibility. |
| `RESEARCH_HARNESS_MAX_REPAIR_ATTEMPTS` | settings.py compatibility | `yaml` | `research_harness.max_repair_attempts` | Non-secret runtime behavior belongs in validated YAML; legacy uppercase access remains for compatibility. |
| `RESEARCH_HARNESS_HYPER_DEEP_REPAIR_ATTEMPTS` | settings.py compatibility | `yaml` | `research_harness.hyper_deep_repair_attempts` | Non-secret runtime behavior belongs in validated YAML; legacy uppercase access remains for compatibility. |
| `RESEARCH_HARNESS_MODEL_CHECKS_ENABLED` | settings.py compatibility | `yaml` | `research_harness.model_checks.enabled` | Non-secret runtime behavior belongs in validated YAML; legacy uppercase access remains for compatibility. |
| `RESEARCH_HARNESS_MODEL_CHECK_TIMEOUT_SECONDS` | settings.py compatibility | `yaml` | `research_harness.model_checks.timeout_seconds` | Non-secret runtime behavior belongs in validated YAML; legacy uppercase access remains for compatibility. |
| `RESEARCH_HARNESS_MODEL_CHECK_MAX_CLAIMS` | settings.py compatibility | `yaml` | `research_harness.model_checks.max_claims` | Non-secret runtime behavior belongs in validated YAML; legacy uppercase access remains for compatibility. |
| `RESEARCH_HARNESS_MODEL_CHECK_PROVIDER` | settings.py compatibility | `yaml` | `research_harness.model_checks.provider` | Non-secret runtime behavior belongs in validated YAML; legacy uppercase access remains for compatibility. |
| `RESEARCH_HARNESS_MODEL_CHECK_MODEL` | settings.py compatibility | `yaml` | `research_harness.model_checks.model` | Non-secret runtime behavior belongs in validated YAML; legacy uppercase access remains for compatibility. |
| `RESEARCH_HARNESS_STORE_FULL_CHECK_DETAILS` | settings.py compatibility | `yaml` | `research_harness.persistence.store_full_check_details` | Non-secret runtime behavior belongs in validated YAML; legacy uppercase access remains for compatibility. |
| `RESEARCH_HARNESS_PERSIST_RUNS` | settings.py compatibility | `yaml` | `research_harness.persistence.persist_runs` | Non-secret runtime behavior belongs in validated YAML; legacy uppercase access remains for compatibility. |
| `RESEARCH_HARNESS_EVIDENCE_STORAGE_POLICY` | settings.py compatibility | `yaml` | `research_harness.persistence.evidence_storage_policy` | Non-secret runtime behavior belongs in validated YAML; legacy uppercase access remains for compatibility. |
| `RESEARCH_HARNESS_CACHE_POLICY` | settings.py compatibility | `yaml` | `research_harness.persistence.cache_policy` | Non-secret runtime behavior belongs in validated YAML; legacy uppercase access remains for compatibility. |
| `RESEARCH_HARNESS_DIRECT_REPAIR_ENABLED` | settings.py compatibility | `yaml` | `research_harness.direct_repair.enabled` | Non-secret runtime behavior belongs in validated YAML; legacy uppercase access remains for compatibility. |
| `RESEARCH_HARNESS_DIRECT_REPAIR_SEARCH_TIMEOUT_SECONDS` | settings.py compatibility | `yaml` | `research_harness.direct_repair.search_timeout_seconds` | Non-secret runtime behavior belongs in validated YAML; legacy uppercase access remains for compatibility. |
| `RESEARCH_HARNESS_DIRECT_REPAIR_SEARCH_RETRIES` | settings.py compatibility | `yaml` | `research_harness.direct_repair.search_retries` | Non-secret runtime behavior belongs in validated YAML; legacy uppercase access remains for compatibility. |
| `MAX_CONCURRENT_WORKFLOWS` | settings.py + .env.template | `yaml` | `agent` | Non-secret runtime behavior belongs in validated YAML. |
| `MAX_CONCURRENT_AGENTS_PER_WORKFLOW` | settings.py + .env.template | `yaml` | `agent` | Non-secret runtime behavior belongs in validated YAML. |
| `STREAM_EVENT_TIMEOUT` | settings.py + .env.template | `yaml` | `agent` | Non-secret runtime behavior belongs in validated YAML. |
| `STREAM_HEARTBEAT_INTERVAL` | settings.py + .env.template | `yaml` | `agent` | Non-secret runtime behavior belongs in validated YAML. |
| `API_V1_PREFIX` | settings.py + .env.template | `yaml` | `api.v1_prefix` | Non-secret runtime behavior belongs in validated YAML. |
| `DEBUG` | settings.py + .env.template | `yaml` | `api.debug` | Non-secret runtime behavior belongs in validated YAML. |
| `API_GATEWAY_ENABLED` | settings.py + .env.template | `yaml` | `api.gateway.enabled` | Non-secret runtime behavior belongs in validated YAML. |
| `API_GATEWAY_USER_ID_HEADER` | settings.py + .env.template | `yaml` | `api.gateway.user_id_header` | Non-secret runtime behavior belongs in validated YAML. |
| `API_GATEWAY_TRUSTED_IPS` | settings.py + .env.template | `yaml` | `api.gateway.trusted_ips` | Non-secret runtime behavior belongs in validated YAML. |
| `JWT_SECRET_KEY` | settings.py + .env.template | `secret_env` | `auth.jwt_secret_key` | Secret, credential ID, token, or credential-bearing URL remains env-sourced. |
| `JWT_ALGORITHM` | settings.py + .env.template | `constant` | `-` | Code invariant, prompt body, password policy, or wire-format constant. |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | settings.py + .env.template | `yaml` | `auth.access_token_expire_minutes` | Non-secret runtime behavior belongs in validated YAML. |
| `JWT_REFRESH_TOKEN_EXPIRE_DAYS` | settings.py + .env.template | `yaml` | `auth.refresh_token_expire_days` | Non-secret runtime behavior belongs in validated YAML. |
| `GOOGLE_OAUTH_CLIENT_ID` | settings.py + .env.template | `secret_env` | `auth.google_oauth_client_id` | Secret, credential ID, token, or credential-bearing URL remains env-sourced. |
| `PASSWORD_MIN_LENGTH` | settings.py | `constant` | `-` | Code invariant, prompt body, password policy, or wire-format constant. |
| `PASSWORD_MAX_LENGTH` | settings.py | `constant` | `-` | Code invariant, prompt body, password policy, or wire-format constant. |
| `PASSWORD_REQUIRE_UPPERCASE` | settings.py | `constant` | `-` | Code invariant, prompt body, password policy, or wire-format constant. |
| `PASSWORD_REQUIRE_LOWERCASE` | settings.py | `constant` | `-` | Code invariant, prompt body, password policy, or wire-format constant. |
| `PASSWORD_REQUIRE_DIGIT` | settings.py | `constant` | `-` | Code invariant, prompt body, password policy, or wire-format constant. |
| `PASSWORD_REQUIRE_SPECIAL` | settings.py | `constant` | `-` | Code invariant, prompt body, password policy, or wire-format constant. |
| `API_KEY_LENGTH` | settings.py | `constant` | `-` | Code invariant, prompt body, password policy, or wire-format constant. |
| `API_KEY_PREFIX` | settings.py | `constant` | `-` | Code invariant, prompt body, password policy, or wire-format constant. |
| `SESSION_COOKIE_NAME` | settings.py + .env.template | `yaml` | `session.cookie_name` | Non-secret runtime behavior belongs in validated YAML. |
| `SESSION_EXPIRE_SECONDS` | settings.py + .env.template | `yaml` | `session.expire_seconds` | Non-secret runtime behavior belongs in validated YAML. |
| `RATE_LIMIT_LOGIN_ATTEMPTS` | settings.py + .env.template | `yaml` | `rate_limit.login_attempts` | Non-secret runtime behavior belongs in validated YAML. |
| `RATE_LIMIT_LOGIN_WINDOW_SECONDS` | settings.py + .env.template | `yaml` | `rate_limit.login_window_seconds` | Non-secret runtime behavior belongs in validated YAML. |
| `RATE_LIMIT_API_CALLS_PER_MINUTE` | settings.py + .env.template | `yaml` | `rate_limit.api_calls_per_minute` | Non-secret runtime behavior belongs in validated YAML. |
| `CIRCUIT_BREAKER_ENABLED` | settings.py + .env.template | `yaml` | `circuit_breaker.enabled` | Non-secret runtime behavior belongs in validated YAML. |
| `CIRCUIT_BREAKER_FAIL_THRESHOLD` | settings.py + .env.template | `yaml` | `circuit_breaker.fail_threshold` | Non-secret runtime behavior belongs in validated YAML. |
| `CIRCUIT_BREAKER_RECOVERY_TIMEOUT` | settings.py + .env.template | `yaml` | `circuit_breaker.recovery_timeout` | Non-secret runtime behavior belongs in validated YAML. |
| `CIRCUIT_BREAKER_EXPECTED_EXCEPTION` | settings.py | `yaml` | `circuit_breaker.expected_exception` | Non-secret runtime behavior belongs in validated YAML. |
| `CORS_ALLOWED_ORIGINS` | settings.py + .env.template | `yaml` | `api.cors.allowed_origins` | Non-secret runtime behavior belongs in validated YAML. |
| `CORS_ALLOW_CREDENTIALS` | settings.py + .env.template | `yaml` | `api.cors.allow_credentials` | Non-secret runtime behavior belongs in validated YAML. |
| `LOG_LEVEL` | settings.py + .env.template | `yaml` | `observability.log_level` | Non-secret runtime behavior belongs in validated YAML. |
| `OBSERVABILITY_ENABLED` | settings.py + .env.template | `yaml` | `observability.enabled` | Non-secret runtime behavior belongs in validated YAML. |
| `PHOENIX_HOST` | settings.py + .env.template | `yaml` | `observability.phoenix.host` | Non-secret runtime behavior belongs in validated YAML. |
| `PHOENIX_PORT` | settings.py + .env.template | `yaml` | `observability.phoenix.port` | Non-secret runtime behavior belongs in validated YAML. |
| `PHOENIX_COLLECTOR_ENDPOINT` | settings.py | `yaml` | `observability.phoenix.collector_endpoint` | Non-secret runtime behavior belongs in validated YAML. |
| `PHOENIX_PROJECT_NAME` | settings.py + .env.template | `yaml` | `observability.phoenix.project_name` | Non-secret runtime behavior belongs in validated YAML. |
| `METRICS_ENABLED` | settings.py + .env.template | `yaml` | `observability.metrics_enabled` | Non-secret runtime behavior belongs in validated YAML. |
| `TRACE_ENABLED` | settings.py + .env.template | `yaml` | `observability.trace_enabled` | Non-secret runtime behavior belongs in validated YAML. |
| `MAX_TRACES` | settings.py + .env.template | `yaml` | `observability.max_traces` | Non-secret runtime behavior belongs in validated YAML. |
| `TRACE_RETENTION_DAYS` | settings.py + .env.template | `yaml` | `observability.trace_retention_days` | Non-secret runtime behavior belongs in validated YAML. |
| `TRACK_LLM_CALLS` | settings.py + .env.template | `yaml` | `observability.track_llm_calls` | Non-secret runtime behavior belongs in validated YAML. |
| `TRACK_AGENT_PERFORMANCE` | settings.py + .env.template | `yaml` | `observability.track_agent_performance` | Non-secret runtime behavior belongs in validated YAML. |
| `TRACK_WORKFLOW_METRICS` | settings.py + .env.template | `yaml` | `observability.track_workflow_metrics` | Non-secret runtime behavior belongs in validated YAML. |
| `MCP_ENABLED` | settings.py + .env.template | `yaml` | `mcp.enabled` | Non-secret runtime behavior belongs in validated YAML. |
| `MCP_SERVER_HOST` | settings.py + .env.template | `yaml` | `mcp.server_host` | Non-secret runtime behavior belongs in validated YAML. |
| `MCP_SERVER_PORT` | settings.py + .env.template | `yaml` | `mcp.server_port` | Non-secret runtime behavior belongs in validated YAML. |
| `MCP_TIMEOUT` | settings.py + .env.template | `yaml` | `mcp.timeout` | Non-secret runtime behavior belongs in validated YAML. |
| `MCP_RETRY_COUNT` | settings.py + .env.template | `yaml` | `mcp.retry_count` | Non-secret runtime behavior belongs in validated YAML. |
| `MCP_FALLBACK_ENABLED` | settings.py + .env.template | `yaml` | `mcp.fallback_enabled` | Non-secret runtime behavior belongs in validated YAML. |
| `TOOL_SELECTION_STRATEGY` | settings.py + .env.template | `yaml` | `mcp.tool_selection_strategy` | Non-secret runtime behavior belongs in validated YAML. |
| `TOOL_QUALITY_THRESHOLD` | settings.py + .env.template | `yaml` | `mcp.tool_quality_threshold` | Non-secret runtime behavior belongs in validated YAML. |
| `TOOL_PERFORMANCE_PRIORITY` | settings.py + .env.template | `yaml` | `mcp.tool_performance_priority` | Non-secret runtime behavior belongs in validated YAML. |
| `DATASET_AUTO_SAVE` | settings.py + .env.template | `yaml` | `dataset.auto_save` | Non-secret runtime behavior belongs in validated YAML. |
| `DATASET_SAVE_FORMAT` | settings.py + .env.template | `yaml` | `dataset.save_format` | Non-secret runtime behavior belongs in validated YAML. |
| `DATASET_BASE_PATH` | settings.py + .env.template | `yaml` | `dataset.base_path` | Non-secret runtime behavior belongs in validated YAML. |
| `WEB_SEARCH_LOG_ASYNC` | settings.py + .env.template | `yaml` | `web_search_logging.async_enabled` | Non-secret runtime behavior belongs in validated YAML. |
| `WEB_SEARCH_LOG_QUEUE_TYPE` | settings.py + .env.template | `yaml` | `web_search_logging.queue_type` | Non-secret runtime behavior belongs in validated YAML. |
| `STORAGE_PROVIDER` | settings.py + .env.template | `yaml` | `storage` | Non-secret runtime behavior belongs in validated YAML. |
| `S3_BUCKET_NAME` | settings.py + .env.template | `yaml` | `storage.s3.bucket_name` | Non-secret runtime behavior belongs in validated YAML. |
| `S3_ENDPOINT_URL` | settings.py + .env.template | `yaml` | `storage.s3.endpoint_url` | Non-secret runtime behavior belongs in validated YAML. |
| `AWS_REGION` | settings.py + .env.template | `yaml` | `storage.s3.region` | Non-secret runtime behavior belongs in validated YAML. |
| `AWS_ACCESS_KEY_ID` | settings.py + .env.template | `secret_env` | `secrets.aws_access_key_id` | Secret, credential ID, token, or credential-bearing URL remains env-sourced. |
| `AWS_SECRET_ACCESS_KEY` | settings.py + .env.template | `secret_env` | `secrets.aws_secret_access_key` | Secret, credential ID, token, or credential-bearing URL remains env-sourced. |
| `RUSTFS_BUCKET_NAME` | settings.py + .env.template | `yaml` | `storage.rustfs.bucket_name` | Non-secret runtime behavior belongs in validated YAML. |
| `RUSTFS_ENDPOINT_URL` | settings.py + .env.template | `yaml` | `storage.rustfs.endpoint_url` | Non-secret runtime behavior belongs in validated YAML. |
| `RUSTFS_ACCESS_KEY` | settings.py + .env.template | `secret_env` | `secrets.rustfs_access_key` | Secret, credential ID, token, or credential-bearing URL remains env-sourced. |
| `RUSTFS_SECRET_KEY` | settings.py + .env.template | `secret_env` | `secrets.rustfs_secret_key` | Secret, credential ID, token, or credential-bearing URL remains env-sourced. |
| `LOCAL_STORAGE_PATH` | settings.py + .env.template | `yaml` | `storage.local.path` | Non-secret runtime behavior belongs in validated YAML. |
| `MAX_FILE_SIZE` | settings.py + .env.template | `yaml` | `document_processing.max_file_size` | Non-secret runtime behavior belongs in validated YAML. |
| `ALLOWED_FILE_EXTENSIONS` | settings.py | `constant` | `-` | Code invariant, prompt body, password policy, or wire-format constant. |
| `CHUNK_SIZE` | settings.py + .env.template | `yaml` | `document_processing.chunk_size` | Non-secret runtime behavior belongs in validated YAML. |
| `CHUNK_OVERLAP` | settings.py + .env.template | `yaml` | `document_processing.chunk_overlap` | Non-secret runtime behavior belongs in validated YAML. |
| `DEFAULT_CHUNKING_STRATEGY` | settings.py | `yaml` | `document_processing.default_chunking_strategy` | Non-secret runtime behavior belongs in validated YAML. |
| `SEMANTIC_CHUNK_THRESHOLD` | settings.py | `yaml` | `document_processing.semantic_chunk_threshold` | Non-secret runtime behavior belongs in validated YAML. |
| `KG_EXTRACTION_ENABLED` | settings.py + .env.template | `yaml` | `knowledge_graph.extraction.enabled` | Non-secret runtime behavior belongs in validated YAML. |
| `KG_EXTRACTION_MODEL` | settings.py + .env.template | `yaml` | `knowledge_graph.extraction.model` | Non-secret runtime behavior belongs in validated YAML. |
| `KG_MIN_CONFIDENCE` | settings.py + .env.template | `yaml` | `knowledge_graph.min_confidence` | Non-secret runtime behavior belongs in validated YAML. |
| `DEEP_RESEARCH_MAX_POLLING_DURATION` | settings.py + .env.template | `yaml` | `deep_research.max_polling_duration` | Non-secret runtime behavior belongs in validated YAML. |
| `DEEP_RESEARCH_POLL_INTERVAL` | settings.py + .env.template | `yaml` | `deep_research.poll_interval` | Non-secret runtime behavior belongs in validated YAML. |
| `DEEP_RESEARCH_DEFAULT_QUALITY_SCORE` | settings.py + .env.template | `yaml` | `deep_research.default_quality_score` | Non-secret runtime behavior belongs in validated YAML. |
| `DEEP_RESEARCH_CHUNK_SIZE` | settings.py + .env.template | `yaml` | `deep_research.chunk_size` | Non-secret runtime behavior belongs in validated YAML. |
| `DEEP_RESEARCH_MAX_SOURCES_IN_MEMORY` | settings.py + .env.template | `yaml` | `deep_research.max_sources_in_memory` | Non-secret runtime behavior belongs in validated YAML. |
| `DEEP_RESEARCH_MAX_CONCURRENT_REQUESTS` | settings.py + .env.template | `yaml` | `deep_research.max_concurrent_requests` | Non-secret runtime behavior belongs in validated YAML. |
| `DEEP_RESEARCH_MIN_REQUEST_INTERVAL` | settings.py + .env.template | `yaml` | `deep_research.min_request_interval` | Non-secret runtime behavior belongs in validated YAML. |
| `ENVIRONMENT` | settings.py + .env.template | `yaml` | `environment` | Non-secret runtime behavior belongs in validated YAML. |
| `ARTIFACTS_ENABLED` | settings.py + .env.template | `yaml` | `artifacts.enabled` | Non-secret runtime behavior belongs in validated YAML. |
| `ARTIFACT_LLM_MODEL` | settings.py + .env.template | `yaml` | `artifacts.llm.model` | Non-secret runtime behavior belongs in validated YAML. |
| `ARTIFACT_LLM_TEMPERATURE` | settings.py + .env.template | `yaml` | `artifacts.llm.temperature` | Non-secret runtime behavior belongs in validated YAML. |
| `ARTIFACT_LLM_MAX_TOKENS` | settings.py + .env.template | `yaml` | `artifacts.llm.max_tokens` | Non-secret runtime behavior belongs in validated YAML. |
| `ARTIFACTS_SYSTEM_PROMPT` | settings.py | `constant` | `-` | Code invariant, prompt body, password policy, or wire-format constant. |
| `CHAT_DEFAULT_MAX_TOKENS` | settings.py | `yaml` | `chat.default_max_tokens` | Non-secret runtime behavior belongs in validated YAML. |
| `ENABLE_WORKFLOW_IN_CHAT` | settings.py | `yaml` | `chat.enable_workflow` | Non-secret runtime behavior belongs in validated YAML. |
| `ENABLE_RESPONSE_REFINEMENT` | settings.py | `yaml` | `chat.enable_response_refinement` | Non-secret runtime behavior belongs in validated YAML. |
| `CHAT_HISTORY_ENABLED` | settings.py | `yaml` | `chat.history_enabled` | Non-secret runtime behavior belongs in validated YAML. |
| `MAX_HISTORY_MESSAGES` | settings.py | `yaml` | `chat.max_history_messages` | Non-secret runtime behavior belongs in validated YAML. |
| `HISTORY_CONTEXT_MAX_TOKENS` | settings.py | `yaml` | `chat.history_context_max_tokens` | Non-secret runtime behavior belongs in validated YAML. |
| `HISTORY_USAGE_LEVEL` | settings.py | `yaml` | `chat.history_usage_level` | Non-secret runtime behavior belongs in validated YAML. |
| `THINKING_BLOCKS_ENABLED` | settings.py | `yaml` | `chat.thinking_blocks_enabled` | Non-secret runtime behavior belongs in validated YAML. |
| `MAX_THINKING_LENGTH` | settings.py | `yaml` | `chat.max_thinking_length` | Non-secret runtime behavior belongs in validated YAML. |
| `DISABLE_THINKING_FOR_SEARCH` | settings.py | `yaml` | `chat.disable_thinking_for_search` | Non-secret runtime behavior belongs in validated YAML. |
| `USE_TIKTOKEN` | settings.py | `yaml` | `context_optimization.use_tiktoken` | Non-secret runtime behavior belongs in validated YAML. |
| `TOKEN_COUNTER_MODEL` | settings.py | `yaml` | `context_optimization.token_counter_model` | Non-secret runtime behavior belongs in validated YAML. |
| `CONTEXT_OVERFLOW_DETECTION` | settings.py | `yaml` | `context_optimization.overflow_detection` | Non-secret runtime behavior belongs in validated YAML. |
| `CONTEXT_WINDOW_THRESHOLD` | settings.py | `yaml` | `context_optimization.window_threshold` | Non-secret runtime behavior belongs in validated YAML. |
| `MAX_CONTEXT_TOKENS` | settings.py | `yaml` | `context_optimization.max_context_tokens` | Non-secret runtime behavior belongs in validated YAML. |
| `CONTEXT_RESERVE_TOKENS` | settings.py | `yaml` | `context_optimization.reserve_tokens` | Non-secret runtime behavior belongs in validated YAML. |
| `TOOL_RESULT_SUMMARIZATION` | settings.py | `yaml` | `context_optimization.tool_result_summarization` | Non-secret runtime behavior belongs in validated YAML. |
| `TOOL_RESULT_MAX_LENGTH` | settings.py | `yaml` | `context_optimization.tool_result_max_length` | Non-secret runtime behavior belongs in validated YAML. |
| `TOOL_RESULT_SUMMARIZATION_MODEL` | settings.py | `yaml` | `context_optimization.tool_result_summarization_model` | Non-secret runtime behavior belongs in validated YAML. |
| `MESSAGE_COMPRESSION_ENABLED` | settings.py | `yaml` | `context_optimization.message_compression_enabled` | Non-secret runtime behavior belongs in validated YAML. |
| `MESSAGE_COMPRESSION_THRESHOLD` | settings.py | `yaml` | `context_optimization.message_compression_threshold` | Non-secret runtime behavior belongs in validated YAML. |
| `MESSAGE_COMPRESSION_RATIO` | settings.py | `yaml` | `context_optimization.message_compression_ratio` | Non-secret runtime behavior belongs in validated YAML. |
| `MESSAGE_HISTORY_MAX_TOKENS` | settings.py | `yaml` | `context_optimization.message_history_max_tokens` | Non-secret runtime behavior belongs in validated YAML. |
| `SEMANTIC_DEDUPLICATION` | settings.py | `yaml` | `context_optimization.semantic_deduplication` | Non-secret runtime behavior belongs in validated YAML. |
| `SEMANTIC_SIMILARITY_THRESHOLD` | settings.py | `yaml` | `context_optimization.semantic_similarity_threshold` | Non-secret runtime behavior belongs in validated YAML. |
| `WORKFLOW_CONTEXT_BUDGET` | settings.py | `yaml` | `context_optimization.workflow_context_budget` | Non-secret runtime behavior belongs in validated YAML. |
| `DEFAULT_WORKFLOW_TOKEN_BUDGET` | settings.py | `yaml` | `context_optimization.default_workflow_token_budget` | Non-secret runtime behavior belongs in validated YAML. |
| `DEEP_RESEARCH_TOKEN_BUDGET` | settings.py | `yaml` | `deep_research.token_budget` | Non-secret runtime behavior belongs in validated YAML. |
| `CHAT_TOKEN_BUDGET` | settings.py | `yaml` | `chat.token_budget` | Non-secret runtime behavior belongs in validated YAML. |
| `OTEL_ENABLED` | settings.py + .env.template | `yaml` | `telemetry.otel.enabled` | Non-secret runtime behavior belongs in validated YAML. |
| `OTEL_EXPORTER_JAEGER_ENDPOINT` | settings.py + .env.template | `yaml` | `telemetry.otel.exporter_jaeger_endpoint` | Non-secret runtime behavior belongs in validated YAML. |
| `OTEL_SERVICE_NAME` | settings.py | `yaml` | `telemetry.otel.service_name` | Non-secret runtime behavior belongs in validated YAML. |
| `OTEL_SERVICE_VERSION` | settings.py | `yaml` | `telemetry.otel.service_version` | Non-secret runtime behavior belongs in validated YAML. |
| `OTEL_DEPLOYMENT_ENVIRONMENT` | settings.py | `yaml` | `telemetry.otel.deployment_environment` | Non-secret runtime behavior belongs in validated YAML. |
| `OTEL_TRACES_SAMPLER` | settings.py | `yaml` | `telemetry.otel.traces_sampler` | Non-secret runtime behavior belongs in validated YAML. |
| `OTEL_TRACES_SAMPLER_ARG` | settings.py | `yaml` | `telemetry.otel.traces_sampler_arg` | Non-secret runtime behavior belongs in validated YAML. |
| `OTEL_BSP_MAX_QUEUE_SIZE` | settings.py | `yaml` | `telemetry.otel.bsp_max_queue_size` | Non-secret runtime behavior belongs in validated YAML. |
| `OTEL_BSP_SCHEDULE_DELAY` | settings.py | `yaml` | `telemetry.otel.bsp_schedule_delay` | Non-secret runtime behavior belongs in validated YAML. |
| `OTEL_BSP_MAX_EXPORT_BATCH_SIZE` | settings.py | `yaml` | `telemetry.otel.bsp_max_export_batch_size` | Non-secret runtime behavior belongs in validated YAML. |
| `CELERY_ENABLED` | settings.py + .env.template | `yaml` | `celery.enabled` | Non-secret runtime behavior belongs in validated YAML. |
| `CELERY_BROKER_URL` | settings.py + .env.template | `secret_env` | `celery.broker_url` | Secret, credential ID, token, or credential-bearing URL remains env-sourced. |
| `CELERY_RESULT_BACKEND` | settings.py + .env.template | `secret_env` | `celery.result_backend` | Secret, credential ID, token, or credential-bearing URL remains env-sourced. |
| `CELERY_TASK_SERIALIZER` | settings.py | `yaml` | `celery.task_serializer` | Non-secret runtime behavior belongs in validated YAML. |
| `CELERY_RESULT_SERIALIZER` | settings.py | `yaml` | `celery.result_serializer` | Non-secret runtime behavior belongs in validated YAML. |
| `CELERY_ACCEPT_CONTENT` | settings.py | `constant` | `-` | Code invariant, prompt body, password policy, or wire-format constant. |
| `CELERY_TIMEZONE` | settings.py | `yaml` | `celery.timezone` | Non-secret runtime behavior belongs in validated YAML. |
| `CELERY_WORKER_PREFETCH_MULTIPLIER` | settings.py | `yaml` | `celery.worker_prefetch_multiplier` | Non-secret runtime behavior belongs in validated YAML. |
| `CELERY_TASK_ACKS_LATE` | settings.py | `yaml` | `celery.task_acks_late` | Non-secret runtime behavior belongs in validated YAML. |
| `MEMORY_SHORT_TERM_TTL` | settings.py | `yaml` | `memory.short_term_ttl` | Non-secret runtime behavior belongs in validated YAML. |
| `MEMORY_LONG_TERM_ENABLED` | settings.py | `yaml` | `memory.long_term_enabled` | Non-secret runtime behavior belongs in validated YAML. |
| `MEMORY_EPISODIC_ENABLED` | settings.py | `yaml` | `memory.episodic_enabled` | Non-secret runtime behavior belongs in validated YAML. |
| `MEMORY_MAX_CONTEXT_ITEMS` | settings.py | `yaml` | `memory.max_context_items` | Non-secret runtime behavior belongs in validated YAML. |
| `QUERY_CLASSIFIER_USE_LLM` | settings.py | `yaml` | `query_classifier.use_llm` | Non-secret runtime behavior belongs in validated YAML. |
| `QUERY_CLASSIFIER_LLM_MODEL` | settings.py | `yaml` | `query_classifier.llm_model` | Non-secret runtime behavior belongs in validated YAML. |
| `QUERY_CLASSIFIER_LLM_TIMEOUT` | settings.py | `yaml` | `query_classifier.llm_timeout` | Non-secret runtime behavior belongs in validated YAML. |
| `EXECUTIVE_SUMMARY_ENABLED` | settings.py + .env.template | `yaml` | `executive_summary.enabled` | Non-secret runtime behavior belongs in validated YAML. |
| `EXECUTIVE_SUMMARY_MIN_WORDS` | settings.py | `yaml` | `executive_summary.min_words` | Non-secret runtime behavior belongs in validated YAML. |
| `EXECUTIVE_SUMMARY_MAX_SENTENCES` | settings.py | `yaml` | `executive_summary.max_sentences` | Non-secret runtime behavior belongs in validated YAML. |
| `QUERY_EXPANSION_ENABLED` | settings.py | `yaml` | `query_expansion.enabled` | Non-secret runtime behavior belongs in validated YAML. |
| `QUERY_EXPANSION_VARIATIONS` | settings.py | `yaml` | `query_expansion.variations` | Non-secret runtime behavior belongs in validated YAML. |
| `COST_AWARE_ROUTING_ENABLED` | settings.py | `yaml` | `cost_aware_routing.enabled` | Non-secret runtime behavior belongs in validated YAML. |
| `DEFAULT_COST_BUDGET` | settings.py | `yaml` | `cost_aware_routing.default_budget` | Non-secret runtime behavior belongs in validated YAML. |
| `CITATIONS_ENABLED` | settings.py + .env.template | `yaml` | `citations.enabled` | Non-secret runtime behavior belongs in validated YAML. |
| `CITATION_DEFAULT_STYLE` | settings.py + .env.template | `yaml` | `citations.default_style` | Non-secret runtime behavior belongs in validated YAML. |
| `FACT_CHECK_ENABLED` | settings.py + .env.template | `yaml` | `fact_check.enabled` | Non-secret runtime behavior belongs in validated YAML. |
| `FACT_CHECK_COMPLEXITY_THRESHOLD` | settings.py + .env.template | `yaml` | `fact_check.complexity_threshold` | Non-secret runtime behavior belongs in validated YAML. |
| `SEARCH_FALLBACK_ENABLED` | settings.py | `yaml` | `search_fallback.enabled` | Non-secret runtime behavior belongs in validated YAML. |
| `DUCKDUCKGO_MAX_RESULTS` | settings.py | `yaml` | `search_fallback.duckduckgo_max_results` | Non-secret runtime behavior belongs in validated YAML. |
| `SEMANTIC_SCHOLAR_API_KEY` | settings.py + .env.template | `secret_env` | `secrets.semantic_scholar_api_key` | Secret, credential ID, token, or credential-bearing URL remains env-sourced. |
| `NEWS_API_KEY` | settings.py + .env.template | `secret_env` | `secrets.news_api_key` | Secret, credential ID, token, or credential-bearing URL remains env-sourced. |
| `TOOL_SEARCH_ENABLED` | settings.py + .env.template | `yaml` | `tool_search.enabled` | Non-secret runtime behavior belongs in validated YAML. |
| `TOOL_SEARCH_TOP_K` | settings.py + .env.template | `yaml` | `tool_search.top_k` | Non-secret runtime behavior belongs in validated YAML. |
| `TOOL_SEARCH_MAX_ROUNDS` | settings.py + .env.template | `yaml` | `tool_search.max_rounds` | Non-secret runtime behavior belongs in validated YAML. |
| `TOOL_SEARCH_RRF_K` | settings.py + .env.template | `yaml` | `tool_search.rrf_k` | Non-secret runtime behavior belongs in validated YAML. |
| `HYBRID_SEARCH_ALPHA` | settings.py | `yaml` | `hybrid_search.alpha` | Non-secret runtime behavior belongs in validated YAML. |
| `HYBRID_SEARCH_CANDIDATE_COUNT` | settings.py | `yaml` | `hybrid_search.candidate_count` | Non-secret runtime behavior belongs in validated YAML. |
| `RERANKER_ENABLED` | settings.py | `yaml` | `reranker.enabled` | Non-secret runtime behavior belongs in validated YAML. |
| `COHERE_API_KEY` | settings.py | `secret_env` | `secrets.cohere_api_key` | Secret, credential ID, token, or credential-bearing URL remains env-sourced. |
| `RERANKER_TOP_N` | settings.py | `yaml` | `reranker.top_n` | Non-secret runtime behavior belongs in validated YAML. |
| `RERANKER_MODEL` | settings.py | `yaml` | `reranker.model` | Non-secret runtime behavior belongs in validated YAML. |
| `CHECKPOINTER_TYPE` | settings.py + .env.template | `yaml` | `checkpointer.type` | Non-secret runtime behavior belongs in validated YAML. |
| `CHECKPOINTER_BLOB_THRESHOLD` | settings.py + .env.template | `yaml` | `checkpointer.blob_threshold` | Non-secret runtime behavior belongs in validated YAML. |
| `CHECKPOINTER_S3_BACKEND` | settings.py + .env.template | `yaml` | `checkpointer.s3.backend` | Non-secret runtime behavior belongs in validated YAML. |
| `CHECKPOINTER_S3_BUCKET` | settings.py + .env.template | `yaml` | `checkpointer.s3.bucket` | Non-secret runtime behavior belongs in validated YAML. |
| `CHECKPOINTER_S3_REGION` | settings.py + .env.template | `yaml` | `checkpointer.s3.region` | Non-secret runtime behavior belongs in validated YAML. |
| `CHECKPOINTER_S3_ENDPOINT_URL` | settings.py + .env.template | `yaml` | `checkpointer.s3.endpoint_url` | Non-secret runtime behavior belongs in validated YAML. |
| `CHECKPOINTER_S3_ACCESS_KEY` | settings.py + .env.template | `secret_env` | `secrets.checkpointer_s3_access_key` | Secret, credential ID, token, or credential-bearing URL remains env-sourced. |
| `CHECKPOINTER_S3_SECRET_KEY` | settings.py + .env.template | `secret_env` | `secrets.checkpointer_s3_secret_key` | Secret, credential ID, token, or credential-bearing URL remains env-sourced. |
| `RECURSIVE_AGENT_ENABLED` | settings.py + .env.template | `yaml` | `recursive_agent.enabled` | Non-secret runtime behavior belongs in validated YAML. |
| `RECURSIVE_MAX_DEPTH` | settings.py + .env.template | `yaml` | `recursive_agent.max_depth` | Non-secret runtime behavior belongs in validated YAML. |
| `RECURSIVE_MAX_TASKS_PER_LEVEL` | settings.py + .env.template | `yaml` | `recursive_agent.max_tasks_per_level` | Non-secret runtime behavior belongs in validated YAML. |
| `RECURSIVE_COMPLEXITY_THRESHOLD` | settings.py + .env.template | `yaml` | `recursive_agent.complexity_threshold` | Non-secret runtime behavior belongs in validated YAML. |
| `RECURSIVE_ATOMIZER_MODEL` | settings.py + .env.template | `yaml` | `recursive_agent.atomizer_model` | Non-secret runtime behavior belongs in validated YAML. |
| `RECURSIVE_PLANNER_MODEL` | settings.py + .env.template | `yaml` | `recursive_agent.planner_model` | Non-secret runtime behavior belongs in validated YAML. |
| `RECURSIVE_BUDGET_CAP` | settings.py + .env.template | `yaml` | `recursive_agent.budget_cap` | Non-secret runtime behavior belongs in validated YAML. |
| `HYPER_DEEP_AGENT_ENABLED` | settings.py + .env.template | `yaml` | `hyper_deep_agent.enabled` | Non-secret runtime behavior belongs in validated YAML. |
| `HYPER_DEEP_MAX_DEPTH` | settings.py + .env.template | `yaml` | `hyper_deep_agent.max_depth` | Non-secret runtime behavior belongs in validated YAML. |
| `HYPER_DEEP_MAX_TASKS_PER_LEVEL` | settings.py + .env.template | `yaml` | `hyper_deep_agent.max_tasks_per_level` | Non-secret runtime behavior belongs in validated YAML. |
| `HYPER_DEEP_COMPLEXITY_THRESHOLD` | settings.py + .env.template | `yaml` | `hyper_deep_agent.complexity_threshold` | Non-secret runtime behavior belongs in validated YAML. |
| `HYPER_DEEP_BUDGET_CAP` | settings.py + .env.template | `yaml` | `hyper_deep_agent.budget_cap` | Non-secret runtime behavior belongs in validated YAML. |
| `RAY_ENABLED` | settings.py | `yaml` | `ray.enabled` | Non-secret runtime behavior belongs in validated YAML. |
| `RAY_ADDRESS` | settings.py | `yaml` | `ray.address` | Non-secret runtime behavior belongs in validated YAML. |
| `RAY_NUM_CPUS` | settings.py | `yaml` | `ray.num_cpus` | Non-secret runtime behavior belongs in validated YAML. |
| `RAY_OBJECT_STORE_MEMORY` | settings.py | `yaml` | `ray.object_store_memory` | Non-secret runtime behavior belongs in validated YAML. |
| `SANDBOX_ENABLED` | settings.py | `yaml` | `sandbox.enabled` | Non-secret runtime behavior belongs in validated YAML. |
| `SANDBOX_TYPE` | settings.py | `yaml` | `sandbox.type` | Non-secret runtime behavior belongs in validated YAML. |
| `SANDBOX_TIMEOUT_SEC` | settings.py | `yaml` | `sandbox.timeout_sec` | Non-secret runtime behavior belongs in validated YAML. |
| `CONTEXTUAL_RETRIEVAL_ENABLED` | settings.py + .env.template | `yaml` | `contextual_retrieval.enabled` | Non-secret runtime behavior belongs in validated YAML. |
| `CONTEXTUAL_MODEL` | settings.py + .env.template | `yaml` | `contextual_retrieval.model` | Non-secret runtime behavior belongs in validated YAML. |
| `CONTEXTUAL_MAX_TOKENS` | settings.py + .env.template | `yaml` | `contextual_retrieval.max_tokens` | Non-secret runtime behavior belongs in validated YAML. |
| `CONTEXTUAL_MAX_CONCURRENT` | settings.py + .env.template | `yaml` | `contextual_retrieval.max_concurrent` | Non-secret runtime behavior belongs in validated YAML. |
| `CONTEXTUAL_MAX_CHUNKS_PER_DOC` | settings.py + .env.template | `yaml` | `contextual_retrieval.max_chunks_per_doc` | Non-secret runtime behavior belongs in validated YAML. |
| `CONTEXTUAL_BUDGET_CAP_USD` | settings.py + .env.template | `yaml` | `contextual_retrieval.budget_cap_usd` | Non-secret runtime behavior belongs in validated YAML. |
| `CONTEXTUAL_EMBED_SOURCE` | settings.py + .env.template | `yaml` | `contextual_retrieval.embed_source` | Non-secret runtime behavior belongs in validated YAML. |
| `EXECUTION_APPROVAL_ENABLED` | settings.py + .env.template | `yaml` | `execution_approval.enabled` | Non-secret runtime behavior belongs in validated YAML. |
| `APPROVAL_REQUIRED_SKILLS` | settings.py | `yaml` | `execution_approval.required_skills` | Non-secret runtime behavior belongs in validated YAML. |
| `APPROVAL_TIMEOUT_SECONDS` | settings.py + .env.template | `yaml` | `execution_approval.timeout_seconds` | Non-secret runtime behavior belongs in validated YAML. |
| `DEFAULT_AUTONOMY_LEVEL` | settings.py | `yaml` | `execution_approval.default_autonomy_level` | Non-secret runtime behavior belongs in validated YAML. |
| `CHANNEL_TELEGRAM_ENABLED` | settings.py + .env.template | `yaml` | `channels.telegram.enabled` | Non-secret runtime behavior belongs in validated YAML. |
| `CHANNEL_TELEGRAM_BOT_TOKEN` | settings.py + .env.template | `secret_env` | `secrets.channel_telegram_bot_token` | Secret, credential ID, token, or credential-bearing URL remains env-sourced. |
| `CHANNEL_DISCORD_ENABLED` | settings.py + .env.template | `yaml` | `channels.discord.enabled` | Non-secret runtime behavior belongs in validated YAML. |
| `CHANNEL_DISCORD_BOT_TOKEN` | settings.py + .env.template | `secret_env` | `secrets.channel_discord_bot_token` | Secret, credential ID, token, or credential-bearing URL remains env-sourced. |
| `CHANNEL_SLACK_ENABLED` | settings.py + .env.template | `yaml` | `channels.slack.enabled` | Non-secret runtime behavior belongs in validated YAML. |
| `CHANNEL_SLACK_BOT_TOKEN` | settings.py + .env.template | `secret_env` | `secrets.channel_slack_bot_token` | Secret, credential ID, token, or credential-bearing URL remains env-sourced. |
| `CHANNEL_SLACK_APP_TOKEN` | settings.py + .env.template | `secret_env` | `secrets.channel_slack_app_token` | Secret, credential ID, token, or credential-bearing URL remains env-sourced. |
| `CHANNEL_BOT_USER_ID` | settings.py + .env.template | `yaml` | `channels.bot_user_id` | Non-secret runtime behavior belongs in validated YAML. |
| `CHANNEL_REQUIRE_MENTION` | settings.py | `yaml` | `channels.require_mention` | Non-secret runtime behavior belongs in validated YAML. Default true. |
| `CHANNEL_ALLOWED_USERS` | settings.py | `yaml` | `channels.allowed_users` | Non-secret runtime behavior belongs in validated YAML. Empty = fail-closed. |
| `CHANNEL_ALLOWED_CHANNELS` | settings.py | `yaml` | `channels.allowed_channels` | Non-secret runtime behavior belongs in validated YAML. Empty = any room. |
| `CHANNEL_IGNORED_CHANNELS` | settings.py | `yaml` | `channels.ignored_channels` | Non-secret runtime behavior belongs in validated YAML. |
| `CHANNEL_CODING_INVOKE` | settings.py | `yaml` | `channels.coding_invoke` | Non-secret runtime behavior belongs in validated YAML. Default false. |
| `CHANNEL_CODING_OWNER_USER_ID` | settings.py | `yaml` | `channels.coding_owner_user_id` | Non-secret runtime behavior belongs in validated YAML. Empty refuses /code. |
| `CONTEXT_MAX_TOKENS` | settings.py + .env.template | `yaml` | `context_assembly.max_tokens` | Non-secret runtime behavior belongs in validated YAML. |
| `CONTEXT_SHORT_TERM_RATIO` | settings.py + .env.template | `yaml` | `context_assembly.short_term_ratio` | Non-secret runtime behavior belongs in validated YAML. |
| `CONTEXT_LONG_TERM_RATIO` | settings.py + .env.template | `yaml` | `context_assembly.long_term_ratio` | Non-secret runtime behavior belongs in validated YAML. |
| `CONTEXT_EPISODIC_RATIO` | settings.py + .env.template | `yaml` | `context_assembly.episodic_ratio` | Non-secret runtime behavior belongs in validated YAML. |
| `CRON_ENABLED` | settings.py + .env.template | `yaml` | `cron.enabled` | Non-secret runtime behavior belongs in validated YAML. |
| `CRON_DEFAULT_TIMEZONE` | settings.py + .env.template | `yaml` | `cron.default_timezone` | Non-secret runtime behavior belongs in validated YAML. |
| `CRON_MAX_TASKS_PER_USER` | settings.py + .env.template | `yaml` | `cron.max_tasks_per_user` | Non-secret runtime behavior belongs in validated YAML. |
| `CRON_LLM_FALLBACK_ENABLED` | settings.py + .env.template | `yaml` | `cron.llm_fallback_enabled` | Non-secret runtime behavior belongs in validated YAML. |
| `CRON_LLM_MODEL` | settings.py + .env.template | `yaml` | `cron.llm_model` | Non-secret runtime behavior belongs in validated YAML. |
| `OLLAMA_BASE_URL` | settings.py + .env.template | `yaml` | `model_providers.ollama.base_url` | Non-secret runtime behavior belongs in validated YAML. |
| `OLLAMA_DEFAULT_MODEL` | settings.py + .env.template | `yaml` | `model_providers.ollama.default_model` | Non-secret runtime behavior belongs in validated YAML. |
| `A2UI_ENABLED` | settings.py + .env.template | `yaml` | `a2ui.enabled` | Non-secret runtime behavior belongs in validated YAML. |
| `A2UI_LLM_MODEL` | settings.py + .env.template | `yaml` | `a2ui.llm_model` | Non-secret runtime behavior belongs in validated YAML. |
| `A2UI_LLM_PROVIDER` | settings.py + .env.template | `yaml` | `a2ui.llm_provider` | Non-secret runtime behavior belongs in validated YAML. |
| `A2UI_MAX_COMPONENTS` | settings.py + .env.template | `yaml` | `a2ui.max_components` | Non-secret runtime behavior belongs in validated YAML. |
| `A2UI_FRAME_TIMEOUT` | settings.py + .env.template | `yaml` | `a2ui.frame_timeout` | Non-secret runtime behavior belongs in validated YAML. |
| `INLINE_VIS_ENABLED` | settings.py + .env.template | `yaml` | `inline_visualization.enabled` | Non-secret runtime behavior belongs in validated YAML. |
| `INLINE_VIS_SYSTEM_PROMPT` | settings.py | `constant` | `-` | Code invariant, prompt body, password policy, or wire-format constant. |
| `GRAFANA_PASSWORD` | .env.template | `secret_env` | `compose.grafana_password` | Secret, credential ID, token, or credential-bearing URL remains env-sourced. |
| `TOOL_SEARCH_ALPHA` | .env.template | `removed` | `-` | Stale template-only key; do not migrate into schema. |
| `TOOL_SEARCH_CACHE_TTL` | .env.template | `removed` | `-` | Stale template-only key; do not migrate into schema. |
| `CI` | target allowlist | `control_env` | `bootstrap controls` | Bootstrap/profile/infrastructure control used before YAML loading. |
| `CONFIG_PATH` | target allowlist | `control_env` | `bootstrap controls` | Bootstrap/profile/infrastructure control used before YAML loading. |
| `NEOS_CONFIG_PATH` | target allowlist | `control_env` | `bootstrap controls` | Bootstrap/profile/infrastructure control used before YAML loading. |
| `NEOS_ENV` | target allowlist | `control_env` | `bootstrap controls` | Bootstrap/profile/infrastructure control used before YAML loading. |
| `NEOS_MODEL_CONFIG_PATH` | target allowlist | `control_env` | `bootstrap controls` | Bootstrap/profile/infrastructure control used before YAML loading. |
| `NEOS_SECRETS_PATH` | target allowlist | `control_env` | `bootstrap controls` | Bootstrap/profile/infrastructure control used before YAML loading. |
| `NODE_ENV` | target allowlist | `control_env` | `bootstrap controls` | Bootstrap/profile/infrastructure control used before YAML loading. |
| `PORT` | target allowlist | `control_env` | `bootstrap controls` | Bootstrap/profile/infrastructure control used before YAML loading. |
