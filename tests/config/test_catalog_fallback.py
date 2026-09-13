"""Committed FE catalog fallback must match to_picker_payload()."""

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.no_db

_SCRIPT = Path("scripts/generate_catalog_fallback.py")


def _generator():
    spec = importlib.util.spec_from_file_location("generate_catalog_fallback", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_committed_catalog_generated_matches_to_picker_payload() -> None:
    module = _generator()
    committed = Path(module.OUT_PATH).read_text(encoding="utf-8")
    assert committed == module.render()


def test_generated_fallback_includes_aux_pins() -> None:
    rendered = _generator().render()

    assert "export const generatedAux" in rendered
    assert '"fast": "claude-haiku-4-5-20251001"' in rendered
    assert '"title": "claude-haiku-4-5-20251001"' in rendered
    assert '"artifact": "claude-haiku-4-5-20251001"' in rendered
