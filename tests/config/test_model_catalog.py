"""모델 카탈로그 스키마와 로더 테스트.

로더는 파일만 읽는다 — DB를 요구하지 않는다 (spec §7).
"""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from neos.config.model_config import (
    ModelCatalog,
    ThinkingContract,
    load_catalog,
    model_config,
    warn_unknown_routed_models,
)

pytestmark = pytest.mark.no_db


def _write(tmp_path: Path, data: dict) -> Path:
    path = tmp_path / "models.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def _invalid_catalog_data() -> dict:
    """A schema violation that would previously wipe the whole catalog.

    Two models claim the same (provider, tier) pair — one of the three
    plausible operator mistakes named in the review.
    """
    return {
        "models": {
            "claude-a": {"provider": "anthropic", "tiers": ["balanced"]},
            "claude-b": {"provider": "anthropic", "tiers": ["balanced"]},
        }
    }


@pytest.fixture
def restore_model_config(monkeypatch):
    """Point ModelConfig at a scratch file for the test, then restore the real catalog.

    `ModelConfig` is a class-level singleton, so any test that calls
    `reload()` or pokes `_catalog` directly must undo it — otherwise every
    later test in the session sees a poisoned (empty or scratch) catalog.
    """
    yield
    monkeypatch.delenv("NEOS_MODEL_CONFIG_PATH", raising=False)
    model_config.reload()


def test_catalog_rejects_unknown_model_field(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        {"models": {"claude-x": {"provider": "anthropic", "capabilities": ["vision"]}}},
    )

    with pytest.raises(ValidationError, match="capabilities"):
        load_catalog(path)


def test_catalog_rejects_unknown_thinking_value(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        {"models": {"claude-x": {"provider": "anthropic", "thinking": "extended"}}},
    )

    with pytest.raises(ValidationError, match="thinking"):
        load_catalog(path)


def test_catalog_rejects_unknown_tier(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        {"models": {"claude-x": {"provider": "anthropic", "tiers": ["cheapest"]}}},
    )

    with pytest.raises(ValidationError, match="tiers"):
        load_catalog(path)


def test_catalog_rejects_two_models_claiming_the_same_tier(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        {
            "models": {
                "claude-a": {"provider": "anthropic", "tiers": ["balanced"]},
                "claude-b": {"provider": "anthropic", "tiers": ["balanced"]},
            }
        },
    )

    with pytest.raises(ValidationError, match="balanced"):
        load_catalog(path)


def test_catalog_allows_one_model_in_two_tiers(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        {"models": {"llama": {"provider": "ollama", "tiers": ["fast", "balanced"]}}},
    )

    catalog = load_catalog(path)

    assert catalog.models["llama"].tiers == ["fast", "balanced"]


def test_catalog_rejects_alias_pointing_at_unknown_model(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        {
            "models": {"claude-a": {"provider": "anthropic"}},
            "aliases": {"llm": {"sonnet": "claude-typo"}},
        },
    )

    with pytest.raises(ValidationError, match="claude-typo"):
        load_catalog(path)


def test_catalog_rejects_default_pointing_at_unknown_alias(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        {
            "models": {"claude-a": {"provider": "anthropic"}},
            "aliases": {"llm": {"sonnet": "claude-a"}},
            "defaults": {"llm": "opus"},
        },
    )

    with pytest.raises(ValidationError, match="opus"):
        load_catalog(path)


def test_pricing_defaults_cache_fields_to_zero(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        {
            "models": {
                "gpt-x": {
                    "provider": "openai",
                    "pricing": {"input": 2.5, "output": 10.0},
                }
            }
        },
    )

    pricing = load_catalog(path).models["gpt-x"].pricing

    assert pricing is not None
    assert pricing.cache_creation == 0.0
    assert pricing.cache_read == 0.0


def test_unspecified_thinking_defaults_to_budgeted(tmp_path: Path) -> None:
    """미등록·미선언 모델은 레거시 분기를 유지한다 (spec §4)."""
    path = _write(tmp_path, {"models": {"claude-a": {"provider": "anthropic"}}})

    assert load_catalog(path).models["claude-a"].thinking is ThinkingContract.BUDGETED


def test_legacy_shape_file_is_converted(tmp_path: Path) -> None:
    """`models:` 키가 없는 옛 형태 파일을 자동 변환한다 (spec §7)."""
    path = _write(
        tmp_path,
        {
            "vision_models": {
                "gpt4o": {
                    "model_id": "gpt-4o",
                    "provider": "openai",
                    "description": "OpenAI GPT-4o Vision",
                    "max_tokens": 4096,
                    "supports_video": False,
                },
                "gemini": {
                    "model_id": "gemini-1.5-pro-latest",
                    "provider": "google",
                    "max_tokens": 8192,
                    "supports_video": True,
                },
            },
            "llm_models": {
                "claude_sonnet": {
                    "model_id": "claude-sonnet-5",
                    "provider": "anthropic",
                    "max_tokens": 8192,
                }
            },
            "embedding_models": {
                "openai_small": {
                    "model_id": "text-embedding-3-small",
                    "provider": "openai",
                    "dimension": 1536,
                }
            },
            "defaults": {"vision": "gpt4o", "llm": "claude_sonnet", "embedding": "openai_small"},
        },
    )

    catalog = load_catalog(path)

    assert catalog.aliases["vision"]["gpt4o"] == "gpt-4o"
    assert catalog.aliases["llm"]["claude_sonnet"] == "claude-sonnet-5"
    assert catalog.aliases["embedding"]["openai_small"] == "text-embedding-3-small"
    # provider "google"은 LLMFactory 키 "gemini"로 정규화된다
    assert catalog.models["gemini-1.5-pro-latest"].provider == "gemini"
    assert catalog.models["gemini-1.5-pro-latest"].supports_video is True
    assert catalog.models["text-embedding-3-small"].dimension == 1536
    # 옛 형태에는 tier·pricing·thinking이 없다
    assert catalog.models["claude-sonnet-5"].tiers == []
    assert catalog.models["claude-sonnet-5"].pricing is None
    assert catalog.models["claude-sonnet-5"].thinking is ThinkingContract.BUDGETED
    assert catalog.defaults == {
        "vision": "gpt4o",
        "llm": "claude_sonnet",
        "embedding": "openai_small",
    }


def test_legacy_shape_conversion_logs_migration_notice(tmp_path: Path, caplog) -> None:
    path = _write(
        tmp_path,
        {"llm_models": {"sonnet": {"model_id": "claude-sonnet-5", "provider": "anthropic"}}},
    )

    with caplog.at_level("INFO", logger="neos.config.model_config"):
        load_catalog(path)

    assert any("legacy" in record.message.lower() for record in caplog.records)


def test_legacy_entry_missing_model_id_is_skipped_with_warning(
    tmp_path: Path, caplog
) -> None:
    """옛 형태 항목에 model_id가 없으면 그 항목만 건너뛰고 나머지는 로드된다."""
    path = _write(
        tmp_path,
        {
            "llm_models": {
                "sonnet": {"provider": "anthropic"},  # model_id 누락
                "opus": {"model_id": "claude-opus-5", "provider": "anthropic"},
            }
        },
    )

    with caplog.at_level("WARNING", logger="neos.config.model_config"):
        catalog = load_catalog(path)

    assert catalog.aliases["llm"] == {"opus": "claude-opus-5"}
    assert catalog.models["claude-opus-5"].provider == "anthropic"
    warnings = [r.message for r in caplog.records if r.levelname == "WARNING"]
    assert any("llm_models" in msg and "sonnet" in msg for msg in warnings)


def test_legacy_entry_that_is_not_a_mapping_is_skipped_with_warning(
    tmp_path: Path, caplog
) -> None:
    """옛 형태 항목 값이 dict가 아니라 문자열 등이면 그 항목만 건너뛴다."""
    path = _write(
        tmp_path,
        {
            "llm_models": {
                "sonnet": "claude-sonnet-5",  # dict가 아니라 맨 문자열
                "opus": {"model_id": "claude-opus-5", "provider": "anthropic"},
            }
        },
    )

    with caplog.at_level("WARNING", logger="neos.config.model_config"):
        catalog = load_catalog(path)

    assert catalog.aliases["llm"] == {"opus": "claude-opus-5"}
    assert catalog.models["claude-opus-5"].provider == "anthropic"
    warnings = [r.message for r in caplog.records if r.levelname == "WARNING"]
    assert any("llm_models" in msg and "sonnet" in msg for msg in warnings)


def test_missing_file_yields_empty_catalog(tmp_path: Path, caplog) -> None:
    """파일이 없으면 부팅을 막지 않고 빈 카탈로그로 성능 저하만 감수한다."""
    with caplog.at_level("ERROR", logger="neos.config.model_config"):
        catalog = load_catalog(tmp_path / "does-not-exist.yaml")

    assert catalog.models == {}
    assert any(record.levelname == "ERROR" for record in caplog.records)


def test_models_for_provider_returns_only_selectable_in_declaration_order(
    tmp_path: Path,
) -> None:
    path = _write(
        tmp_path,
        {
            "models": {
                "claude-new": {"provider": "anthropic"},
                "gpt-x": {"provider": "openai"},
                "claude-old": {"provider": "anthropic", "selectable": False},
                "claude-mid": {"provider": "anthropic"},
            }
        },
    )
    catalog = load_catalog(path)

    assert catalog.models_for_provider("anthropic") == ["claude-new", "claude-mid"]


def test_tiers_for_provider_emits_canonical_tier_order(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        {
            "models": {
                "big": {"provider": "anthropic", "tiers": ["powerful"]},
                "small": {"provider": "anthropic", "tiers": ["fast"]},
                "mid": {"provider": "anthropic", "tiers": ["balanced"]},
            }
        },
    )
    catalog = load_catalog(path)

    assert list(catalog.tiers_for_provider("anthropic")) == ["fast", "balanced", "powerful"]
    assert catalog.tiers_for_provider("anthropic")["powerful"] == "big"


def test_pricing_for_requires_provider_match(tmp_path: Path) -> None:
    """provider가 어긋나면 가격을 주지 않는다 (현행 중첩 dict 동작 보존)."""
    path = _write(
        tmp_path,
        {
            "models": {
                "gpt-x": {
                    "provider": "openai",
                    "pricing": {"input": 2.5, "output": 10.0},
                }
            }
        },
    )
    catalog = load_catalog(path)

    assert catalog.pricing_for("openai", "gpt-x") is not None
    assert catalog.pricing_for("anthropic", "gpt-x") is None
    assert catalog.pricing_for("openai", "gpt-unknown") is None


def test_thinking_contract_of_unregistered_model_is_budgeted(tmp_path: Path) -> None:
    catalog = load_catalog(_write(tmp_path, {"models": {}}))

    assert catalog.thinking_contract("claude-from-the-future") is ThinkingContract.BUDGETED


def test_committed_catalog_loads_and_is_non_empty() -> None:
    """리포지토리에 커밋된 카탈로그가 실제로 유효하다."""
    catalog = load_catalog(Path("neos/config/models.yaml"))

    assert isinstance(catalog, ModelCatalog)
    assert catalog.models


def test_legacy_alias_helpers_resolve_committed_catalog() -> None:
    from neos.config.model_config import (
        get_embedding_model_id,
        get_llm_model_id,
        get_vision_model_id,
    )

    assert get_vision_model_id("gpt4o") == "gpt-4o"
    assert get_vision_model_id("claude") == "claude-sonnet-5"
    assert get_llm_model_id("claude_sonnet") == "claude-sonnet-5"
    assert get_llm_model_id("claude_opus") == "claude-opus-5"
    assert get_llm_model_id("claude_haiku") == "claude-haiku-4-5-20251001"
    assert get_embedding_model_id("openai_small") == "text-embedding-3-small"
    # 인자 없이 호출하면 defaults를 따른다
    assert get_vision_model_id() == "gpt-4o"
    assert get_llm_model_id() == "claude-sonnet-5"
    assert get_embedding_model_id() == "text-embedding-3-small"


def test_legacy_model_dict_keeps_model_id_and_provider() -> None:
    from neos.config.model_config import model_config

    entry = model_config.get_vision_model("claude")

    assert entry["model_id"] == "claude-sonnet-5"
    assert entry["provider"] == "anthropic"


def test_legacy_lookup_of_unknown_alias_raises_with_available_names() -> None:
    from neos.config.model_config import model_config

    with pytest.raises(ValueError, match="Available models"):
        model_config.get_llm_model("nonexistent_alias")


def test_unknown_model_warns_once_per_name(caplog) -> None:
    """카탈로그에 없는 모델은 통과시키되, 이름별로 한 번만 경고한다 (spec §6)."""
    from neos.utils.llm_factory import LLMFactory

    LLMFactory._warned_unknown_models.clear()

    with caplog.at_level("WARNING", logger="neos.utils.llm_factory"):
        LLMFactory._warn_if_unknown_model("claude-from-the-future")
        LLMFactory._warn_if_unknown_model("claude-from-the-future")
        LLMFactory._warn_if_unknown_model("claude-sonnet-5")

    warnings = [r for r in caplog.records if "claude-from-the-future" in r.message]
    assert len(warnings) == 1
    assert not [r for r in caplog.records if "claude-sonnet-5" in r.message]


def test_create_llm_warns_for_unregistered_model(caplog, monkeypatch) -> None:
    """미등록 모델은 예외가 아니라 경고로 통과한다."""
    from types import SimpleNamespace
    from unittest.mock import patch

    from neos.utils.llm_factory import LLMFactory

    LLMFactory._warned_unknown_models.clear()
    LLMFactory.clear_cache()
    # settings 객체 전체를 바꾼다 — 실제 Settings에 setattr하면
    # validate_assignment가 걸리거나 다른 테스트로 상태가 새어 나간다.
    monkeypatch.setattr(
        "neos.providers.anthropic.settings",
        SimpleNamespace(
            ANTHROPIC_API_KEY="test-key",
            LLM_TIMEOUT=30,
            THINKING_BLOCKS_ENABLED=False,
            MAX_THINKING_LENGTH=0,
        ),
    )

    with caplog.at_level("WARNING", logger="neos.utils.llm_factory"):
        with patch("neos.providers.anthropic.ChatAnthropic"):
            LLMFactory.create_llm(
                provider="anthropic",
                model="claude-not-in-catalog",
                temperature=0.3,
                use_cache=False,
            )

    assert any("claude-not-in-catalog" in r.message for r in caplog.records)


def test_warn_unknown_routed_models_flags_typos(caplog) -> None:
    from neos.config.model_config import warn_unknown_routed_models
    from neos.config.schema import ModelRoutingConfig

    routing = ModelRoutingConfig.model_validate(
        {
            "anthropic": {"everyday": "claude-sonnet-5", "powerful": "claude-opus-5"},
            "openai": {"everyday": "gpt-5.6-tera", "powerful": "gpt-5.6-sol"},
        }
    )

    with caplog.at_level("WARNING", logger="neos.config.model_config"):
        unknown = warn_unknown_routed_models(routing)

    assert unknown == ["gpt-5.6-tera"]
    assert any("gpt-5.6-tera" in record.message for record in caplog.records)


def test_warn_unknown_routed_models_is_silent_for_committed_defaults(caplog) -> None:
    from neos.config.model_config import warn_unknown_routed_models
    from neos.config.schema import ModelRoutingConfig

    with caplog.at_level("WARNING", logger="neos.config.model_config"):
        unknown = warn_unknown_routed_models(ModelRoutingConfig())

    assert unknown == []
    assert not [r for r in caplog.records if "model_routing" in r.message]


def test_main_lifespan_checks_routed_models_against_the_catalog() -> None:
    """기동 경로에 검사가 연결돼 있는지 소스로 고정한다."""
    source = Path("neos/main.py").read_text(encoding="utf-8")

    assert "warn_unknown_routed_models" in source


# ---- Fix A: a validation failure must not wipe a previously-good catalog ----


def test_reload_with_invalid_catalog_retains_last_good_catalog(
    tmp_path: Path, monkeypatch, caplog, restore_model_config
) -> None:
    """An operator typo in models.yaml must not wipe a working catalog.

    Reproduces one of the three plausible mistakes from the review: a new
    model claims a tier an existing model already holds.
    """
    # Establish a known-good state from the real, committed catalog first.
    model_config.reload()
    good_catalog = model_config.catalog
    assert good_catalog.models, "sanity: the real catalog must be non-empty"

    bad_path = _write(tmp_path, _invalid_catalog_data())
    monkeypatch.setenv("NEOS_MODEL_CONFIG_PATH", str(bad_path))

    with caplog.at_level("ERROR", logger="neos.config.model_config"):
        model_config.reload()

    # The previous, valid catalog is retained verbatim -- not swapped for
    # an empty one.
    assert model_config.catalog is good_catalog
    assert model_config.catalog.models

    error_messages = [r.message for r in caplog.records if r.levelname == "ERROR"]
    assert any("rejected" in msg.lower() for msg in error_messages)
    assert any("previous catalog" in msg.lower() for msg in error_messages)


def test_reload_first_load_invalid_yields_empty_catalog_with_clear_error(
    tmp_path: Path, monkeypatch, caplog, restore_model_config
) -> None:
    """No last-good catalog exists yet: fall back to empty, but say so loudly."""
    bad_path = _write(tmp_path, _invalid_catalog_data())
    monkeypatch.setenv("NEOS_MODEL_CONFIG_PATH", str(bad_path))
    # Simulate "no catalog has ever loaded successfully yet".
    model_config._catalog = None

    with caplog.at_level("ERROR", logger="neos.config.model_config"):
        model_config.reload()

    assert model_config.catalog.models == {}

    error_messages = [r.message for r in caplog.records if r.levelname == "ERROR"]
    assert any("empty" in msg.lower() for msg in error_messages)
    assert any(
        "fall back to defaults" in msg.lower() or "falling back to defaults" in msg.lower()
        for msg in error_messages
    )


def test_load_catalog_itself_still_raises_validation_error(tmp_path: Path) -> None:
    """Fix A changes reload()/startup logging, not load_catalog()'s contract.

    tests/config/test_model_catalog.py's schema tests depend on load_catalog
    raising ValidationError directly.
    """
    path = _write(tmp_path, _invalid_catalog_data())

    with pytest.raises(ValidationError, match="balanced"):
        load_catalog(path)


def test_warn_unknown_routed_models_logs_error_when_catalog_is_empty(
    caplog, restore_model_config
) -> None:
    """An empty catalog must be loud at startup, not inferred from routing warnings."""
    from neos.config.schema import ModelRoutingConfig

    model_config._catalog = ModelCatalog()

    with caplog.at_level("ERROR", logger="neos.config.model_config"):
        warn_unknown_routed_models(ModelRoutingConfig())

    error_messages = [r.message for r in caplog.records if r.levelname == "ERROR"]
    assert any("empty" in msg.lower() for msg in error_messages)


def test_warn_unknown_routed_models_does_not_log_empty_error_for_a_good_catalog(
    caplog, restore_model_config
) -> None:
    from neos.config.schema import ModelRoutingConfig

    model_config.reload()

    with caplog.at_level("ERROR", logger="neos.config.model_config"):
        warn_unknown_routed_models(ModelRoutingConfig())

    assert not [r for r in caplog.records if r.levelname == "ERROR"]


# ---- vision capability flag ----


def test_vision_flag_defaults_to_false_and_parses(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        {
            "models": {
                "seeing-model": {"provider": "anthropic", "vision": True},
                "blind-model": {"provider": "openai"},
            }
        },
    )

    catalog = load_catalog(path)

    assert catalog.models["seeing-model"].vision is True
    assert catalog.models["blind-model"].vision is False


def test_supports_vision_reads_the_live_catalog() -> None:
    from neos.config.model_config import supports_vision

    # 카탈로그에 없는 모델은 능력을 주장하지 않는다
    assert supports_vision("no-such-model-xyz") is False
    # 카탈로그가 True 로 적은 모델은 True 다
    assert supports_vision("claude-sonnet-5") is True
