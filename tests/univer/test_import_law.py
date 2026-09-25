from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.no_db

_PACKAGE = Path("neos/univer")
_FORBIDDEN = (
    "neos.coding.loop.durable",
    "neos.workflow.deep_analysis",
    "neos.fsi",
)


def test_univer_package_does_not_import_durable_da_or_fsi() -> None:
    sources = sorted(_PACKAGE.glob("*.py"))
    assert sources
    offenders: list[str] = []
    for path in sources:
        text = path.read_text()
        for name in _FORBIDDEN:
            if f"import {name}" in text or f"from {name}" in text:
                offenders.append(f"{path}: {name}")
    assert offenders == []
