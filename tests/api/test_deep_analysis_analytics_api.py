"""Smoke tests for the deep_analysis analytics endpoint (L5)."""

import pytest

pytestmark = pytest.mark.no_db


def test_analytics_route_defined_on_router():
    from neos.api.handlers.deep_analysis_analytics_handlers import router

    paths = {getattr(r, "path", "") for r in router.routes}
    assert "/deep-analysis/analytics" in paths


def test_analytics_router_included_in_main():
    # main.py imports and registers the router (line ~536); importing main
    # must not raise and the include call must reference our router.
    import neos.main as main_mod
    from neos.api.handlers.deep_analysis_analytics_handlers import (
        router as analytics_router,
    )

    assert main_mod.deep_analysis_analytics_router is analytics_router


def test_analytics_handler_period_mapping():
    from neos.api.handlers.deep_analysis_analytics_handlers import _PERIOD_DAYS

    assert _PERIOD_DAYS["day"] == 1
    assert _PERIOD_DAYS["week"] == 7
    assert _PERIOD_DAYS["month"] == 30
    assert _PERIOD_DAYS["all"] is None
