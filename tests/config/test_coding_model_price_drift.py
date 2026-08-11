"""`coding_model` 가격이 모델 카탈로그와 어긋나면 기동 시 경고하는지 검증한다.

`coding_model.input_cost_micros_per_million` / `output_...`은 코딩 루프의
예산 가드용 정수(micros)다. 운영자 정책이므로 카탈로그가 이 값을 덮어쓰지
않는다 — 협상 요율을 쓸 수 있어야 한다.

문제는 같은 모델의 가격이 두 곳에 존재하고 조용히 어긋날 수 있다는 것이다.
`neos/config/schema.py`는 순수 스키마 모듈이고 `model_config`가 그쪽에서
`StrictConfigModel`을 가져오므로, 검증기가 카탈로그를 조회하면 순환 import가
된다. 그래서 드리프트 감지는 기동 시 경고로 처리한다.
"""

import pytest

from neos.config.model_config import warn_coding_model_price_drift
from neos.config.schema import CodingModelConfig

pytestmark = pytest.mark.no_db

LOGGER = "neos.config.model_config"

# claude-sonnet-5: 카탈로그 $3.00 / $15.00 per 1M
SONNET5_INPUT_MICROS = 3_000_000
SONNET5_OUTPUT_MICROS = 15_000_000


def _coding_model(**overrides) -> CodingModelConfig:
    data = {
        "enabled": True,
        "model": "claude-sonnet-5",
        "input_cost_micros_per_million": SONNET5_INPUT_MICROS,
        "output_cost_micros_per_million": SONNET5_OUTPUT_MICROS,
    }
    data.update(overrides)
    return CodingModelConfig.model_validate(data)


def test_matching_prices_are_silent(caplog) -> None:
    with caplog.at_level("WARNING", logger=LOGGER):
        drift = warn_coding_model_price_drift(_coding_model())

    assert drift == []
    assert not [r for r in caplog.records if "coding_model" in r.message]


def test_input_price_drift_is_reported(caplog) -> None:
    with caplog.at_level("WARNING", logger=LOGGER):
        drift = warn_coding_model_price_drift(
            _coding_model(input_cost_micros_per_million=9_000_000)
        )

    assert drift == ["input"]
    assert any("input" in r.message and "claude-sonnet-5" in r.message
               for r in caplog.records)


def test_output_price_drift_is_reported(caplog) -> None:
    with caplog.at_level("WARNING", logger=LOGGER):
        drift = warn_coding_model_price_drift(
            _coding_model(output_cost_micros_per_million=1)
        )

    assert drift == ["output"]


def test_both_prices_can_drift(caplog) -> None:
    with caplog.at_level("WARNING", logger=LOGGER):
        drift = warn_coding_model_price_drift(
            _coding_model(
                input_cost_micros_per_million=1,
                output_cost_micros_per_million=2,
            )
        )

    assert drift == ["input", "output"]


def test_disabled_coding_model_is_not_checked(caplog) -> None:
    """비활성 상태의 0 가격은 드리프트가 아니다."""
    with caplog.at_level("WARNING", logger=LOGGER):
        drift = warn_coding_model_price_drift(
            CodingModelConfig.model_validate({"enabled": False})
        )

    assert drift == []
    assert not [r for r in caplog.records if "coding_model" in r.message]


def test_model_outside_the_catalog_is_not_checked(caplog) -> None:
    """카탈로그가 모르는 모델은 비교 대상이 없다 — allowlist가 아니다."""
    with caplog.at_level("WARNING", logger=LOGGER):
        drift = warn_coding_model_price_drift(
            _coding_model(model="claude-brand-new-unreleased")
        )

    assert drift == []


def test_unset_model_is_not_checked() -> None:
    assert warn_coding_model_price_drift(_coding_model(model=None)) == []


def test_committed_default_profile_has_no_drift() -> None:
    """커밋된 설정 프로필이 실제로 깨끗한지 확인한다."""
    from pathlib import Path

    from neos.config.loader import load_yaml_file
    from neos.config.schema import AppConfig

    for name in ("neos.default.yaml", "neos.production.yaml"):
        config = AppConfig.model_validate(load_yaml_file(Path("config") / name))

        assert warn_coding_model_price_drift(config.coding_model) == [], (
            f"config/{name} coding_model prices disagree with the model catalog"
        )


def test_startup_path_runs_the_drift_check() -> None:
    from pathlib import Path

    source = Path("neos/main.py").read_text(encoding="utf-8")

    assert "warn_coding_model_price_drift" in source
