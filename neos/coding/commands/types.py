"""Shared slash-command types for API, channel, and the coding loop."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping


class CommandFamily(StrEnum):
    """How a recognized command is supposed to run."""

    CONTROL = "control"
    PROMPT = "prompt"
    CHANNEL = "channel"
    DISABLED = "disabled"


class CommandDisposition(StrEnum):
    """Interpreter result. Parse once; every surface branches on this."""

    CHAT = "chat"
    UNKNOWN = "unknown"
    DENIED = "denied"
    EXECUTE = "execute"
    APPLY_IN_LOOP = "apply_in_loop"
    INJECT = "inject"
    CHANNEL = "channel"


class CommandStatus(StrEnum):
    OK = "ok"
    QUEUED = "queued"
    DENIED = "denied"
    UNKNOWN = "unknown"
    UNAVAILABLE = "unavailable"
    CHANNEL = "channel"
    CHAT = "chat"


@dataclass(frozen=True, slots=True)
class CommandSpec:
    name: str
    family: CommandFamily
    description: str
    usage: str = ""
    aliases: tuple[str, ...] = ()
    requires_task: bool = True
    lock_bypass: bool = False
    enabled: bool = True
    apply_in_loop: bool = False


@dataclass(frozen=True, slots=True)
class ParsedCommand:
    name: str
    args: str
    raw: str
    token: str
    slash: bool


@dataclass(frozen=True, slots=True)
class CommandDecision:
    disposition: CommandDisposition
    parsed: ParsedCommand
    spec: CommandSpec | None = None
    inject_text: str = ""
    message: str = ""
    canonical_text: str = ""


@dataclass(frozen=True, slots=True)
class CommandResult:
    name: str
    status: CommandStatus
    message: str
    args: str = ""
    payload: Mapping[str, Any] = field(default_factory=dict)

    def as_mapping(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "message": self.message,
            "args": self.args,
            "payload": dict(self.payload),
        }
