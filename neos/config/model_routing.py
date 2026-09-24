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


@dataclass(frozen=True, slots=True)
class EffortResolution:
    """해석된 사고량. `effort is None` 이면 **아무것도 보내지 않는다.**

    `source` 는 값이 어디서 왔는가다 -- 거절됐을 때도 채워진다. user 가 적은
    것이 틀렸는지 역할 기본값이 틀렸는지 갈려야 고칠 곳을 안다.

    `refused` 는 왜 None 인가다. 비어 있으면 아무도 값을 정하지 않은 것이고,
    그 경우와 "정했는데 못 쓴다" 는 다른 사건이다 -- 조용히 떨어뜨리면
    운영자가 `high` 를 적고도 아무 일이 없는 이유를 알 수 없다.
    """

    effort: str | None
    source: ResolutionSource | None = None
    refused: str = ""
    detail: str = ""


def resolve_effort(
    *,
    model: str,
    role: WorkloadRole,
    supported_levels: tuple[str, ...],
    user_effort: str | None = None,
    conversation_effort: str | None = None,
    feature_override: str | None = None,
    role_default: str | None = None,
) -> EffortResolution:
    """`resolve_model` 과 **같은 사슬**로 사고량을 정한다 (로드맵 K5).

    우선순위도 `ResolutionSource` 어휘도 모델 쪽 것을 그대로 쓴다 -- 따로
    사슬을 만들면 "고침은 한 호출부에만" 이 재발한다.

    모델에 없는 단계가 하나 더 있다: **그 모델이 그 레벨을 받는가.** 안 받으면
    보내지 않는다. 가장 가까운 레벨로 낮춰 보내지도 않는다 -- 그러면 운영자가
    적은 것과 실제로 돈 것이 달라지고 그 차이는 어디에도 남지 않는다.

    `supported_levels` 를 인자로 받는 이유는 카탈로그를 두 번 읽지 않기
    위해서다. 부르는 쪽이 이미 모델을 해석했고, 같은 자리에서
    `effort_levels_for(model)` 을 읽어 넘긴다.
    """
    del role  # 우선순위에 쓰이지 않는다. 역할 기본값은 부르는 쪽이 이미 골랐다.

    for value, source in (
        (user_effort, ResolutionSource.USER),
        (conversation_effort, ResolutionSource.CONVERSATION),
        (feature_override, ResolutionSource.FEATURE_OVERRIDE),
        (role_default, ResolutionSource.ROLE_DEFAULT),
    ):
        if not value:
            continue
        return _gate_effort(value, source, model, supported_levels)

    # 아무도 정하지 않았다. **K5 의 기본 상태**이고, 이것이 필드를 넣는
    # 커밋을 표본 경계가 아니게 만든다(로드맵 §경계 10).
    return EffortResolution(effort=None)


def _gate_effort(
    value: str,
    source: ResolutionSource,
    model: str,
    supported_levels: tuple[str, ...],
) -> EffortResolution:
    from neos.config.model_config import ALL_EFFORT_LEVELS

    if value not in ALL_EFFORT_LEVELS:
        # 설정 검증을 우회해 들어온 값(DB 의 옛 행, 쿠키)도 여기서 걸린다.
        return EffortResolution(
            effort=None,
            source=source,
            refused="unknown_level",
            detail=f"{value!r} is not one of {list(ALL_EFFORT_LEVELS)}",
        )
    if not supported_levels:
        return EffortResolution(
            effort=None,
            source=source,
            refused="model_declares_no_effort",
            detail=f"{model} declares no effort levels",
        )
    if value not in supported_levels:
        return EffortResolution(
            effort=None,
            source=source,
            refused="level_not_supported",
            detail=f"{model} takes {list(supported_levels)}, not {value!r}",
        )
    return EffortResolution(effort=value, source=source)
