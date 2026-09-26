from __future__ import annotations

from pathlib import Path

import pytest

from neos.fsi.profile import compile_leaf_spec, compile_tool_policy, load_profile
from neos.fsi.schemas import READER_SCHEMAS
from neos.subagent.types import SandboxMode

pytestmark = pytest.mark.no_db

_PROFILES = Path(__file__).resolve().parents[2] / "skills" / "financial-services" / "profiles"

_MODE_B = (
    "kyc-screener",
    "gl-reconciler",
    "month-end-closer",
    "statement-auditor",
    "valuation-reviewer",
)
_MODE_A = (
    "model-builder",
    "pitch-agent",
    "market-researcher",
    "earnings-reviewer",
    "meeting-prep-agent",
)
_ALL_SLUGS = _MODE_B + _MODE_A

_WRITE_LEAF = {
    "kyc-screener": "kyc-escalator",
    "gl-reconciler": "gl-reconciler-resolver",
    "month-end-closer": "close-poster",
    "statement-auditor": "stmt-flagger",
    "valuation-reviewer": "valuation-publisher",
    "model-builder": "model-builder-builder",
    "pitch-agent": "pitch-deck-writer",
    "market-researcher": "market-note-writer",
    "earnings-reviewer": "earnings-note-writer",
    "meeting-prep-agent": "briefing-pack-writer",
}

_SCHEMA_LEAF = {
    "kyc-screener": "kyc-doc-reader",
    "gl-reconciler": "gl-reconciler-reader",
    "month-end-closer": "close-ledger-reader",
    "statement-auditor": "stmt-statement-reader",
    "valuation-reviewer": "valuation-package-reader",
    "model-builder": "model-data-puller",
    "pitch-agent": "pitch-researcher",
    "market-researcher": "market-sector-reader",
    "earnings-reviewer": "earnings-transcript-reader",
    "meeting-prep-agent": "briefing-news-reader",
}

_EXPECTED_LEAVES = {
    "kyc-screener": (
        ("kyc-doc-reader", "fsi-reader", False),
        ("kyc-rules-engine", "fsi-critic", False),
        ("kyc-escalator", "fsi-writer", True),
    ),
    "gl-reconciler": (
        ("gl-reconciler-reader", "fsi-reader", False),
        ("gl-reconciler-critic", "fsi-critic", False),
        ("gl-reconciler-resolver", "fsi-writer", True),
    ),
    "month-end-closer": (
        ("close-ledger-reader", "fsi-reader", False),
        ("close-rollforward", "fsi-critic", False),
        ("close-poster", "fsi-writer", True),
    ),
    "statement-auditor": (
        ("stmt-statement-reader", "fsi-reader", False),
        ("stmt-reconciler", "fsi-critic", False),
        ("stmt-flagger", "fsi-writer", True),
    ),
    "valuation-reviewer": (
        ("valuation-package-reader", "fsi-reader", False),
        ("valuation-runner", "fsi-critic", False),
        ("valuation-publisher", "fsi-writer", True),
    ),
    "model-builder": (
        ("model-data-puller", "fsi-puller", False),
        ("model-builder-builder", "fsi-writer", True),
        ("model-builder-auditor", "fsi-critic", False),
    ),
    "pitch-agent": (
        ("pitch-researcher", "fsi-puller", False),
        ("pitch-modeler", "fsi-modeler", False),
        ("pitch-deck-writer", "fsi-writer", True),
    ),
    "market-researcher": (
        ("market-sector-reader", "fsi-reader", False),
        ("market-comps-spreader", "fsi-critic", False),
        ("market-note-writer", "fsi-writer", True),
    ),
    "earnings-reviewer": (
        ("earnings-transcript-reader", "fsi-reader", False),
        ("earnings-model-updater", "fsi-critic", False),
        ("earnings-note-writer", "fsi-writer", True),
    ),
    "meeting-prep-agent": (
        ("briefing-news-reader", "fsi-reader", False),
        ("briefing-profiler", "fsi-critic", False),
        ("briefing-pack-writer", "fsi-writer", True),
    ),
}


@pytest.fixture(params=_ALL_SLUGS)
def slug(request: pytest.FixtureRequest) -> str:
    return str(request.param)


def _load(slug: str) -> dict[str, object]:
    return dict(load_profile(slug, profiles_dir=_PROFILES))


def test_load_profile_each_named_slug(slug: str) -> None:
    profile = _load(slug)
    assert profile["slug"] == slug
    assert profile["isolation_surface"] == "cma_leaves"
    tools = profile["tools"]
    assert isinstance(tools, dict)
    assert tools["default"] == "deny"
    assert tools["orchestrator_allow"] == [
        "read_file.v1",
        "search_text.v1",
        "glob_files.v1",
    ]
    assert profile["handoff_allowlist"] == []
    if slug in _MODE_B:
        assert profile["mode"] == "B"
    else:
        assert profile["mode"] == "A"


def test_compile_tool_policy_has_no_write_or_handoff(slug: str) -> None:
    tools = compile_tool_policy(_load(slug))
    assert "write_file.v1" not in tools
    assert "edit_file.v1" not in tools
    assert "execute.v1" not in tools
    assert "handoff.v1" not in tools
    assert "spawn_agent.v1" in tools


def test_exactly_one_writer_and_expected_leaves(slug: str) -> None:
    profile = _load(slug)
    leaves = profile["leaves"]
    assert isinstance(leaves, list)
    expected = _EXPECTED_LEAVES[slug]
    assert len(leaves) == len(expected)
    writers = 0
    for leaf, (name, template, write) in zip(leaves, expected, strict=True):
        assert isinstance(leaf, dict)
        assert leaf["name"] == name
        assert leaf["catalog_template"] == template
        assert bool(leaf["write"]) is write
        if write:
            writers += 1
    assert writers == 1


def test_schema_leaf_name_matches_reader_schemas(slug: str) -> None:
    profile = _load(slug)
    schema_name = _SCHEMA_LEAF[slug]
    leaves = profile["leaves"]
    assert isinstance(leaves, list)
    schema_leaf = next(
        leaf
        for leaf in leaves
        if isinstance(leaf, dict) and leaf.get("name") == schema_name
    )
    assert schema_leaf["output_schema_ref"] == schema_name
    assert schema_name in READER_SCHEMAS
    for leaf in leaves:
        assert isinstance(leaf, dict)
        if leaf["name"] == schema_name:
            continue
        if leaf.get("catalog_template") in {"fsi-reader", "fsi-puller"}:
            pytest.fail(f"unexpected extra schema leaf {leaf['name']}")
        assert leaf.get("output_schema_ref") is None


def test_write_leaf_sandbox_and_write_tool(slug: str) -> None:
    profile = _load(slug)
    writer = compile_leaf_spec(profile, _WRITE_LEAF[slug])
    assert "write_file.v1" in writer.allowed_tools
    if slug in _MODE_A:
        assert writer.sandbox_mode is SandboxMode.WORKTREE
    else:
        assert writer.sandbox_mode is SandboxMode.NONE
    for leaf in profile["leaves"]:  # type: ignore[union-attr]
        assert isinstance(leaf, dict)
        if leaf.get("write"):
            continue
        spec = compile_leaf_spec(profile, str(leaf["name"]))
        if slug in _MODE_A:
            assert spec.sandbox_mode is SandboxMode.PARENT_RO
        else:
            assert spec.sandbox_mode is SandboxMode.NONE


def test_model_builder_builder_has_no_execute() -> None:
    profile = _load("model-builder")
    spec = compile_leaf_spec(profile, "model-builder-builder")
    assert "execute.v1" not in spec.allowed_tools
    assert "write_file.v1" in spec.allowed_tools


def test_kyc_rules_engine_keeps_screening() -> None:
    profile = _load("kyc-screener")
    spec = compile_leaf_spec(profile, "kyc-rules-engine")
    assert "mcp.screening.search" in spec.allowed_tools
    assert spec.sandbox_mode is SandboxMode.NONE
