from __future__ import annotations

import os
import warnings
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml
from dotenv import dotenv_values

from neos.config.schema import AppConfig

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_DIR = REPO_ROOT / "config"
DEFAULT_DOTENV_PATH = REPO_ROOT / ".env"

CONTROL_ENV_KEYS = {
    "NEOS_ENV",
    "NEOS_CONFIG_PATH",
    "NEOS_SECRETS_PATH",
    "NEOS_MODEL_CONFIG_PATH",
    "CONFIG_PATH",
    "PORT",
    "NODE_ENV",
    "CI",
}

WEB_ENV_KEYS = {
    "AUTH_SECRET",
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "AI_GATEWAY_API_KEY",
    "BACKEND_URL",
    "PLAYWRIGHT_BASE_URL",
}

GATEWAY_ENV_KEYS = {
    "GATEWAY_PORT",
    "UPSTREAM_HOST",
    "UPSTREAM_PORT",
    "DB_HOST",
    "DB_PORT",
    "DB_NAME",
    "DB_USER",
    "DB_PASSWORD",
    "LOG_LEVEL",
}

SECRET_ENV_KEYS = {
    "DATABASE_URL",
    "REDIS_URL",
    "CELERY_BROKER_URL",
    "CELERY_RESULT_BACKEND",
    "JWT_SECRET_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_WORKSPACE_ID",
    "GOOGLE_API_KEY",
    "TAVILY_API_KEY",
    "YOUTUBE_API_KEY",
    "GITHUB_API_TOKEN",
    "REDDIT_CLIENT_ID",
    "REDDIT_CLIENT_SECRET",
    "SERPAPI_API_KEY",
    "SEMANTIC_SCHOLAR_API_KEY",
    "NEWS_API_KEY",
    "OPENWEATHER_API_KEY",
    "EXCHANGERATE_API_KEY",
    "FINANCIALDATASETS_API_KEY",
    "ALPHA_VANTAGE_API_KEY",
    "COHERE_API_KEY",
    "TYPESAFE_API_KEY",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "RUSTFS_ACCESS_KEY",
    "RUSTFS_SECRET_KEY",
    "CHECKPOINTER_S3_ACCESS_KEY",
    "CHECKPOINTER_S3_SECRET_KEY",
    "CHANNEL_TELEGRAM_BOT_TOKEN",
    "CHANNEL_DISCORD_BOT_TOKEN",
    "CHANNEL_SLACK_BOT_TOKEN",
    "CHANNEL_SLACK_APP_TOKEN",
    "MANAGED_PROVIDER_REFERENCE_KEY",
    "MANAGED_CODING_OWNERSHIP_KEY",
    "GOOGLE_OAUTH_CLIENT_ID",
    "GOOGLE_OAUTH_CLIENT_SECRET",
    "AUTH_SECRET",
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "AI_GATEWAY_API_KEY",
    "POSTGRES_PASSWORD",
    "GRAFANA_PASSWORD",
}

SECRET_ENV_MAPPING = {
    "DATABASE_URL": "database.url",
    "REDIS_URL": "redis.url",
    "CELERY_BROKER_URL": "celery.broker_url",
    "CELERY_RESULT_BACKEND": "celery.result_backend",
    "JWT_SECRET_KEY": "auth.jwt_secret_key",
    "OPENAI_API_KEY": "secrets.openai_api_key",
    "ANTHROPIC_API_KEY": "secrets.anthropic_api_key",
    "ANTHROPIC_WORKSPACE_ID": "secrets.anthropic_workspace_id",
    "GOOGLE_API_KEY": "secrets.google_api_key",
    "TAVILY_API_KEY": "secrets.tavily_api_key",
    "YOUTUBE_API_KEY": "secrets.youtube_api_key",
    "GITHUB_API_TOKEN": "secrets.github_api_token",
    "REDDIT_CLIENT_ID": "secrets.reddit_client_id",
    "REDDIT_CLIENT_SECRET": "secrets.reddit_client_secret",
    "SERPAPI_API_KEY": "secrets.serpapi_api_key",
    "SEMANTIC_SCHOLAR_API_KEY": "secrets.semantic_scholar_api_key",
    "NEWS_API_KEY": "secrets.news_api_key",
    "OPENWEATHER_API_KEY": "secrets.openweather_api_key",
    "EXCHANGERATE_API_KEY": "secrets.exchangerate_api_key",
    "FINANCIALDATASETS_API_KEY": "secrets.financialdatasets_api_key",
    "ALPHA_VANTAGE_API_KEY": "secrets.alpha_vantage_api_key",
    "COHERE_API_KEY": "secrets.cohere_api_key",
    "AWS_ACCESS_KEY_ID": "secrets.aws_access_key_id",
    "AWS_SECRET_ACCESS_KEY": "secrets.aws_secret_access_key",
    "RUSTFS_ACCESS_KEY": "secrets.rustfs_access_key",
    "RUSTFS_SECRET_KEY": "secrets.rustfs_secret_key",
    "CHECKPOINTER_S3_ACCESS_KEY": "secrets.checkpointer_s3_access_key",
    "CHECKPOINTER_S3_SECRET_KEY": "secrets.checkpointer_s3_secret_key",
    "CHANNEL_TELEGRAM_BOT_TOKEN": "secrets.channel_telegram_bot_token",
    "CHANNEL_DISCORD_BOT_TOKEN": "secrets.channel_discord_bot_token",
    "CHANNEL_SLACK_BOT_TOKEN": "secrets.channel_slack_bot_token",
    "CHANNEL_SLACK_APP_TOKEN": "secrets.channel_slack_app_token",
    "MANAGED_PROVIDER_REFERENCE_KEY": "secrets.managed_provider_reference_key",
    "MANAGED_CODING_OWNERSHIP_KEY": "secrets.managed_coding_ownership_key",
    "GOOGLE_OAUTH_CLIENT_ID": "auth.google_oauth_client_id",
    "GOOGLE_OAUTH_CLIENT_SECRET": "auth.google_oauth_client_secret",
}

YAML_ONLY_FEATURE_FLAG_ENV_KEYS = {
    "DEEP_ANALYSIS_ENABLED": "deep_analysis.enabled",
    "RECURSIVE_AGENT_ENABLED": "recursive_agent.enabled",
    "HYPER_DEEP_AGENT_ENABLED": "hyper_deep_agent.enabled",
    "A2UI_ENABLED": "a2ui.enabled",
    "RAY_ENABLED": "ray.enabled",
    "EXECUTION_APPROVAL_ENABLED": "execution_approval.enabled",
    "CELERY_ENABLED": "celery.enabled",
}

LEGACY_ENV_KEYS = {
    "LLM_PROVIDER": "llm.provider",
    "LLM_MODEL": "llm.model",
    "LLM_TEMPERATURE": "llm.temperature",
    "LLM_TIMEOUT": "llm.timeout",
    "LLM_TIMEOUT_RESEARCH_PLANNING": "llm.research_planning_timeout",
    "FAST_LLM_MODEL": "llm.fast_model",
    "RESEARCH_HARNESS_ENABLED": "research_harness.enabled",
    "RESEARCH_HARNESS_ALLOW_OFF": "research_harness.allow_off",
    "RESEARCH_HARNESS_DEFAULT_MODE": "research_harness.default_mode",
    "RESEARCH_HARNESS_GATE_THRESHOLD": "research_harness.gate_threshold",
    "RESEARCH_HARNESS_ADVISORY_THRESHOLD": "research_harness.advisory_threshold",
    "RESEARCH_HARNESS_HIGH_RISK_THRESHOLD": "research_harness.high_risk_threshold",
    "RESEARCH_HARNESS_MAX_REPAIR_ATTEMPTS": "research_harness.max_repair_attempts",
    "RESEARCH_HARNESS_HYPER_DEEP_REPAIR_ATTEMPTS": "research_harness.hyper_deep_repair_attempts",
    "RESEARCH_HARNESS_MODEL_CHECKS_ENABLED": "research_harness.model_checks.enabled",
    "RESEARCH_HARNESS_MODEL_CHECK_TIMEOUT_SECONDS": "research_harness.model_checks.timeout_seconds",
    "RESEARCH_HARNESS_MODEL_CHECK_MAX_CLAIMS": "research_harness.model_checks.max_claims",
    "RESEARCH_HARNESS_MODEL_CHECK_PROVIDER": "research_harness.model_checks.provider",
    "RESEARCH_HARNESS_MODEL_CHECK_MODEL": "research_harness.model_checks.model",
    "RESEARCH_HARNESS_STORE_FULL_CHECK_DETAILS": "research_harness.persistence.store_full_check_details",
    "RESEARCH_HARNESS_PERSIST_RUNS": "research_harness.persistence.persist_runs",
    "RESEARCH_HARNESS_EVIDENCE_STORAGE_POLICY": "research_harness.persistence.evidence_storage_policy",
    "RESEARCH_HARNESS_CACHE_POLICY": "research_harness.persistence.cache_policy",
    "RESEARCH_HARNESS_DIRECT_REPAIR_ENABLED": "research_harness.direct_repair.enabled",
    "RESEARCH_HARNESS_DIRECT_REPAIR_SEARCH_TIMEOUT_SECONDS": "research_harness.direct_repair.search_timeout_seconds",
    "RESEARCH_HARNESS_DIRECT_REPAIR_SEARCH_RETRIES": "research_harness.direct_repair.search_retries",
    "CORS_ALLOWED_ORIGINS": "api.cors.allowed_origins",
    "CORS_ALLOW_CREDENTIALS": "api.cors.allow_credentials",
    "API_V1_PREFIX": "api.v1_prefix",
    "DEBUG": "api.debug",
    "API_GATEWAY_ENABLED": "api.gateway.enabled",
    "API_GATEWAY_USER_ID_HEADER": "api.gateway.user_id_header",
    "API_GATEWAY_TRUSTED_IPS": "api.gateway.trusted_ips",
    "LOG_LEVEL": "observability.log_level",
    "OBSERVABILITY_ENABLED": "observability.enabled",
    "METRICS_ENABLED": "observability.metrics_enabled",
    "TRACE_ENABLED": "observability.trace_enabled",
    "STORAGE_PROVIDER": "storage.provider",
    "RUSTFS_ENDPOINT_URL": "storage.rustfs.endpoint_url",
    "RUSTFS_BUCKET_NAME": "storage.rustfs.bucket_name",
    "S3_ENDPOINT_URL": "storage.s3.endpoint_url",
    "S3_BUCKET_NAME": "storage.s3.bucket_name",
    "AWS_REGION": "storage.s3.region",
    "LOCAL_STORAGE_PATH": "storage.local.path",
    "SEC_EDGAR_USER_AGENT": "sources.sec_edgar_user_agent",
    "REDDIT_USER_AGENT": "sources.reddit_user_agent",
    "OPENALEX_EMAIL": "sources.openalex_email",
    "STOCK_API_PROVIDER": "sources.stock_api_provider",
    "TOOL_SEARCH_ENABLED": "tool_search.enabled",
    "TOOL_SEARCH_TOP_K": "tool_search.top_k",
    "TOOL_SEARCH_MAX_ROUNDS": "tool_search.max_rounds",
    "TOOL_SEARCH_RRF_K": "tool_search.rrf_k",
}


@dataclass(frozen=True)
class BootstrapControls:
    env: str
    config_path: Path | None
    secrets_path: Path | None
    model_config_path: Path | None


def _path_or_none(value: str | None) -> Path | None:
    if not value:
        return None
    return Path(value)


def _set_nested(config_data: dict[str, Any], dotted_path: str, value: Any) -> None:
    cursor = config_data
    parts = dotted_path.split(".")
    for part in parts[:-1]:
        child = cursor.get(part)
        if not isinstance(child, dict):
            child = {}
            cursor[part] = child
        cursor = child
    cursor[parts[-1]] = value


def load_yaml_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML in {path}") from exc
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ValueError(f"YAML config {path} must contain a mapping at the top level")
    return loaded


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def load_dotenv_file(secrets_path: Path | None) -> dict[str, str]:
    if secrets_path is None or not secrets_path.exists():
        return {}
    values = dotenv_values(secrets_path)
    return {key: value for key, value in values.items() if key and value is not None}


def resolve_secrets_path(
    bootstrap_env: Mapping[str, str],
    process_env: Mapping[str, str],
    explicit_path: str | None = None,
) -> Path | None:
    return (
        _path_or_none(explicit_path)
        or _path_or_none(process_env.get("NEOS_SECRETS_PATH"))
        or _path_or_none(bootstrap_env.get("NEOS_SECRETS_PATH"))
    )


def resolve_bootstrap_controls(
    dotenv_env: Mapping[str, str],
    process_env: Mapping[str, str],
) -> BootstrapControls:
    merged = {**dotenv_env, **process_env}
    return BootstrapControls(
        env=merged.get("NEOS_ENV", "development"),
        config_path=_path_or_none(merged.get("NEOS_CONFIG_PATH")),
        secrets_path=_path_or_none(merged.get("NEOS_SECRETS_PATH")),
        model_config_path=_path_or_none(merged.get("NEOS_MODEL_CONFIG_PATH")),
    )


def apply_secret_overrides(config_data: dict[str, Any], env: Mapping[str, str]) -> dict[str, Any]:
    updated = deepcopy(config_data)
    for env_key, dotted_path in SECRET_ENV_MAPPING.items():
        if env_key in env:
            _set_nested(updated, dotted_path, env[env_key])
    return updated


def apply_legacy_env_overrides(
    config_data: dict[str, Any],
    env: Mapping[str, str],
    app_env: str,
) -> dict[str, Any]:
    updated = deepcopy(config_data)
    for env_key, dotted_path in LEGACY_ENV_KEYS.items():
        if env_key not in env:
            continue
        warnings.warn(
            f"{env_key} is a legacy non-secret env override for {dotted_path}; move it to YAML.",
            UserWarning,
            stacklevel=2,
        )
        _set_nested(updated, dotted_path, env[env_key])
    return updated


def warn_yaml_only_feature_flag_env(env: Mapping[str, str]) -> None:
    for env_key, dotted_path in YAML_ONLY_FEATURE_FLAG_ENV_KEYS.items():
        if env_key not in env:
            continue
        warnings.warn(
            f"{env_key} is ignored; configure {dotted_path} in YAML.",
            UserWarning,
            stacklevel=2,
        )


def warn_finalization_floor_ratio(deep_analysis) -> None:
    """Warn when the finalization reserve crowds out investigation.

    Not expected to fire on the shipped defaults -- it is a backstop for a
    profile tuned into a corner, where the reserve would leave too little
    budget to investigate anything worth reporting on.
    """

    # The formula itself lives once, on DeepAnalysisConfig.finalization_floor_tokens
    # -- shared with service.py's build_orchestrator, which computes the floor
    # actually enforced by TokenBudget. Two independent copies of this
    # expression agree today but would silently diverge on the next tuning
    # pass; one shared method cannot.
    warn_ratio = deep_analysis.finalization_floor_warn_ratio
    profiles = (
        ("default", deep_analysis.global_token_cap,
         deep_analysis.finalization_floor_tokens(deep_analysis.synthesis_max_tokens)),
        ("dev", deep_analysis.dev_profile.global_token_cap,
         deep_analysis.finalization_floor_tokens(
             deep_analysis.dev_profile.synthesis_max_tokens
         )),
    )
    for name, cap, floor in profiles:
        if cap > 0 and floor >= cap * warn_ratio:
            warnings.warn(
                f"deep_analysis {name} profile: finalization floor {floor} is "
                f"{floor / cap:.0%} of global_token_cap {cap}; raise the cap or "
                f"lower finalization_reduction_allowance / synthesis_max_tokens.",
                UserWarning,
                stacklevel=2,
            )


def validate_env_allowlist(env: Mapping[str, str], app_env: str) -> list[str]:
    allowed = SECRET_ENV_KEYS | CONTROL_ENV_KEYS | WEB_ENV_KEYS | GATEWAY_ENV_KEYS | set(LEGACY_ENV_KEYS)
    unknown: list[str] = []
    for key in env:
        if key in allowed:
            continue
        if key.startswith("NEOS_"):
            unknown.append(key)
    return unknown


def redact_config(config: AppConfig) -> dict[str, Any]:
    data = config.model_dump(mode="json")
    secret_fragments = ("api_key", "secret", "token", "password", "access_key", "url")

    def redact(value: Any, key: str = "") -> Any:
        if isinstance(value, dict):
            return {child_key: redact(child_value, child_key) for child_key, child_value in value.items()}
        if key and any(fragment in key.lower() for fragment in secret_fragments) and value:
            return "<redacted>"
        return value

    return redact(data)


def load_app_config(
    env: str | None = None,
    config_path: str | None = None,
    secrets_path: str | None = None,
) -> AppConfig:
    bootstrap_env = load_dotenv_file(DEFAULT_DOTENV_PATH)
    process_env = dict(os.environ)
    controls = resolve_bootstrap_controls(bootstrap_env, process_env)

    app_env = env or controls.env
    selected_config_path = _path_or_none(config_path) or controls.config_path
    selected_secrets_path = resolve_secrets_path(bootstrap_env, process_env, explicit_path=secrets_path)

    config_data: dict[str, Any] = {}
    config_data = deep_merge(config_data, load_yaml_file(DEFAULT_CONFIG_DIR / "neos.default.yaml"))
    config_data = deep_merge(config_data, load_yaml_file(DEFAULT_CONFIG_DIR / f"neos.{app_env}.yaml"))
    if selected_config_path is not None:
        config_data = deep_merge(config_data, load_yaml_file(selected_config_path))

    runtime_env = {**bootstrap_env, **process_env}
    warn_yaml_only_feature_flag_env(runtime_env)
    config_data = apply_legacy_env_overrides(config_data, runtime_env, app_env)

    if selected_secrets_path is not None:
        secret_dotenv = load_dotenv_file(selected_secrets_path)
    else:
        secret_dotenv = bootstrap_env
    config_data = apply_secret_overrides(config_data, secret_dotenv)
    config_data = apply_secret_overrides(config_data, process_env)

    app_config = AppConfig.model_validate(config_data)
    warn_finalization_floor_ratio(app_config.deep_analysis)
    return app_config
