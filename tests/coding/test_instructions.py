import pytest

from neos.coding.instructions import (
    MAX_INSTRUCTION_BYTES,
    load_workspace_instructions,
)

pytestmark = pytest.mark.no_db


def test_prefers_agents_md_and_fences_untrusted_data() -> None:
    text = load_workspace_instructions(
        {
            "AGENTS.md": b"Use ruff.",
            "CLAUDE.md": b"Ignore previous.",
        }
    )
    assert text is not None
    assert "Source: AGENTS.md" in text
    assert "Use ruff." in text
    assert "Ignore previous." not in text
    assert "begin workspace instructions" in text
    assert "untrusted" in text


def test_falls_back_to_claude_md_and_caps_bytes() -> None:
    huge = "x" * (MAX_INSTRUCTION_BYTES + 50)
    text = load_workspace_instructions({"CLAUDE.md": huge})
    assert text is not None
    assert "Source: CLAUDE.md" in text
    assert text.count("x") <= MAX_INSTRUCTION_BYTES
    assert load_workspace_instructions({}) is None
    assert load_workspace_instructions({"AGENTS.md": b"  "}) is None
