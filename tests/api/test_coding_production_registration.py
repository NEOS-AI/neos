from pathlib import Path

from neos.coding.runtime import (
    coding_runtime,
    create_development_coding_runtime,
)
from neos.coding.workers.development_supervisor import (
    CodingDevelopmentSupervisor,
)
from neos.config.settings import settings


def test_coding_websocket_bypasses_generic_production_filter() -> None:
    source = Path("neos/main.py").read_text()

    assert "app.include_router(\n    coding_ws_router" in source
    assert "_include_router_for_runtime(coding_ws_router" not in source


def test_runtime_creates_supervisor_only_with_fake_loop_enabled(
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "CODING_FAKE_LOOP_ENABLED", True)
    runtime = create_development_coding_runtime()
    assert isinstance(runtime.supervisor, CodingDevelopmentSupervisor)

    monkeypatch.setattr(settings, "CODING_FAKE_LOOP_ENABLED", False)
    runtime = create_development_coding_runtime()
    assert runtime.supervisor is None


def test_production_registration_does_not_create_development_supervisor() -> None:
    assert coding_runtime.supervisor is None
