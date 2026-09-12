"""Coding slash-command catalog, interpreter, and application service."""

from neos.coding.commands.catalog import (
    all_command_specs,
    catalog_listings,
    lookup_command,
)
from neos.coding.commands.interpret import interpret_coding_command, is_slash_input
from neos.coding.commands.parse import parse_slash_command, strip_leading_mentions
from neos.coding.commands.service import CodingCommandService, format_help
from neos.coding.commands.types import (
    CommandDecision,
    CommandDisposition,
    CommandFamily,
    CommandResult,
    CommandSpec,
    CommandStatus,
    ParsedCommand,
)

__all__ = [
    "CodingCommandService",
    "CommandDecision",
    "CommandDisposition",
    "CommandFamily",
    "CommandResult",
    "CommandSpec",
    "CommandStatus",
    "ParsedCommand",
    "all_command_specs",
    "catalog_listings",
    "format_help",
    "interpret_coding_command",
    "is_slash_input",
    "lookup_command",
    "parse_slash_command",
    "strip_leading_mentions",
]
