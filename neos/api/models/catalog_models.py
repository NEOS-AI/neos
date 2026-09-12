"""GET /api/v1/models picker payload."""

from typing import Literal

from pydantic import BaseModel


class CatalogModelOut(BaseModel):
    id: str
    catalog_id: str
    name: str
    provider: str
    description: str
    thinking: Literal["adaptive", "budgeted", "none"]
    vision: bool
    role_alias: str | None
    default: bool


class CatalogResponse(BaseModel):
    version: int
    etag: str
    default_id: str
    models: list[CatalogModelOut]
    remaps: dict[str, str]
