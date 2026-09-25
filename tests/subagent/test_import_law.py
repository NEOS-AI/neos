from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


pytestmark = pytest.mark.no_db

_FORBIDDEN = (
    "neos.coding.loop.durable",
    "neos.coding.loop.base",
    "neos.coding.sandbox.bindings",
    "neos.coding.repositories",
    "neos.api.channels",
    "neos.workflow.deep_analysis",
    "neos.agents",
    "neos.univer",
)

_PACKAGE = Path("neos/subagent")


def test_importing_subagent_does_not_load_durable_loop() -> None:
    script = (
        "import sys\n"
        "import neos.subagent\n"
        "assert 'neos.coding.loop.durable' not in sys.modules\n"
        "assert 'neos.coding.sandbox.bindings' not in sys.modules\n"
        "assert 'neos.coding.repositories' not in sys.modules\n"
        "assert 'neos.api.channels' not in sys.modules\n"
        "assert 'neos.workflow.deep_analysis' not in sys.modules\n"
        "assert 'neos.agents' not in sys.modules\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_package_sources_do_not_import_forbidden_modules() -> None:
    sources = sorted(_PACKAGE.glob("*.py"))
    assert sources
    offenders: list[str] = []
    for path in sources:
        text = path.read_text()
        for name in _FORBIDDEN:
            if f"import {name}" in text or f"from {name}" in text:
                offenders.append(f"{path}: {name}")
    assert offenders == []
