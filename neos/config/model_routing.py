from __future__ import annotations

import re
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


_CLAUDE_5_MODEL = re.compile(r"^claude-(?:[a-z0-9]+-)*5(?:-|$)")


def is_claude_5(model: str) -> bool:
    return bool(_CLAUDE_5_MODEL.match(model))


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
            return ModelResolution(
                model=model,
                provider=cast(ModelProvider, provider),
                role=cast(WorkloadRole, role),
                source=source,
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
    return ModelResolution(
        model=model,
        provider=cast(ModelProvider, provider),
        role=cast(WorkloadRole, role),
        source=ResolutionSource.ROLE_DEFAULT,
    )
