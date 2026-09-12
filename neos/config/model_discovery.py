"""Optional live Anthropic id overlay.

Default off (`model_catalog.live_anthropic`). When off there is no network
and the overlay is empty. When on, only ids are merged: YAML wins, and
live-only ids are never selectable or picker-visible.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from neos.config.model_config import ModelCatalog, ModelSpec

logger = logging.getLogger(__name__)

_ANTHROPIC_MODELS_URL = "https://api.anthropic.com/v1/models"
_ANTHROPIC_VERSION = "2023-06-01"

_overlay: frozenset[str] = frozenset()


def reset_overlay() -> None:
    """Test helper. Production callers use refresh_live_overlay()."""
    global _overlay
    _overlay = frozenset()


def current_overlay() -> frozenset[str]:
    return _overlay


def live_model_spec(model: str) -> ModelSpec | None:
    """Synthetic spec for a live-only id. YAML pins are never returned here."""
    if model not in _overlay:
        return None
    from neos.config.model_config import ModelSpec

    return ModelSpec(provider="anthropic", selectable=False)


def refresh_live_overlay(
    catalog: ModelCatalog,
    *,
    enabled: bool,
    api_key: str | None,
    fetch_ids: Callable[[], Iterable[str]] | None = None,
) -> frozenset[str]:
    """Refresh the in-memory overlay.

    * flag off → no network, overlay emptied
    * auth empty / transient error → keep last overlay (empty on first fail)
    * success → overlay = live ids not already in YAML
    """
    global _overlay
    if not enabled:
        _overlay = frozenset()
        return _overlay
    if not api_key:
        return _overlay

    fetcher = fetch_ids if fetch_ids is not None else lambda: _fetch_anthropic_ids(api_key)
    try:
        live = [str(item) for item in fetcher() if item]
    except Exception:
        logger.warning("live Anthropic catalog fetch failed; keeping last overlay")
        return _overlay

    unknown = frozenset(mid for mid in live if mid not in catalog.models)
    _overlay = unknown
    _record_live_unknown(len(unknown))
    return _overlay


def sync_live_overlay(catalog: ModelCatalog) -> frozenset[str]:
    """Apply the process flag + key. No network when the flag is off."""
    from neos.config.settings import settings

    return refresh_live_overlay(
        catalog,
        enabled=settings.config.model_catalog.live_anthropic,
        api_key=getattr(settings, "ANTHROPIC_API_KEY", None),
    )


def _fetch_anthropic_ids(api_key: str) -> list[str]:
    import httpx

    from neos.utils.anthropic_client import anthropic_default_headers

    headers = {
        "x-api-key": api_key,
        "anthropic-version": _ANTHROPIC_VERSION,
        **anthropic_default_headers(),
    }
    response = httpx.get(_ANTHROPIC_MODELS_URL, headers=headers, timeout=10.0)
    response.raise_for_status()
    payload = response.json()
    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []
    ids: list[str] = []
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get("id"), str):
            ids.append(row["id"])
    return ids


def _record_live_unknown(count: int) -> None:
    if count <= 0:
        return
    try:
        from neos.observability.metrics import get_metrics_collector

        get_metrics_collector().catalog_live_unknown_total.inc(count)
    except Exception:
        logger.debug("catalog live-unknown metric increment failed", exc_info=True)
