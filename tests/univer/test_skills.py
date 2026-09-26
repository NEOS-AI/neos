from __future__ import annotations

import pytest

from neos.skills.markdown_catalog import univer_catalog

pytestmark = pytest.mark.no_db

_SKILLS = (
    "univer-sheets-headless",
    "univer-docs-headless",
    "univer-formula-audit",
    "univer-qc",
)
_LIVE_BOOT_FORBIDDEN = (
    "FUniver.newAPI",
    "preset-sheets-node-core",
)


def _markdown(name: str) -> str:
    body = univer_catalog().load_markdown(name)
    assert body is not None
    return body


@pytest.mark.parametrize("name", _SKILLS)
def test_skill_teaches_in_memory_sidecar(name: str) -> None:
    body = _markdown(name)
    assert "InMemorySidecar" in body
    assert "## When to Use" not in body
    assert "## Boundaries" not in body
    for forbidden in _LIVE_BOOT_FORBIDDEN:
        assert forbidden not in body


def test_sheets_and_docs_teach_save() -> None:
    assert "univer.save.v1" in _markdown("univer-sheets-headless")
    assert "univer.save.v1" in _markdown("univer-docs-headless")


def test_formula_teaches_wait_sum_and_name_error() -> None:
    body = _markdown("univer-formula-audit")
    assert "univer.formula_wait.v1" in body
    assert "SUM" in body
    assert "#NAME?" in body


def test_qc_teaches_read_only_inspect() -> None:
    assert "univer.inspect.v1" in _markdown("univer-qc")


def test_docs_teaches_insert_text_command() -> None:
    assert "doc.command.insert-text" in _markdown("univer-docs-headless")
