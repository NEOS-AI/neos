import pytest

from neos.config.schema import AppConfig
from neos.config.settings import Settings


pytestmark = pytest.mark.no_db


def _settings() -> Settings:
    return Settings(config=AppConfig())


def test_deep_analysis_budget_defaults():
    settings = _settings()

    assert settings.DEEP_ANALYSIS_GLOBAL_TOKEN_CAP == 300000
    assert settings.DEEP_ANALYSIS_MAX_DEPTH == 4
    assert settings.DEEP_ANALYSIS_PARALLEL_WORKERS == 4
    assert settings.DEEP_ANALYSIS_SCORE_FLOOR == 0.05
    assert settings.DEEP_ANALYSIS_VALUE_DECAY == 0.8


def test_deep_analysis_grading_defaults():
    settings = _settings()

    assert settings.DEEP_ANALYSIS_QUOTE_MATCH_THRESHOLD == 0.92
    assert settings.DEEP_ANALYSIS_CLAIM_RETRY_CAP == 2
    assert settings.DEEP_ANALYSIS_RESOLVE_THRESHOLD == 0.7


def test_deep_analysis_nested_effort_and_tiers():
    cfg = _settings().config.deep_analysis

    assert cfg.effort["scout"].token_cap == 2000
    assert cfg.effort["dig"].token_cap == 12000
    assert cfg.confidence_cap == {1: 0.6, 2: 0.8, 3: 0.95}
    assert "arxiv.org" in cfg.source_tiers["tier1"]


def test_deep_analysis_dev_profile_present():
    dev = _settings().config.deep_analysis.dev_profile

    assert dev.global_token_cap == 20000
    assert dev.parallel_workers == 2
    assert dev.max_depth == 2


def test_deep_analysis_operational_limits_are_configured():
    cfg = _settings().config.deep_analysis

    assert cfg.search_result_limit == 3
    assert cfg.fetch_timeout_seconds == 15.0
    assert cfg.evidence_context_chars == 2000
    assert cfg.excerpt_max_chars == 500
    assert cfg.decompose_max_tokens == 1500
    assert cfg.worker_max_output_tokens == 4000
    assert cfg.synthesis_max_tokens == 4000
    assert cfg.sse_keepalive_seconds == 0.5


def test_deep_analysis_job_service_defaults():
    """Phase 3a(D22): durable job 서비스 설정.

    job_time_limit은 반드시 job_soft_time_limit보다 커야 한다 -- soft가 먼저
    올라야 예외를 잡아 job_failed를 남길 수 있고, hard는 그 뒤의 마지막 수단이다.
    """
    cfg = _settings().config.deep_analysis

    assert cfg.job_queue == "analysis"
    assert cfg.job_soft_time_limit == 3600
    assert cfg.job_time_limit == 3900
    assert cfg.job_time_limit > cfg.job_soft_time_limit
    assert cfg.job_max_retries == 2
    assert cfg.events_poll_interval == 1.0
    assert cfg.events_stream_idle_timeout == 300.0


def test_deep_analysis_job_settings_reachable_via_legacy_uppercase():
    settings = _settings()

    assert settings.DEEP_ANALYSIS_JOB_QUEUE == "analysis"
    assert settings.DEEP_ANALYSIS_EVENTS_POLL_INTERVAL == 1.0
