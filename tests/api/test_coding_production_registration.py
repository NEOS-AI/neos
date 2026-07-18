from pathlib import Path


def test_coding_websocket_bypasses_generic_production_filter() -> None:
    source = Path("neos/main.py").read_text()

    assert "app.include_router(\n    coding_ws_router" in source
    assert "_include_router_for_runtime(coding_ws_router" not in source
