"""Catalog identity: canonicalize, spelling, remaps, picker projection."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from neos.config.model_config import ModelCatalog, model_config
from neos.config.model_identity import (
    AmbiguousModelError,
    ModelIdentity,
    RemapCycleError,
    canonicalize,
    catalog_shaped,
    to_picker_payload,
)
from neos.config.schema import ModelRoutingConfig

pytestmark = pytest.mark.no_db


CURRENT_PICKER_IDS = {
    "anthropic/claude-sonnet-5",
    "anthropic/claude-opus-5.5",
    "anthropic/claude-haiku-4.5",
    "anthropic/claude-sonnet-4.5",
    "anthropic/claude-sonnet-4.5-thinking",
    "openai/gpt-6-sol",
    "openai/gpt-6-luna",
}

RETIRED_REMAPS = {
    "openai/gpt-4o": "gpt-6-sol",
    "openai/gpt-4o-mini": "gpt-6-sol",
    "openai/gpt-4.1": "gpt-6-sol",
    "openai/gpt-4.1-mini": "gpt-6-sol",
    "anthropic/claude-3.7-sonnet-thinking": "claude-sonnet-4-5-20250929",
    "anthropic/claude-opus-4.5": "claude-opus-5-5",
    "google/gemini-2.5-flash-lite": "claude-sonnet-5",
    "google/gemini-3-pro-preview": "claude-sonnet-5",
    "xai/grok-4.1-fast-non-reasoning": "claude-sonnet-5",
    "xai/grok-code-fast-1-thinking": "claude-sonnet-5",
    # 2026-09-24 은퇴한 모델의 옛 피커 쿠키
    "anthropic/claude-opus-5": "claude-opus-5-5",
    "openai/gpt-5.6-sol": "gpt-6-sol",
    "openai/gpt-5.6-terra": "gpt-6-sol",
}

# 은퇴한 핀 · 역할 별칭. remaps 와 달리 저장된 대화 핀에도 걸린다.
RETIRED_PINS = {
    "claude-opus-5": "claude-opus-5-5",
    "opus-5": "claude-opus-5-5",
    "gpt-5.6-sol": "gpt-6-sol",
    "gpt-5.6-terra": "gpt-6-sol",
}


def _catalog(data: dict) -> ModelCatalog:
    return ModelCatalog.model_validate(data)


def _pin(
    provider: str = "anthropic",
    *,
    selectable: bool = True,
    gateway_id: str | None = None,
    picker: dict | None = None,
    role_alias: str | None = None,
    wire_id: str | None = None,
    id_forms: list[str] | None = None,
    thinking: str = "budgeted",
    vision: bool = False,
) -> dict:
    spec: dict = {"provider": provider, "selectable": selectable, "thinking": thinking}
    if gateway_id is not None:
        spec["gateway_id"] = gateway_id
    if picker is not None:
        spec["picker"] = picker
    if role_alias is not None:
        spec["role_alias"] = role_alias
    if wire_id is not None:
        spec["wire_id"] = wire_id
    if id_forms is not None:
        spec["id_forms"] = id_forms
    if vision:
        spec["vision"] = True
    return spec


def _picker(name: str, description: str, group: str, extras: list[dict] | None = None) -> dict:
    row = {"name": name, "description": description, "group": group}
    if extras:
        row["extras"] = extras
    return row


# ---- catalog_shaped --------------------------------------------------------


def test_catalog_shaped_strips_known_provider_prefix_then_dots_to_dashes() -> None:
    assert catalog_shaped("  anthropic/claude-sonnet-5  ") == "claude-sonnet-5"
    assert catalog_shaped("anthropic/claude-haiku-4.5") == "claude-haiku-4-5"
    assert catalog_shaped("openai/gpt-5.6-terra") == "gpt-5-6-terra"
    assert catalog_shaped("google/gemini-2.5-flash-lite") == "gemini-2-5-flash-lite"
    assert catalog_shaped("xai/grok-4.1-fast") == "grok-4-1-fast"


def test_catalog_shaped_does_not_invent_a_dated_suffix() -> None:
    assert catalog_shaped("anthropic/claude-haiku-4.5") == "claude-haiku-4-5"
    assert "20251001" not in catalog_shaped("anthropic/claude-haiku-4.5")


def test_catalog_shaped_leaves_unknown_prefixes_and_empty_rest_alone() -> None:
    assert catalog_shaped("unknown/foo.bar") == "unknown/foo-bar"
    assert catalog_shaped("anthropic/") == "anthropic/"
    assert catalog_shaped("claude-sonnet-5") == "claude-sonnet-5"


# ---- canonicalize: empty / unknown -----------------------------------------


def test_canonicalize_rejects_empty_and_non_str() -> None:
    catalog = _catalog({"models": {"claude-a": _pin()}})

    assert canonicalize("", catalog=catalog) is None
    assert canonicalize("   ", catalog=catalog) is None
    assert canonicalize(None, catalog=catalog) is None  # type: ignore[arg-type]
    assert canonicalize(123, catalog=catalog) is None  # type: ignore[arg-type]


def test_undeclared_bare_sonnet_is_unknown() -> None:
    catalog = _catalog(
        {
            "models": {"claude-sonnet-5": _pin(role_alias="sonnet-5")},
            "role_aliases": {"sonnet-5": {"current": "claude-sonnet-5"}},
        }
    )

    assert canonicalize("sonnet", catalog=catalog) is None
    assert canonicalize("opus", catalog=catalog) is None
    assert canonicalize("haiku", catalog=catalog) is None


def test_ambiguous_model_error_is_reserved_and_unused_in_v1() -> None:
    assert issubclass(AmbiguousModelError, ValueError)
    catalog = _catalog({"models": {"claude-sonnet-5": _pin()}})
    # Undeclared short names stay None; load uniqueness is what prevents collisions.
    assert canonicalize("sonnet", catalog=catalog) is None


# ---- remaps hop to pins ----------------------------------------------------


def test_remap_hops_to_the_catalog_pin_and_stops() -> None:
    catalog = _catalog(
        {
            "models": {
                "claude-opus-5-5": _pin(gateway_id="anthropic/claude-opus-5.5"),
                "claude-sonnet-5": _pin(),
            },
            "remaps": {"anthropic/claude-opus-4.5": "claude-opus-5-5"},
        }
    )

    ident = canonicalize("anthropic/claude-opus-4.5", catalog=catalog)

    assert ident is not None
    assert ident.catalog_id == "claude-opus-5-5"
    assert ident.source == "remap"
    assert ident.gateway_id == "anthropic/claude-opus-5.5"


def test_apply_remap_false_does_not_follow_a_raw_cookie() -> None:
    catalog = _catalog(
        {
            "models": {"claude-opus-5-5": _pin(gateway_id="anthropic/claude-opus-5.5")},
            "remaps": {"anthropic/claude-opus-4.5": "claude-opus-5-5"},
        }
    )

    assert (
        canonicalize(
            "anthropic/claude-opus-4.5", catalog=catalog, apply_remap=False
        )
        is None
    )


def test_remap_cycle_raises() -> None:
    catalog = _catalog(
        {
            "models": {
                "pin-a": _pin(),
                "pin-b": _pin(),
            },
            "remaps": {"pin-a": "pin-b", "pin-b": "pin-a"},
        }
    )

    with pytest.raises(RemapCycleError):
        canonicalize("pin-a", catalog=catalog)


def test_self_remap_is_a_cycle() -> None:
    catalog = _catalog(
        {
            "models": {"pin-a": _pin()},
            "remaps": {"pin-a": "pin-a"},
        }
    )

    with pytest.raises(RemapCycleError):
        canonicalize("pin-a", catalog=catalog)


# ---- role alias / pin / gateway / id_form ----------------------------------


def test_declared_role_alias_resolves_to_current_pin() -> None:
    catalog = _catalog(
        {
            "models": {
                "claude-sonnet-5": _pin(
                    role_alias="sonnet-5",
                    gateway_id="anthropic/claude-sonnet-5",
                )
            },
            "role_aliases": {"sonnet-5": {"current": "claude-sonnet-5"}},
        }
    )

    ident = canonicalize("sonnet-5", catalog=catalog)

    assert ident is not None
    assert ident.catalog_id == "claude-sonnet-5"
    assert ident.source == "role_alias"
    assert ident.role_alias == "sonnet-5"
    assert ident.provider == "anthropic"
    assert ident.wire_id == "claude-sonnet-5"


def test_catalog_pin_key_resolves_as_pin() -> None:
    catalog = _catalog(
        {
            "models": {
                "claude-sonnet-5": _pin(
                    role_alias="sonnet-5",
                    gateway_id="anthropic/claude-sonnet-5",
                    wire_id="claude-sonnet-5",
                )
            },
            "role_aliases": {"sonnet-5": {"current": "claude-sonnet-5"}},
        }
    )

    ident = canonicalize("claude-sonnet-5", catalog=catalog)

    assert ident is not None
    assert ident.source == "pin"
    assert ident.catalog_id == "claude-sonnet-5"
    assert ident.gateway_id == "anthropic/claude-sonnet-5"


def test_exact_gateway_id_and_extra_resolve() -> None:
    catalog = _catalog(
        {
            "models": {
                "claude-sonnet-4-5-20250929": _pin(
                    gateway_id="anthropic/claude-sonnet-4.5",
                    picker=_picker(
                        "Sonnet 4.5",
                        "prev",
                        "anthropic",
                        extras=[
                            {
                                "gateway_id": "anthropic/claude-sonnet-4.5-thinking",
                                "name": "Thinking",
                                "description": "extended",
                                "group": "reasoning",
                            }
                        ],
                    ),
                )
            }
        }
    )

    primary = canonicalize("anthropic/claude-sonnet-4.5", catalog=catalog)
    extra = canonicalize("anthropic/claude-sonnet-4.5-thinking", catalog=catalog)

    assert primary is not None and primary.source == "gateway"
    assert extra is not None and extra.source == "gateway"
    assert primary.catalog_id == extra.catalog_id == "claude-sonnet-4-5-20250929"


def test_id_forms_resolve_without_inventing_a_date() -> None:
    catalog = _catalog(
        {
            "models": {
                "claude-haiku-4-5-20251001": _pin(
                    gateway_id="anthropic/claude-haiku-4.5",
                    id_forms=["claude-haiku-4-5", "claude-haiku-4.5"],
                )
            }
        }
    )

    via_form = canonicalize("claude-haiku-4-5", catalog=catalog)
    via_dotted = canonicalize("claude-haiku-4.5", catalog=catalog)

    assert via_form is not None and via_form.source == "id_form"
    assert via_dotted is not None and via_dotted.source == "id_form"
    assert via_form.catalog_id == via_dotted.catalog_id == "claude-haiku-4-5-20251001"


def test_spelling_retry_turns_gateway_shaped_pin_into_the_pin_key() -> None:
    """anthropic/claude-sonnet-5 → claude-sonnet-5 when that is already a pin.

    Dated pins are not invented: anthropic/claude-haiku-4.5 does not become
    claude-haiku-4-5-20251001 without gateway_id / id_forms / a remap.
    """
    catalog = _catalog(
        {
            "models": {
                "claude-sonnet-5": _pin(),
                "claude-haiku-4-5-20251001": _pin(),
            }
        }
    )

    spelled = canonicalize("anthropic/claude-sonnet-5", catalog=catalog)
    dated = canonicalize("anthropic/claude-haiku-4.5", catalog=catalog)

    assert spelled is not None
    assert spelled.catalog_id == "claude-sonnet-5"
    assert spelled.source == "pin"
    assert dated is None


def test_spelling_retry_does_not_run_remaps_a_second_time() -> None:
    catalog = _catalog(
        {
            "models": {"claude-sonnet-5": _pin()},
            "remaps": {"claude-sonnet-5": "claude-sonnet-5"},
        }
    )
    # apply_remap=False: the raw gateway is not a remap key; spelling yields
    # the pin key, which is also a remap key — step 7 must not hop remaps.
    ident = canonicalize(
        "anthropic/claude-sonnet-5", catalog=catalog, apply_remap=False
    )

    assert ident is not None
    assert ident.source == "pin"
    assert ident.catalog_id == "claude-sonnet-5"


def test_wire_id_defaults_to_the_catalog_key() -> None:
    catalog = _catalog(
        {
            "models": {
                "claude-sonnet-5": _pin(),
                "custom": _pin(wire_id="claude-custom-wire"),
            }
        }
    )

    defaulted = canonicalize("claude-sonnet-5", catalog=catalog)
    explicit = canonicalize("custom", catalog=catalog)

    assert defaulted is not None and defaulted.wire_id == "claude-sonnet-5"
    assert explicit is not None and explicit.wire_id == "claude-custom-wire"


# ---- to_picker_payload -----------------------------------------------------


def _three_row_remap_catalog() -> ModelCatalog:
    """PR fixture: live haiku gateway, opus-4.5 remap, sonnet-5→5.1 remap."""
    return _catalog(
        {
            "models": {
                "claude-haiku-4-5-20251001": _pin(
                    gateway_id="anthropic/claude-haiku-4.5",
                    picker=_picker("Haiku 4.5", "fast", "anthropic"),
                    vision=True,
                ),
                "claude-opus-5-5": _pin(
                    gateway_id="anthropic/claude-opus-5.5",
                    picker=_picker("Opus 5", "powerful", "anthropic"),
                    thinking="adaptive",
                    vision=True,
                ),
                "claude-sonnet-5-1": _pin(
                    gateway_id="anthropic/claude-sonnet-5-1",
                    role_alias="sonnet-5",
                    picker=_picker("Sonnet 5.1", "balanced", "anthropic"),
                    thinking="adaptive",
                    vision=True,
                ),
                "claude-sonnet-5": _pin(selectable=True),
            },
            "role_aliases": {"sonnet-5": {"current": "claude-sonnet-5-1"}},
            "remaps": {
                "anthropic/claude-opus-4.5": "claude-opus-5-5",
                "anthropic/claude-sonnet-5": "claude-sonnet-5-1",
            },
        }
    )


def test_three_row_remap_fixture_projects_pins_to_gateway_ids() -> None:
    catalog = _three_row_remap_catalog()
    routing = ModelRoutingConfig.model_validate(
        {
            "anthropic": {
                "everyday": "claude-sonnet-5-1",
                "powerful": "claude-opus-5-5",
            }
        }
    )

    payload = to_picker_payload(catalog, routing)
    by_id = {row.id: row for row in payload.models}

    haiku = by_id["anthropic/claude-haiku-4.5"]
    assert haiku.catalog_id == "claude-haiku-4-5-20251001"
    assert "anthropic/claude-haiku-4.5" not in payload.remaps

    assert payload.remaps["anthropic/claude-opus-4.5"] == "anthropic/claude-opus-5.5"
    assert payload.remaps["anthropic/claude-sonnet-5"] == "anthropic/claude-sonnet-5-1"
    assert payload.default_id == "anthropic/claude-sonnet-5-1"


def test_picker_membership_is_opt_in_not_every_selectable_pin() -> None:
    catalog = _catalog(
        {
            "models": {
                "shown": _pin(
                    gateway_id="anthropic/shown",
                    picker=_picker("Shown", "in picker", "anthropic"),
                ),
                "hidden-selectable": _pin(selectable=True),
                "gpt-6-astra": _pin(provider="openai", selectable=True),
            }
        }
    )

    payload = to_picker_payload(catalog, ModelRoutingConfig())

    assert [row.id for row in payload.models] == ["anthropic/shown"]
    assert "hidden-selectable" not in {row.catalog_id for row in payload.models}
    assert "gpt-6-astra" not in {row.catalog_id for row in payload.models}


def test_remap_to_a_selectable_pin_without_picker_falls_back_to_default_id() -> None:
    catalog = _catalog(
        {
            "models": {
                "everyday": _pin(
                    gateway_id="anthropic/everyday",
                    picker=_picker("Everyday", "default", "anthropic"),
                ),
                "other": _pin(selectable=True),
            },
            "remaps": {"old/cookie": "other"},
        }
    )
    routing = ModelRoutingConfig.model_validate(
        {"anthropic": {"everyday": "everyday", "powerful": "everyday"}}
    )

    payload = to_picker_payload(catalog, routing)

    assert payload.remaps["old/cookie"] == "anthropic/everyday"
    assert payload.default_id == "anthropic/everyday"


def test_committed_picker_reproduces_today_seven_chat_models() -> None:
    payload = to_picker_payload(model_config.catalog, ModelRoutingConfig())

    assert {row.id for row in payload.models} == CURRENT_PICKER_IDS
    assert "openai/gpt-6-astra" not in {row.id for row in payload.models}
    assert payload.default_id == "anthropic/claude-sonnet-5"
    thinking = next(
        row for row in payload.models if row.id.endswith("-thinking")
    )
    assert thinking.provider == "reasoning"
    assert thinking.catalog_id == "claude-sonnet-4-5-20250929"


def test_committed_remaps_match_retired_model_map_pins() -> None:
    catalog = model_config.catalog
    for raw, pin in RETIRED_REMAPS.items():
        assert catalog.remaps[raw] == pin
        ident = canonicalize(raw, catalog=catalog)
        assert ident is not None
        assert ident.catalog_id == pin
        assert ident.source == "remap"


def test_legacy_llm_aliases_stay_pin_valued() -> None:
    assert model_config.catalog.aliases["llm"]["claude_sonnet"] == "claude-sonnet-5"
    assert model_config.catalog.aliases["llm"]["claude_opus"] == "claude-opus-5-5"
    assert (
        model_config.catalog.aliases["llm"]["claude_haiku"]
        == "claude-haiku-4-5-20251001"
    )


def test_canonicalize_on_committed_catalog_live_gateway_ids() -> None:
    catalog = model_config.catalog

    sonnet = canonicalize("anthropic/claude-sonnet-5", catalog=catalog)
    haiku = canonicalize("anthropic/claude-haiku-4.5", catalog=catalog)
    thinking = canonicalize(
        "anthropic/claude-sonnet-4.5-thinking", catalog=catalog
    )

    assert sonnet is not None and sonnet.catalog_id == "claude-sonnet-5"
    assert haiku is not None and haiku.catalog_id == "claude-haiku-4-5-20251001"
    assert thinking is not None and thinking.catalog_id == "claude-sonnet-4-5-20250929"
    assert isinstance(sonnet, ModelIdentity)


# ---- anthropic wire_id pass-through ----------------------------------------


def test_anthropic_create_llm_sends_wire_id_when_set(monkeypatch) -> None:
    from neos.config.model_config import ThinkingContract
    from neos.providers.anthropic import AnthropicProvider

    catalog = _catalog(
        {
            "models": {
                "claude-custom": _pin(
                    thinking="none", wire_id="claude-custom-wire"
                )
            }
        }
    )
    monkeypatch.setattr(
        "neos.providers.anthropic.get_model_spec",
        catalog.get_model_spec,
    )
    monkeypatch.setattr(
        "neos.providers.anthropic.thinking_contract",
        lambda model: ThinkingContract.NONE,
    )
    monkeypatch.setattr(
        "neos.providers.anthropic.settings",
        SimpleNamespace(
            ANTHROPIC_API_KEY="test-key",
            LLM_TIMEOUT=30,
            THINKING_BLOCKS_ENABLED=False,
            MAX_THINKING_LENGTH=0,
        ),
    )
    provider = AnthropicProvider.__new__(AnthropicProvider)

    with patch("neos.providers.anthropic.ChatAnthropic") as chat_anthropic:
        provider.create_llm(
            model="claude-custom", temperature=0.3, max_tokens=1024
        )

    assert chat_anthropic.call_args.kwargs["model"] == "claude-custom-wire"


def test_anthropic_create_llm_sends_model_when_wire_id_unset(monkeypatch) -> None:
    from neos.config.model_config import ThinkingContract
    from neos.providers.anthropic import AnthropicProvider

    monkeypatch.setattr(
        "neos.providers.anthropic.settings",
        SimpleNamespace(
            ANTHROPIC_API_KEY="test-key",
            LLM_TIMEOUT=30,
            THINKING_BLOCKS_ENABLED=False,
            MAX_THINKING_LENGTH=0,
        ),
    )
    monkeypatch.setattr(
        "neos.providers.anthropic.thinking_contract",
        lambda model: ThinkingContract.NONE,
    )
    provider = AnthropicProvider.__new__(AnthropicProvider)

    with patch("neos.providers.anthropic.ChatAnthropic") as chat_anthropic:
        provider.create_llm(
            model="claude-not-in-catalog",
            temperature=0.3,
            max_tokens=1024,
        )

    assert chat_anthropic.call_args.kwargs["model"] == "claude-not-in-catalog"


# ---- catalog metrics -------------------------------------------------------


def _resolve_count(source: str) -> float:
    from neos.observability.metrics import get_metrics_collector

    return get_metrics_collector().catalog_resolve_total.labels(
        source=source
    )._value.get()


def _remap_count() -> float:
    from neos.observability.metrics import get_metrics_collector

    return get_metrics_collector().catalog_remap_total._value.get()


def test_canonicalize_increments_resolve_total_by_source_only() -> None:
    catalog = _catalog(
        {
            "models": {
                "claude-sonnet-5": _pin(
                    role_alias="sonnet-5",
                    gateway_id="anthropic/claude-sonnet-5",
                    id_forms=["claude-sonnet"],
                )
            },
            "role_aliases": {"sonnet-5": {"current": "claude-sonnet-5"}},
            "remaps": {"old/cookie": "claude-sonnet-5"},
        }
    )

    cases = [
        ("sonnet-5", "role_alias"),
        ("claude-sonnet-5", "pin"),
        ("old/cookie", "remap"),
        ("anthropic/claude-sonnet-5", "gateway"),
        ("claude-sonnet", "id_form"),
        ("not-a-model", "unknown"),
    ]
    for raw, source in cases:
        before = _resolve_count(source)
        canonicalize(raw, catalog=catalog)
        assert _resolve_count(source) == before + 1

    sample = (
        __import__("neos.observability.metrics", fromlist=["get_metrics_collector"])
        .get_metrics_collector()
        .catalog_resolve_total.collect()[0]
    )
    for metric in sample.samples:
        assert "id" not in metric.labels
        assert set(metric.labels) <= {"source"}


def test_remap_total_increments_without_raw_id_label() -> None:
    catalog = _catalog(
        {
            "models": {"claude-opus-5-5": _pin()},
            "remaps": {"anthropic/claude-opus-4.5": "claude-opus-5-5"},
        }
    )

    before = _remap_count()
    canonicalize("anthropic/claude-opus-4.5", catalog=catalog)
    canonicalize("claude-opus-5-5", catalog=catalog)
    after = _remap_count()

    assert after == before + 1
    sample = (
        __import__("neos.observability.metrics", fromlist=["get_metrics_collector"])
        .get_metrics_collector()
        .catalog_remap_total.collect()[0]
    )
    for metric in sample.samples:
        assert "id" not in metric.labels


@pytest.mark.parametrize("old, successor", sorted(RETIRED_PINS.items()))
def test_retired_pins_resolve_to_their_successor_from_every_source(
    old: str, successor: str
) -> None:
    """저장된 대화 핀도 후계로 간다 -- remaps 는 거기에 걸리지 않는다.

    안 걸면 `claude-opus-5` 는 미등록 모델이 되어 BUDGETED 계약으로
    `budget_tokens` 를 보내고, Opus 5 는 그것을 400 으로 거절한다.
    """
    from neos.config.model_routing import ResolutionSource, resolve_model
    from neos.config.schema import ModelRoutingConfig

    catalog = model_config.catalog
    assert old not in catalog.models
    assert old not in catalog.remaps
    for apply_remap in (True, False):
        ident = canonicalize(old, catalog=catalog, apply_remap=apply_remap)
        assert ident is not None and ident.catalog_id == successor
        assert ident.source == "retired"

    provider = catalog.models[successor].provider
    resolved = resolve_model(
        config=ModelRoutingConfig(),
        provider=provider,
        role="everyday",
        conversation_model=old,
    )
    assert resolved.source is ResolutionSource.CONVERSATION
    assert resolved.model == successor
    assert model_config.catalog.thinking_contract(old) is (
        catalog.models[successor].thinking
    )


def test_retired_rejects_a_live_key_or_an_unknown_target() -> None:
    base = {
        "models": {"m-new": {"provider": "anthropic"}},
    }
    with pytest.raises(ValueError, match="still a live catalog key"):
        _catalog({**base, "retired": {"m-new": "m-new"}})
    with pytest.raises(ValueError, match="unknown model"):
        _catalog({**base, "retired": {"m-old": "m-gone"}})


def test_picker_rows_carry_effort_levels_and_the_model_default() -> None:
    from neos.config.model_config import effort_levels_for

    routing = ModelRoutingConfig()
    pin = next(
        name for name in ("claude-opus-5-5", "gpt-6-sol") if effort_levels_for(name)
    )
    level = effort_levels_for(pin)[0]
    routing.effort.models = {pin: level}

    payload = to_picker_payload(model_config.catalog, routing)
    row = next(r for r in payload.models if r.catalog_id == pin)

    assert row.effort_levels == effort_levels_for(pin)
    assert row.effort_default == level
    others = [r for r in payload.models if r.catalog_id != pin]
    assert all(r.effort_default is None for r in others)
