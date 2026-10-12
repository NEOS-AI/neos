"""`workflow.skill_execution` -- 기본값이 계약이다 (spec §4)."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from neos.config.loader import YAML_ONLY_FEATURE_FLAG_ENV_KEYS, load_yaml_file
from neos.config.schema import WorkflowConfig
from neos.config.settings import _legacy_setting_path, settings

pytestmark = pytest.mark.no_db

REPO = Path(__file__).resolve().parents[2]


def test_defaults_are_off_with_the_spec_limits() -> None:
    config = WorkflowConfig().skill_execution
    assert config.enabled is False
    assert config.max_skills_per_turn == 3
    assert config.timeout_seconds == 15
    assert config.max_results_per_skill == 5
    assert config.max_content_chars == 4000


@pytest.mark.parametrize(
    "kwargs",
    [{"max_skills_per_turn": 0}, {"timeout_seconds": 0}, {"max_results_per_skill": 0}, {"bogus": 1}],
)
def test_out_of_range_or_unknown_values_are_rejected(kwargs) -> None:
    with pytest.raises(ValidationError):
        WorkflowConfig(skill_execution=kwargs)


def test_the_flat_alias_points_at_the_flag() -> None:
    assert _legacy_setting_path("SKILL_EXECUTION_ENABLED") == "workflow.skill_execution.enabled"
    assert YAML_ONLY_FEATURE_FLAG_ENV_KEYS["SKILL_EXECUTION_ENABLED"] == "workflow.skill_execution.enabled"


def test_the_test_session_runs_with_the_flag_off() -> None:
    # development 프로파일은 켜지만 테스트 세션 오버레이가 끈다 -- 꺼져 있지 않으면
    # 워크플로 테스트가 실제 스킬(네트워크)을 부르고 정적 그래프 스냅샷이 바뀐다.
    assert settings.SKILL_EXECUTION_ENABLED is False


def test_only_development_enables_it() -> None:
    dev = load_yaml_file(REPO / "config" / "neos.development.yaml")
    assert dev["workflow"]["skill_execution"]["enabled"] is True
    for name in ("neos.default.yaml", "neos.staging.yaml", "neos.production.yaml"):
        data = load_yaml_file(REPO / "config" / name)
        enabled = ((data.get("workflow") or {}).get("skill_execution") or {}).get("enabled", False)
        assert enabled is False, name
    overlay = load_yaml_file(REPO / "tests" / "fixtures" / "config" / "test-session.yaml")
    assert overlay["workflow"]["skill_execution"]["enabled"] is False
