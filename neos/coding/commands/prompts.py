"""Prompt-family expansions. Short NEOS-owned text, not upstream prompts."""

from __future__ import annotations

from neos.coding.commands.parse import sanitize_command_args

_TEMPLATES = {
    "init": (
        "Draft a workspace AGENTS.md covering build, test, and coding "
        "conventions. Stay read-only except for that draft. Do not overwrite "
        "an existing AGENTS.md without asking."
    ),
    "plan": (
        "Switch to plan. Write a short implementation plan with a "
        "`Critical Files:` list. Do not edit or execute."
    ),
    "review": (
        "Review the current workspace changes. Report bugs, regressions, "
        "and missing tests. Do not edit files unless the user asks."
    ),
    "commit": (
        "Prepare a commit for the current workspace changes using the "
        "commit skill. Do not run a free-form git commit through execute."
    ),
}


def expand_prompt_command(name: str, args: str) -> str:
    body = _TEMPLATES.get(name, "")
    focus = sanitize_command_args(args, max_len=400)
    if focus:
        return f"{body}\n\nFocus: {focus}"
    return body
