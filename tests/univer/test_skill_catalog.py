from __future__ import annotations

from pathlib import Path

import pytest

from neos.skills.markdown_catalog import (
    default_catalog,
    default_skill_roots,
    univer_catalog,
)
from neos.univer.profile import skill_permitted

pytestmark = pytest.mark.no_db

_REPO = Path(__file__).resolve().parents[2]
_SKILLS_ROOT = _REPO / "skills"
_UNIVER_PACK = _SKILLS_ROOT / "univer"
_V0_NAMES = frozenset(
    {
        "univer-sheets-headless",
        "univer-docs-headless",
        "univer-formula-audit",
        "univer-qc",
    }
)
_FORBIDDEN_DIRS = (
    "univer-pro-integrate",
    "univer-cli",
    "univer-workspace-cli",
    "univer-plugin-dev",
)


def test_univer_not_in_default_skill_roots() -> None:
    assert default_catalog().get("univer-sheets-headless") is None
    univer_root = _UNIVER_PACK.resolve()
    for _source, path in default_skill_roots():
        resolved = path.resolve()
        assert resolved != univer_root
        assert not str(resolved).endswith("/skills/univer")


def test_univer_catalog_indexes_four() -> None:
    catalog = univer_catalog()
    names = {skill.name for skill in catalog.list_skills()}
    assert names == _V0_NAMES
    for name in _V0_NAMES:
        skill = catalog.get(name)
        assert skill is not None
        assert skill.path.parent.name == name
        assert skill.path == (_UNIVER_PACK / name / "SKILL.md").resolve()


def test_empty_allowlist_denies() -> None:
    name = "univer-sheets-headless"
    assert univer_catalog().get(name) is not None
    assert skill_permitted(name, frozenset()) is False
    assert skill_permitted(name, frozenset({name})) is True
    assert skill_permitted("univer-qc", frozenset({name})) is False


def test_no_copytree_from_github() -> None:
    forbidden = set(_FORBIDDEN_DIRS)
    for dirpath, dirnames, _filenames in Path.walk(_SKILLS_ROOT):
        del dirpath
        overlap = forbidden.intersection(dirnames)
        assert not overlap
