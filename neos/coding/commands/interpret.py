"""Turn raw text into a CommandDecision. Shared by API, channel, and loop."""

from __future__ import annotations

from neos.coding.commands.catalog import lookup_command
from neos.coding.commands.parse import parse_slash_command, sanitize_command_args
from neos.coding.commands.prompts import expand_prompt_command
from neos.coding.commands.types import (
    CommandDecision,
    CommandDisposition,
    CommandFamily,
    ParsedCommand,
)


_LOOP_DISABLED = (
    "Scheduled /loop is disabled. Recurring cron is not enabled "
    "in this deployment."
)
_DISABLED = "Command /{name} is disabled in this deployment."
_UNKNOWN = "Unknown command /{name}. Try /help."


def interpret_coding_command(text: str) -> CommandDecision:
    parsed = parse_slash_command(text)
    if not parsed.slash:
        return CommandDecision(
            disposition=CommandDisposition.CHAT,
            parsed=parsed,
            inject_text=parsed.raw,
        )
    spec = lookup_command(parsed.name)
    if spec is None:
        return CommandDecision(
            disposition=CommandDisposition.UNKNOWN,
            parsed=parsed,
            message=_UNKNOWN.format(name=parsed.name or "?"),
        )
    args = sanitize_command_args(parsed.args)
    canonical = f"/{spec.name}"
    if args:
        canonical = f"{canonical} {args}"
    if spec.family is CommandFamily.DISABLED or not spec.enabled:
        message = _LOOP_DISABLED if spec.name == "loop" else _DISABLED.format(
            name=spec.name
        )
        return CommandDecision(
            disposition=CommandDisposition.DENIED,
            parsed=parsed,
            spec=spec,
            message=message,
            canonical_text=canonical,
        )
    if spec.family is CommandFamily.CHANNEL:
        return CommandDecision(
            disposition=CommandDisposition.CHANNEL,
            parsed=parsed,
            spec=spec,
            canonical_text=canonical,
        )
    if spec.family is CommandFamily.PROMPT:
        inject = expand_prompt_command(spec.name, args)
        return CommandDecision(
            disposition=CommandDisposition.INJECT,
            parsed=parsed,
            spec=spec,
            inject_text=inject,
            canonical_text=canonical,
            message=f"Queued /{spec.name} for the coding loop.",
        )
    if spec.apply_in_loop:
        return CommandDecision(
            disposition=CommandDisposition.APPLY_IN_LOOP,
            parsed=parsed,
            spec=spec,
            canonical_text=canonical,
            message=f"Queued /{spec.name} for the next safe point.",
        )
    return CommandDecision(
        disposition=CommandDisposition.EXECUTE,
        parsed=parsed,
        spec=spec,
        canonical_text=canonical,
    )


def is_slash_input(text: str) -> bool:
    parsed: ParsedCommand = parse_slash_command(text)
    return parsed.slash
