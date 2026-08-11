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

    assert dev.global_token_cap == 140000
    assert dev.parallel_workers == 2
    assert dev.max_depth == 2
    assert dev.synthesis_max_tokens == 2000


def test_deep_analysis_operational_limits_are_configured():
    cfg = _settings().config.deep_analysis

    assert cfg.search_result_limit == 3
    assert cfg.fetch_timeout_seconds == 15.0
    assert cfg.evidence_context_chars == 2000
    assert cfg.excerpt_max_chars == 500
    # Calibrated from the 20260728T104241Z cassette: three decompose
    # responses hit the old 1500-token cap and were truncated mid-JSON
    # (see neos/config/schema.py comment for the arithmetic).
    assert cfg.decompose_max_tokens == 3200
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


def test_truncation_retry_multiplier_default():
    from neos.config.settings import settings

    assert settings.config.deep_analysis.truncation_retry_multiplier == 2.0


def test_truncation_retry_multiplier_rejects_values_at_or_below_one():
    from pydantic import ValidationError

    from neos.config.schema import DeepAnalysisConfig

    with pytest.raises(ValidationError):
        DeepAnalysisConfig(truncation_retry_multiplier=1.0)
    with pytest.raises(ValidationError):
        DeepAnalysisConfig(truncation_retry_multiplier=0.5)


def test_finalization_reduction_allowance_default():
    from neos.config.settings import settings

    assert settings.config.deep_analysis.finalization_reduction_allowance == 2


def test_default_config_does_not_warn_about_the_floor():
    """기본값에서 보일 경고가 아니다 — 보인다면 산식이나 기본값이 틀린 것이다."""
    import warnings

    from neos.config.loader import warn_finalization_floor_ratio
    from neos.config.settings import settings

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        warn_finalization_floor_ratio(settings.config.deep_analysis)

    assert [w for w in caught if issubclass(w.category, UserWarning)] == []


def test_a_disproportionate_floor_warns():
    import warnings

    from neos.config.loader import warn_finalization_floor_ratio
    from neos.config.settings import settings

    config = settings.config.deep_analysis.model_copy(deep=True)
    config.dev_profile.global_token_cap = 4000

    # 층 값은 config 에서 읽는다 -- 하드코딩하면 `report_retry_cap` 이나
    # `synthesis_max_tokens` 를 조정할 때마다 이 테스트가 조용히 낡는다.
    floor = config.finalization_floor_tokens(
        config.dev_profile.synthesis_max_tokens
    )
    assert floor > 4000  # 경고가 나올 조건인지 먼저 확인

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        warn_finalization_floor_ratio(config)

    messages = [str(w.message) for w in caught]
    assert any(str(floor) in m and "4000" in m for m in messages)


def test_the_floor_counts_input_not_only_output():
    """G6: floor는 출력만 셌고 reserve()는 입력+출력을 뺐다.

    node_reduction 한 번의 input_bound 실측 최대는 6,480 -- 기존 dev floor
    4,400 전체보다 크다. 두 tier 모두 reserve()가 실제로 차감하는 통화로
    사이징돼야 한다.
    """
    from neos.config.schema import DeepAnalysisConfig

    config = DeepAnalysisConfig()

    # default 프로파일. assembly 는 절단 확장을 센다(D56): `call_text` 가
    # 같은 프롬프트를 출력 2배로 다시 보내므로 입력이 2회, 출력이 1+2회다 --
    # 2*3.0*4000 + 3*4000 = 36,000. grading 5.0*4000+800 = 20,800.
    # -> attempt 56,800 * (report_retry_cap 1 + 1) = 113,600
    assert config.report_floor_tokens(4_000) == 113_600
    # reduction (1.6+1)*4000=10,400 * allowance 2 = 20,800
    assert config.finalization_floor_tokens(4_000) == 113_600 + 20_800

    # dev 프로파일 (synthesis_max_tokens=2000)
    # assembly 2*3.0*2000 + 3*2000 = 18,000 -- 표본 #12 가 실측한 절단 시도
    # 1회 비용 17,852 를 덮는다. 옛 값 8,000 은 못 덮었고, 그래서 시도 1 이
    # 6개 run 중 4개에서 예약을 거절당했다.
    assert config.report_floor_tokens(2_000) == 57_600
    assert config.finalization_floor_tokens(2_000) == 68_000


def test_the_assembly_tier_funds_every_attempt_including_its_truncation_retry():
    """D56. 바닥이 재시도를 실제로 감당하는지 -- 표본 #12 의 실측 숫자로.

    `call_text` 는 잘린 조립에 **같은 프롬프트를 출력 2배로** 다시 보낸다
    (llm.py:464-474). 그래서 한 시도가 예약을 두 번 한다:

        input_bound=5926 max_out=2000 total=7926   <- 시도
        input_bound=5926 max_out=4000 total=9926   <- 확장

    옛 조립항 8,000 은 이 17,852 를 못 덮었고, 그래서 시도 1 이 6개 run 중
    4개에서 `input_bound` 로 거절돼 결정론 템플릿으로 강등됐다 -- 재시도
    루프가 실재한 적이 없던 이유다(D53·D55).
    """
    from neos.config.schema import DeepAnalysisConfig

    config = DeepAnalysisConfig()
    smt = config.dev_profile.synthesis_max_tokens

    # `available_for_assembly` = remaining - grading_floor (token_budget.py).
    # 최악의 경우 remaining 은 report_floor 까지 줄어 있다.
    assembly_tier = config.report_floor_tokens(smt) - config.grading_floor_tokens(smt)

    input_bound = 5_926  # 표본 #12 `01eadc5b` 실측
    attempt = input_bound + smt
    expansion = input_bound + int(config.truncation_retry_multiplier * smt)
    attempts = config.report_retry_cap + 1

    # 모든 시도가 절단되는 최악의 경우까지 덮어야 한다 -- 바닥은 예약
    # 보증이지 기대값이 아니다.
    assert assembly_tier >= attempts * (attempt + expansion)

    # 그리고 옛 공식으로는 못 덮었다는 것이 이 테스트의 요점이다.
    old_assembly = int((config.assembly_input_ratio + 1) * smt)
    old_tier = attempts * old_assembly
    assert old_tier < attempts * (attempt + expansion)


def test_the_shipped_defaults_do_not_trip_the_finalization_floor_warning():
    """D56 이 바닥을 키웠다. 경고는 코너로 몰린 프로파일용 백스톱이지
    기본값이 늘 켜두는 것이 아니다 -- dev cap 을 함께 올린 이유다."""
    import warnings as _warnings

    from neos.config.loader import warn_finalization_floor_ratio
    from neos.config.schema import DeepAnalysisConfig

    config = DeepAnalysisConfig()

    with _warnings.catch_warnings(record=True) as caught:
        _warnings.simplefilter("always")
        warn_finalization_floor_ratio(config)

    assert [str(w.message) for w in caught] == []


def test_the_report_tier_never_exceeds_the_total_floor():
    """TokenBudget의 불변식이 config 산식에서 이미 성립해야 한다."""
    from neos.config.schema import DeepAnalysisConfig

    config = DeepAnalysisConfig()
    for synth in (1, 100, 1_200, 4_000, 40_000):
        assert config.report_floor_tokens(synth) <= (
            config.finalization_floor_tokens(synth)
        )


def test_dev_profile_can_hold_a_worker_call():
    """실측 worker_analysis input_bound는 5,542~17,723이다.

    dev의 기존 20,000 캡은 floor를 빼기 전에도 워커 호출 하나를 확실히
    담지 못했다 -- dev run이 병리적이었던 이유다.
    """
    from neos.config.schema import DeepAnalysisConfig

    config = DeepAnalysisConfig()
    cap = config.dev_profile.global_token_cap
    floor = config.finalization_floor_tokens(
        config.dev_profile.synthesis_max_tokens
    )

    assert cap - floor > 17_723 * 2
