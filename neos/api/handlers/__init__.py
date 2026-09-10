"""API handlers package - thin layer for FastAPI routes.

Routers are loaded lazily so importing one handler module does not import
unrelated optional dependencies.
"""

from importlib import import_module

_ROUTER_EXPORTS = {
    "query_router": "neos.api.handlers.query_handlers",
    "document_router": "neos.api.handlers.document_handlers",
    "analytics_router": "neos.api.handlers.analytics_handlers",
}

__all__ = [
    "query_router",
    "document_router",
    "analytics_router",
]


def __getattr__(name: str):
    if name not in _ROUTER_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = import_module(_ROUTER_EXPORTS[name])
    router = module.router
    globals()[name] = router
    return router
