"""Canonical Claude-Code-shaped command catalog.

Concepts only: NEOS does not import Claude Code sources or prompts.
Disabled entries stay fail-closed (cron, TUI, MCP, coordinator).
"""

from __future__ import annotations

from neos.coding.commands.types import CommandFamily, CommandSpec

_SPECS: tuple[CommandSpec, ...] = (
    CommandSpec(
        name="compact",
        family=CommandFamily.CONTROL,
        description="Compact the coding transcript at the next safe point.",
        usage="/compact [keep-hint]",
        lock_bypass=True,
        apply_in_loop=True,
    ),
    CommandSpec(
        name="clear",
        family=CommandFamily.CONTROL,
        description="Clear conversation context. Keeps the task binding.",
        usage="/clear",
        lock_bypass=True,
        apply_in_loop=True,
    ),
    CommandSpec(
        name="cost",
        family=CommandFamily.CONTROL,
        description="Show tracked token and cost counters for this task.",
        usage="/cost",
        lock_bypass=True,
    ),
    CommandSpec(
        name="export",
        family=CommandFamily.CONTROL,
        description="Export a redacted transcript (never raw loop_state).",
        usage="/export",
        lock_bypass=True,
    ),
    CommandSpec(
        name="help",
        family=CommandFamily.CONTROL,
        description="List commands this deployment will interpret.",
        usage="/help [name]",
        requires_task=False,
        lock_bypass=True,
    ),
    CommandSpec(
        name="stop",
        family=CommandFamily.CONTROL,
        description="Cancel the active coding run.",
        usage="/stop",
        lock_bypass=True,
    ),
    CommandSpec(
        name="status",
        family=CommandFamily.CONTROL,
        description="Show the bound coding task status.",
        usage="/status",
        lock_bypass=True,
    ),
    CommandSpec(
        name="init",
        family=CommandFamily.PROMPT,
        description="Draft workspace agent instructions. Always-ask before overwrite.",
        usage="/init",
    ),
    CommandSpec(
        name="plan",
        family=CommandFamily.PROMPT,
        description="Switch to a read-only implementation plan.",
        usage="/plan [focus]",
    ),
    CommandSpec(
        name="review",
        family=CommandFamily.PROMPT,
        description="Review current workspace changes without editing.",
        usage="/review [focus]",
    ),
    CommandSpec(
        name="commit",
        family=CommandFamily.PROMPT,
        description="Prepare a commit. Does not open free git commit on execute.",
        usage="/commit [message]",
    ),
    CommandSpec(
        name="code",
        family=CommandFamily.CHANNEL,
        description="Start a coding task on this channel thread.",
        usage="/code <task>",
        aliases=("!code",),
        requires_task=False,
    ),
    CommandSpec(
        name="learn",
        family=CommandFamily.CHANNEL,
        description="Stage a lesson. Fail-closed unless learning is enabled.",
        usage="/learn <text>",
        requires_task=False,
        lock_bypass=False,
    ),
    CommandSpec(
        name="new",
        family=CommandFamily.CHANNEL,
        description="Stop the bound task and unbind this thread.",
        usage="/new",
        aliases=("reset",),
        requires_task=False,
        lock_bypass=True,
    ),
    CommandSpec(
        name="approve",
        family=CommandFamily.CHANNEL,
        description="Approve the pending tool or workflow card.",
        usage="/approve [approval_id]",
        lock_bypass=True,
    ),
    CommandSpec(
        name="deny",
        family=CommandFamily.CHANNEL,
        description="Deny the pending tool or workflow card.",
        usage="/deny [approval_id]",
        lock_bypass=True,
    ),
    CommandSpec(
        name="loop",
        family=CommandFamily.DISABLED,
        description="Schedule a recurring prompt. Disabled; cron is default-off.",
        usage="/loop [interval] <prompt>",
        requires_task=False,
        lock_bypass=True,
        enabled=False,
    ),
    CommandSpec(
        name="cron",
        family=CommandFamily.DISABLED,
        description="Cron control. Disabled in this deployment.",
        usage="/cron",
        requires_task=False,
        lock_bypass=True,
        enabled=False,
    ),
    CommandSpec(
        name="mcp",
        family=CommandFamily.DISABLED,
        description="MCP server control. Not enabled on the coding loop.",
        usage="/mcp",
        requires_task=False,
        lock_bypass=True,
        enabled=False,
    ),
    CommandSpec(
        name="chrome",
        family=CommandFamily.DISABLED,
        description="Browser control. Not enabled on the coding loop.",
        usage="/chrome",
        requires_task=False,
        lock_bypass=True,
        enabled=False,
    ),
    CommandSpec(
        name="vim",
        family=CommandFamily.DISABLED,
        description="TUI vim mode. Not available via API.",
        usage="/vim",
        requires_task=False,
        lock_bypass=True,
        enabled=False,
    ),
    CommandSpec(
        name="theme",
        family=CommandFamily.DISABLED,
        description="TUI theme. Not available via API.",
        usage="/theme",
        requires_task=False,
        lock_bypass=True,
        enabled=False,
    ),
    CommandSpec(
        name="login",
        family=CommandFamily.DISABLED,
        description="Interactive login. Not available via API.",
        usage="/login",
        requires_task=False,
        lock_bypass=True,
        enabled=False,
    ),
    CommandSpec(
        name="plugin",
        family=CommandFamily.DISABLED,
        description="Plugin marketplace. Not enabled on the coding loop.",
        usage="/plugin",
        requires_task=False,
        lock_bypass=True,
        enabled=False,
    ),
)

_BY_TOKEN: dict[str, CommandSpec] = {}
for _spec in _SPECS:
    _BY_TOKEN[_spec.name] = _spec
    for _alias in _spec.aliases:
        _BY_TOKEN[_alias.lstrip("/!").lower()] = _spec


def all_command_specs() -> tuple[CommandSpec, ...]:
    return _SPECS


def lookup_command(name: str) -> CommandSpec | None:
    token = (name or "").strip().lower().lstrip("/!")
    if not token:
        return None
    return _BY_TOKEN.get(token)


def catalog_listings() -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "name": spec.name,
            "aliases": list(spec.aliases),
            "family": spec.family.value,
            "description": spec.description,
            "usage": spec.usage or f"/{spec.name}",
            "enabled": spec.enabled,
            "requires_task": spec.requires_task,
        }
        for spec in _SPECS
    )
