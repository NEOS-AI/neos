from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Literal, cast

if TYPE_CHECKING:
    from neos.config.schema import ModelRoutingConfig


ModelProvider = Literal["anthropic", "openai"]
WorkloadRole = Literal["everyday", "powerful"]


class ResolutionSource(str, Enum):
    USER = "user"
    CONVERSATION = "conversation"
    FEATURE_OVERRIDE = "feature_override"
    ROLE_DEFAULT = "role_default"


@dataclass(frozen=True, slots=True)
class ModelResolution:
    model: str
    provider: ModelProvider
    role: WorkloadRole
    source: ResolutionSource
    role_alias: str | None = None


def _canonicalize_pick(
    picked: str, source: ResolutionSource
) -> tuple[str, str | None]:
    """Turn a role alias (or known pin) into the catalog pin.

    Remaps apply only to user/cookie strings. Conversation rows and feature
    pins stay as stored so a remap of a gateway id cannot rewrite a pin that
    happens to share a spelling. Unknown values pass through — the catalog
    is not an allowlist, and we do not fall back to a hardcoded dated id.
    """
    from neos.config.model_config import model_config
    from neos.config.model_identity import canonicalize

    ident = canonicalize(
        picked,
        catalog=model_config.catalog,
        apply_remap=source is ResolutionSource.USER,
    )
    if ident is None:
        return picked, None
    return ident.catalog_id, ident.role_alias


def resolve_model(
    *,
    config: ModelRoutingConfig,
    provider: ModelProvider,
    role: WorkloadRole,
    user_model: str | None = None,
    conversation_model: str | None = None,
    feature_override: str | None = None,
) -> ModelResolution:
    if provider not in {"anthropic", "openai"}:
        raise ValueError(f"Unknown model provider: {provider}")
    if role not in {"everyday", "powerful"}:
        raise ValueError(f"Unknown model role: {role}")

    for model, source in (
        (user_model, ResolutionSource.USER),
        (conversation_model, ResolutionSource.CONVERSATION),
        (feature_override, ResolutionSource.FEATURE_OVERRIDE),
    ):
        if model:
            pin, role_alias = _canonicalize_pick(model, source)
            return ModelResolution(
                model=pin,
                provider=cast(ModelProvider, provider),
                role=cast(WorkloadRole, role),
                source=source,
                role_alias=role_alias,
            )

    provider_mapping = getattr(config, provider)
    try:
        model = getattr(provider_mapping, role)
    except AttributeError as exc:
        raise ValueError(
            f"Incomplete model routing mapping for provider: {provider}"
        ) from exc
    if not model:
        raise ValueError(f"Incomplete model routing mapping for provider: {provider}")
    pin, role_alias = _canonicalize_pick(model, ResolutionSource.ROLE_DEFAULT)
    return ModelResolution(
        model=pin,
        provider=cast(ModelProvider, provider),
        role=cast(WorkloadRole, role),
        source=ResolutionSource.ROLE_DEFAULT,
        role_alias=role_alias,
    )
