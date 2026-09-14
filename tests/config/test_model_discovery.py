"""Live Anthropic catalog overlay. Default off; tests never hit the network."""

from __future__ import annotations

import pytest

from neos.config.model_config import ModelCatalog, get_model_spec, model_config
from neos.config.model_identity import to_picker_payload
from neos.config.schema import AppConfig, ModelRoutingConfig

pytestmark = pytest.mark.no_db


def _catalog() -> ModelCatalog:
    return ModelCatalog.model_validate(
        {
            "models": {
                "claude-sonnet-5": {
                    "provider": "anthropic",
                    "selectable": True,
                    "gateway_id": "anthropic/claude-sonnet-5",
                    "picker": {
                        "name": "Sonnet 5",
                        "description": "balanced",
                        "group": "anthropic",
                    },
                }
            }
        }
    )


@pytest.fixture
def reset_overlay():
    from neos.config import model_discovery

    model_discovery.reset_overlay()
    yield
    model_discovery.reset_overlay()


def test_live_anthropic_flag_defaults_false() -> None:
    assert AppConfig().model_catalog.live_anthropic is False


def test_sync_live_overlay_never_constructs_settings_before_it_is_bound(
    reset_overlay, monkeypatch
) -> None:
    """The first catalog load runs while `model_config` is importing.

    Constructing `Settings()` there re-enters `validate_coding_model_policy`,
    which needs the catalog that is still being built -- a circular import.
    """
    import sys
    import types

    from neos.config import model_discovery

    monkeypatch.setitem(
        sys.modules,
        "neos.config.settings",
        types.ModuleType("neos.config.settings"),
    )
    refreshed: list[int] = []
    monkeypatch.setattr(
        model_discovery,
        "refresh_live_overlay",
        lambda *args, **kwargs: refreshed.append(1) or frozenset({"x"}),
    )

    assert model_discovery.sync_live_overlay(_catalog()) == frozenset()
    assert refreshed == []


def test_fresh_process_imports_coding_modules_with_real_loop_enabled() -> None:
    """development enables the real coding loop; importing must not cycle."""
    import os
    import subprocess
    import sys

    env = {
        **os.environ,
        "NEOS_ENV": "development",
        "ANTHROPIC_API_KEY": "sk-ant-test-placeholder",
    }
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import neos.coding.loop.durable\n"
            "from neos.config.settings import settings\n"
            "assert settings.config.coding_model.enabled is True\n",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]


def test_flag_off_does_not_fetch_and_overlay_is_empty(reset_overlay) -> None:
    from neos.config.model_discovery import current_overlay, refresh_live_overlay

    called: list[int] = []

    overlay = refresh_live_overlay(
        _catalog(),
        enabled=False,
        api_key="sk-test",
        fetch_ids=lambda: called.append(1) or ["claude-new-live"],
    )

    assert overlay == frozenset()
    assert current_overlay() == frozenset()
    assert called == []


def test_live_ids_merge_yaml_wins_and_live_only_never_selectable(
    reset_overlay,
) -> None:
    from neos.config.model_discovery import live_model_spec, refresh_live_overlay

    catalog = _catalog()
    overlay = refresh_live_overlay(
        catalog,
        enabled=True,
        api_key="sk-test",
        fetch_ids=lambda: ["claude-sonnet-5", "claude-new-live"],
    )

    assert overlay == frozenset({"claude-new-live"})
    assert live_model_spec("claude-sonnet-5") is None
    live = live_model_spec("claude-new-live")
    assert live is not None
    assert live.selectable is False
    assert live.picker is None
    assert live.provider == "anthropic"

    payload = to_picker_payload(catalog, ModelRoutingConfig())
    assert "claude-new-live" not in {row.catalog_id for row in payload.models}
    assert {row.catalog_id for row in payload.models} == {"claude-sonnet-5"}


def test_get_model_spec_yaml_wins_over_live_overlay(
    reset_overlay, monkeypatch
) -> None:
    from neos.config.model_discovery import refresh_live_overlay

    catalog = _catalog()
    monkeypatch.setattr(model_config, "_catalog", catalog)
    refresh_live_overlay(
        catalog,
        enabled=True,
        api_key="sk-test",
        fetch_ids=lambda: ["claude-sonnet-5", "claude-new-live"],
    )

    yaml_spec = get_model_spec("claude-sonnet-5")
    assert yaml_spec is not None
    assert yaml_spec.selectable is True
    assert yaml_spec.picker is not None

    live = get_model_spec("claude-new-live")
    assert live is not None
    assert live.selectable is False
    assert live.picker is None


def test_auth_empty_keeps_last_overlay(reset_overlay) -> None:
    from neos.config.model_discovery import current_overlay, refresh_live_overlay

    catalog = _catalog()
    first = refresh_live_overlay(
        catalog,
        enabled=True,
        api_key="sk-test",
        fetch_ids=lambda: ["claude-kept"],
    )
    assert first == frozenset({"claude-kept"})

    called: list[int] = []
    second = refresh_live_overlay(
        catalog,
        enabled=True,
        api_key="",
        fetch_ids=lambda: called.append(1) or ["claude-should-not-appear"],
    )

    assert second == frozenset({"claude-kept"})
    assert current_overlay() == frozenset({"claude-kept"})
    assert called == []


def test_transient_error_keeps_last_overlay(reset_overlay) -> None:
    from neos.config.model_discovery import refresh_live_overlay

    catalog = _catalog()
    refresh_live_overlay(
        catalog,
        enabled=True,
        api_key="sk-test",
        fetch_ids=lambda: ["claude-kept"],
    )

    def boom() -> list[str]:
        raise TimeoutError("anthropic unreachable")

    kept = refresh_live_overlay(
        catalog, enabled=True, api_key="sk-test", fetch_ids=boom
    )

    assert kept == frozenset({"claude-kept"})


def test_first_fail_leaves_empty_overlay(reset_overlay) -> None:
    from neos.config.model_discovery import current_overlay, refresh_live_overlay

    def boom() -> list[str]:
        raise TimeoutError("anthropic unreachable")

    overlay = refresh_live_overlay(
        _catalog(), enabled=True, api_key="sk-test", fetch_ids=boom
    )

    assert overlay == frozenset()
    assert current_overlay() == frozenset()


def test_successful_empty_fetch_evicts_overlay(reset_overlay) -> None:
    from neos.config.model_discovery import refresh_live_overlay

    catalog = _catalog()
    refresh_live_overlay(
        catalog,
        enabled=True,
        api_key="sk-test",
        fetch_ids=lambda: ["claude-stale"],
    )

    evicted = refresh_live_overlay(
        catalog, enabled=True, api_key="sk-test", fetch_ids=lambda: []
    )

    assert evicted == frozenset()


def test_live_unknown_metric_has_no_id_label(reset_overlay) -> None:
    from neos.config.model_discovery import refresh_live_overlay
    from neos.observability.metrics import get_metrics_collector

    collector = get_metrics_collector()
    before = collector.catalog_live_unknown_total._value.get()

    refresh_live_overlay(
        _catalog(),
        enabled=True,
        api_key="sk-test",
        fetch_ids=lambda: ["claude-new-live", "claude-also-new"],
    )

    after = collector.catalog_live_unknown_total._value.get()
    assert after == before + 2
    sample = collector.catalog_live_unknown_total.collect()[0]
    for metric in sample.samples:
        assert "id" not in metric.labels
