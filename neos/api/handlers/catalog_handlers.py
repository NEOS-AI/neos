"""Catalog picker API — GET /models."""

from __future__ import annotations

import hashlib
import json

from fastapi import APIRouter, Depends, HTTPException, Response

from neos.api.dependencies.auth import get_current_active_user
from neos.api.models.catalog_models import CatalogModelOut, CatalogResponse
from neos.config.model_config import ModelCatalog, _catalog_path, model_config
from neos.config.model_identity import to_picker_payload
from neos.config.schema import ModelRoutingConfig
from neos.config.settings import settings
from neos.database.models import User

router = APIRouter()

_CACHE_CONTROL = "private, max-age=60"


def _yaml_identity() -> str:
    path = _catalog_path()
    try:
        stat = path.stat()
    except OSError:
        return "missing"
    return f"{path}:{stat.st_mtime_ns}:{stat.st_size}"


def _payload_etag(
    catalog: ModelCatalog,
    routing: ModelRoutingConfig,
    yaml_identity: str,
) -> str:
    hasher = hashlib.sha256()
    hasher.update(yaml_identity.encode())
    hasher.update(routing.model_dump_json().encode())
    currents = {name: alias.current for name, alias in catalog.role_aliases.items()}
    hasher.update(json.dumps(currents, sort_keys=True).encode())
    return hasher.hexdigest()


@router.get("/models", response_model=CatalogResponse)
async def get_catalog_models(
    response: Response,
    current_user: User = Depends(get_current_active_user),
) -> CatalogResponse:
    if not settings.config.model_catalog.picker_api:
        raise HTTPException(status_code=404, detail="Not Found")

    catalog = model_config.catalog
    if not catalog.models:
        raise HTTPException(status_code=503, detail="Model catalog is empty")

    routing = settings.config.model_routing
    payload = to_picker_payload(catalog, routing)
    etag = _payload_etag(catalog, routing, _yaml_identity())
    response.headers["ETag"] = f'"{etag}"'
    response.headers["Cache-Control"] = _CACHE_CONTROL
    return CatalogResponse(
        version=payload.version,
        etag=etag,
        default_id=payload.default_id,
        models=[
            CatalogModelOut.model_validate(row, from_attributes=True)
            for row in payload.models
        ],
        remaps=payload.remaps,
    )
