from __future__ import annotations

import pytest

from neos.skills.markdown_catalog import (
    default_catalog,
    fsi_catalog,
    fsi_lseg_catalog,
)

pytestmark = pytest.mark.no_db


def test_fsi_catalog_indexes_forty_eight_anthropic_skills() -> None:
    index = fsi_catalog()._ensure_index()
    assert len(index) == 48
    names = {skill.name for skill in fsi_catalog().list_skills()}
    assert len(names) == 48


def test_fsi_catalog_includes_kyc_doc_parse() -> None:
    assert fsi_catalog().get("kyc-doc-parse") is not None


def test_fsi_catalog_includes_xlsx_author() -> None:
    assert fsi_catalog().get("xlsx-author") is not None


def test_fsi_catalog_excludes_skill_creator() -> None:
    assert fsi_catalog().get("skill-creator") is None


def test_default_catalog_does_not_index_kyc_doc_parse() -> None:
    assert default_catalog().get("kyc-doc-parse") is None


def test_lseg_catalog_does_not_index_equity_research() -> None:
    assert fsi_lseg_catalog().get("equity-research") is None
