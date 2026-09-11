"""Coding system prompt builder — Phase 1."""

from __future__ import annotations

from pathlib import Path

import pytest

from neos.coding.model.base import ToolDefinition
from neos.coding.prompts import CodingPromptEnv, build_coding_system_prompt

pytestmark = pytest.mark.no_db

REPO_ROOT = Path(__file__).resolve().parents[3]


def _tools() -> tuple[ToolDefinition, ...]:
    return (
        ToolDefinition(
            name="search_text.v1",
            description="Search workspace text. Do not use execute.v1 with rg.",
            input_schema={"type": "object", "properties": {}},
        ),
        ToolDefinition(
            name="execute.v1",
            description="Run an allowed command.",
            input_schema={"type": "object", "properties": {}},
        ),
    )


def test_prompt_contains_required_sections_in_order() -> None:
    prompt = build_coding_system_prompt(_tools())
    headings = [
        "## Intro",
        "## System",
        "## Tasks",
        "## Actions",
        "## Tools",
        "## Skills",
        "## Tone",
    ]
    positions = [prompt.index(heading) for heading in headings]
    assert positions == sorted(positions)
    assert prompt.index("<!-- neos:dynamic -->") < prompt.index("## Tools")


def test_prompt_states_the_six_behavior_contracts() -> None:
    prompt = build_coding_system_prompt(_tools())
    assert "Do not change a file you have not read in this session" in prompt
    assert "Stay within the requested scope" in prompt
    assert "Prefer dedicated tools over execute.v1" in prompt
    assert "do not claim success" in prompt
    assert "Report results honestly" in prompt
    assert "Do not retry the same denied input" in prompt


def test_prompt_lists_supplied_tools_and_not_unrelated_ones() -> None:
    prompt = build_coding_system_prompt(_tools())
    assert "search_text.v1" in prompt
    assert "execute.v1" in prompt
    assert "todo_write.v1" not in prompt


def test_prompt_includes_allowlist_and_rejects_brand_copy() -> None:
    prompt = build_coding_system_prompt(
        _tools(),
        env=CodingPromptEnv(command_allowlist=("pytest", "ruff")),
    )
    assert "pytest" in prompt
    assert "ruff" in prompt
    assert "Claude Code" not in prompt
    assert "You are Claude" not in prompt


def test_prompt_lists_catalog_skill_names_not_bodies() -> None:
    prompt = build_coding_system_prompt(_tools())
    assert "## Skills" in prompt
    assert "load_skill.v1" in prompt
    assert "pdf" in prompt
    assert "verify" in prompt
    assert "from pypdf import PdfReader" not in prompt


def test_live_registry_descriptions_teach_search_over_execute() -> None:
    from neos.coding.tools.registry import CodingToolRegistry

    tools = CodingToolRegistry.default(command_allowlist=frozenset({"pytest"}))
    prompt = build_coding_system_prompt(tools.definitions())
    search = next(item for item in tools.definitions() if item.name == "search_text.v1")
    execute = next(item for item in tools.definitions() if item.name == "execute.v1")
    assert "execute.v1" in search.description
    assert "rg" in search.description or "grep" in search.description
    assert "-c" in execute.description
    assert search.name in prompt
    assert "edit_file.v1" in prompt


def test_runtime_uses_the_builder_instead_of_the_one_liner() -> None:
    source = (REPO_ROOT / "neos" / "coding" / "runtime.py").read_text(encoding="utf-8")
    assert "build_coding_system_prompt" in source
    assert (
        "Work safely in the provided sandbox and complete the coding task."
        not in source
    )


def test_approved_lessons_appear_under_lessons_heading() -> None:
    prompt = build_coding_system_prompt(
        _tools(),
        env=CodingPromptEnv(approved_lessons=("The rate limit is 60.",)),
    )
    assert "## Lessons" in prompt
    lessons_at = prompt.index("## Lessons")
    assert "The rate limit is 60." in prompt[lessons_at:]


def test_staged_text_does_not_appear_unless_passed() -> None:
    staged = "Staged lesson must stay out of the prompt."
    prompt = build_coding_system_prompt(_tools())
    assert "## Lessons" not in prompt
    assert staged not in prompt
