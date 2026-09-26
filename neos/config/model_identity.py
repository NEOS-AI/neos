"""Catalog identity resolution.

No I/O. `canonicalize` is the only spelling/remap/alias hop. Remap values
are catalog pins; picker payload remaps project those pins to gateway_ids.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from neos.config.model_config import ModelCatalog, ModelSpec
    from neos.config.schema import ModelRoutingConfig

_KNOWN_PREFIXES = frozenset({"anthropic", "openai", "google", "gemini", "xai"})
_MAX_REMAP_HOPS = 4
RESERVED_WINDOW_CAP = 20_000

IdentitySource = Literal["role_alias", "pin", "remap", "gateway", "id_form", "retired"]


def reserved_tokens(window: int) -> int:
    """Hooks/lessons/instructions must not eat the usable window."""
    if window <= 0:
        return 0
    return min(RESERVED_WINDOW_CAP, window // 10)


def usable_window_tokens(
    *,
    context_window: int | None,
    max_output_tokens: int,
    input_limit: int | None = None,
    thinking_budget: int = 0,
) -> int | None:
    """usable = (input_limit ?? window − max_out) − reserved − thinking.

    Unknown models (no window and no input_limit) return None so callers
    keep request shaping and fall back to the 80k compact constant.
    """
    if input_limit is not None:
        raw = input_limit
        window = context_window if context_window is not None else input_limit
    elif context_window is not None:
        raw = context_window - max_output_tokens
        window = context_window
    else:
        return None
    return max(0, raw - reserved_tokens(window) - max(0, thinking_budget))


@dataclass(frozen=True, slots=True)
class CatalogWindow:
    context_window: int | None
    input_limit: int | None
    thinking_budget: int
    usable: int | None


def catalog_window_for(
    raw: str,
    *,
    catalog: ModelCatalog,
    max_output_tokens: int,
) -> CatalogWindow:
    """Resolve a catalog pin to window fields. Unknown models stay empty."""
    ident = canonicalize(raw, catalog=catalog, apply_remap=False)
    if ident is None:
        return CatalogWindow(None, None, 0, None)
    spec = catalog.models.get(ident.catalog_id)
    if spec is None:
        return CatalogWindow(None, None, 0, None)
    budgets = spec.thinking_budgets or {}
    thinking = int(budgets.get("default") or 0)
    usable = usable_window_tokens(
        context_window=spec.context_window,
        max_output_tokens=max_output_tokens,
        input_limit=spec.input_limit,
        thinking_budget=thinking,
    )
    return CatalogWindow(
        context_window=spec.context_window,
        input_limit=spec.input_limit,
        thinking_budget=thinking,
        usable=usable,
    )


def usable_window_for(
    raw: str,
    *,
    catalog: ModelCatalog,
    max_output_tokens: int,
) -> int | None:
    return catalog_window_for(
        raw, catalog=catalog, max_output_tokens=max_output_tokens
    ).usable


class RemapCycleError(ValueError):
    """A remaps: chain looped or exceeded the hop cap."""


class AmbiguousModelError(ValueError):
    """Reserved. v1 load uniqueness makes this unreachable at resolve time."""


@dataclass(frozen=True, slots=True)
class ModelIdentity:
    catalog_id: str
    provider: str
    role_alias: str | None
    wire_id: str
    gateway_id: str | None
    source: IdentitySource


@dataclass(frozen=True, slots=True)
class PickerModel:
    id: str
    catalog_id: str
    name: str
    provider: str
    description: str
    thinking: str
    vision: bool
    role_alias: str | None
    default: bool
    # 이 모델이 받는 사고량 레벨(카탈로그)과 설정의 모델별 기본값. 프론트는
    # 어떤 모델이 어떤 레벨을 받는지 하드코딩하지 않고 이것을 읽는다.
    effort_levels: tuple[str, ...] = ()
    effort_default: str | None = None


@dataclass(frozen=True, slots=True)
class PickerPayload:
    version: int
    default_id: str
    models: list[PickerModel]
    remaps: dict[str, str]


def catalog_shaped(raw: str) -> str:
    """Strip a known provider/ prefix, then '.' → '-'. Never invents a date."""
    s = raw.strip()
    if "/" in s:
        prefix, rest = s.split("/", 1)
        if prefix in _KNOWN_PREFIXES and rest:
            s = rest
    return s.replace(".", "-")


def _identity_from_pin(
    catalog: ModelCatalog, pin: str, source: IdentitySource
) -> ModelIdentity:
    spec = catalog.models[pin]
    return ModelIdentity(
        catalog_id=pin,
        provider=spec.provider,
        role_alias=spec.role_alias,
        wire_id=spec.wire_id or pin,
        gateway_id=spec.gateway_id,
        source=source,
    )


def _lookup_surfaces(catalog: ModelCatalog) -> tuple[dict[str, str], dict[str, str]]:
    """gateway_id / extras gateway_id → pin, id_forms → pin."""
    by_gateway: dict[str, str] = {}
    by_id_form: dict[str, str] = {}
    for name, spec in catalog.models.items():
        if spec.gateway_id:
            by_gateway[spec.gateway_id] = name
        if spec.picker is not None:
            for extra in spec.picker.extras:
                if extra.gateway_id:
                    by_gateway[extra.gateway_id] = name
        for form in spec.id_forms:
            by_id_form[form] = name
    return by_gateway, by_id_form


def _resolve_declared(
    current: str,
    catalog: ModelCatalog,
    by_gateway: dict[str, str],
    by_id_form: dict[str, str],
) -> ModelIdentity | None:
    if current in catalog.role_aliases:
        pin = catalog.role_aliases[current].current
        if pin not in catalog.models:
            return None
        return _identity_from_pin(catalog, pin, "role_alias")
    if current in catalog.models:
        return _identity_from_pin(catalog, current, "pin")
    if current in by_gateway:
        return _identity_from_pin(catalog, by_gateway[current], "gateway")
    if current in by_id_form:
        return _identity_from_pin(catalog, by_id_form[current], "id_form")
    return None


def _record_catalog_metrics(source: IdentitySource | None, *, remapped: bool) -> None:
    """Cardinality-safe: source label only, never a raw id."""
    try:
        from neos.observability.metrics import get_metrics_collector

        collector = get_metrics_collector()
        collector.catalog_resolve_total.labels(
            source=source or "unknown"
        ).inc()
        if remapped:
            collector.catalog_remap_total.inc()
    except Exception:
        return


def canonicalize(
    raw: str,
    *,
    catalog: ModelCatalog,
    apply_remap: bool = True,
) -> ModelIdentity | None:
    """Return identity or None (unknown).

    v1 resolves only declared surfaces. Undeclared short names (sonnet, opus)
    return None — they are not guessed and not treated as 'latest'.
    """
    if not isinstance(raw, str) or not raw.strip():
        return None

    current = raw.strip()
    successor = catalog.retired.get(current)
    if successor is not None:
        # 은퇴는 출처를 가리지 않는다 (apply_remap 과 무관).
        ident = _identity_from_pin(catalog, successor, "retired")
        _record_catalog_metrics(ident.source, remapped=True)
        return ident
    seen: list[str] = []
    if apply_remap:
        while current in catalog.remaps:
            if current in seen or len(seen) >= _MAX_REMAP_HOPS:
                _record_catalog_metrics("remap", remapped=True)
                raise RemapCycleError(
                    f"remap cycle involving {current!r} (seen {seen})"
                )
            seen.append(current)
            current = catalog.remaps[current]
        if seen:
            if current not in catalog.models:
                _record_catalog_metrics(None, remapped=True)
                return None
            ident = _identity_from_pin(catalog, current, "remap")
            _record_catalog_metrics(ident.source, remapped=True)
            return ident

    by_gateway, by_id_form = _lookup_surfaces(catalog)
    hit = _resolve_declared(current, catalog, by_gateway, by_id_form)
    if hit is not None:
        _record_catalog_metrics(hit.source, remapped=False)
        return hit

    # Spelling-only retry, once. Turns anthropic/claude-sonnet-5 into the
    # pin key when that key already exists. Does not turn
    # anthropic/claude-haiku-4.5 into claude-haiku-4-5-20251001.
    spelled = catalog_shaped(current)
    if spelled != current:
        hit = _resolve_declared(spelled, catalog, by_gateway, by_id_form)
        _record_catalog_metrics(hit.source if hit else None, remapped=False)
        return hit
    _record_catalog_metrics(None, remapped=False)
    return None


def to_picker_payload(
    catalog: ModelCatalog,
    routing: ModelRoutingConfig | None = None,
) -> PickerPayload:
    """Project picker: rows and remaps (raw → pin.gateway_id)."""
    if routing is None:
        from neos.config.schema import ModelRoutingConfig

        routing = ModelRoutingConfig()

    everyday = canonicalize(
        routing.anthropic.everyday, catalog=catalog, apply_remap=False
    )
    default_pin = everyday.catalog_id if everyday is not None else None
    default_id = ""
    if everyday is not None and everyday.gateway_id:
        default_id = everyday.gateway_id

    rows: list[PickerModel] = []
    visible_ids: set[str] = set()
    for name, spec in catalog.models.items():
        if spec.picker is None or not spec.gateway_id:
            continue
        primary = _picker_row(
            spec,
            catalog_id=name,
            gateway_id=spec.gateway_id,
            name=spec.picker.name,
            description=spec.picker.description,
            group=spec.picker.group,
            default=name == default_pin,
            effort_default=routing.effort.models.get(name),
        )
        rows.append(primary)
        visible_ids.add(primary.id)
        for extra in spec.picker.extras:
            if not extra.gateway_id:
                continue
            extra_row = _picker_row(
                spec,
                catalog_id=name,
                gateway_id=extra.gateway_id,
                name=extra.name,
                description=extra.description,
                group=extra.group,
                default=False,
                effort_default=routing.effort.models.get(name),
            )
            rows.append(extra_row)
            visible_ids.add(extra_row.id)

    projected: dict[str, str] = {}
    for raw, pin in catalog.remaps.items():
        spec = catalog.models.get(pin)
        target = spec.gateway_id if spec is not None else None
        if target and target in visible_ids:
            projected[raw] = target
        else:
            projected[raw] = default_id

    return PickerPayload(
        version=1,
        default_id=default_id,
        models=rows,
        remaps=projected,
    )


def _picker_row(
    spec: ModelSpec,
    *,
    catalog_id: str,
    gateway_id: str,
    name: str,
    description: str,
    group: str,
    default: bool,
    effort_default: str | None = None,
) -> PickerModel:
    return PickerModel(
        id=gateway_id,
        catalog_id=catalog_id,
        name=name,
        provider=group,
        description=description,
        thinking=spec.thinking.value,
        vision=spec.vision,
        role_alias=spec.role_alias,
        default=default,
        effort_levels=tuple(spec.effort_levels),
        effort_default=effort_default,
    )
