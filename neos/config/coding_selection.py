from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from neos.config.model_config import (
    get_model_spec,
    model_config,
    models_for_provider,
)
from neos.config.model_routing import resolve_model

if TYPE_CHECKING:
    from neos.config.schema import AppConfig, CodingModelConfig, ModelRoutingConfig

CODING_PROVIDERS = frozenset({"anthropic", "openai", "gemini", "ollama"})
_ROLE_ROUTED_PROVIDERS = frozenset({"anthropic", "openai"})


@dataclass(frozen=True, slots=True)
class CodingModelSelection:
    provider: str
    model: str
    source: str


def resolve_coding_selection(
    *,
    coding: "CodingModelConfig",
    routing: "ModelRoutingConfig",
) -> CodingModelSelection:
    """Pick the vendor + model the coding loop should talk to.

    The model catalog owns vendor identity. An explicit `coding.model` that
    is in the catalog wins over `coding.provider`, so `gpt-6-astra` cannot
    be silently sent to Anthropic because a YAML default still says so.
    Unknown model names keep the configured provider so new IDs work
    before the catalog is updated.
    """
    if coding.provider not in CODING_PROVIDERS:
        raise ValueError(f"Unknown coding model provider: {coding.provider}")

    if coding.model:
        spec = get_model_spec(coding.model)
        if spec is not None:
            return CodingModelSelection(
                provider=spec.provider,
                model=coding.model,
                source="catalog",
            )
        return CodingModelSelection(
            provider=coding.provider,
            model=coding.model,
            source="feature_override",
        )

    if coding.provider in _ROLE_ROUTED_PROVIDERS:
        resolved = resolve_model(
            config=routing,
            provider=coding.provider,  # type: ignore[arg-type]
            role="everyday",
        )
        return CodingModelSelection(
            provider=resolved.provider,
            model=resolved.model,
            source="role_default",
        )

    model = _default_model_for_provider(coding.provider)
    if not model:
        raise ValueError(
            f"coding loop has no default model for provider {coding.provider!r}"
        )
    return CodingModelSelection(
        provider=coding.provider,
        model=model,
        source="provider_default",
    )


def _default_model_for_provider(provider: str) -> str | None:
    selectable = models_for_provider(provider)
    if selectable:
        return selectable[0]
    for name, spec in model_config.catalog.models.items():
        if spec.provider == provider:
            return name
    return None


def resolve_coding_selection_from_app(config: "AppConfig") -> CodingModelSelection:
    return resolve_coding_selection(
        coding=config.coding_model,
        routing=config.model_routing,
    )


def coding_credential_for(config: "AppConfig", provider: str) -> str | None:
    secrets = config.secrets
    if provider == "anthropic":
        return secrets.anthropic_api_key
    if provider == "openai":
        return secrets.openai_api_key
    if provider == "gemini":
        return secrets.google_api_key
    if provider == "ollama":
        return "local"
    return None
