from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from neos.config.model_config import (
    model_config,
    models_for_provider,
)
from neos.config.model_identity import canonicalize
from neos.config.model_routing import resolve_model

if TYPE_CHECKING:
    from neos.config.model_routing import EffortResolution
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
        ident = canonicalize(
            coding.model, catalog=model_config.catalog, apply_remap=False
        )
        if ident is not None:
            return CodingModelSelection(
                provider=ident.provider,
                model=ident.catalog_id,
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


def resolve_coding_effort(
    *,
    coding: "CodingModelConfig",
    routing: "ModelRoutingConfig",
    selection: CodingModelSelection,
) -> "EffortResolution":
    """코딩 루프가 실제로 보내는 사고량 (로드맵 K5 ④).

    DA 의 `resolve_harness_effort` 와 **같은 사슬**이다 -- feature override
    (`coding_model.effort`) → 모델별 기본값(`model_routing.effort.models`) →
    역할 기본값. 역할은 `everyday` 다: 모델을 고를 때 코딩이 타는 역할과
    같아야 한다(`resolve_coding_selection`).

    ⚠️ 그래서 운영자가 `model_routing.effort.models` 나 `everyday` 에 값을
    적으면 채팅·DA 와 **함께** 코딩에도 걸린다. 한 모델에 한 기본값이라는
    뜻이고, 그 값을 바꾸는 커밋은 코딩 에이전트 지표의 경계이기도 하다.
    """
    from neos.config.model_config import effort_levels_for
    from neos.config.model_routing import resolve_effort

    return resolve_effort(
        model=selection.model,
        role="everyday",
        supported_levels=effort_levels_for(selection.model),
        feature_override=coding.effort,
        model_default=routing.effort.models.get(selection.model),
        role_default=routing.effort.everyday,
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
        base_url = (config.model_providers.ollama.base_url or "").strip()
        return base_url or None
    return None
