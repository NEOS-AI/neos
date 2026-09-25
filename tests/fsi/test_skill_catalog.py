from __future__ import annotations

from pathlib import Path

import pytest

from neos.skills.markdown_catalog import (
    FSI_ANTHROPIC_VERTICALS,
    FSI_PACK,
    default_catalog,
    default_skill_roots,
    fsi_catalog,
    fsi_lseg_catalog,
    fsi_partner_skill_roots,
    fsi_skill_roots,
    fsi_spglobal_catalog,
    research_skill_roots,
)

pytestmark = pytest.mark.no_db

REPO_ROOT = Path(__file__).resolve().parents[2]
_EXPECTED_VERTICALS = (
    "financial-analysis",
    "equity-research",
    "investment-banking",
    "private-equity",
    "fund-admin",
    "operations",
    "wealth-management",
)


def test_fsi_skill_roots_end_with_seven_verticals_in_order() -> None:
    roots = fsi_skill_roots()
    assert len(roots) == 7
    assert all(source == "repo" for source, _path in roots)
    names = tuple(path.name for _source, path in roots)
    assert names == _EXPECTED_VERTICALS
    assert names == FSI_ANTHROPIC_VERTICALS
    for _source, path in roots:
        assert path == FSI_PACK / path.name
        assert path.parent == FSI_PACK


def test_fsi_catalog_kyc_doc_parse_absent_until_pack() -> None:
    assert fsi_catalog().get("kyc-doc-parse") is not None


def test_default_catalog_does_not_index_xlsx_author() -> None:
    assert default_catalog().get("xlsx-author") is None


def test_default_skill_roots_remain_coding_only() -> None:
    roots = default_skill_roots()
    paths = {path.resolve() for _source, path in roots}

    assert (REPO_ROOT / "neos" / "coding" / "skills").resolve() in paths
    assert (REPO_ROOT / "skills").resolve() not in paths
    assert FSI_PACK.resolve() not in paths
    assert all(source != "repo" for source, _path in roots)
    for _source, path in roots:
        resolved = path.resolve()
        assert resolved != FSI_PACK.resolve()
        for vertical in FSI_ANTHROPIC_VERTICALS:
            assert resolved != (FSI_PACK / vertical).resolve()


def test_research_skill_roots_do_not_add_fsi_pack() -> None:
    roots = research_skill_roots()
    paths = [path.resolve() for _source, path in roots]
    assert (REPO_ROOT / "skills").resolve() in paths
    assert FSI_PACK.resolve() not in paths
    for vertical in FSI_ANTHROPIC_VERTICALS:
        assert (FSI_PACK / vertical).resolve() not in paths


def test_unknown_partner_vendor_raises() -> None:
    with pytest.raises(ValueError, match="unknown FSI partner vertical"):
        fsi_partner_skill_roots("acme")  # type: ignore[arg-type]


def test_partner_catalogs_use_vendor_roots() -> None:
    assert fsi_partner_skill_roots("lseg") == (("repo", FSI_PACK / "lseg"),)
    assert fsi_partner_skill_roots("spglobal") == (
        ("repo", FSI_PACK / "spglobal"),
    )
    assert fsi_lseg_catalog().get("equity-research") is None
    assert fsi_spglobal_catalog().get("earnings-preview-single") is None
