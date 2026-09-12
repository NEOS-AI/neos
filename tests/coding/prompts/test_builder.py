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
        "## Using tools",
        "## Session",
        "## Environment",
        "## Tools",
        "## Skills",
        "## Tone",
    ]
    positions = [prompt.index(heading) for heading in headings]
    assert positions == sorted(positions)
    boundary = prompt.index("<!-- neos:dynamic -->")
    assert prompt.index("## Using tools") < boundary
    assert boundary < prompt.index("## Session")
    assert boundary < prompt.index("## Environment")
    assert boundary < prompt.index("## Tools")


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
    assert "verify" in prompt
    assert "commit" in prompt
    assert "pdf" not in prompt
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


def test_using_tools_is_static_and_prefers_dedicated() -> None:
    prompt = build_coding_system_prompt(_tools())
    using = prompt[prompt.index("## Using tools") : prompt.index("<!-- neos:dynamic -->")]
    assert "dedicated" in using.lower()
    assert "execute.v1" in using
    assert "parallel" in using.lower()


def test_session_requires_one_in_progress_todo() -> None:
    prompt = build_coding_system_prompt(_tools())
    session = prompt[prompt.index("## Session") : prompt.index("## Environment")]
    assert "in_progress" in session
    assert "one" in session.lower()
    assert "complete" in session.lower()
    assert "explore" in session.lower()


def test_session_lists_deferred_tool_names_not_schemas() -> None:
    from neos.coding.tools.registry import CodingToolRegistry

    prompt = build_coding_system_prompt(_tools())
    boundary = prompt.index("<!-- neos:dynamic -->")
    session_at = prompt.index("## Session")
    session = prompt[session_at : prompt.index("## Environment")]
    deferred = CodingToolRegistry.deferred_tool_names()

    assert boundary < session_at
    assert deferred
    for name in deferred:
        assert name in session
    assert "input_schema" not in session
    assert "properties" not in session
    assert "git_status.v1" in session
    assert "web_fetch.v1" in session
    assert "spawn_agent.v1" in session


def test_environment_holds_workspace_and_allowlist() -> None:
    prompt = build_coding_system_prompt(
        _tools(),
        env=CodingPromptEnv(
            workspace_root="/tmp/ws",
            command_allowlist=("pytest", "ruff"),
        ),
    )
    intro = prompt[prompt.index("## Intro") : prompt.index("## System")]
    environment = prompt[prompt.index("## Environment") : prompt.index("## Tools")]
    tools = prompt[prompt.index("## Tools") : prompt.index("## Skills")]
    assert "/tmp/ws" not in intro
    assert "/tmp/ws" in environment
    assert "pytest" in environment
    assert "ruff" in environment
    assert "execute.v1 allowlist" not in tools


def test_skill_listing_prefers_when_to_use(monkeypatch: pytest.MonkeyPatch) -> None:
    from neos.skills.markdown_catalog import MarkdownSkill

    skill = MarkdownSkill(
        name="demo",
        description="Fallback description that must not appear.",
        path=REPO_ROOT / "neos" / "coding" / "skills" / "verify.md",
        source="coding",
        when_to_use="Use this when planning a change.",
    )
    monkeypatch.setattr(
        "neos.skills.markdown_catalog.list_skills",
        lambda: (skill,),
    )
    prompt = build_coding_system_prompt(_tools())
    assert "Use this when planning a change." in prompt
    assert "Fallback description that must not appear." not in prompt
